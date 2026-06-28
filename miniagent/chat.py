"""Chat engine - interfaces with Qwen via DashScope OpenAI-compatible API."""

import json
import re
import uuid
from typing import Any
from pathlib import Path

from openai import OpenAI

from .config import load_config, get_skills_dir
from .skills import Skill, SkillsLoader
from .tools import ToolRegistry, create_default_tools
from .database import HistoryDB
from .utils import sanitize_tool_arguments, validate_tool_args, log_api_error, logger, switch_debug_session


class ChatEngine:
    """Core chat engine: builds prompts with skills, calls LLM, manages history.

    Supports OpenAI function calling for tool execution.
    """

    # Skill types that typically need many tool rounds
    _HEAVY_SKILLS: set[str] = {'shell-pptx', 'html-ppt', 'pptx', 'frontend-slides'}
    _DOC_SKILLS: set[str] = {'docx', 'pdf', 'xlsx'}

    # Per-task slide/page tracking for dynamic max_rounds adjustment
    _SLIDE_FILE_PATTERN: re.Pattern = re.compile(r'slide\d+.*\.html$', re.IGNORECASE)

    # Tool result character limits (0 = no truncation)
    # read_file: 8000 chars — slide HTML files are 2-6 KB; need full content
    #   for edit_file old_text matching. 300 was too short and caused
    #   "old_text not found" errors in PPT workflows.
    _TOOL_TRUNCATE_LIMITS: dict[str, int] = {
        "read_file": 8000,
        "shell": 1000,
        "run_node": 500,
        "run_python": 500,
        "write_file": 0,
        "edit_file": 0,
        "list_dir": 0,
        "web_search": 0,
        "web_fetch": 2000,
        "find_skills": 0,
        "use_skill": 0,
        "save_document": 0,
    }
    _TOOL_TRUNCATE_DEFAULT = 2000

    @staticmethod
    def _truncate_tool_result(fn_name: str, result: str) -> str:
        """Truncate tool result to reduce context tokens.

        Strategy by tool type:
        - read_file: keep first 8000 chars (slide HTML files are 2-6 KB;
          needs full content for edit_file old_text matching)
        - shell: keep first 1000 chars (stdout often has key info at top)
        - run_node/run_python: keep first 500 chars
        - write_file/edit_file/list_dir/use_skill: keep full (already short)
        - Others default: 2000 chars
        """
        limit = ChatEngine._TOOL_TRUNCATE_LIMITS.get(
            fn_name, ChatEngine._TOOL_TRUNCATE_DEFAULT,
        )
        if limit <= 0 or len(result) <= limit:
            return result
        return (
            f"{result[:limit]}\n\n"
            f"[结果已截断，共 {len(result)} 字符，以上仅显示前 {limit} 字符]"
        )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or load_config()
        self.history: list[dict[str, Any]] = []
        self.skills = SkillsLoader(get_skills_dir(self.config))
        self.tools = create_default_tools()
        self._client: OpenAI | None = None
        self._tool_calls_count = 0
        
        # Initialize database for persistent history
        self.db = HistoryDB()
        self.session_id = "default"  # Can be customized per session

        # System prompt caching — avoids rebuilding ~4KB+ of static text every chat() call
        self._static_prompt_cache: str | None = None
        self._skills_context_cache: str | None = None
        self._miniagent_root: Path = Path(__file__).resolve().parent.parent

        # Slide/page count detected during tool execution (for dynamic max_rounds)
        self._detected_slide_count = 0
        self._slide_paths: set[str] = set()

    @staticmethod
    def _estimate_max_rounds(user_input: str, active_skills: list[Skill] | None = None) -> int:
        """Dynamically estimate max tool-call rounds based on task complexity.

        Heuristics:
        - Base: 15 rounds for trivial tasks, 30 for PPT skills, 25 for doc skills
        - Per-page bonus: If the user mentions a slide/page count, add
          count * multiplier rounds (6 for PPT, 3 for docs)
          Real-world data: ~6 rounds needed per slide for generation + build.
        - When no count specified for PPT/doc, assume a moderate default scale
        - Floor: 80 rounds minimum for non-PPT tasks; PPT/doc have higher defaults
        """
        import re

        skill_names: set[str] = {s.name for s in (active_skills or [])}
        is_heavy = bool(skill_names & ChatEngine._HEAVY_SKILLS)
        is_doc = bool(skill_names & ChatEngine._DOC_SKILLS)

        if is_heavy:
            base = 30
            multiplier = 6  # ~6 rounds per slide (generation + verification + build)
        elif is_doc:
            base = 25
            multiplier = 3  # ~3 rounds per page
        else:
            base = 15
            multiplier = 1

        # Detect slide/page count from user input
        count_patterns = [
            r'(\d+)\s*(?:页|张|个|slides?|pages?|页幻灯|幻灯片|PPT)',
            r'(?:制作|生成|创建|写|帮我做|做一个)\s*(\d+)\s*(?:页|张|个|slides?|pages?)',
            r'(?:about|around|approximately)\s*(\d+)\s*(?:slides?|pages?)',
        ]
        item_count = 0
        for pat in count_patterns:
            m = re.search(pat, user_input, re.IGNORECASE)
            if m:
                item_count = max(item_count, int(m.group(1)))

        if item_count > 0:
            # Scale linearly with page count: more pages = more rounds
            estimated = base + item_count * multiplier + 10  # 10 buffer rounds
        elif is_heavy:
            # PPT task with no page count — typical PPT has 10-15 slides
            estimated = base + 60  # 30 + 60 = 90, covers ~10 slides
        elif is_doc:
            # Doc task with no page count — moderate scale
            estimated = base + 40  # 25 + 40 = 65
        else:
            estimated = base

        return max(estimated, 80)

    @classmethod
    def _try_detect_slide(cls, fn_name: str, fn_args: dict[str, Any]) -> str | None:
        """Detect if a tool call is creating a slide HTML file.

        Returns the slide filename stem (e.g. 'slide01-cover') if detected, else None.
        """
        if fn_name not in ("write_file", "shell"):
            return None

        path = fn_args.get("path", "") or fn_args.get("command", "")
        if not path or not isinstance(path, str):
            return None

        m = cls._SLIDE_FILE_PATTERN.search(path)
        return Path(m.group()).stem if m else None

    def _check_and_adjust_max_rounds(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
        current_max: int,
        is_heavy: bool = False,
    ) -> int:
        """Check if this tool call created a new slide, and adjust max_rounds accordingly.

        Returns the (possibly increased) max_rounds value.
        """
        slide_name = self._try_detect_slide(fn_name, fn_args)
        if not slide_name:
            return current_max

        if slide_name in self._slide_paths:
            return current_max  # Already counted

        self._slide_paths.add(slide_name)
        self._detected_slide_count = len(self._slide_paths)

        if is_heavy and self._detected_slide_count > 0:
            # Recalculate: base(30) + count * multiplier(6) + buffer(10)
            adjusted = 30 + self._detected_slide_count * 6 + 10
            if adjusted > current_max:
                logger.info(
                    "[max_rounds] Detected %d slides, adjusting max_rounds: %d -> %d",
                    self._detected_slide_count, current_max, adjusted,
                )
                return adjusted

        return current_max

    @property
    def client(self) -> OpenAI:
        """Lazy-initialize the OpenAI client."""
        if self._client is None:
            self._client = OpenAI(
                api_key=self.config.get("api_key", ""),
                base_url=self.config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            )
        return self._client

    def _build_static_prompt(self) -> str:
        """Build and cache the static portion of the system prompt.

        These parts never change within a session: tool instructions, platform rules,
        output directory rules, HTML rules, and CLI preference rules.
        Called lazily on first access; result is cached indefinitely.
        """
        if self._static_prompt_cache is not None:
            return self._static_prompt_cache

        parts: list[str] = [self.config.get("system_prompt", "你是一个有帮助的 AI 助手。")]

        # ── Tool instructions ──
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
                "- Fetch web page content -> use web_fetch\n"
                "- Search locally installed skills -> use find_skills\n"
                "- Activate a specific skill -> use use_skill\n\n"
                "# CRITICAL: Batch File Editing Rule\n\n"
                "When editing files with edit_file:\n"
                "- ALWAYS read the file with read_file FIRST. NEVER guess file content.\n"
                "- After reading, identify ALL changes needed, then make them in ONE edit_file call.\n"
                "- Use LARGE old_text blocks that span MULTIPLE lines — replace entire sections at once,\n"
                "  not single lines one at a time. This is faster and avoids old_text mismatch errors.\n"
                "- Only split edits if the changes are in completely different, non-adjacent parts of\n"
                "  the file (more than 50 lines apart).\n"
                "BAD pattern (wastes rounds): read → edit 1 line → edit 1 line → edit 1 line\n"
                "GOOD pattern: read → ONE edit_file replacing the entire block that needs changes\n\n"
                "# Script Execution\n\n"
                "Use run_node for JavaScript/Node.js and run_python for Python.\n"
                "Both support: 'path' (script file) or 'code' (inline code), 'cwd' (working dir), 'timeout', 'args'.\n"
                "Examples:\n"
                '- run_node(path="build.js", cwd="my-ppt")\n'
                '- run_python(code="import os; print(os.getcwd())")\n'
                '- run_node(path="script.js", args="--production", timeout=120)\n\n'
                "# Platform: Windows / PowerShell\n\n"
                "This environment is Windows (PowerShell 5.1). ALL shell commands MUST use PowerShell syntax, NOT bash.\n"
                "Critical rules:\n"
                "- Use `mkdir \"path\"` NOT `mkdir -p path` (PowerShell doesn't support -p, creates literal '-p' dir)\n"
                "- Use `xcopy \"src\" \"dst\" /E /I /Y /Q` NOT `cp -r`\n"
                "- Use `Remove-Item \"path\" -Recurse -Force` NOT `rm -rf`\n"
                "- Use `Get-Content \"file\"` NOT `cat file`\n"
                "- Use `;` for command chaining, NOT `&&` (PowerShell 5.1 does NOT support `&&` at all)\n"
                "- Environment variables: use `$env:VAR=\"value\"` NOT `VAR=value` (bash syntax)\n"
                "  Example: `$env:NODE_OPTIONS=\"\"; node script.js` NOT `NODE_OPTIONS=\"\" node script.js`\n"
                "- To set env var for current process: `$env:VAR=\"value\"; your-command`\n"
                "- Paths use backslash `\\` or forward slash `/` (both work in PowerShell)\n"
                "- Never use bash-specific syntax: `mkdir -p`, `cp -r`, `rm -rf`, `&&`, `||`, `$(...)`, `VAR=val cmd`\n\n"
                f"# Output Directory\n\n"
                f"MiniAgent 安装目录: {self._miniagent_root}\n"
                f"所有生成的文件统一输出到: {self._miniagent_root / 'output'} 目录下。\n"
                f"每项新任务在 output/ 下创建唯一项目目录（如 output/项目名/），\n"
                f"同一对话中的所有文件都必须放到该项目目录内。\n"
                f"项目目录名一旦确定，整个对话过程不得更改，不要另建不同名的目录。\n"
                f"不要给项目目录加时间戳后缀。不要用 shell 检查/创建/重命名已有项目目录。\n"
                f"write_file 会自动创建父目录，直接写入即可。\n"
                f"shell/run_node/run_python 默认 cwd 已是 output/ 目录。\n"
                f"当需要进入项目子目录执行脚本时，直接 cd 子目录名即可（不要重复 output/）：\n"
                f'- shell(command="cd \\"项目名\\"; node build.js")  ← 正确\n'
                f'- run_node(path="build.js", cwd="项目名")           ← 更推荐，path 相对 cwd 解析\n\n'
                "# Document Saving Rule\n\n"
                "IMPORTANT: Whenever you generate a complete document (HTML page, Markdown file, "
                "JSON data, CSV data, code file, or any other structured content), you MUST call "
                "save_document to save it to disk. Do NOT just output the document in chat — "
                "always save it as a file so the user can find it later.\n\n"
                "Use tools proactively. When the user asks you to save, read, "
                "edit files, run commands or search for information, call the appropriate tool directly. "
                "Always tell the user what you're doing before/after tool calls."
            )

        # ── Self-Contained HTML Rule ──
        parts.append(
            "# CRITICAL: Self-Contained HTML Rule\n\n"
            "EVERY HTML file you generate MUST be fully self-contained — a single .html file that "
            "renders correctly when opened directly in a browser. This is the #1 rule for HTML output.\n"
            "What this means:\n"
            "- ALL CSS must be inside `<style>...</style>` tags in the `<head>`, NOT `<link href=\"...\">`\n"
            "- ALL JavaScript must be inside `<script>...</script>` tags, NOT `<script src=\"...\">`\n"
            "- Use `read_file` to read the content of any needed CSS/JS file, then paste it inline\n"
            "- CDN font imports (Google Fonts `@import url(...)`) are the ONLY allowed external references\n"
            "- NEVER write `<link href=\"*.css\">` or `<script src=\"*.js\">` — always inline instead\n"
            "- CRITICAL: If any inlined JS contains the literal string `</script>` (e.g. inside a "
            "template literal), you MUST escape it as `<\\/script>`. Otherwise the HTML parser "
            "will terminate the `<script>` element prematurely, dumping raw JS onto the page.\n"
        )

        # ── CLI preference rule ──
        parts.append(
            "# CRITICAL: Prefer CLI over Python scripts for one-off operations\n\n"
            "When a task can be done with a single shell command (e.g. file conversion, "
            "text processing, downloading), use the `shell` tool directly. Do NOT write "
            "multi-line Python scripts for simple operations. Writing code adds unnecessary "
            "risk of syntax errors, encoding issues, and `\\n` literal confusion.\n"
            "File conversion tools — use via `shell`, NOT `run_node`:\n"
            "- markitdown: Python CLI (pip install markitdown). NOT a Node.js module. "
            "Convert Office→Markdown: `markitdown input.docx -o output.md`\n"
            "- pandoc: Convert Markdown→Word: `pandoc input.md -o output.docx`\n"
            "- When pandoc is unavailable, use the `docx` skill for Word documents\n"
            "Other CLI examples:\n"
            "- Process text: `rg 'pattern' file.txt` or `sed` (CLI) ✓\n"
            "- Create files: use the `write_file` tool directly ✓\n"
        )

        self._static_prompt_cache = "\n\n---\n\n".join(parts)
        return self._static_prompt_cache

    def _build_skills_context(self) -> str:
        """Build and cache the skills-related portion of the system prompt.

        Includes always-active skills content and the available-skills summary.
        Invalidated on reload_skills().
        """
        if self._skills_context_cache is not None:
            return self._skills_context_cache

        parts: list[str] = []

        # Always-active skills
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.build_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # Skills summary
        summary = self.skills.build_summary()
        if summary:
            parts.append(
                f"# Available Skills\n\n"
                f"Skills are knowledge/instruction packs that auto-activate when user keywords match. "
                f"They are NOT tools — use the 'find_skills' tool to search skills and "
                f"the 'use_skill' tool to explicitly load a skill's instructions.\n"
                f"Available skills (auto-match by keywords):\n\n"
                f"{summary}"
            )

        self._skills_context_cache = "\n\n---\n\n".join(parts) if parts else ""
        return self._skills_context_cache

    def build_system_prompt(self) -> str:
        """Build the stable system prompt (Layers 1+2 only).

        Returns ONLY static tool instructions + always-active skills + skills summary.
        This content is IDENTICAL across all chat() calls within a session,
        enabling LLM server-side prefix caching (KV cache reuse for ~4KB+ of tokens).
        Dynamic per-call skills are returned separately via _build_dynamic_messages().
        """
        parts: list[str] = []

        # Layer 1: static prompt (cached, never rebuilds)
        parts.append(self._build_static_prompt())

        # Layer 2: skills context (cached, invalidated on reload_skills())
        skills_ctx = self._build_skills_context()
        if skills_ctx:
            parts.append(skills_ctx)

        return "\n\n---\n\n".join(parts)

    def _build_dynamic_messages(
        self,
        active_skills: list[Skill] | None = None,
    ) -> list[dict[str, Any]]:
        """Build per-call dynamic system messages for Layer 3 content.

        Returns a list of messages (system role) to be inserted after the stable
        system prompt. These contain call-specific skill activations and html-ppt
        architecture guidance.

        Separating dynamic content from the stable system prompt ensures the main
        system message is byte-for-byte identical across calls, which is critical
        for LLM server-side prefix/KV caching.
        """
        messages: list[dict[str, Any]] = []
        always_skills = self.skills.get_always_skills()
        always_names = {s.name for s in always_skills}

        # Specifically activated skills (not always-active)
        if active_skills:
            extra = [s for s in active_skills if s.name not in always_names]
            if extra:
                extra_content = self.skills.build_context(extra)
                if extra_content:
                    messages.append({
                        "role": "system",
                        "content": f"# Activated Skills (this request only)\n\n{extra_content}",
                    })

        # html-ppt architecture guidance
        all_active = list(always_skills)
        if active_skills:
            all_active.extend(s for s in active_skills if s.name not in always_names)
        html_ppt = next((s for s in all_active if s.name == "html-ppt"), None)
        if html_ppt:
            assets_dir = html_ppt.path.parent / 'assets'
            messages.append({
                "role": "system",
                "content": (
                    "# html-ppt Slide Architecture (READ BEFORE GENERATING — OR RESULT WILL BE BROKEN)\n\n"
                    "The html-ppt skill provides a complete slide system. You MUST use it. "
                    "NEVER write custom CSS/JS to replace the slide engine — your job is ONLY to write "
                    "the slide CONTENT (text, layouts, cards) inside the skill's structure.\n\n"
                    "## Mandatory Architecture (non-negotiable)\n\n"
                    "Every slide deck MUST follow this exact structure:\n"
                    "```\n"
                    "<div class=\"deck\">\n"
                    "  <section class=\"slide is-active\" data-title=\"Slide 1\">\n"
                    "    <!-- YOUR CONTENT HERE -->\n"
                    "    <aside class=\"notes\"><!-- speaker notes (optional) --></aside>\n"
                    "  </section>\n"
                    "  <section class=\"slide\" data-title=\"Slide 2\">\n"
                    "    <!-- YOUR CONTENT HERE -->\n"
                    "  </section>\n"
                    "  ...\n"
                    "</div>\n"
                    "<div style=\"position:fixed;bottom:12px;left:12px;font-size:11px;color:#888;z-index:100;pointer-events:none\">\n"
                    "  S — 演讲者视图 · T — 切换主题 · ← → — 翻页 · F — 全屏 · O — 总览\n"
                    "</div>\n"
                    "<script>/* runtime.js content here */</script>\n"
                    "```\n\n"
                    "## Rules\n"
                    "1. **One `<section class=\"slide\">` per logical page** — 5 slides means 5 `<section>` elements.\n"
                    "2. **base.css IS the slide engine** — its `.deck` (viewport container) and `.slide` (absolute overlay) "
                    "CSS must be inlined. Without it, slides collapse into a scrollable document.\n"
                    "3. **runtime.js IS the keyboard navigator** — ← → space PgUp PgDn S T F O keys. MUST be inlined at bottom.\n"
                    "4. **DO NOT write your own slide code** — no scroll-based nav, no IntersectionObserver, no margin-bottom slides, "
                    "no custom animation frameworks. All of that is already in base.css + runtime.js.\n"
                    "5. If slides look like a scrolling document instead of paginated — you did something wrong.\n\n"
                    "## How to inline (use read_file)\n"
                    f"Read these from {assets_dir} and paste inline:\n"
                    f"  1. `{assets_dir / 'fonts.css'}` → <style> (CDN @import rules — only external refs allowed)\n"
                    f"  2. `{assets_dir / 'base.css'}` → <style> (MANDATORY — the slide engine)\n"
                    f"  3. `{assets_dir / 'themes' / '<chosen>.css'}` → <style> (pick ONE theme)\n"
                    f"  4. `{assets_dir / 'animations' / 'animations.css'}` → <style> (if using data-anim)\n"
                    f"  5. `{assets_dir / 'runtime.js'}` → <script> at end of <body> (MANDATORY — keyboard nav)\n"
                    f"  6. `{assets_dir / 'animations' / 'fx-runtime.js'}` + fx/*.js → <script> (only if using data-fx)\n\n"
                    "## DO NOT\n"
                    "- Omit base.css or runtime.js\n"
                    "- Write custom scrolling/IntersectionObserver/navigation code\n"
                    "- Make slides display as a vertical document (margin-bottom, scroll behavior)\n"
                    "- Use `<link href=\"...\">` or `<script src=\"...\">` — always inline\n"
                ),
            })

        return messages

    def _parse_at_commands(self, user_input: str) -> tuple[str, list[Skill]]:
        """Parse @skill-name commands from user input.

        Returns:
            Tuple of (cleaned_input, list of activated Skill objects).
            cleaned_input has @skill-name references removed.
        """
        import re
        activated: list[Skill] = []
        cleaned = user_input

        # Match @skill-name patterns (skill names: letters, digits, hyphens)
        at_pattern = re.compile(r'@([a-zA-Z][a-zA-Z0-9_-]*)')
        for match in at_pattern.finditer(user_input):
            skill_name = match.group(1)
            skill = self.skills.get(skill_name)
            if skill:
                activated.append(skill)

        # Remove @skill-name from the input (clean up extra spaces)
        cleaned = at_pattern.sub('', cleaned).strip()
        # Collapse multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        return cleaned, activated

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
        # Parse @skill-name commands from input
        cleaned_input, at_skills = self._parse_at_commands(user_input)

        # Match skills
        matched_skills = list(active_skills or [])
        matched_skills.extend(at_skills)
        # If user explicitly activated skills (via @ or active_skills param),
        # suppress auto-match to avoid polluting with conflicting skill instructions
        if matched_skills:
            auto_match = False
        if auto_match:
            auto_matched = self.skills.match_triggers(cleaned_input)
            # Deduplicate by name
            existing_names = {s.name for s in matched_skills}
            for s in auto_matched:
                if s.name not in existing_names:
                    matched_skills.append(s)
                    existing_names.add(s.name)

        # Build stable system prompt (identical every call → LLM KV cache hit)
        system_prompt = self.build_system_prompt()

        # Build messages: stable system + dynamic skills + history + user input
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Append per-call dynamic system messages (extra skills, html-ppt guidance)
        dynamic_msgs = self._build_dynamic_messages(matched_skills)
        messages.extend(dynamic_msgs)

        messages.extend(self.history)
        messages.append({"role": "user", "content": cleaned_input if cleaned_input else user_input})
        prefix_count = len(messages)  # system + history + user — never trimmed

        # Log matched skills
        if matched_skills:
            names = [s.name for s in matched_skills]
            print(f"\n  [Skills: {', '.join(names)}]")

        # Tool calling loop
        self._tool_calls_count = 0
        tool_definitions = self.tools.get_definitions()

        # Dynamically estimate max rounds based on task complexity
        max_rounds = self._estimate_max_rounds(user_input, matched_skills)

        # Determine if this is a PPT/doc task (for dynamic slide-count adjustment)
        _skill_names: set[str] = {s.name for s in matched_skills}
        _is_heavy = bool(_skill_names & self._HEAVY_SKILLS)

        # Reset slide tracking for this chat call
        self._detected_slide_count = 0
        self._slide_paths.clear()

        # Track consecutive failures to break infinite retry loops
        _consecutive_failures: dict[str, int] = {}
        _MAX_CONSECUTIVE_FAILURES = 3

        # Token usage accumulator for this chat() call
        _call_prompt_tokens = 0
        _call_completion_tokens = 0

        # Progress checkpoint tracking (for PPT/doc tasks)
        _round_counter = 0
        _CHECKPOINT_INTERVAL = 5  # Inject progress summary every N LLM rounds

        while self._tool_calls_count < max_rounds:
            # Call LLM
            kwargs: dict[str, Any] = {
                "model": self.config.get("model", "qwen-plus"),
                "messages": messages,
                "temperature": self.config.get("temperature", 0.7),
                "max_tokens": self.config.get("max_tokens", 32768),
            }
            if tool_definitions:
                kwargs["tools"] = tool_definitions

            # Debug log: dump full prompt sent to LLM (truncate individual msgs)
            logger.debug(
                "[llm_request] round=%d, model=%s, max_tokens=%d, temp=%.1f, "
                "msg_count=%d, tools=%d",
                self._tool_calls_count, kwargs['model'], kwargs['max_tokens'],
                kwargs['temperature'], len(messages), len(tool_definitions),
            )
            _req_lines = ["=== LLM REQUEST ==="]
            for _i, _m in enumerate(messages):
                _role = _m.get("role", "?")
                _content = str(_m.get("content", "") or "")
                _tc = _m.get("tool_calls")
                _tcid = _m.get("tool_call_id", "")
                if _tc:
                    _tc_parts = []
                    for _t in _tc:
                        _fn = _t.get("function", {})
                        _tc_parts.append(
                            f"{_fn.get('name','?')}(args={_fn.get('arguments','')[:200]})"
                        )
                    _req_lines.append(
                        f"[{_i}] role={_role}, tool_calls=[{'; '.join(_tc_parts)}]"
                    )
                elif _tcid:
                    _req_lines.append(
                        f"[{_i}] role={_role}, tool_call_id={_tcid}, "
                        f"content={_content[:500]}"
                    )
                else:
                    _req_lines.append(
                        f"[{_i}] role={_role}, content={_content[:800]}"
                    )
            _req_lines.append("=== END LLM REQUEST ===")
            logger.debug("\n".join(_req_lines))

            try:
                resp = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                error_text = log_api_error(e, "CLI API call", messages)
                self._update_history(user_input, error_text)
                return error_text

            # ── Token usage: log per-round & accumulate ──
            if resp.usage:
                pt = resp.usage.prompt_tokens or 0
                ct = resp.usage.completion_tokens or 0
                tt = resp.usage.total_tokens or pt + ct
                _call_prompt_tokens += pt
                _call_completion_tokens += ct
                logger.info(
                    "[token_usage] round=%d, prompt_tokens=%d, completion_tokens=%d, total=%d",
                    self._tool_calls_count, pt, ct, tt,
                )
            else:
                logger.debug("[token_usage] round=%d, usage=N/A (not returned by API)", self._tool_calls_count)

            choice = resp.choices[0]
            message = choice.message

            # Debug: log full LLM response with boundary markers
            _resp_parts = [
                f"[llm_response] round={self._tool_calls_count}, "
                f"model={kwargs['model']}, finish_reason={choice.finish_reason}",
            ]
            if message.content:
                _resp_parts.append(
                    f"=== LLM RAW RESPONSE (text, len={len(message.content)}) ===\n"
                    f"{message.content[:3000]}\n"
                    f"=== END LLM RAW RESPONSE ==="
                )
            if message.tool_calls:
                _tc_lines = ["=== LLM RAW RESPONSE (tool_calls) ==="]
                for tc in message.tool_calls:
                    _tc_lines.append(
                        f"  {tc.function.name}({tc.function.arguments or '{}'})"
                    )
                _tc_lines.append("=== END LLM RAW RESPONSE ===")
                _resp_parts.append("\n".join(_tc_lines))
            if resp.usage:
                _resp_parts.append(
                    f"usage: prompt={resp.usage.prompt_tokens}, "
                    f"completion={resp.usage.completion_tokens}, "
                    f"total={resp.usage.total_tokens}"
                )
            logger.debug("\n".join(_resp_parts))

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
                self._update_history(user_input, response_text,
                                     prompt_tokens=_call_prompt_tokens,
                                     completion_tokens=_call_completion_tokens)
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
                        self._update_history(user_input, response_text,
                                             prompt_tokens=_call_prompt_tokens,
                                             completion_tokens=_call_completion_tokens)
                        return response_text
                    # Still execute with empty args to give feedback to LLM
                    fn_args = {}

                # Log tool call
                arg_preview = ", ".join(f"{k}={repr(v)[:60]}" for k, v in fn_args.items())
                print(f"  [Tool: {fn_name}({arg_preview})]")

                # Execute
                result = self.tools.execute(fn_name, fn_args)
                self._tool_calls_count += 1

                # Dynamically adjust max_rounds if new slides/pages detected
                if _is_heavy:
                    max_rounds = self._check_and_adjust_max_rounds(
                        fn_name, fn_args, max_rounds, is_heavy=True,
                    )

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

                # Truncate result to save context tokens
                truncated_result = self._truncate_tool_result(fn_name, result)

                # Log result (truncated for console display)
                if len(result) > 200:
                    print(f"  [Result: {result[:200]}...]")
                else:
                    print(f"  [Result: {result}]")

                # Add tool result to messages (truncated version)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": truncated_result,
                })

            # Sliding window: trim old tool messages to control context size.
            # For PPT/doc tasks, scale history window by detected slide count
            # so the model retains context of all previously generated slides
            # (prevents infinite re-reading loops on large PPTs).
            config_history = self.config.get("max_tool_history", 20)
            if self._detected_slide_count > 0:
                # Each slide ≈ 6 rounds (12 tool msgs); keep all + buffer
                max_tool_msgs = max(config_history, self._detected_slide_count * 12 + 20)
            else:
                max_tool_msgs = max(config_history, max_rounds)
            tool_msg_count = len(messages) - prefix_count
            if max_tool_msgs > 0 and tool_msg_count > max_tool_msgs:
                excess = tool_msg_count - max_tool_msgs
                # Keep prefix intact, only trim the tool-message suffix
                del messages[prefix_count:prefix_count + excess]
                logger.debug(
                    "[chat] Trimmed %d old tool messages (kept %d, total=%d)",
                    excess, max_tool_msgs, len(messages),
                )

            # ── Progress checkpoint: inject summary for PPT/doc tasks ──
            # Use in-place replace (not insert) to keep prefix structure stable
            # for LLM prompt caching.
            _round_counter += 1
            if (
                _is_heavy
                and _round_counter % _CHECKPOINT_INTERVAL == 0
                and self._detected_slide_count > 0
            ):
                slide_names = sorted(self._slide_paths)
                overview = ", ".join(slide_names[:8])
                if len(slide_names) > 8:
                    overview += f"... (共 {len(slide_names)} 个)"
                checkpoint_msg = {
                    "role": "system",
                    "content": (
                        f"[进度] 第 {_round_counter} 轮 LLM 调用: "
                        f"已生成 {self._detected_slide_count} 个 slide 文件 ({overview})，"
                        f"共 {self._tool_calls_count} 次工具调用"
                    ),
                }
                # Replace existing checkpoint in-place, or insert on first time
                existing = messages[prefix_count] if len(messages) > prefix_count else None
                if existing is not None and existing.get("role") == "system":
                    messages[prefix_count] = checkpoint_msg
                else:
                    messages.insert(prefix_count, checkpoint_msg)
                    prefix_count += 1
                logger.debug(
                    "[chat] Injected progress checkpoint at round %d: %d slides",
                    _round_counter, self._detected_slide_count,
                )

        # Exceeded max tool rounds
        response_text = (
            f"[Notice] 已达到最大工具调用轮次 ({max_rounds})。请重试或简化请求。"
        )
        self._update_history(user_input, response_text,
                             prompt_tokens=_call_prompt_tokens,
                             completion_tokens=_call_completion_tokens)
        return response_text

    def _update_history(
        self,
        user_input: str,
        response_text: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """Update conversation history (clean, without tool artifacts).

        Args:
            user_input: The user's message.
            response_text: The assistant's response.
            prompt_tokens: Total prompt tokens across all LLM rounds for this call.
            completion_tokens: Total completion tokens across all LLM rounds.
        """
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": response_text})

        # Save to database for persistence
        try:
            self.db.save_conversation_pair(
                user_input=user_input,
                assistant_response=response_text,
                session_id=self.session_id
            )

            # Accumulate token usage for this session
            if prompt_tokens or completion_tokens:
                self.db.update_session_tokens(
                    session_id=self.session_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                # Fetch running session totals for summary log
                session_totals = self.db.get_session_tokens(self.session_id)
                logger.info(
                    "[token_usage] call_summary: prompt=%d, completion=%d, total=%d | "
                    "session_total: prompt=%d, completion=%d, total=%d",
                    prompt_tokens, completion_tokens, prompt_tokens + completion_tokens,
                    session_totals["prompt_tokens"],
                    session_totals["completion_tokens"],
                    session_totals["total_tokens"],
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
        switch_debug_session(new_id)
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
        switch_debug_session(session_id)
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
        """Reload skills from disk and invalidate skills-related caches."""
        self.skills.reload()
        self._skills_context_cache = None  # Invalidate: always-skills content / summary may have changed
