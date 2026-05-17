"""MiniAgent Web Server - FastAPI backend with WebSocket chat support."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .chat import ChatEngine
from .config import load_config, get_config_path, get_app_dir
from .skills import Skill
from openai import AsyncOpenAI


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
        "max_tokens": cfg.get("max_tokens", 4096),
        "max_history": cfg.get("max_history", 20),
        "has_api_key": bool(cfg.get("api_key")),
    }


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


@app.post("/api/chat")
async def api_chat(body: dict[str, Any]):
    """Synchronous chat endpoint."""
    engine = get_engine()
    user_input = body.get("message", "").strip()
    if not user_input:
        return {"error": "message is required"}

    # Handle commands
    if user_input.startswith("/"):
        return _handle_command(engine, user_input)

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

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            user_input = msg.get("message", "").strip()

            if not user_input:
                await ws.send_json({"type": "error", "content": "message is required"})
                continue

            # Handle commands
            if user_input.startswith("/"):
                cmd_result = _handle_command(engine, user_input)
                await ws.send_json(cmd_result)
                continue

            # Stream the chat response
            try:
                await _stream_chat(engine, ws, user_input)
            except WebSocketDisconnect:
                raise
            except Exception as e:
                print(f"[WS] Error in _stream_chat: {e}")
                try:
                    await ws.send_json({"type": "error", "content": str(e)})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] Unexpected error: {e}")


async def _stream_chat(engine: ChatEngine, ws: WebSocket, user_input: str):
    """Stream a chat response via WebSocket, sending tool calls in real-time.

    Uses AsyncOpenAI to avoid blocking the event loop during streaming.
    """
    # Match skills
    matched_skills = []
    auto_matched = engine.skills.match_triggers(user_input)
    matched_skills.extend(auto_matched)

    system_prompt = engine.build_system_prompt(matched_skills)

    # Send skill activation notification
    if matched_skills:
        names = [s.name for s in matched_skills]
        await ws.send_json({
            "type": "status",
            "content": f"Skills: {', '.join(names)}"
        })

    # Build messages for API call
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend(engine.history)
    messages.append({"role": "user", "content": user_input})

    tool_definitions = engine.tools.get_definitions()
    tool_rounds = 0
    max_rounds = 10

    # Create async OpenAI client (lightweight, per-request is fine)
    async_client = AsyncOpenAI(
        api_key=engine.config.get("api_key", ""),
        base_url=engine.config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )

    while tool_rounds < max_rounds:
        kwargs: dict[str, Any] = {
            "model": engine.config.get("model", "qwen-plus"),
            "messages": messages,
            "temperature": engine.config.get("temperature", 0.7),
            "max_tokens": engine.config.get("max_tokens", 4096),
            "stream": True,
        }
        if tool_definitions:
            kwargs["tools"] = tool_definitions

        try:
            # Use AsyncOpenAI — async for properly yields to event loop
            stream = await async_client.chat.completions.create(**kwargs)

            # Collect streamed content (non-blocking)
            content_parts = []
            tool_calls_data: dict[int, dict] = {}  # index -> tool call data
            finish_reason = None

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # Text content
                if delta.content:
                    content_parts.append(delta.content)
                    # Send text chunk to client
                    await ws.send_json({
                        "type": "text",
                        "content": delta.content,
                    })

                # Tool calls (streamed incrementally)
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
                            if tc.function.arguments:
                                tool_calls_data[idx]["arguments"] += tc.function.arguments

                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

        except Exception as e:
            await ws.send_json({"type": "error", "content": f"API error: {e}"})
            engine._update_history(user_input, f"[Error] {e}")
            return

        # Build assistant message
        full_content = "".join(content_parts)
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": full_content}

        if tool_calls_data:
            ordered_calls = [tool_calls_data[i] for i in sorted(tool_calls_data.keys())]
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in ordered_calls
            ]
        messages.append(assistant_msg)

        # No tool calls -> done
        if not tool_calls_data:
            await ws.send_json({"type": "done"})
            engine._update_history(user_input, full_content)
            return

        # Execute tool calls
        for tc_data in ordered_calls:
            fn_name = tc_data["name"]
            fn_args_str = tc_data["arguments"] or "{}"

            try:
                fn_args = json.loads(fn_args_str)
                if not isinstance(fn_args, dict):
                    fn_args = {}
            except json.JSONDecodeError:
                fn_args = {}

            # Notify client about tool call
            await ws.send_json({
                "type": "tool_start",
                "name": fn_name,
                "args": fn_args,
            })

            # Execute tool (run in thread to avoid blocking event loop)
            result = await asyncio.to_thread(engine.tools.execute, fn_name, fn_args)
            tool_rounds += 1

            # Notify client about tool result
            await ws.send_json({
                "type": "tool_end",
                "name": fn_name,
                "result": result[:500] if len(result) > 500 else result,
                "truncated": len(result) > 500,
            })

            # Add to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc_data["id"],
                "content": result,
            })

    # Exceeded max rounds
    warning = "[Notice] Reached maximum tool call rounds."
    await ws.send_json({"type": "text", "content": warning})
    await ws.send_json({"type": "done"})
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
