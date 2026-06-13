"""Chat engine - interfaces with Qwen via DashScope OpenAI-compatible API."""

import json
import uuid
from typing import Any
from pathlib import Path

from openai import OpenAI

from .config import load_config
from .skills import Skill, SkillsLoader
from .tools import ToolRegistry, create_default_tools
from .database import HistoryDB
from .utils import sanitize_tool_arguments, validate_tool_args, log_api_error, logger


class ChatEngine:
    """Core chat engine: builds prompts with skills, calls LLM, manages history.

    Supports OpenAI function calling for tool execution.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or load_config()
        self.history: list[dict[str, Any]] = []
        self.skills = SkillsLoader(
            self.config.get("skills_dir")
            or Path.home() / ".miniagent" / "skills"
        )
        self.tools = create_default_tools()
        self._client: OpenAI | None = None
        self._tool_calls_count = 0
        self._max_tool_rounds = 30  # Safety limit for tool call loops
        
        # Initialize database for persistent history
        self.db = HistoryDB()
        self.session_id = "default"  # Can be customized per session

    @property
    def client(self) -> OpenAI:
        """Lazy-initialize the OpenAI client."""
        if self._client is None:
            self._client = OpenAI(
                api_key=self.config.get("api_key", ""),
                base_url=self.config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            )
        return self._client

    def build_system_prompt(self, active_skills: list[Skill] | None = None) -> str:
        """Build the full system prompt with skills injected."""
        # Determine MiniAgent installation root
        miniagent_root = Path(__file__).resolve().parent.parent

        parts = [self.config.get("system_prompt", "你是一个有帮助的 AI 助手。")]

        # Tool instructions
        tool_names = self.tools.tool_names
        if tool_names:
            parts.append(
                "# Available Tools\n\n"
                "You have access to the following tools. When you need to:\n"
                "- Read/write/edit files -> use read_file, write_file, edit_file, list_dir\n"
                "- Execute CMD commands (copy, delete, run scripts, etc.) -> use shell\n"
                "- Run Node.js / JavaScript scripts or inline code -> use run_node\n"
                "- Run Python scripts or inline code -> use run_python\n"
                "- Search the web -> use web_search\n"
                "- Fetch web page content -> use web_fetch\n\n"
                "# Script Execution\n\n"
                "Use run_node for JavaScript/Node.js and run_python for Python.\n"
                "Both support: 'path' (script file) or 'code' (inline code), 'cwd' (working dir), 'timeout', 'args'.\n"
                "Examples:\n"
                '- run_node(path="build.js", cwd="my-ppt")\n'
                '- run_python(code="import os; print(os.getcwd())")\n'
                '- run_node(path="script.js", args="--production", timeout=120)\n\n'
                f"# Output Directory\n\n"
                f"MiniAgent 安装目录: {miniagent_root}\n"
                f"所有生成的文件（PPT、HTML、文档等）统一输出到: {miniagent_root / 'output'}\n"
                f"使用 shell/run_node/run_python 时，通过 cwd 参数指向此目录。\n\n"
                "# Document Saving Rule\n\n"
                "IMPORTANT: Whenever you generate a complete document (HTML page, Markdown file, "
                "JSON data, CSV data, code file, or any other structured content), you MUST call "
                "save_document to save it to disk. Do NOT just output the document in chat — "
                "always save it as a file so the user can find it later.\n\n"
                "Use tools proactively. When the user asks you to save, read, "
                "edit files, run commands or search for information, call the appropriate tool directly. "
                "Always tell the user what you're doing before/after tool calls."
            )

        # Always-active skills
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.build_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # Specifically activated skills
        if active_skills:
            always_names = {s.name for s in always_skills}
            extra = [s for s in active_skills if s.name not in always_names]
            if extra:
                extra_content = self.skills.build_context(extra)
                if extra_content:
                    parts.append(f"# Activated Skills\n\n{extra_content}")

        # Skills summary
        summary = self.skills.build_summary()
        if summary:
            parts.append(
                f"# Available Skills\n\n"
                f"Auto-match and load relevant skills when user keywords match:\n\n"
                f"{summary}"
            )

        return "\n\n---\n\n".join(parts)

    def chat(
        self,
        user_input: str,
        active_skills: list[Skill] | None = None,
        auto_match: bool = True,
        stream: bool = False,
    ) -> str:
        """Send a message and get the response.

        Supports tool calling: if the model requests a tool call, the tool
        is executed and the result is fed back to the model automatically.

        Args:
            user_input: The user's message.
            active_skills: Explicitly activated skills.
            auto_match: Whether to auto-match skills by keywords.
            stream: Whether to stream the final text response.

        Returns:
            The assistant's final response text.
        """
        # Match skills
        matched_skills = list(active_skills or [])
        if auto_match:
            auto_matched = self.skills.match_triggers(user_input)
            auto_names = {s.name for s in auto_matched}
            for s in matched_skills:
                auto_names.discard(s.name)
            matched_skills.extend([s for s in auto_matched if s.name in auto_names])

        # Build system prompt
        system_prompt = self.build_system_prompt(matched_skills)

        # Build messages
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_input})

        # Log matched skills
        if matched_skills:
            names = [s.name for s in matched_skills]
            print(f"\n  [Skills: {', '.join(names)}]")

        # Tool calling loop
        self._tool_calls_count = 0
        tool_definitions = self.tools.get_definitions()

        # Track consecutive failures to break infinite retry loops
        _consecutive_failures: dict[str, int] = {}
        _MAX_CONSECUTIVE_FAILURES = 3

        while self._tool_calls_count < self._max_tool_rounds:
            # Call LLM
            kwargs: dict[str, Any] = {
                "model": self.config.get("model", "qwen-plus"),
                "messages": messages,
                "temperature": self.config.get("temperature", 0.7),
                "max_tokens": self.config.get("max_tokens", 32768),
            }
            if tool_definitions:
                kwargs["tools"] = tool_definitions

            # Debug log: show what's being sent to the LLM
            msg_preview = messages[-1].get("content", "") if messages else ""
            logger.debug(
                f"[chat] round={self._tool_calls_count}, model={kwargs['model']}, "
                f"max_tokens={kwargs['max_tokens']}, temp={kwargs['temperature']}, "
                f"msg_count={len(messages)}, tools={len(tool_definitions)}"
            )
            logger.debug(
                f"[chat] last_msg_preview={msg_preview[:300]}"
            )

            try:
                resp = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                error_text = log_api_error(e, "CLI API call", messages)
                self._update_history(user_input, error_text)
                return error_text

            choice = resp.choices[0]
            message = choice.message

            # Add assistant message to conversation
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": sanitize_tool_arguments(
                                tc.function.arguments or "{}",
                                tc.function.name,
                            ),
                        },
                    }
                    for tc in message.tool_calls
                ]
            messages.append(assistant_msg)

            # No tool calls -> we're done
            if not message.tool_calls:
                response_text = message.content or ""
                if stream and response_text:
                    print(f"Assistant > {response_text}")
                # Update history (without tool call artifacts)
                self._update_history(user_input, response_text)
                return response_text

            # Execute tool calls (use sanitized args from assistant_msg)
            sanitized_calls = assistant_msg.get("tool_calls", [])
            for i, tool_call in enumerate(message.tool_calls):
                fn_name = tool_call.function.name

                # Prefer sanitized arguments from assistant_msg
                if i < len(sanitized_calls):
                    fn_args_str = sanitized_calls[i]["function"]["arguments"]
                else:
                    fn_args_str = tool_call.function.arguments or "{}"

                # Parse arguments
                try:
                    fn_args = json.loads(fn_args_str)
                    if not isinstance(fn_args, dict):
                        fn_args = {}
                except json.JSONDecodeError:
                    fn_args = {}

                # Validate arguments before execution
                is_valid, validation_msg = validate_tool_args(fn_name, fn_args)
                if not is_valid:
                    _consecutive_failures[fn_name] = _consecutive_failures.get(fn_name, 0) + 1
                    logger.warning(
                        f"[chat] Tool '{fn_name}' args validation failed: {validation_msg}. "
                        f"consecutive_failures={_consecutive_failures[fn_name]}"
                    )
                    if _consecutive_failures.get(fn_name, 0) >= _MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            f"[chat] Tool '{fn_name}' has failed {_consecutive_failures[fn_name]} "
                            f"times consecutively. Breaking tool loop."
                        )
                        response_text = (
                            f"工具 {fn_name} 连续失败 {_consecutive_failures[fn_name]} 次，"
                            f"已中止执行。请重试或简化请求。"
                        )
                        self._update_history(user_input, response_text)
                        return response_text
                    # Still execute with empty args to give feedback to LLM
                    fn_args = {}

                # Log tool call
                arg_preview = ", ".join(f"{k}={repr(v)[:60]}" for k, v in fn_args.items())
                print(f"  [Tool: {fn_name}({arg_preview})]")

                # Execute
                result = self.tools.execute(fn_name, fn_args)
                self._tool_calls_count += 1

                # Track consecutive failures
                if "Error" in result or "失败" in result:
                    _consecutive_failures[fn_name] = _consecutive_failures.get(fn_name, 0) + 1
                    logger.warning(
                        f"[chat] Tool '{fn_name}' failed (consecutive={_consecutive_failures[fn_name]}): "
                        f"result={result[:200]}"
                    )
                    if _consecutive_failures.get(fn_name, 0) >= _MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            f"[chat] Tool '{fn_name}' has failed {_consecutive_failures[fn_name]} "
                            f"times consecutively. Breaking tool loop."
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": (
                                f"Error: Tool '{fn_name}' has failed "
                                f"{_consecutive_failures[fn_name]} times. STOP calling this tool."
                            ),
                        })
                        # Continue to next round — LLM will see the error and should stop
                else:
                    _consecutive_failures.pop(fn_name, None)

                # Log result (truncated)
                if len(result) > 200:
                    print(f"  [Result: {result[:200]}...]")
                else:
                    print(f"  [Result: {result}]")

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        # Exceeded max tool rounds
        response_text = "[Notice] Reached maximum tool call rounds. Please try again with a simpler request."
        self._update_history(user_input, response_text)
        return response_text

    def _update_history(self, user_input: str, response_text: str) -> None:
        """Update conversation history (clean, without tool artifacts)."""
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": response_text})

        # Save to database for persistence
        try:
            self.db.save_conversation_pair(
                user_input=user_input,
                assistant_response=response_text,
                session_id=self.session_id
            )

            # Auto-title the session with the first user message (first 10 chars)
            if len(self.history) == 2:
                title = user_input[:10].replace('\n', ' ').strip()
                if title:
                    self.db.update_session_title(self.session_id, title)
        except Exception as e:
            print(f"Warning: Failed to save history to database: {e}")

        # Trim in-memory history
        max_h = self.config.get("max_history", 20)
        if max_h > 0 and len(self.history) > max_h * 2:
            self.history = self.history[-(max_h * 2):]

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.history.clear()
        # Also clear from database
        try:
            self.db.clear_history(self.session_id)
        except Exception as e:
            print(f"Warning: Failed to clear history from database: {e}")

    def new_session(self) -> str:
        """Start a new conversation session.

        If the current session has messages, it is preserved in the database
        and titled with the first user message (first 10 characters).

        Returns:
            The new session_id
        """
        old_session_id = self.session_id

        # Title the old session if it has messages in memory
        if self.history:
            try:
                for msg in self.history:
                    if msg.get("role") == "user":
                        title = msg["content"][:10].replace('\n', ' ').strip()
                        if title:
                            self.db.update_session_title(old_session_id, title)
                        break
                # Also try DB in case history was trimmed
                else:
                    first = self.db.get_first_user_message(old_session_id)
                    if first:
                        title = first[:10].replace('\n', ' ').strip()
                        if title:
                            self.db.update_session_title(old_session_id, title)
            except Exception:
                pass

        # Generate new session_id
        new_id = uuid.uuid4().hex[:12]
        self.session_id = new_id
        self.history.clear()
        return new_id

    def switch_to_session(self, session_id: str) -> list[dict[str, Any]]:
        """Switch to an existing session and load its history.

        Args:
            session_id: The session to switch to

        Returns:
            List of messages in the session
        """
        self.session_id = session_id
        self.history = []
        try:
            messages = self.db.get_session_messages(session_id)
            for msg in messages:
                self.history.append({"role": msg["role"], "content": msg["content"]})
            return messages
        except Exception:
            return []

    def load_history_from_db(self, limit: int = 100) -> list[dict[str, Any]]:
        """Load conversation history from database.
        
        Args:
            limit: Maximum number of messages to load
            
        Returns:
            List of message dictionaries
        """
        return self.db.get_history(session_id=self.session_id, limit=limit)

    def reload_skills(self) -> None:
        """Reload skills from disk."""
        self.skills.reload()
