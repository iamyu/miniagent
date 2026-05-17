"""Tool system for MiniAgent - lightweight function calling tools."""

from __future__ import annotations

import json
import re
import difflib
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any


class Tool(ABC):
    """Base class for MiniAgent tools.

    Each tool defines:
    - name: tool name for function calling
    - description: what the tool does
    - parameters: JSON Schema dict for parameters
    - execute(**kwargs): run the tool, return result string
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        ...

    def to_schema(self) -> dict[str, Any]:
        """OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self._tools.values()]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def execute(self, name: str, params: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
        try:
            return tool.execute(**params)
        except TypeError as e:
            return f"Error: Invalid parameters for '{name}': {e}"
        except Exception as e:
            return f"Error executing '{name}': {e}"


# ---------------------------------------------------------------------------
# File System Tools
# ---------------------------------------------------------------------------

_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".coverage", "htmlcov", ".workbuddy",
}


class ReadFileTool(Tool):
    """Read file contents with optional pagination."""

    MAX_CHARS = 128_000
    DEFAULT_LIMIT = 500

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read a text file. Returns content with line numbers. "
            "Use offset and limit for large files (offset is 1-indexed)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative file path"},
                "offset": {"type": "integer", "description": "Line number to start from (1-indexed, default 1)", "default": 1},
                "limit": {"type": "integer", "description": "Max lines to read (default 500)", "default": 500},
            },
            "required": ["path"],
        }

    def execute(self, path: str = "", offset: int = 1, limit: int | None = None, **kw: Any) -> str:
        try:
            if not path:
                return "Error: path is required"
            fp = Path(path)
            if not fp.exists():
                return f"Error: File not found: {path}"
            if not fp.is_file():
                return f"Error: Not a file: {path}"

            raw = fp.read_bytes()
            if not raw:
                return f"(Empty file: {path})"

            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return f"Error: Cannot read binary file: {path}"

            text = text.replace("\r\n", "\n")
            all_lines = text.splitlines()
            total = len(all_lines)

            limit = limit or self.DEFAULT_LIMIT
            if offset < 1:
                offset = 1
            if offset > total:
                return f"Error: offset {offset} exceeds file length ({total} lines)"

            start = offset - 1
            end = min(start + limit, total)
            numbered = [f"{i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
            result = "\n".join(numbered)

            if len(result) > self.MAX_CHARS:
                trimmed = []
                chars = 0
                for line in numbered:
                    chars += len(line) + 1
                    if chars > self.MAX_CHARS:
                        break
                    trimmed.append(line)
                end = start + len(trimmed)
                result = "\n".join(trimmed)

            if end < total:
                result += f"\n\n(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to read more.)"
            else:
                result += f"\n\n(End of file - {total} lines total)"
            return result

        except PermissionError as e:
            return f"Error: Permission denied: {e}"
        except Exception as e:
            return f"Error reading file: {e}"


class WriteFileTool(Tool):
    """Write content to a file."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Creates parent directories if needed. "
            "Overwrites if the file exists. For partial edits, prefer edit_file. "
            "If path is a relative path (e.g. 'report.md' or 'sub/file.txt'), "
            "it will be saved under ~/.miniagent/ directory automatically."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path. Relative paths (e.g. 'report.md') are saved to ~/.miniagent/. Absolute paths (e.g. 'D:\\report.md') are used as-is.",
                },
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"],
        }

    def execute(self, path: str = "", content: str = "", **kw: Any) -> str:
        try:
            if not path:
                return "Error: path is required"
            if content is None:
                return "Error: content is required"
            fp = Path(path)
            # Relative path -> save under ~/.miniagent/
            if not fp.is_absolute():
                default_dir = Path.home() / ".miniagent"
                fp = default_dir / fp
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to {fp}"
        except PermissionError as e:
            return f"Error: Permission denied: {e}"
        except Exception as e:
            return f"Error writing file: {e}"


class EditFileTool(Tool):
    """Edit a file by replacing text."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing old_text with new_text. "
            "If old_text appears multiple times, provide more context or set replace_all=true. "
            "Copy the exact text from read_file output."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit"},
                "old_text": {"type": "string", "description": "The exact text to find (copy from read_file output)"},
                "new_text": {"type": "string", "description": "The replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    @staticmethod
    def _strip_line_prefix(text: str) -> str:
        """Remove line number prefix like '123| ' from read_file output."""
        lines = text.split("\n")
        stripped = []
        for line in lines:
            m = re.match(r"^\d+\|\s?", line)
            if m:
                stripped.append(line[m.end():])
            else:
                stripped.append(line)
        return "\n".join(stripped)

    def execute(
        self,
        path: str = "",
        old_text: str = "",
        new_text: str = "",
        replace_all: bool = False,
        **kw: Any,
    ) -> str:
        try:
            if not path:
                return "Error: path is required"
            if old_text is None:
                return "Error: old_text is required"
            if new_text is None:
                return "Error: new_text is required"

            fp = Path(path)
            if not fp.exists():
                return f"Error: File not found: {path}"

            raw = fp.read_bytes()
            uses_crlf = b"\r\n" in raw
            content = raw.decode("utf-8").replace("\r\n", "\n")

            # Normalize inputs
            norm_old = old_text.replace("\r\n", "\n")
            norm_new = new_text.replace("\r\n", "\n")

            # Try exact match first
            count = content.count(norm_old)
            if count == 0:
                # Try stripping line number prefixes
                stripped_old = self._strip_line_prefix(norm_old)
                if stripped_old != norm_old and stripped_old in content:
                    norm_old = stripped_old
                    count = content.count(norm_old)
                else:
                    # Fuzzy: try trimming whitespace per line
                    trimmed_old = "\n".join(l.strip() for l in norm_old.splitlines())
                    trimmed_content_lines = content.splitlines()
                    found = False
                    for i in range(len(trimmed_content_lines) - len(norm_old.splitlines()) + 1):
                        window = "\n".join(l.strip() for l in trimmed_content_lines[i:i + len(norm_old.splitlines())])
                        if window == trimmed_old:
                            # Reconstruct with original indentation
                            actual_old = "\n".join(trimmed_content_lines[i:i + len(norm_old.splitlines())])
                            norm_old = actual_old
                            count = content.count(norm_old)
                            found = True
                            break
                    if not found:
                        return (
                            f"Error: old_text not found in {path}. "
                            f"Make sure to copy the exact text from read_file output."
                        )

            if count > 1 and not replace_all:
                return (
                    f"Error: old_text appears {count} times in {path}. "
                    f"Provide more context to make it unique, or set replace_all=true."
                )

            if replace_all:
                new_content = content.replace(norm_old, norm_new)
            else:
                new_content = content.replace(norm_old, norm_new, 1)

            if uses_crlf:
                new_content = new_content.replace("\n", "\r\n")

            fp.write_bytes(new_content.encode("utf-8"))
            return f"Successfully edited {fp}"

        except PermissionError as e:
            return f"Error: Permission denied: {e}"
        except Exception as e:
            return f"Error editing file: {e}"


class ListDirTool(Tool):
    """List directory contents."""

    DEFAULT_MAX = 200

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return (
            "List directory contents. Set recursive=true for nested listing. "
            "Auto-ignores .git, node_modules, __pycache__ etc."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
                "recursive": {"type": "boolean", "description": "Recursively list all files (default false)"},
                "max_entries": {"type": "integer", "description": "Max entries to return (default 200)"},
            },
            "required": ["path"],
        }

    def execute(self, path: str = "", recursive: bool = False, max_entries: int | None = None, **kw: Any) -> str:
        try:
            if not path:
                return "Error: path is required"
            dp = Path(path)
            if not dp.exists():
                return f"Error: Directory not found: {path}"
            if not dp.is_dir():
                return f"Error: Not a directory: {path}"

            cap = max_entries or self.DEFAULT_MAX
            items: list[str] = []
            total = 0

            if recursive:
                for item in sorted(dp.rglob("*")):
                    if any(p in _IGNORE_DIRS for p in item.parts):
                        continue
                    total += 1
                    if len(items) < cap:
                        rel = item.relative_to(dp)
                        items.append(f"{rel}/" if item.is_dir() else str(rel))
            else:
                for item in sorted(dp.iterdir()):
                    if item.name in _IGNORE_DIRS:
                        continue
                    total += 1
                    if len(items) < cap:
                        prefix = "DIR  " if item.is_dir() else "FILE "
                        size = ""
                        if item.is_file():
                            sz = item.stat().st_size
                            if sz >= 1024:
                                size = f"  ({sz / 1024:.1f} KB)"
                            else:
                                size = f"  ({sz} B)"
                        items.append(f"  {prefix}{item.name}{size}")

            if not items and total == 0:
                return f"Directory {path} is empty"

            result = "\n".join(items)
            if total > cap:
                result += f"\n\n(Showing first {cap} of {total} entries)"
            return result

        except PermissionError as e:
            return f"Error: Permission denied: {e}"
        except Exception as e:
            return f"Error listing directory: {e}"


# ---------------------------------------------------------------------------
# Web Tools
# ---------------------------------------------------------------------------

class WebSearchTool(Tool):
    """Search the web using DuckDuckGo (no API key needed)."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for information. Returns titles, URLs, and snippets. "
            "Use count to control number of results (default 5, max 10)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "description": "Number of results (1-10, default 5)"},
            },
            "required": ["query"],
        }

    def execute(self, query: str = "", count: int | None = None, **kw: Any) -> str:
        if not query:
            return "Error: query is required"
        count = min(max(count or 5, 1), 10)

        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from duckduckgo_search import DDGS
            ddgs = DDGS()
            results = ddgs.text(query, max_results=count)
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, r in enumerate(results[:count], 1):
                title = r.get("title", "")
                url = r.get("href", "")
                body = r.get("body", "")
                lines.append(f"{i}. {title}")
                lines.append(f"   {url}")
                if body:
                    # Truncate long snippets
                    if len(body) > 200:
                        body = body[:200] + "..."
                    lines.append(f"   {body}")
            return "\n".join(lines)
        except ImportError:
            return (
                "Error: duckduckgo-search package not installed.\n"
                "Install with: pip install duckduckgo-search"
            )
        except Exception as e:
            return f"Error: Web search failed: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL."""

    MAX_CHARS = 50_000

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a URL and extract its text content. "
            "Returns page title and main text content (HTML tags stripped). "
            "Max 50000 characters."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        }

    @staticmethod
    def _strip_tags(html: str) -> str:
        """Simple HTML tag stripping."""
        import html as html_module
        # Remove script and style blocks
        text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
        # Convert some tags to text
        text = re.sub(r"<h[1-6][^>]*>([\s\S]*?)</h[1-6]>", lambda m: "\n" + m.group(1) + "\n", text, flags=re.I)
        text = re.sub(r"<li[^>]*>([\s\S]*?)</li>", lambda m: "\n- " + m.group(1), text, flags=re.I)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</(p|div|section|article)>", "\n\n", text, flags=re.I)
        text = re.sub(r"<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>",
                      lambda m: f"{m.group(2)} ({m.group(1)})", text, flags=re.I)
        # Strip remaining tags
        text = re.sub(r"<[^>]+>", "", text)
        # Decode entities
        text = html_module.unescape(text)
        # Normalize whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def execute(self, url: str = "", **kw: Any) -> str:
        if not url:
            return "Error: url is required"
        url = url.strip(" \t\r\n`\"'")

        try:
            from urllib.request import urlopen, Request
            from urllib.error import URLError

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            req = Request(url, headers=headers)
            with urlopen(req, timeout=15) as resp:
                raw = resp.read(int(self.MAX_CHARS * 2))  # Read more than needed, we truncate later
                content_type = resp.headers.get("Content-Type", "")

            if "text/html" in content_type or raw[:256].lower().startswith(b"<!doctype") or raw[:256].lower().startswith(b"<html"):
                text = self._strip_tags(raw.decode("utf-8", errors="replace"))

                # Extract title
                title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>", raw.decode("utf-8", errors="replace"), re.I)
                title = title_match.group(1).strip() if title_match else ""

                if title:
                    text = f"# {title}\n\n{text}"

                if len(text) > self.MAX_CHARS:
                    text = text[:self.MAX_CHARS] + "\n\n(Content truncated)"

                return f"[External content]\n\n{text}"

            elif "application/json" in content_type:
                text = raw.decode("utf-8", errors="replace")
                if len(text) > self.MAX_CHARS:
                    text = text[:self.MAX_CHARS] + "\n\n(Content truncated)"
                return f"[External content - JSON]\n\n{text}"

            else:
                text = raw.decode("utf-8", errors="replace")
                if len(text) > self.MAX_CHARS:
                    text = text[:self.MAX_CHARS] + "\n\n(Content truncated)"
                return f"[External content]\n\n{text}"

        except ImportError:
            return "Error: urllib not available"
        except Exception as e:
            return f"Error fetching URL: {e}"


