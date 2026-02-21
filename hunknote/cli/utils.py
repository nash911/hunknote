"""Shared utility functions for CLI commands."""

import difflib
import hashlib
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from hunknote.cache import CacheMetadata
from hunknote.git_ctx import GitError, get_repo_root
from hunknote.styles import (
    StyleConfig,
    load_style_config_from_dict,
)
from hunknote.scope import (
    ScopeConfig,
    load_scope_config_from_dict,
)
from hunknote import global_config
from hunknote.user_config import get_repo_style_config


def generate_message_diff(original: str, current: str) -> str:
    """Generate a git diff-style comparison between two messages.

    Args:
        original: The original AI-generated message.
        current: The current (possibly edited) message.

    Returns:
        A git diff-style string showing the differences.
    """
    original_lines = original.strip().splitlines(keepends=True)
    current_lines = current.strip().splitlines(keepends=True)

    # Add newlines if missing for proper diff output
    if original_lines and not original_lines[-1].endswith("\n"):
        original_lines[-1] += "\n"
    if current_lines and not current_lines[-1].endswith("\n"):
        current_lines[-1] += "\n"

    diff = difflib.unified_diff(
        original_lines,
        current_lines,
        fromfile="a/original_message",
        tofile="b/current_message",
        lineterm="",
    )

    return "".join(diff)


