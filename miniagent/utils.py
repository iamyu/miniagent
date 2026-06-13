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
        logger.warning("[tool_args] empty arguments for tool '%s', defaulting to {}", tool_name)
        return "{}"

    raw = arguments_str.strip()

    # Already valid JSON
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # Pre-clean: replace real newlines / carriage returns inside JSON string values
    # with their JSON-escaped equivalents. LLMs often output raw newlines in
    # large content fields (e.g. HTML in save_document), breaking JSON validity.
    raw_fixed = raw.replace("\n", "\\n").replace("\r", "\\r")
    if raw_fixed != raw:
        try:
            json.loads(raw_fixed)
            logger.info("[tool_args] repaired arguments for '%s' by escaping newlines", tool_name)
            return raw_fixed
        except json.JSONDecodeError:
            pass  # fall through to remaining fixes

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
                    "[tool_args] repaired arguments for '%s' (fix #%d): raw=%.200s -> repaired=%.200s",
                    tool_name, i + 1, raw, repaired
                )
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            continue

    # All repairs failed
    logger.error(
        "[tool_args] CRITICAL: cannot repair arguments for tool '%s'. raw=%.500s",
        tool_name, raw
    )
    return "{}"


def _extract_json_object(s: str) -> str:
    """Extract the first JSON object from a string.

    If a complete object is found (balanced braces), returns it.
    If the string ends with an unclosed object (truncated), attempts to
    close it by appending the missing structural characters.
    """
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

    # No complete object; try to repair truncated JSON
    if start >= 0 and depth > 0:
        truncated = s[start:]
        # Try appending closing braces
        repaired = truncated + ('}' * depth)
        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError:
            pass
        # If still failing, try closing string first then braces
        if in_string:
            repaired = truncated + '"' + ('}' * depth)
            try:
                json.loads(repaired)
                return repaired
            except json.JSONDecodeError:
                pass
            # If content ends with '\', it's a dangling escape char; strip and retry
            if truncated.endswith('\\'):
                repaired = truncated[:-1] + '"' + ('}' * depth)
                try:
                    json.loads(repaired)
                    return repaired
                except json.JSONDecodeError:
                    pass

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


def validate_tool_args(tool_name: str, args: dict) -> tuple[bool, str]:
    """Validate tool arguments for completeness before execution.

    Catches truncated/incomplete arguments that would produce partial results
    and trigger infinite model retry loops.

    Returns:
        (is_valid: bool, message: str)
    """
    if not args or not isinstance(args, dict):
        return False, "Arguments empty or not a dict"

    # Content-writing tools (write_file, save_document): verify content field
    if tool_name in ("write_file", "save_document"):
        content = args.get("content", "")
        if content is None or (isinstance(content, str) and not content.strip()):
            return False, "Content field is empty or None"

        if isinstance(content, str):
            content_stripped = content.strip()
            content_len = len(content_stripped)

            # If it looks like HTML but is too short → likely truncated
            if content_stripped.startswith("<") and content_len < 50:
                return False, (
                    f"HTML-like content too short ({content_len} chars), "
                    f"likely truncated during streaming"
                )

            # HTML document: check basic structure completeness
            lower = content_stripped.lower()
            if lower.startswith("<!doctype") or lower.startswith("<html"):
                if not lower.rstrip().endswith("</html>"):
                    return False, (
                        f"HTML document appears truncated "
                        f"(starts with <html/doctype but does not end with </html>)"
                    )

            # Generic length sanity
            if content_len < 10:
                return False, f"Content too short ({content_len} chars)"

    # Shell tool: check command field
    if tool_name == "shell":
        command = args.get("command", "")
        if not command or not command.strip():
            return False, "Command field is empty"

    return True, "OK"


def log_api_error(error: Exception, context: str = "", messages: list | None = None) -> str:
    """Log an API error with debugging context.

    Returns a user-friendly error string.
    """
    error_str = str(error)
    logger.error("[api_error] %s: %s", context, error_str)

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
                tc_summary = '; '.join(tc_info)
                logger.debug("[api_error] msg[%d]: role=%s, tool_calls=[%s]", i, role, tc_summary)
            else:
                logger.debug("[api_error] msg[%d]: role=%s, content=%.200s", i, role, content)

    return f"API error: {error_str}"