# ---------------------------------------------------------------------------
# Shell Tool
# ---------------------------------------------------------------------------

class ShellTool(Tool):
    """Execute Windows CMD commands."""

    MAX_TIMEOUT = 300  # Hard limit: 5 minutes

    # Commands that are too dangerous to run without explicit confirmation
    _DANGEROUS_PATTERNS = [
        "format ", "del /s", "del /q", "rmdir /s", "rd /s",
        "diskpart", "bcdedit", "reg delete", "net user",
        "shutdown", "taskkill /f", "wmic",
    ]

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Execute a Windows CMD command. Use for file operations (copy, move, delete), "
            "running scripts (python, node, npm), system info, and other CLI tasks. "
            "Returns stdout and stderr. Set timeout for long-running commands (default 30s, max 300s). "
            "Set cwd to change working directory."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "CMD command to execute (e.g., 'dir', 'copy a.txt b.txt', 'python script.py')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30, max 300)",
                    "default": 30,
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command (default: current directory)",
                },
            },
            "required": ["command"],
        }

    def execute(
        self,
        command: str = "",
        timeout: int | None = None,
        cwd: str = "",
        **kw: Any,
    ) -> str:
        if not command:
            return "Error: command is required"

        # Normalize timeout
        timeout = min(max(timeout or 30, 1), self.MAX_TIMEOUT)

        # Safety check: warn but don't block dangerous commands
        cmd_lower = command.lower().strip()
        for pattern in self._DANGEROUS_PATTERNS:
            if pattern in cmd_lower:
                return (
                    f"Error: Command blocked for safety. "
                    f"The pattern '{pattern}' is considered dangerous. "
                    f"If you really need this, run it manually in CMD."
                )

        try:
            import subprocess
            import os as _os

            # Build PATH with bundled runtimes prepended
            env = dict(_os.environ)
            runtime_dirs = []
            # Bundled with miniagent package
            bundled_runtime = Path(__file__).resolve().parent.parent / "runtime"
            if bundled_runtime.exists():
                for sub in ("node", "python"):
                    d = bundled_runtime / sub
                    if d.exists():
                        runtime_dirs.append(str(d))
            # Project-level runtime
            project_runtime = Path(cwd) / "runtime" if cwd else Path.cwd() / "runtime"
            if project_runtime.exists():
                for sub in ("node", "python"):
                    d = project_runtime / sub
                    if d.exists():
                        runtime_dirs.append(str(d))
            if runtime_dirs:
                env["PATH"] = _os.pathsep.join(runtime_dirs + env.get("PATH", "").split(_os.pathsep))
                # Also clean NODE_OPTIONS for shell mode
                env.pop("NODE_OPTIONS", None)

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd or None,
                encoding="gbk",
                errors="replace",
                env=env,
            )

            exit_code = result.returncode
            stdout = result.stdout.rstrip() if result.stdout else ""
            stderr = result.stderr.rstrip() if result.stderr else ""

            # Build output
            parts = []
            if stdout:
                parts.append(stdout)
            if stderr:
                parts.append(f"[stderr]\n{stderr}")
            if exit_code != 0:
                parts.append(f"[Exit code: {exit_code}]")

            if not parts:
                return "(Command completed with no output)"

            output = "\n".join(parts)

            # Truncate extremely long output
            MAX_OUTPUT = 50_000
            if len(output) > MAX_OUTPUT:
                output = output[:MAX_OUTPUT] + f"\n\n(Output truncated, {len(output)} chars total)"

            return output

        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds. Use a larger timeout if needed."
        except FileNotFoundError as e:
            return f"Error: Command not found: {e}"
        except Exception as e:
            return f"Error executing command: {e}"


