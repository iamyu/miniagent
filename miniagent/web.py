"""MiniAgent Web Server - FastAPI backend with WebSocket chat support."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .chat import ChatEngine
from .config import load_config, save_config as persist_config, get_config_path, get_app_dir
from .skills import Skill
from .utils import sanitize_tool_arguments, validate_tool_args, log_api_error, logger
from openai import AsyncOpenAI


# ---------------------------------------------------------------------------
# WS Safe Send Helper
# ---------------------------------------------------------------------------

async def _ws_safe_send(ws: WebSocket, data: dict) -> bool:
    """Safely send JSON data via WebSocket.

    Returns True if send succeeded, False if connection is closed.
    Callers should check the return value and stop processing on False.
    """
    try:
        await ws.send_json(data)
        return True
    except Exception:
        return False


async def _check_ws_alive(ws: WebSocket) -> bool:
    """Check if WebSocket connection is still alive.

    Uses FastAPI's client_state to detect disconnection.
    Returns False if the client has disconnected.
    """
    try:
        from starlette.websockets import WebSocketState
        return ws.client_state == WebSocketState.CONNECTED
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tool Arguments Validation
# ---------------------------------------------------------------------------

def _filter_valid_tool_calls(
    tool_calls_data: dict[int, dict],
    consecutive_failures: dict[str, int],
    max_consecutive_failures: int = 3,
) -> list[dict]:
    """Filter and validate collected tool calls.

    Sanitizes arguments, validates JSON parse and content completeness.
    Tracks consecutive failures per tool name to break infinite retry loops.

    Args:
        tool_calls_data: Raw accumulated tool call data from streaming.
        consecutive_failures: Dict tracking consecutive failures per tool name (mutated).
        max_consecutive_failures: Max allowed consecutive failures before rejecting.

    Returns:
        List of valid tool call dicts, each with keys:
            data, sanitized_args, parsed_args, sanitized_args_str
    """
    valid: list[dict] = []

    for idx in sorted(tool_calls_data.keys()):
        tc = tool_calls_data[idx]
        args_raw = tc.get("arguments", "")
        name = tc.get("name", "unknown")

        # Check for accumulated consecutive failures
        fail_count = consecutive_failures.get(name, 0)
        if fail_count >= max_consecutive_failures:
            logger.warning(
                f"[ws_stream] Tool '{name}' has failed {fail_count} times "
                f"consecutively (max={max_consecutive_failures}), skipping"
            )
            continue

        # Sanitize and parse JSON
        sanitized = sanitize_tool_arguments(args_raw, name)
        try:
            parsed = json.loads(sanitized)
            if not isinstance(parsed, dict):
                parsed = {}
        except json.JSONDecodeError:
            logger.error(
                f"[ws_stream] Tool '{name}' args parse FAILED even after "
                f"sanitize: raw_len={len(args_raw)}, raw_preview={args_raw[:200]}"
            )
            consecutive_failures[name] = consecutive_failures.get(name, 0) + 1
            continue

        # Validate argument completeness (shared utility from utils.py)
        is_valid, msg = validate_tool_args(name, parsed)
        if not is_valid:
            logger.warning(
                f"[ws_stream] Tool '{name}' args validation FAILED: {msg}. "
                f"content_len={len(parsed.get('content', '') or '')}"
            )
            consecutive_failures[name] = consecutive_failures.get(name, 0) + 1
            continue

        # Success: reset failure counter
        consecutive_failures.pop(name, None)

        valid.append({
            "data": tc,
            "sanitized_args": sanitized,
            "parsed_args": parsed,
        })

    return valid


def _track_tool_failure(tool_name: str, result: str, consecutive_failures: dict[str, int]) -> None:
    """Update consecutive failure tracking based on tool result."""
    if "Error" in result or "失败" in result:
        consecutive_failures[tool_name] = consecutive_failures.get(tool_name, 0) + 1
        logger.warning(
            f"[ws_tool] Tool '{tool_name}' failed (consecutive={consecutive_failures[tool_name]}): "
            f"result={result[:200]}"
        )
    else:
        consecutive_failures.pop(tool_name, None)


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="MiniAgent", version="1.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine (lazy-init on first request)
_engine: ChatEngine | None = None
_static_dir = Path(__file__).resolve().parent / "static"


def get_engine() -> ChatEngine:
    """Get or create the chat engine singleton."""
    global _engine
    if _engine is None:
        _engine = ChatEngine()
    return _engine


def _reset_engine() -> None:
    """Reset engine (e.g. after config change)."""
    global _engine
    _engine = None


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def api_config():
    """Return current config (sensitive fields masked)."""
    cfg = load_config()
    return {
        "model": cfg.get("model", "qwen-plus"),
        "base_url": cfg.get("base_url", ""),
        "temperature": cfg.get("temperature", 0.7),
        "max_tokens": cfg.get("max_tokens", 32768),
        "max_history": cfg.get("max_history", 20),
        "max_tool_history": cfg.get("max_tool_history", 20),
        "has_api_key": bool(cfg.get("api_key")),
    }


@app.post("/api/config")
async def api_save_config(data: dict[str, Any]):
    """Save configuration values to user-level config file."""
    allowed_keys = {"model", "base_url", "temperature", "max_tokens", "max_history", "max_tool_history", "api_key"}
    update = {k: v for k, v in data.items() if k in allowed_keys}

    if "max_tokens" in update:
        try:
            update["max_tokens"] = int(update["max_tokens"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "max_tokens 必须为整数"}

    if "temperature" in update:
        try:
            update["temperature"] = float(update["temperature"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "temperature 必须为数字"}

    if not update:
        return {"ok": False, "error": "没有有效的配置项"}

    # Merge with existing config (preserve keys not in update)
    existing = load_config()
    existing.update(update)
    persist_config(existing)

    # Reset engine so next request picks up new config
    _reset_engine()

    logger.info(f"[config] saved: {json.dumps({k: v for k, v in update.items() if k != 'api_key'}, ensure_ascii=False)}")
    return {"ok": True}


@app.post("/api/open-file")
async def api_open_file(data: dict[str, Any]):
    """Open a local file with the OS default application."""
    import os
    import subprocess
    import platform

    filepath = data.get("path", "")
    if not filepath:
        return {"ok": False, "error": "缺少 path 参数"}

    path = Path(filepath)
    if not path.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(str(path))
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/tools")
async def api_tools():
    """Return list of available tools."""
    engine = get_engine()
    tools = []
    for name in engine.tools.tool_names:
        tool = engine.tools.get(name)
        if tool:
            tools.append({
                "name": tool.name,
                "description": tool.description,
            })
    return tools


@app.get("/api/skills")
async def api_skills():
    """Return list of available skills."""
    engine = get_engine()
    skills = engine.skills.list_all()
    result = []
    for s in skills:
        result.append({
            "name": s.name,
            "description": s.description,
            "always": s.always,
            "triggers": s.triggers or [],
        })
    return result


@app.get("/api/history")
async def api_history(limit: int = 50):
    """Return conversation history from database."""
    engine = get_engine()
    try:
        history = engine.load_history_from_db(limit=limit)
        return {"history": history, "count": len(history)}
    except Exception as e:
        return {"error": str(e), "history": [], "count": 0}


@app.get("/api/recent-sessions")
async def api_recent_sessions(limit: int = 10):
    """Return recent conversation sessions with first message preview."""
    engine = get_engine()
    try:
        sessions = engine.db.get_all_sessions(limit=limit)
        return {"sessions": sessions}
    except Exception as e:
        return {"error": str(e), "sessions": []}


@app.post("/api/new-session")
async def api_new_session():
    """Start a new conversation session.

    The current session is preserved in the database with an auto-generated title.
    Returns the new session_id.
    """
    engine = get_engine()
    new_id = engine.new_session()
    return {"status": "ok", "session_id": new_id}


@app.get("/api/sessions/{session_id}/messages")
async def api_session_messages(session_id: str, limit: int = 100):
    """Get all messages for a specific session."""
    engine = get_engine()
    try:
        messages = engine.db.get_session_messages(session_id, limit=limit)
        return {"session_id": session_id, "messages": messages, "count": len(messages)}
    except Exception as e:
        return {"error": str(e), "messages": [], "count": 0}


@app.post("/api/sessions/{session_id}/switch")
async def api_switch_session(session_id: str):
    """Switch to an existing session and load its history into the engine."""
    engine = get_engine()
    messages = engine.switch_to_session(session_id)
    return {"status": "ok", "session_id": session_id, "messages": messages}


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str):
    """Delete a session and all its messages."""
    engine = get_engine()
    try:
        engine.db.clear_history(session_id)
        return {"status": "ok", "session_id": session_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/chat")
async def api_chat(body: dict[str, Any]):
    """Synchronous chat endpoint."""
    engine = get_engine()
    user_input = body.get("message", "").strip()
    if not user_input:
        return {"error": "message is required"}

    # Handle slash commands
    if user_input.startswith("/"):
        return _handle_command(engine, user_input)

    # Handle @skill-name commands
    if user_input.startswith("@"):
        cleaned, at_skills = engine._parse_at_commands(user_input)
        if at_skills:
            try:
                response = await asyncio.to_thread(
                    engine.chat, user_input,
                    active_skills=at_skills,
                    auto_match=False,  # User explicitly chose a skill — don't auto-match others
                )
                return {"response": response}
            except Exception as e:
                return {"error": str(e)}

    try:
        response = await asyncio.to_thread(engine.chat, user_input)
        return {"response": response}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/clear")
async def api_clear():
    """Clear chat history."""
    engine = get_engine()
    engine.clear_history()
    return {"status": "ok"}


@app.post("/api/reload-skills")
async def api_reload_skills():
    """Reload skills from disk."""
    engine = get_engine()
    engine.reload_skills()
    return {"status": "ok", "count": len(engine.skills.list_all())}


@app.get("/api/browse-files")
async def api_browse_files(path: str = ""):
    """Browse files within the project directory (MiniAgent root).
    
    Returns a directory tree for building a file picker UI.
    Only allows browsing within the project root directory.
    
    Args:
        path: Relative path within project root (empty = root)
    """
    import os as _os
    
    # Determine project root (d:\AI\miniagent\)
    project_root = Path(__file__).resolve().parent.parent
    
    # Resolve the requested path relative to project root
    if path:
        # Normalize path separators and remove any leading slashes
        clean_path = path.replace('\\', '/').strip('/')
        target = (project_root / clean_path).resolve()
    else:
        target = project_root.resolve()
    
    # Security: ensure target is within project root
    try:
        target.relative_to(project_root.resolve())
    except ValueError:
        return {"error": "禁止访问项目目录以外的路径", "tree": []}
    
    if not target.exists() or not target.is_dir():
        return {"error": "目录不存在", "tree": []}
    
    # Files/dirs to exclude from browsing
    EXCLUDE_DIRS = {
        '.git', '__pycache__', '.codebuddy', 'node_modules',
        '.venv', 'venv', '.pytest_cache', '.mypy_cache',
        '.egg-info', '.workbuddy',
    }
    EXCLUDE_FILES = {'.DS_Store', 'Thumbs.db', '.gitignore'}
    
    # Calculate relative path from project root (for display)
    try:
        rel_path = str(target.relative_to(project_root.resolve()))
        if rel_path == '.':
            rel_path = ''
    except ValueError:
        rel_path = ''
    
    items = []
    try:
        with _os.scandir(str(target)) as entries:
            for entry in sorted(entries, key=lambda e: (not e.is_dir(), e.name.lower())):
                if entry.name.startswith('.'):
                    continue
                if entry.is_dir():
                    if entry.name in EXCLUDE_DIRS:
                        continue
                    items.append({
                        "name": entry.name,
                        "type": "dir",
                        "path": _os.path.join(rel_path, entry.name).replace('\\', '/'),
                    })
                elif entry.is_file():
                    if entry.name in EXCLUDE_FILES:
                        continue
                    items.append({
                        "name": entry.name,
                        "type": "file",
                        "path": _os.path.join(rel_path, entry.name).replace('\\', '/'),
                    })
    except PermissionError:
        return {"error": "无权限访问该目录", "tree": []}
    
    return {
        "root": str(project_root),
        "current_path": rel_path,
        "tree": items,
    }


# ---------------------------------------------------------------------------
# WebSocket Streaming Chat
# ---------------------------------------------------------------------------

@app.websocket("/api/ws")
async def ws_chat(ws: WebSocket):
    """WebSocket endpoint for streaming chat."""
    await ws.accept()

    engine = get_engine()
    ws_connected = True  # Track connection state for this session

    try:
        while ws_connected:
            # Receive message with timeout to detect stale connections
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=300)
            except asyncio.TimeoutError:
                # No message for 5 min — connection is stale, close gracefully
                logger.info("[WS] No message received for 300s, closing idle connection")
                break

            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await _ws_safe_send(ws, {"type": "error", "content": "Invalid JSON message"})
                continue

            user_input = msg.get("message", "").strip()

            if not user_input:
                await _ws_safe_send(ws, {"type": "error", "content": "message is required"})
                continue

            # Handle commands
            if user_input.startswith("/"):
                cmd_result = _handle_command(engine, user_input)
                await _ws_safe_send(ws, cmd_result)
                continue

            # Stream the chat response
            try:
                await _stream_chat(engine, ws, user_input)
            except WebSocketDisconnect:
                ws_connected = False
                raise
            except Exception as e:
                logger.error(f"[WS] Error in _stream_chat: {e}")
                ws_connected = False
                try:
                    await ws.send_json({"type": "error", "content": str(e)})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.error(f"[WS] Unexpected error: {e}")
    finally:
        # Cleanup: ensure any pending state is cleared
        logger.info("[WS] Connection closed")


async def _stream_chat(engine: ChatEngine, ws: WebSocket, user_input: str):
    """Stream a chat response via WebSocket with tool call execution.

    Architecture:
      1. Phase 1 (collect): All streaming chunks appended to memory buffers.
         Text → frontend in real-time; tool args → accumulated locally.
      2. Phase 2 (validate): After stream ends, parse & validate tool arguments.
         Incomplete/truncated args are rejected with error feedback.
      3. Phase 3 (execute): Only validated tools execute serially.
         File writes are never triggered with incomplete content.

    Fault tolerance:
      - Connection state checked before every ws.send_json().
      - On disconnect: stop chunk collection, clear buffer, return immediately.
      - Consecutive tool failures tracked; same tool rejected after N failures.
      - API errors return immediately (no retry loop).
    """
    # --- Skill matching & system prompt ---
    # Parse @skill-name commands from input
    cleaned_input, at_skills = engine._parse_at_commands(user_input)

    matched_skills: list[Skill] = []
    matched_skills.extend(at_skills)
    # Only auto-match if user didn't explicitly specify a skill via @
    if not at_skills:
        auto_matched = engine.skills.match_triggers(cleaned_input)
        existing_names = {s.name for s in matched_skills}
        for s in auto_matched:
            if s.name not in existing_names:
                matched_skills.append(s)
                existing_names.add(s.name)

    # Build stable system prompt (identical every call → LLM KV cache hit)
    system_prompt = engine.build_system_prompt()

    if matched_skills:
        names = [s.name for s in matched_skills]
        await _ws_safe_send(ws, {
            "type": "status",
            "content": f"Skills: {', '.join(names)}"
        })

    # --- Build messages for API ---
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    # Append per-call dynamic system messages (extra skills, html-ppt guidance)
    dynamic_msgs = engine._build_dynamic_messages(matched_skills)
    messages.extend(dynamic_msgs)

    messages.extend(engine.history)
    # Use cleaned_input (with @skill-name removed) if non-empty, otherwise use original
    llm_input = cleaned_input if cleaned_input else user_input
    messages.append({"role": "user", "content": llm_input})
    prefix_count = len(messages)  # system + history + user — never trimmed

    tool_definitions = engine.tools.get_definitions()
    tool_rounds = 0
    max_rounds = engine._estimate_max_rounds(user_input, matched_skills)

    # Determine if this is a PPT task (for dynamic slide-count adjustment)
    _skill_names: set[str] = {s.name for s in matched_skills}
    _is_heavy = bool(_skill_names & engine._HEAVY_SKILLS)

    # Reset slide tracking for this chat call
    engine._detected_slide_count = 0
    engine._slide_paths.clear()

    # Track consecutive failures per tool name to break infinite retry loops
    consecutive_failures: dict[str, int] = {}
    MAX_CONSECUTIVE_FAILURES = 3

    # Token usage accumulators for this streaming chat call
    _call_prompt_tokens = 0
    _call_completion_tokens = 0

    # Progress checkpoint tracking (for PPT/doc tasks)
    _round_counter = 0
    _CHECKPOINT_INTERVAL = 5  # Inject progress summary every N LLM rounds

    # --- Async HTTP client ---
    _http_timeout = httpx.Timeout(30.0, connect=30.0, read=600.0, write=30.0, pool=10.0)
    async_client = AsyncOpenAI(
        api_key=engine.config.get("api_key", ""),
        base_url=engine.config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        http_client=httpx.AsyncClient(timeout=_http_timeout),
    )

    while tool_rounds < max_rounds:
        kwargs: dict[str, Any] = {
            "model": engine.config.get("model", "qwen-plus"),
            "messages": messages,
            "temperature": engine.config.get("temperature", 0.7),
            "max_tokens": engine.config.get("max_tokens", 32768),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tool_definitions:
            kwargs["tools"] = tool_definitions

        # Debug log: dump full prompt sent to LLM (truncate individual msgs)
        logger.debug(
            "[llm_request] round=%d, model=%s, max_tokens=%d, temp=%.1f, "
            "msg_count=%d, tools=%d",
            tool_rounds, kwargs['model'], kwargs['max_tokens'],
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

        # ================================================================
        # Phase 1: Collect streaming data into memory buffers
        # ================================================================
        try:
            stream = await async_client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error(
                f"[ws_stream] API call failed at round={tool_rounds}: {e}. "
                f"Stopping — no retry."
            )
            await _ws_safe_send(ws, {
                "type": "error",
                "content": f"API 调用失败: {e}"
            })
            return  # Stop immediately — don't re-enter the while loop

        content_parts: list[str] = []       # Accumulated text chunks
        tool_calls_data: dict[int, dict] = {}  # index → {id, name, arguments}
        tool_name_notified: set[int] = set()   # track which tool_start events sent
        finish_reason = None
        chunk_count = 0
        tool_chunk_count = 0

        _last_chunk_time = time.time()
        _last_chunk_log_time = 0.0  # For periodic chunk debug logging
        _stream_aiter = stream.__aiter__()
        _chunk_timeout = 120  # initial timeout between chunks
        _stream_start_time = time.time()
        _stream_round_usage = None  # Captured from final chunk (include_usage=True)

        # --- Stream iteration ---
        logger.debug(f"[ws_stream] round={tool_rounds}, streaming started...")

        while True:
            # Check connection before reading next chunk
            if not await _check_ws_alive(ws):
                logger.warning("[ws_stream] Connection lost during streaming — aborting")
                return

            # Read next chunk with timeout
            try:
                chunk = await asyncio.wait_for(
                    _stream_aiter.__anext__(),
                    timeout=_chunk_timeout
                )
            except asyncio.TimeoutError:
                elapsed = time.time() - _stream_start_time
                logger.error(
                    f"[ws_stream] round={tool_rounds}, NO chunk for {_chunk_timeout}s "
                    f"(total elapsed={elapsed:.0f}s). Connection may be hung. "
                    f"last_chunk={_last_chunk_time - _stream_start_time:.0f}s ago."
                )
                if elapsed > 360:
                    logger.error(f"[ws_stream] Aborting after {elapsed:.0f}s total hang")
                    break
                _chunk_timeout = min(_chunk_timeout * 2, 300)
                continue
            except StopAsyncIteration:
                break  # Stream ended normally

            _last_chunk_time = time.time()
            _chunk_timeout = 120  # Reset after successful chunk
            chunk_count += 1

            # Capture usage BEFORE checking choices (final chunk often has usage but no choices)
            if chunk.usage:
                _stream_round_usage = chunk.usage

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason or finish_reason

            # --- Text content: stream to frontend immediately ---
            if delta.content:
                content_parts.append(delta.content)
                # Log chunks periodically (every 20th content chunk or every 5s)
                now = time.time()
                if chunk_count % 20 == 1 or now - _last_chunk_log_time > 5:
                    total_text = sum(len(p) for p in content_parts)
                    logger.debug(
                        f"[ws_stream] round={tool_rounds}, chunk#{chunk_count}: "
                        f"text_accum={total_text}, lat={now - _stream_start_time:.2f}s"
                    )
                    _last_chunk_log_time = now
                if not await _ws_safe_send(ws, {
                    "type": "text",
                    "content": delta.content,
                }):
                    return  # Connection lost

            # --- Tool calls: buffer locally (don't execute yet!) ---
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_data[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_data[idx]["name"] = tc.function.name
                            if idx not in tool_name_notified:
                                tool_name_notified.add(idx)
                                logger.debug(
                                    f"[ws_stream] round={tool_rounds}, "
                                    f"tool_call[{idx}]: name={tc.function.name}"
                                )
                                if not await _ws_safe_send(ws, {
                                    "type": "tool_start",
                                    "name": tc.function.name,
                                    "index": idx,
                                    "args": "",
                                }):
                                    return
                        if tc.function.arguments:
                            tool_chunk_count += 1
                            chunk_text = tc.function.arguments
                            tool_calls_data[idx]["arguments"] += chunk_text
                            # Log tool arg chunks periodically (every 10th)
                            if tool_chunk_count % 10 == 1:
                                acc_len = len(tool_calls_data[idx]["arguments"])
                                logger.debug(
                                    f"[ws_stream] round={tool_rounds}, "
                                    f"tool_arg[{idx}] {tc.function.name}: "
                                    f"chunk#{tool_chunk_count}, args_accum={acc_len}"
                                )
                            # Stream to frontend for live display
                            if not await _ws_safe_send(ws, {
                                "type": "tool_args",
                                "index": idx,
                                "name": tc.function.name,
                                "content": chunk_text,
                            }):
                                return

        # --- Stream statistics ---
        total_tc_args = sum(len(v["arguments"]) for v in tool_calls_data.values())
        logger.debug(
            f"[ws_stream] round={tool_rounds}, streaming done — "
            f"chunks={chunk_count}, text_len={sum(len(p) for p in content_parts)}, "
            f"tool_call_args_len={total_tc_args}, finish_reason={finish_reason}"
        )

        # --- Token usage: log & accumulate ---
        if _stream_round_usage:
            pt = _stream_round_usage.prompt_tokens or 0
            ct = _stream_round_usage.completion_tokens or 0
            tt = _stream_round_usage.total_tokens or pt + ct
            _call_prompt_tokens += pt
            _call_completion_tokens += ct
            logger.info(
                "[token_usage] round=%d, prompt_tokens=%d, completion_tokens=%d, total=%d",
                tool_rounds, pt, ct, tt,
            )
        else:
            logger.debug("[token_usage] round=%d, usage=N/A (not returned in stream)", tool_rounds)

        # Stream ended without finish_reason → may be truncated
        if not finish_reason:
            logger.warning(
                f"[ws_stream] round={tool_rounds}: stream ended without finish_reason. "
                f"Collected data may be incomplete."
            )

        # Stream ended with 'length' → model hit max_tokens limit, content may be truncated
        if finish_reason == "length":
            logger.warning(
                f"[ws_stream] round={tool_rounds}: finish_reason='length'. "
                f"Model output hit max_tokens limit — content may be truncated. "
                f"Consider increasing max_tokens (current={kwargs['max_tokens']})."
            )

        # ================================================================
        # Phase 2: Validate collected tool arguments
        # ================================================================
        full_content = "".join(content_parts)

        # ---- Debug: log raw LLM response with boundary markers ----
        tc_names = {k: v['name'] for k, v in tool_calls_data.items()}
        logger.debug(
            "[llm_response] round=%d, model=%s, max_tokens=%d, content_len=%d, tool_calls=%s\n"
            "=== LLM RAW RESPONSE ===\n%s\n=== END LLM RAW RESPONSE ===",
            tool_rounds, kwargs['model'], kwargs['max_tokens'],
            len(full_content), json.dumps(tc_names, ensure_ascii=False),
            full_content,
        )

        if tool_calls_data:
            logger.debug(
                f"[llm_response] round={tool_rounds}, tool_calls="
                f"{json.dumps({k: {'name': v['name'], 'args_preview': v['arguments'][:200]} for k, v in tool_calls_data.items()}, ensure_ascii=False)}"
            )

        # Filter: only keep tools with valid, complete arguments
        valid_tools = _filter_valid_tool_calls(
            tool_calls_data,
            consecutive_failures,
            MAX_CONSECUTIVE_FAILURES,
        )

        rejected_count = len(tool_calls_data) - len(valid_tools)
        if rejected_count > 0:
            logger.warning(
                f"[ws_stream] round={tool_rounds}: rejected {rejected_count} tool calls "
                f"due to incomplete/invalid arguments"
            )
            # Notify frontend about rejected tools
            await _ws_safe_send(ws, {
                "type": "status",
                "content": (
                    f"⚠ {rejected_count} 个工具调用因参数不完整被跳过"
                    if tool_rounds == 0 else ""
                ),
            })

        # --- Build assistant message ---
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": full_content}

        if valid_tools:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["data"]["id"],
                    "type": "function",
                    "function": {
                        "name": tc["data"]["name"],
                        "arguments": tc["sanitized_args"],
                    },
                }
                for tc in valid_tools
            ]
        messages.append(assistant_msg)

        # No tool calls at all → done
        if not tool_calls_data:
            await _ws_safe_send(ws, {"type": "done"})
            engine._update_history(user_input, full_content,
                                   prompt_tokens=_call_prompt_tokens,
                                   completion_tokens=_call_completion_tokens)
            return

        # All tool calls rejected → send error and stop (don't let model retry)
        if tool_calls_data and not valid_tools:
            error_msg = (
                "工具调用参数不完整，可能是流式输出被截断。"
                "请尝试：1) 增大 max_tokens 设置；2) 简化请求内容；3) 重试。"
            )
            logger.error(
                f"[ws_stream] All {len(tool_calls_data)} tool calls rejected. "
                f"Stopping to prevent infinite retry."
            )
            await _ws_safe_send(ws, {"type": "error", "content": error_msg})
            return

        # ================================================================
        # Phase 3: Execute validated tools (serial, one at a time)
        # ================================================================
        for i, tc in enumerate(valid_tools):
            # Check connection before each tool execution
            if not await _check_ws_alive(ws):
                logger.warning("[ws_stream] Connection lost before tool execution")
                return

            fn_name = tc["data"]["name"]
            fn_args = tc["parsed_args"]

            # Notify frontend
            await _ws_safe_send(ws, {
                "type": "processing",
                "content": f"正在执行: {fn_name}..."
            })

            # Execute tool (in thread to avoid blocking event loop)
            result = await asyncio.to_thread(engine.tools.execute, fn_name, fn_args)
            tool_rounds += 1

            # Dynamically adjust max_rounds if new slides/pages detected
            if _is_heavy:
                max_rounds = engine._check_and_adjust_max_rounds(
                    fn_name, fn_args, max_rounds, is_heavy=True,
                )

            # Track consecutive failures to break infinite retry loops
            _track_tool_failure(fn_name, result, consecutive_failures)

            # Truncate result to save context tokens
            truncated_result = ChatEngine._truncate_tool_result(fn_name, result)

            # Notify client about result (send FULL result to frontend, not truncated)
            # Also send formatted args for display (e.g. HTML content with proper line breaks)
            formatted_args = json.dumps(fn_args, indent=2, ensure_ascii=False)
            await _ws_safe_send(ws, {
                "type": "tool_end",
                "name": fn_name,
                "index": i,
                "result": result,
                "truncated": len(result) > 500,
                "args": formatted_args,
            })

            # Add tool result to message history (truncated version for LLM context)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["data"]["id"],
                "content": truncated_result,
            })

        # Sliding window: trim old tool messages to control context size.
        # For PPT/doc tasks, scale history window by detected slide count
        # so the model retains context of all previously generated slides.
        config_history = engine.config.get("max_tool_history", 20)
        if engine._detected_slide_count > 0:
            # Each slide ≈ 6 rounds (12 tool msgs); keep all + buffer
            max_tool_msgs = max(config_history, engine._detected_slide_count * 12 + 20)
        else:
            max_tool_msgs = max(config_history, max_rounds)
        tool_msg_count = len(messages) - prefix_count
        if max_tool_msgs > 0 and tool_msg_count > max_tool_msgs:
            excess = tool_msg_count - max_tool_msgs
            del messages[prefix_count:prefix_count + excess]
            logger.debug(
                "[ws_stream] Trimmed %d old tool messages (kept %d, total=%d)",
                excess, max_tool_msgs, len(messages),
            )

        # ── Progress checkpoint: inject summary for PPT/doc tasks ──
        # Use in-place replace (not insert) to keep prefix structure stable
        # for LLM prompt caching.
        _round_counter += 1
        if (
            _is_heavy
            and _round_counter % _CHECKPOINT_INTERVAL == 0
            and engine._detected_slide_count > 0
        ):
            slide_names = sorted(engine._slide_paths)
            overview = ", ".join(slide_names[:8])
            if len(slide_names) > 8:
                overview += f"... (共 {len(slide_names)} 个)"
            checkpoint_msg = {
                "role": "system",
                "content": (
                    f"[进度] 第 {_round_counter} 轮 LLM 调用: "
                    f"已生成 {engine._detected_slide_count} 个 slide 文件 ({overview})，"
                    f"共 {tool_rounds} 次工具调用"
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
                "[ws_stream] Injected progress checkpoint at round %d: %d slides",
                _round_counter, engine._detected_slide_count,
            )
            await _ws_safe_send(ws, {
                "type": "status",
                "content": (
                    f"📊 进度: 第 {_round_counter} 轮, "
                    f"已生成 {engine._detected_slide_count} 个 slide"
                ),
            })

    # --- Exceeded max tool rounds ---
    warning = (
        f"[Notice] 已达到最大工具调用轮次 ({max_rounds})。"
        f"请尝试简化请求或拆分任务。"
    )
    logger.warning(f"[ws_stream] max tool rounds ({max_rounds}) exceeded")
    await _ws_safe_send(ws, {"type": "text", "content": warning})
    await _ws_safe_send(ws, {"type": "done"})
    engine._update_history(user_input, warning,
                           prompt_tokens=_call_prompt_tokens,
                           completion_tokens=_call_completion_tokens)


def _handle_command(engine: ChatEngine, cmd: str) -> dict[str, Any]:
    """Handle slash commands."""
    cmd_lower = cmd.lower().strip()

    if cmd_lower in ("/quit", "/exit", "/q"):
        return {"type": "system", "content": "Use browser to close."}
    elif cmd_lower == "/clear":
        engine.clear_history()
        return {"type": "system", "content": "History cleared."}
    elif cmd_lower == "/skills":
        skills = engine.skills.list_all()
        if not skills:
            return {"type": "system", "content": "No skills available."}
        lines = []
        for s in skills:
            tag = " [always]" if s.always else ""
            triggers = f" ({', '.join(s.triggers)})" if s.triggers else ""
            lines.append(f"- {s.name}{tag}: {s.description}{triggers}")
        return {"type": "system", "content": "\n".join(lines)}
    elif cmd_lower == "/tools":
        lines = []
        for name in engine.tools.tool_names:
            tool = engine.tools.get(name)
            if tool:
                lines.append(f"- {name}: {tool.description}")
        return {"type": "system", "content": "\n".join(lines)}
    elif cmd_lower == "/reload":
        engine.reload_skills()
        count = len(engine.skills.list_all())
        return {"type": "system", "content": f"Reloaded {count} skill(s)."}
    elif cmd_lower.startswith("/use "):
        skill_name = cmd[5:].strip()
        skill = engine.skills.get(skill_name)
        if not skill:
            return {"type": "system", "content": f"Skill '{skill_name}' not found."}
        else:
            return {"type": "system", "content": f"Skill '{skill_name}' activated."}
    else:
        return {"type": "system", "content": f"Unknown command: {cmd}"}


# ---------------------------------------------------------------------------
# Static Files & Index
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    """Serve the main page."""
    index_path = _static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>MiniAgent Web</h1><p>Static files not found.</p>")


# Mount static files (must be last)
# Custom subclass to add Cache-Control header to prevent stale browser cache
class _NoCacheStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                # Add no-cache for JS/CSS to avoid stale cache after code updates
                headers[b"cache-control"] = b"no-cache, no-store, must-revalidate"
                message["headers"] = list(headers.items())
            await send(message)
        await super().__call__(scope, receive, send_wrapper)

app.mount("/static", _NoCacheStaticFiles(directory=str(_static_dir)), name="static")
