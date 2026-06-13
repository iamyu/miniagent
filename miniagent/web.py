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
        "has_api_key": bool(cfg.get("api_key")),
    }


@app.post("/api/config")
async def api_save_config(data: dict[str, Any]):
    """Save configuration values to user-level config file."""
    allowed_keys = {"model", "base_url", "temperature", "max_tokens", "max_history", "api_key"}
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
                    auto_match=True,
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
    auto_matched = engine.skills.match_triggers(cleaned_input)
    existing_names = {s.name for s in matched_skills}
    for s in auto_matched:
        if s.name not in existing_names:
            matched_skills.append(s)
            existing_names.add(s.name)

    system_prompt = engine.build_system_prompt(matched_skills)

    if matched_skills:
        names = [s.name for s in matched_skills]
        await _ws_safe_send(ws, {
            "type": "status",
            "content": f"Skills: {', '.join(names)}"
        })

    # --- Build messages for API ---
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend(engine.history)
    # Use cleaned_input (with @skill-name removed) if non-empty, otherwise use original
    llm_input = cleaned_input if cleaned_input else user_input
    messages.append({"role": "user", "content": llm_input})

    tool_definitions = engine.tools.get_definitions()
    tool_rounds = 0
    max_rounds = 30

    # Track consecutive failures per tool name to break infinite retry loops
    consecutive_failures: dict[str, int] = {}
    MAX_CONSECUTIVE_FAILURES = 3

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
        }
        if tool_definitions:
            kwargs["tools"] = tool_definitions

        msg_preview = messages[-1].get("content", "") if messages else ""
        logger.debug(
            f"[ws_stream] round={tool_rounds}, model={kwargs['model']}, "
            f"max_tokens={kwargs['max_tokens']}, temp={kwargs['temperature']}, "
            f"msg_count={len(messages)}, tools={len(tool_definitions)}"
        )
        logger.debug(f"[ws_stream] last_msg_preview={msg_preview[:300]}")

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

        # ---- Debug: save raw LLM response to log file ----
        try:
            log_dir = get_app_dir() / "debug"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            log_file = log_dir / f"llm_response_{ts}.log"
            tc_names = {k: v['name'] for k, v in tool_calls_data.items()}
            lines = [
                f"# round={tool_rounds}, model={kwargs['model']}, max_tokens={kwargs['max_tokens']}",
                f"# timestamp={time.strftime('%Y-%m-%d %H:%M:%S')}",
                "=" * 60,
                full_content,
                "=" * 60,
                f"# tool_calls: {json.dumps(tc_names, ensure_ascii=False)}",
            ]
            log_file.write_text("\n".join(lines), encoding="utf-8")
            logger.debug(f"[ws_stream] LLM raw response saved to: {log_file}")
        except Exception as e:
            logger.error(f"[ws_stream] Failed to save LLM response log: {e}")

        if tool_calls_data:
            logger.debug(
                f"[ws_stream] round={tool_rounds}, tool_calls="
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
            engine._update_history(user_input, full_content)
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

            # Track consecutive failures to break infinite retry loops
            _track_tool_failure(fn_name, result, consecutive_failures)

            # Notify client about result
            await _ws_safe_send(ws, {
                "type": "tool_end",
                "name": fn_name,
                "index": i,
                "result": result[:500] if len(result) > 500 else result,
                "truncated": len(result) > 500,
            })

            # Add tool result to message history
            messages.append({
                "role": "tool",
                "tool_call_id": tc["data"]["id"],
                "content": result,
            })

    # --- Exceeded max tool rounds ---
    warning = (
        f"[Notice] 已达到最大工具调用轮次 ({max_rounds})。"
        f"请尝试简化请求或拆分任务。"
    )
    logger.warning(f"[ws_stream] max tool rounds ({max_rounds}) exceeded")
    await _ws_safe_send(ws, {"type": "text", "content": warning})
    await _ws_safe_send(ws, {"type": "done"})
    engine._update_history(user_input, warning)


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
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