def get_current_branch_safe() -> str:
    """Safely get the current branch name without raising errors.

    Returns:
        The branch name, or 'unknown' if it cannot be determined.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return "unknown"
    except OSError:
        return "unknown"


def find_editor() -> list[str]:
    """Find an available text editor.

    Preference order:
    1. gedit --wait (if gedit is available)
    2. $EDITOR environment variable
    3. nano as fallback

    Returns:
        List of command parts to run the editor.
    """
    # Try gedit first
    # noinspection PyArgumentList
    if shutil.which("gedit"):
        return ["gedit", "--wait"]

    # Try $EDITOR
    editor = os.environ.get("EDITOR")
    if editor:
        return [editor]

    # Fallback to nano
    # noinspection PyArgumentList
    if shutil.which("nano"):
        return ["nano"]

    # Last resort: vi
    return ["vi"]


def open_editor(file_path: Path) -> None:
    """Open the file in an editor and wait for it to close.

    Args:
        file_path: Path to the file to edit.
    """
    editor_cmd = find_editor()

    typer.echo(f"Opening editor: {' '.join(editor_cmd)}")

    try:
        # Run the editor and wait for it to complete
        result = subprocess.run(
            editor_cmd + [str(file_path)],
            check=False,
        )

        if result.returncode != 0:
            typer.echo(f"Warning: Editor exited with code {result.returncode}", err=True)

    except FileNotFoundError:
        typer.echo(f"Error: Editor not found: {editor_cmd[0]}", err=True)
        raise typer.Exit(1)


def process_intent_options(intent: Optional[str], intent_file: Optional[Path]) -> Optional[str]:
    """Process --intent and --intent-file options.

    Args:
        intent: Direct intent text from --intent option.
        intent_file: Path to file containing intent from --intent-file option.

    Returns:
        Combined intent content, or None if no intent provided.

    Raises:
        typer.Exit: If intent_file cannot be read.
    """
    parts = []

    # Add --intent content first
    if intent:
        trimmed = intent.strip()
        if trimmed:
            parts.append(trimmed)

    # Add --intent-file content
    if intent_file:
        if not intent_file.exists():
            typer.echo(f"Error: Intent file not found: {intent_file}", err=True)
            raise typer.Exit(1)
        try:
            file_content = intent_file.read_text().strip()
            if file_content:
                parts.append(file_content)
        except Exception as e:
            typer.echo(f"Error reading intent file: {e}", err=True)
            raise typer.Exit(1)

    # Combine with blank line if both provided
    if not parts:
        return None

    return "\n\n".join(parts)


def compute_intent_fingerprint(intent_content: Optional[str]) -> Optional[str]:
    """Compute a fingerprint for intent content for cache keying.

    Args:
        intent_content: The intent content string.

    Returns:
        A 12-character hex fingerprint, or None if no intent.
    """
    if not intent_content:
        return None

    return hashlib.sha256(intent_content.encode("utf-8")).hexdigest()[:12]


def inject_intent_into_context(context_bundle: str, intent_content: str) -> str:
    """Inject the [INTENT] block into the context bundle.

    The intent block is placed after [FILE_CHANGES] and before [LAST_5_COMMITS].

    Args:
        context_bundle: The original context bundle string.
        intent_content: The intent content to inject.

    Returns:
        The context bundle with the [INTENT] block inserted.
    """
    intent_block = f"\n[INTENT]\n{intent_content}\n"

    # Insert before [LAST_5_COMMITS] section
    if "[LAST_5_COMMITS]" in context_bundle:
        return context_bundle.replace(
            "[LAST_5_COMMITS]",
            f"{intent_block}\n[LAST_5_COMMITS]"
        )

    # Fallback: append before [STAGED_DIFF] if LAST_5_COMMITS not found
    if "[STAGED_DIFF]" in context_bundle:
        return context_bundle.replace(
            "[STAGED_DIFF]",
            f"{intent_block}\n[STAGED_DIFF]"
        )

    # Last resort: append at the end
    return context_bundle + intent_block


def display_debug_info(
    _repo_root: Path,
    metadata: CacheMetadata,
    current_message: str,
    cache_valid: bool,
    intent_content: Optional[str] = None,
) -> None:
    """Display debug information about the cache.

    Args:
        _repo_root: The root directory of the git repository.
        metadata: The cache metadata.
        current_message: The current commit message (may be edited).
        cache_valid: Whether the cache is currently valid.
        intent_content: The intent content if provided.
    """
    typer.echo("=" * 60)
    typer.echo("                  HUNKNOTE DEBUG INFO")
    typer.echo("=" * 60)
    typer.echo()

    # Cache status
    status = "VALID (using cached message)" if cache_valid else "INVALID (will regenerate)"
    typer.echo(f"Cache Status: {status}")
    typer.echo(f"Cache Key: {metadata.context_hash[:16]}...")

    # Parse and format timestamp
    try:
        generated_dt = datetime.fromisoformat(metadata.generated_at)
        formatted_time = generated_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, AttributeError):
        formatted_time = metadata.generated_at

    typer.echo(f"Generated At: {formatted_time}")
    typer.echo(f"LLM Model: {metadata.model}")
    typer.echo()

    # Token and character counts
    typer.echo("Usage Statistics:")
    typer.echo(f"  Tokens:     {metadata.input_tokens:,} input / {metadata.output_tokens:,} output")
    if metadata.input_chars > 0 or metadata.prompt_chars > 0 or metadata.output_chars > 0:
        typer.echo(f"  Characters: {metadata.input_chars:,} context / {metadata.prompt_chars:,} prompt / {metadata.output_chars:,} output")
    typer.echo()

    # Staged files
    typer.echo("Staged Files:")
    for f in metadata.staged_files:
        typer.echo(f"  - {f}")
    typer.echo()

    # Intent info (if provided)
    if intent_content:
        # Show first ~80 chars plus total length (as per spec)
        preview = intent_content[:80]
        if len(intent_content) > 80:
            preview += "..."
        typer.echo(f"Intent: {preview} ({len(intent_content)} chars)")
        typer.echo()
    else:
        typer.echo("Intent: (not provided)")
        typer.echo()

    # Diff preview
    typer.echo("Diff Preview:")
    for line in metadata.diff_preview.split("\n")[:15]:
        typer.echo(f"  {line}")
    if len(metadata.diff_preview.split("\n")) > 15:
        typer.echo("  ...")
    typer.echo()

    # Message edit status
    if current_message.strip() != metadata.original_message.strip():
        typer.echo("Message Edit Status: MODIFIED")
        typer.echo()
        typer.echo("Message Diff:")
        diff_output = generate_message_diff(metadata.original_message, current_message)
        if diff_output:
            for line in diff_output.splitlines():
                typer.echo(f"  {line}")
        else:
            typer.echo("  (no visible differences)")
    else:
        typer.echo("Message Edit Status: UNMODIFIED")
        typer.echo()
        typer.echo("Current Message:")
        for line in current_message.strip().split("\n"):
            typer.echo(f"  {line}")

    typer.echo()
    typer.echo("=" * 60)


def get_effective_style_config() -> StyleConfig:
    """Get the effective style configuration (repo overrides global)."""
    # Start with defaults
    config_dict = {"style": {"profile": "default"}}

    # Merge global config
    global_style = global_config.get_style_config()
    if global_style:
        config_dict["style"].update(global_style)

    # Merge repo config (overrides global)
    try:
        repo_root = get_repo_root()
        repo_style = get_repo_style_config(repo_root)
        if repo_style:
            config_dict["style"].update(repo_style)
    except GitError:
        pass  # Not in a repo, use global only

    return load_style_config_from_dict(config_dict)


def get_effective_scope_config() -> ScopeConfig:
    """Get the effective scope configuration (repo overrides global)."""
    from hunknote.user_config import get_repo_scope_config

    # Start with defaults
    config_dict: dict = {"scope": {}}

    # Merge global config
    global_scope = global_config.get_scope_config()
    if global_scope:
        config_dict["scope"].update(global_scope)

    # Merge repo config (overrides global)
    try:
        repo_root = get_repo_root()
        repo_scope = get_repo_scope_config(repo_root)
        if repo_scope:
            config_dict["scope"].update(repo_scope)
    except GitError:
        pass  # Not in a repo, use global only

    return load_scope_config_from_dict(config_dict)


def colorize_diff(text: str) -> str:
    """Add ANSI color codes to diff lines like git diff.

    - Red for removed lines (-)
    - Green for added lines (+)
    - Cyan for hunk headers (@@)
    - Bold for diff/file header lines

    Args:
        text: Raw diff text.

    Returns:
        Colorized diff text with ANSI escape codes.
    """
    red = "\033[31m"
    green = "\033[32m"
    cyan = "\033[36m"
    bold = "\033[1m"
    reset = "\033[0m"

    colorized = []
    for line in text.split("\n"):
        if line.startswith("@@"):
            colorized.append(f"{cyan}{line}{reset}")
        elif line.startswith("---") or line.startswith("+++"):
            colorized.append(f"{bold}{line}{reset}")
        elif line.startswith("-"):
            colorized.append(f"{red}{line}{reset}")
        elif line.startswith("+"):
            colorized.append(f"{green}{line}{reset}")
        elif line.startswith("diff --git"):
            colorized.append(f"{bold}{line}{reset}")
        else:
            colorized.append(line)
    return "\n".join(colorized)


def show_in_pager(text: str) -> None:
    """Display text in a scrollable pager.

    Uses the system pager (less) which supports arrow-key scrolling
    and q/Q to quit. Falls back to direct output if pager is unavailable.

    Args:
        text: The text to display.
    """
    # Prefer 'less' with options for color and raw control chars
    # noinspection PyArgumentList
    less_path = shutil.which("less")
    if less_path:
        try:
            proc = subprocess.Popen(
                [less_path, "-R", "--quit-if-one-screen"],
                stdin=subprocess.PIPE,
                encoding="utf-8",
            )
            proc.communicate(input=text)
            return
        except (OSError, BrokenPipeError):
            pass

    # Fallback: try 'more'
    # noinspection PyArgumentList
    more_path = shutil.which("more")
    if more_path:
        try:
            proc = subprocess.Popen(
                [more_path],
                stdin=subprocess.PIPE,
                encoding="utf-8",
            )
            proc.communicate(input=text)
            return
        except (OSError, BrokenPipeError):
            pass

    # Final fallback: print directly
    typer.echo(text)