# ---------------------------------------------------------------------------
# Runtime Helper
# ---------------------------------------------------------------------------

def _find_runtime(name: str, exe_name: str) -> str | None:
    """Find a runtime executable.

    Search order:
    1. Bundled runtime: <miniagent_package>/runtime/<name>/<exe_name>
    2. Project-level runtime: ./runtime/<name>/<exe_name> (cwd-relative)
    3. System PATH via shutil.which()
    """
    # 1. Bundled with miniagent package
    bundled = Path(__file__).resolve().parent.parent / "runtime" / name / exe_name
    if bundled.exists():
        return str(bundled)

    # 2. Project-level runtime (cwd-relative)
    project_level = Path.cwd() / "runtime" / name / exe_name
    if project_level.exists():
        return str(project_level)

    # 3. System PATH
    return shutil.which(exe_name)


# ---------------------------------------------------------------------------
# Script Execution Tools (Node.js & Python)
# ---------------------------------------------------------------------------

class RunNodeTool(Tool):
    """Run Node.js / JavaScript scripts or inline code."""

    MAX_TIMEOUT = 300  # 5 minutes hard limit

    @property
    def name(self) -> str:
        return "run_node"

    @property
    def description(self) -> str:
        return (
            "Run a Node.js / JavaScript script. Supports two modes:\n"
            "1. File mode: provide 'path' to a .js file.\n"
            "2. Inline mode: provide 'code' as a JavaScript string to execute directly.\n"
            "Set 'cwd' to change working directory, 'timeout' for max execution time."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to a .js file to run with Node.js. Mutually exclusive with 'code'.",
                },
                "code": {
                    "type": "string",
                    "description": "Inline JavaScript code to execute directly. Mutually exclusive with 'path'.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the script (default: current directory)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 60, max 300)",
                    "default": 60,
                },
                "args": {
                    "type": "string",
                    "description": "Additional command-line arguments to pass to the script (space-separated)",
                },
            },
        }

    def execute(self, path: str = "", code: str = "", cwd: str = "",
                timeout: int | None = None, args: str = "", **kw: Any) -> str:
        if not path and not code:
            return "Error: Either 'path' (script file) or 'code' (inline JS) is required"
        if path and code:
            return "Error: Provide either 'path' or 'code', not both"

        timeout = min(max(timeout or 60, 1), self.MAX_TIMEOUT)

        # Find node executable (bundled first, then system)
        node_exe = _find_runtime("node", "node.exe" if __import__("os").name == "nt" else "node")
        if not node_exe:
            return (
                "Error: Node.js not found.\n"
                "Searched:\n"
                "  - runtime/node/node.exe (bundled)\n"
                "  - ./runtime/node/node.exe (project)\n"
                "  - System PATH\n"
                "Download portable Node.js from https://nodejs.org and place in runtime/node/"
            )

        # Build clean environment (remove NODE_OPTIONS which may cause issues)
        import os as _os
        clean_env = {k: v for k, v in _os.environ.items()
                     if k not in ("NODE_OPTIONS",)}

        try:
            if code:
                # Inline mode: write to temp file, run, delete
                tmp_dir = tempfile.mkdtemp(prefix="miniagent_node_")
                tmp_file = Path(tmp_dir) / "_inline.js"
                tmp_file.write_text(code, encoding="utf-8")
                cmd = [node_exe, str(tmp_file)]
                if args:
                    cmd.extend(args.split())
            else:
                # File mode
                fp = Path(path)
                if not fp.exists():
                    return f"Error: Script file not found: {path}"
                if not fp.is_file():
                    return f"Error: Not a file: {path}"
                cmd = [node_exe, str(fp)]
                if args:
                    cmd.extend(args.split())

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd or None,
                encoding="utf-8",
                errors="replace",
                env=clean_env,
            )

            parts = []
            if result.stdout:
                parts.append(result.stdout.rstrip())
            if result.stderr:
                parts.append(f"[stderr]\n{result.stderr.rstrip()}")
            if result.returncode != 0:
                parts.append(f"[Exit code: {result.returncode}]")

            if not parts:
                return "(Script completed with no output)"

            output = "\n".join(parts)
            if len(output) > 50_000:
                output = output[:50_000] + f"\n\n(Output truncated, {len(output)} chars total)"
            return output

        except subprocess.TimeoutExpired:
            return f"Error: Script timed out after {timeout} seconds"
        except Exception as e:
            return f"Error running Node.js: {e}"
        finally:
            # Clean up temp files from inline mode
            if code:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass


