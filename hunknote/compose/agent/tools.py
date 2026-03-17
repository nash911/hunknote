"""Agent tools for ReAct agents in Phase 2 and Phase 5b.

Each tool is a Python function with a structured signature. Tools are dispatched
by name via execute_tool(). Results have both truncated (for LLM context) and
full (for trace storage) output.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from hunknote.compose.models import HunkRef


@dataclass
class ToolResult:
    """Structured result from a tool call."""

    tool_name: str
    success: bool
    output: str           # Text result shown to the LLM (may be truncated)
    full_output: str      # Complete untruncated output (for trace storage)
    truncated: bool = False


# Max chars returned to the LLM context from a single tool call.
TOOL_OUTPUT_MAX_CHARS = 3000


TOOL_DEFINITIONS = [
    {
        "name": "ripgrep",
        "description": "Search the repository for a text pattern. Returns matching file paths, line numbers, and context.",
        "parameters": {
            "pattern": "string (required) — regex pattern to search for",
            "file_glob": "string (optional) — file glob filter, e.g. '*.py' or '*.ts'",
            "context_lines": "int (optional, default 2) — lines of context around matches",
            "max_results": "int (optional, default 20) — maximum matches to return",
        },
    },
    {
        "name": "read_file",
        "description": "Read lines from a file in the repository (current HEAD version).",
        "parameters": {
            "file_path": "string (required) — path relative to repo root",
            "line_start": "int (optional) — first line to read (1-indexed)",
            "line_end": "int (optional) — last line to read (inclusive)",
        },
    },
    {
        "name": "read_staged_file",
        "description": "Read the staged version of a file (HEAD + all staged hunks applied). Use this to see what the file WILL look like after all changes.",
        "parameters": {
            "file_path": "string (required) — path relative to repo root",
            "line_start": "int (optional)",
            "line_end": "int (optional)",
        },
    },
    {
        "name": "get_hunk",
        "description": "Retrieve the full diff content and metadata of a specific hunk by ID.",
        "parameters": {
            "hunk_id": "string (required) — the hunk ID, e.g. 'H3_a1b2c3'",
        },
    },
    {
        "name": "list_hunks",
        "description": "List all hunk IDs with their file paths and header lines. Use this for a quick overview.",
        "parameters": {},
    },
    {
        "name": "list_file_operations",
        "description": (
            "List all file-level operations (renames and hunkless deletions) "
            "with their synthetic IDs, old/new paths, and diff headers.  "
            "Use this to understand which files were renamed or deleted "
            "and to determine dependencies with regular hunks."
        ),
        "parameters": {},
    },
]


def execute_tool(
    tool_name: str,
    args: dict,
    repo_root: Path,
    inventory: dict[str, HunkRef],
    hunk_summaries: Optional[dict] = None,
) -> ToolResult:
    """Execute a tool and return a structured result."""
    if tool_name == "ripgrep":
        return _run_ripgrep(repo_root, **args)
    elif tool_name == "read_file":
        return _run_read_file(repo_root, **args)
    elif tool_name == "read_staged_file":
        return _run_read_staged_file(repo_root, **args)
    elif tool_name == "get_hunk":
        return _run_get_hunk(inventory, hunk_summaries, **args)
    elif tool_name == "list_hunks":
        return _run_list_hunks(inventory)
    elif tool_name == "list_file_operations":
        return _run_list_file_operations(inventory)
    else:
        return ToolResult(
            tool_name=tool_name, success=False,
            output=f"Unknown tool: {tool_name}",
            full_output=f"Unknown tool: {tool_name}",
        )


def format_tool_definitions(tool_names: Optional[list[str]] = None) -> str:
    """Format tool definitions for inclusion in a system prompt."""
    defs = TOOL_DEFINITIONS
    if tool_names is not None:
        defs = [d for d in defs if d["name"] in tool_names]

    lines: list[str] = []
    for d in defs:
        lines.append(f"Tool: {d['name']}")
        lines.append(f"  Description: {d['description']}")
        lines.append("  Parameters:")
        for pname, pdesc in d["parameters"].items():
            lines.append(f"    - {pname}: {pdesc}")
        lines.append("")
    return "\n".join(lines)


def _truncate(text: str, max_chars: int = TOOL_OUTPUT_MAX_CHARS) -> tuple[str, bool]:
    """Truncate for LLM context. Returns (truncated_text, was_truncated)."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n... [truncated]", True


def _run_ripgrep(
    repo_root: Path,
    pattern: str,
    file_glob: str = "",
    context_lines: int = 2,
    max_results: int = 20,
) -> ToolResult:
    """Run ripgrep on the repo. Falls back to grep if rg is not installed."""
    if shutil.which("rg"):
        cmd = [
            "rg", "--line-number",
            f"--context={context_lines}",
            f"--max-count={max_results}",
        ]
        if file_glob:
            cmd.extend(["--glob", file_glob])
        cmd.append(pattern)
    else:
        cmd = ["grep", "-rn", f"-C{context_lines}", f"-m{max_results}"]
        if file_glob:
            cmd.extend(["--include", file_glob])
        cmd.append(pattern)
        cmd.append(".")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=repo_root, timeout=10,
        )
        full_output = result.stdout
        if not full_output.strip():
            full_output = "(no matches found)"
    except subprocess.TimeoutExpired:
        full_output = "(search timed out after 10s)"
    except Exception as e:
        full_output = f"(search failed: {e})"

    output, truncated = _truncate(full_output)
    return ToolResult(
        tool_name="ripgrep", success=True, output=output,
        full_output=full_output, truncated=truncated,
    )


