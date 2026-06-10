"""Utility functions shared across the miniagent package."""

import json
import logging

# Module-level logger
logger = logging.getLogger("miniagent")
logger.setLevel(logging.DEBUG)

# Add a console handler if none exists
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)


def sanitize_tool_arguments(arguments_str: str, tool_name: str = "unknown") -> str:
    """Sanitize tool call arguments to ensure valid JSON.

    DashScope API requires function.arguments to be valid JSON. If the LLM
    returns malformed JSON, this function attempts to repair it.

    Args:
        arguments_str: Raw arguments string from the LLM tool call.
        tool_name: Name of the tool (for logging).

    Returns:
        A valid JSON string (or "{}" if repair fails).
    """
    if not arguments_str or not arguments_str.strip():
        logger.warning(f"[tool_args] empty arguments for tool '{tool_name}', defaulting to {{}}")
        return "{}"

    raw = arguments_str.strip()

    # Already valid JSON
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # Try common fixes
    fixes_tried = [
        # Fix 1: Remove trailing commas (common LLM mistake)
        lambda s: s.replace(", }", "}").replace(",}", "}").replace(", ]", "]").replace(",]", "]"),
        # Fix 2: Extract just the first complete JSON object
        lambda s: _extract_json_object(s),
        # Fix 3: Try parsing with ast.literal_eval (Python-style dicts)
        lambda s: _try_python_literal(s),
    ]

    for i, fix in enumerate(fixes_tried):
        try:
            repaired = fix(raw)
            if repaired and repaired != raw:
                parsed = json.loads(repaired)
                logger.info(
                    f"[tool_args] repaired arguments for '{tool_name}' "
                    f"(fix #{i+1}): raw={raw[:200]} -> repaired={repaired[:200]}"
                )
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            continue

    # All repairs failed
    logger.error(
        f"[tool_args] CRITICAL: cannot repair arguments for tool '{tool_name}'. "
        f"raw={raw[:500]}"
    )
    return "{}"


def _extract_json_object(s: str) -> str:
    """Extract the first complete JSON object from a string."""
    depth = 0
    start = -1
    in_string = False
    escape_next = False
    
    for i, ch in enumerate(s):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                return s[start:i+1]
    
    return s


def _try_python_literal(s: str) -> str:
    """Try converting a Python-style dict string to JSON."""
    import ast
    try:
        obj = ast.literal_eval(s)
        if isinstance(obj, dict):
            return json.dumps(obj, ensure_ascii=False)
    except Exception:
        pass
    return s


def log_api_error(error: Exception, context: str = "", messages: list | None = None) -> str:
    """Log an API error with debugging context.

    Returns a user-friendly error string.
    """
    error_str = str(error)
    logger.error(f"[api_error] {context}: {error_str}")

    if messages:
        # Log the last few messages (truncated) for debugging
        for i, msg in enumerate(messages[-6:]):
            role = msg.get("role", "?")
            content = str(msg.get("content", ""))[:300]
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                tc_info = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    tc_info.append(
                        f"{fn.get('name', '?')}("
                        f"args={fn.get('arguments', '')[:100]}"
                        f")"
                    )
                logger.debug(f"[api_error] msg[{i}]: role={role}, tool_calls=[{'; '.join(tc_info)}]")
            else:
                logger.debug(f"[api_error] msg[{i}]: role={role}, content={content[:200]}")

    return f"API error: {error_str}"