class RunPythonTool(Tool):
    """Run Python scripts or inline code."""

    MAX_TIMEOUT = 300  # 5 minutes hard limit

    @property
    def name(self) -> str:
        return "run_python"

    @property
    def description(self) -> str:
        return (
            "Run a Python script. Supports two modes:\n"
            "1. File mode: provide 'path' to a .py file.\n"
            "2. Inline mode: provide 'code' as a Python code string to execute directly.\n"
            "Set 'cwd' to change working directory, 'timeout' for max execution time."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to a .py file to run with Python. Mutually exclusive with 'code'.",
                },
                "code": {
                    "type": "string",
                    "description": "Inline Python code to execute directly. Mutually exclusive with 'path'.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the script (default: current directory)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 60, max 300)",
                    "default": 60,
                },
                "args": {
                    "type": "string",
                    "description": "Additional command-line arguments to pass to the script (space-separated)",
                },
            },
        }

    def execute(self, path: str = "", code: str = "", cwd: str = "",
                timeout: int | None = None, args: str = "", **kw: Any) -> str:
        if not path and not code:
            return "Error: Either 'path' (script file) or 'code' (inline Python) is required"
        if path and code:
            return "Error: Provide either 'path' or 'code', not both"

        timeout = min(max(timeout or 60, 1), self.MAX_TIMEOUT)

        # Find python executable (bundled first, then system)
        import os as _os
        _is_win = _os.name == "nt"
        python_exe = _find_runtime("python", "python.exe" if _is_win else "python3")
        if not python_exe:
            return (
                "Error: Python not found.\n"
                "Searched:\n"
                "  - runtime/python/python.exe (bundled)\n"
                "  - ./runtime/python/python.exe (project)\n"
                "  - System PATH\n"
                "Download portable Python from https://www.python.org and place in runtime/python/"
            )

        try:
            if code:
                # Inline mode: write to temp file, run, delete
                tmp_dir = tempfile.mkdtemp(prefix="miniagent_py_")
                tmp_file = Path(tmp_dir) / "_inline.py"
                tmp_file.write_text(code, encoding="utf-8")
                cmd = [python_exe, str(tmp_file)]
                if args:
                    cmd.extend(args.split())
            else:
                # File mode
                fp = Path(path)
                if not fp.exists():
                    return f"Error: Script file not found: {path}"
                if not fp.is_file():
                    return f"Error: Not a file: {path}"
                cmd = [python_exe, str(fp)]
                if args:
                    cmd.extend(args.split())

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd or None,
                encoding="utf-8",
                errors="replace",
            )

            parts = []
            if result.stdout:
                parts.append(result.stdout.rstrip())
            if result.stderr:
                parts.append(f"[stderr]\n{result.stderr.rstrip()}")
            if result.returncode != 0:
                parts.append(f"[Exit code: {result.returncode}]")

            if not parts:
                return "(Script completed with no output)"

            output = "\n".join(parts)
            if len(output) > 50_000:
                output = output[:50_000] + f"\n\n(Output truncated, {len(output)} chars total)"
            return output

        except subprocess.TimeoutExpired:
            return f"Error: Script timed out after {timeout} seconds"
        except Exception as e:
            return f"Error running Python: {e}"
        finally:
            # Clean up temp files from inline mode
            if code:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Save Document Tool