def _run_read_file(
    repo_root: Path,
    file_path: str,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
) -> ToolResult:
    """Read lines from a file (HEAD version via git show HEAD:<path>)."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{file_path}"],
            capture_output=True, text=True,
            cwd=repo_root, timeout=10,
        )
        if result.returncode != 0:
            return ToolResult(
                tool_name="read_file", success=False,
                output=f"File not found: {file_path}",
                full_output=result.stderr,
            )
        content = result.stdout
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_name="read_file", success=False,
            output="(timed out)", full_output="(timed out)",
        )

    lines = content.split("\n")
    if line_start is not None or line_end is not None:
        start = (line_start or 1) - 1
        end = line_end or len(lines)
        lines = lines[start:end]

    numbered = [f"{i + (line_start or 1)}:{ln}" for i, ln in enumerate(lines)]
    full_output = "\n".join(numbered)
    output, truncated = _truncate(full_output)
    return ToolResult(
        tool_name="read_file", success=True, output=output,
        full_output=full_output, truncated=truncated,
    )


def _run_read_staged_file(
    repo_root: Path,
    file_path: str,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
) -> ToolResult:
    """Read the staged version of a file (index version via git show :<path>)."""
    try:
        result = subprocess.run(
            ["git", "show", f":{file_path}"],
            capture_output=True, text=True,
            cwd=repo_root, timeout=10,
        )
        if result.returncode != 0:
            return ToolResult(
                tool_name="read_staged_file", success=False,
                output=f"File not found in index: {file_path}",
                full_output=result.stderr,
            )
        content = result.stdout
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_name="read_staged_file", success=False,
            output="(timed out)", full_output="(timed out)",
        )

    lines = content.split("\n")
    if line_start is not None or line_end is not None:
        start = (line_start or 1) - 1
        end = line_end or len(lines)
        lines = lines[start:end]

    numbered = [f"{i + (line_start or 1)}:{ln}" for i, ln in enumerate(lines)]
    full_output = "\n".join(numbered)
    output, truncated = _truncate(full_output)
    return ToolResult(
        tool_name="read_staged_file", success=True, output=output,
        full_output=full_output, truncated=truncated,
    )


def _run_get_hunk(
    inventory: dict[str, HunkRef],
    hunk_summaries: Optional[dict],
    hunk_id: str,
) -> ToolResult:
    """Return the full diff and summary of a hunk."""
    hunk = inventory.get(hunk_id)
    if not hunk:
        return ToolResult(
            tool_name="get_hunk", success=False,
            output=f"Hunk {hunk_id} not found",
            full_output=f"Hunk {hunk_id} not found",
        )
    lines = "\n".join(hunk.lines)
    summary_text = ""
    if hunk_summaries and hunk_id in hunk_summaries:
        s = hunk_summaries[hunk_id]
        summary_text = (
            f"\nSummary: {s.intent}\nCategory: {s.category}"
            f"\nSymbols modified: {', '.join(s.symbols_modified)}"
            f"\nSymbols referenced: {', '.join(s.symbols_referenced)}"
        )
    full_output = f"Hunk {hunk_id} in {hunk.file_path}\n{hunk.header}\n{lines}{summary_text}"
    output, truncated = _truncate(full_output)
    return ToolResult(
        tool_name="get_hunk", success=True, output=output,
        full_output=full_output, truncated=truncated,
    )


def _run_list_hunks(inventory: dict[str, HunkRef]) -> ToolResult:
    """List all hunk IDs with file paths and headers."""
    from hunknote.compose.inventory import is_file_op_id

    lines: list[str] = []
    for hid in sorted(
        (k for k in inventory if not is_file_op_id(k)),
        key=lambda x: int(x.split("_")[0][1:]),
    ):
        h = inventory[hid]
        lines.append(f"{hid}: {h.file_path}  {h.header.strip()}")
    full_output = "\n".join(lines)
    output, truncated = _truncate(full_output)
    return ToolResult(
        tool_name="list_hunks", success=True, output=output,
        full_output=full_output, truncated=truncated,
    )


def _run_list_file_operations(inventory: dict[str, HunkRef]) -> ToolResult:
    """List all synthetic file-operation entries (renames and deletions)."""
    from hunknote.compose.inventory import is_file_op_id, RENAME_PREFIX, DELETE_PREFIX

    lines: list[str] = []
    for hid in sorted(k for k in inventory if is_file_op_id(k)):
        h = inventory[hid]
        if hid.startswith(RENAME_PREFIX):
            lines.append(f"{hid}: RENAME  {h.header}")
            lines.append(f"  New path: {h.file_path}")
            lines.append(f"  Diff header: {' | '.join(h.lines)}")
        elif hid.startswith(DELETE_PREFIX):
            lines.append(f"{hid}: DELETE  {h.header}")
            lines.append(f"  Path: {h.file_path}")
            lines.append(f"  Diff header: {' | '.join(h.lines)}")
        lines.append("")

    if not lines:
        full_output = "(no file operations — no renames or hunkless deletions)"
    else:
        full_output = "\n".join(lines)

    output, truncated = _truncate(full_output)
    return ToolResult(
        tool_name="list_file_operations", success=True, output=output,
        full_output=full_output, truncated=truncated,
    )