# ---------------------------------------------------------------------------

class SaveDocumentTool(Tool):
    """Save generated documents to MiniAgent's output directory."""

    @staticmethod
    def _get_output_dir() -> Path:
        """Get the output directory under MiniAgent installation."""
        # MiniAgent package is at <install>/miniagent/, so output goes to <install>/output/
        miniagent_root = Path(__file__).resolve().parent.parent
        return miniagent_root / "output"

    # Auto-detect extension from content
    _TYPE_HINTS: list[tuple[str, str]] = [
        ("<!DOCTYPE html", ".html"), ("<html", ".html"),
        ("# ", ".md"),             # Common MD heading
        ("```", ".md"),            # Code block in MD
        ("{", ".json"),            # Likely JSON
        (",", ".csv"),             # Likely CSV
    ]

    @property
    def name(self) -> str:
        return "save_document"

    @property
    def description(self) -> str:
        return (
            "Save generated documents to the output directory (~/.miniagent/output/). "
            "Use this when you generate HTML pages, Markdown documents, JSON data, "
            "CSV files, or any other document content. "
            "If no filename is given, auto-generates one with timestamp. "
            "If no extension is given, auto-detects from content type."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The full document content to save",
                },
                "filename": {
                    "type": "string",
                    "description": "Filename with extension (e.g., 'report.md', 'index.html'). "
                                   "If omitted, auto-generates a name with timestamp.",
                },
            },
            "required": ["content"],
        }

    def execute(self, content: str = "", filename: str = "", **kw: Any) -> str:
        try:
            if not content:
                return "Error: content is required"

            # Ensure output dir exists
            output_dir = self._get_output_dir()
            output_dir.mkdir(parents=True, exist_ok=True)

            # Determine filename
            if not filename:
                filename = self._auto_filename(content)
            else:
                # Ensure filename has no path separator
                filename = Path(filename).name

            # If filename has no extension, auto-detect
            fp = Path(filename)
            if not fp.suffix:
                ext = self._detect_extension(content)
                filename = f"{fp.stem}{ext}"

            filepath = output_dir / filename
            filepath.write_text(content, encoding="utf-8")
            return f"Document saved to: {filepath}\n(Characters: {len(content)})"
        except PermissionError as e:
            return f"Error: Permission denied: {e}"
        except Exception as e:
            return f"Error saving document: {e}"

    def _auto_filename(self, content: str) -> str:
        """Generate a filename with timestamp and auto-detected extension."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = self._detect_extension(content)
        return f"doc_{ts}{ext}"

    def _detect_extension(self, content: str) -> str:
        """Detect file extension from content."""
        # Check first 500 chars for type hints
        preview = content[:500].strip().lower()
        for hint, ext in self._TYPE_HINTS:
            if hint.lower() in preview:
                return ext
        # Check if content is valid JSON
        stripped = content.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or \
           (stripped.startswith("[") and stripped.endswith("]")):
            try:
                json.loads(content)
                return ".json"
            except (json.JSONDecodeError, ValueError):
                pass
        # Default to .txt
        return ".txt"


# ---------------------------------------------------------------------------
# Default Tool Factory
# ---------------------------------------------------------------------------

def create_default_tools() -> ToolRegistry:
    """Create and register all built-in tools."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(ListDirTool())
    registry.register(ShellTool())
    registry.register(RunNodeTool())
    registry.register(RunPythonTool())
    registry.register(SaveDocumentTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    return registry
