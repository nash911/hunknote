"""CLI entry point for aicommit."""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import typer

from aicommit.cache import (
    CacheMetadata,
    compute_context_hash,
    extract_staged_files,
    get_diff_preview,
    get_message_file,
    invalidate_cache,
    is_cache_valid,
    load_cache_metadata,
    load_cached_message,
    save_cache,
    update_message_cache,
)
from aicommit.formatters import render_commit_message
from aicommit.git_ctx import (
    GitError,
    NoStagedChangesError,
    build_context_bundle,
    get_repo_root,
    get_staged_diff,
    get_status,
)
from aicommit.llm import LLMError, LLMResult, MissingAPIKeyError, generate_commit_json

app = typer.Typer(
    name="aicommit",
    help="AI-powered git commit message generator using LLMs",
    add_completion=False,
)



def _find_editor() -> list[str]:
    """Find an available text editor.

    Preference order:
    1. gedit --wait (if gedit is available)
    2. $EDITOR environment variable
    3. nano as fallback

    Returns:
        List of command parts to run the editor.
    """
    # Try gedit first
    if shutil.which("gedit"):
        return ["gedit", "--wait"]

    # Try $EDITOR
    editor = os.environ.get("EDITOR")
    if editor:
        return [editor]

    # Fallback to nano
    if shutil.which("nano"):
        return ["nano"]

    # Last resort: vi
    return ["vi"]


def _open_editor(file_path: Path) -> None:
    """Open the file in an editor and wait for it to close.

    Args:
        file_path: Path to the file to edit.
    """
    editor_cmd = _find_editor()

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


def _display_debug_info(
    repo_root: Path,
    metadata: CacheMetadata,
    current_message: str,
    cache_valid: bool,
) -> None:
    """Display debug information about the cache.

    Args:
        repo_root: The root directory of the git repository.
        metadata: The cache metadata.
        current_message: The current commit message (may be edited).
        cache_valid: Whether the cache is currently valid.
    """
    typer.echo("=" * 60)
    typer.echo("                  AICOMMIT DEBUG INFO")
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
    typer.echo(f"Tokens: {metadata.input_tokens} input / {metadata.output_tokens} output")
    typer.echo()

    # Staged files
    typer.echo("Staged Files:")
    for f in metadata.staged_files:
        typer.echo(f"  - {f}")
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
        typer.echo("Original AI Message:")
        for line in metadata.original_message.strip().split("\n"):
            typer.echo(f"  {line}")
        typer.echo()
        typer.echo("Current Message:")
        for line in current_message.strip().split("\n"):
            typer.echo(f"  {line}")
    else:
        typer.echo("Message Edit Status: UNMODIFIED")
        typer.echo()
        typer.echo("Current Message:")
        for line in current_message.strip().split("\n"):
            typer.echo(f"  {line}")

    typer.echo()
    typer.echo("=" * 60)


@app.command()
def main(
    max_diff_chars: int = typer.Option(
        50000,
        "--max-diff-chars",
        help="Maximum characters for the staged diff",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        is_flag=True,
        flag_value=True,
        help="Print raw JSON output for debugging",
    ),
    regenerate: bool = typer.Option(
        False,
        "--regenerate",
        "-r",
        is_flag=True,
        flag_value=True,
        help="Force regenerate the commit message, ignoring cache",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        is_flag=True,
        flag_value=True,
        help="Show full metadata of the cached aicommit message",
    ),
    edit: bool = typer.Option(
        False,
        "--edit",
        "-e",
        is_flag=True,
        flag_value=True,
        help="Open the generated message file in an editor for manual edits",
    ),
    commit: bool = typer.Option(
        False,
        "--commit",
        "-c",
        is_flag=True,
        flag_value=True,
        help="Perform the commit using the generated message",
    ),
) -> None:
    """Generate an AI-powered git commit message from staged changes."""
    try:
        # Step 1: Get repo root
        repo_root = get_repo_root()

        # Step 2: Build context bundle
        typer.echo("Collecting git context...", err=True)
        context_bundle = build_context_bundle(max_chars=max_diff_chars)

        # Step 3: Compute context hash
        current_hash = compute_context_hash(context_bundle)

        # Step 4: Extract staged files and diff preview for metadata
        status_output = get_status()
        staged_files = extract_staged_files(status_output)
        staged_diff = get_staged_diff(max_chars=max_diff_chars)
        diff_preview = get_diff_preview(staged_diff, max_chars=500)

        # Step 5: Check cache validity (unless --regenerate or --json)
        cache_valid = not regenerate and not json_output and is_cache_valid(repo_root, current_hash)

        if cache_valid:
            # Use cached message
            typer.echo("Using cached commit message...", err=True)
            message = load_cached_message(repo_root)
            metadata = load_cache_metadata(repo_root)
        else:
            # Generate new message via LLM
            typer.echo("Generating commit message...", err=True)
            llm_result = generate_commit_json(context_bundle)

            # Handle --json flag: print raw JSON and exit
            if json_output:
                typer.echo(llm_result.commit_json.model_dump_json(indent=2))
                raise typer.Exit(0)

            # Render the commit message
            message = render_commit_message(llm_result.commit_json)

            # Save to cache
            save_cache(
                repo_root=repo_root,
                context_hash=current_hash,
                message=message,
                model=llm_result.model,
                input_tokens=llm_result.input_tokens,
                output_tokens=llm_result.output_tokens,
                staged_files=staged_files,
                diff_preview=diff_preview,
            )
            metadata = load_cache_metadata(repo_root)

        # Step 6: Handle --debug flag
        if debug:
            if metadata:
                _display_debug_info(repo_root, metadata, message, cache_valid)
            else:
                typer.echo("No cache metadata found.", err=True)
            raise typer.Exit(0)

        # Step 7: Get message file path
        message_file = get_message_file(repo_root)

        # Step 8: If --edit flag, open editor
        if edit:
            _open_editor(message_file)
            # Re-read the file after editing
            message = message_file.read_text()
            # Update the message cache (but keep original metadata for diff comparison)
            update_message_cache(repo_root, message)
            typer.echo("Message updated from editor.", err=True)

        # Step 9: Print the final message to stdout
        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(message)
        typer.echo("=" * 60)

        # Step 10: If --commit flag, perform the commit
        if commit:
            typer.echo("")
            typer.echo("Committing...", err=True)
            result = subprocess.run(
                ["git", "commit", "-F", str(message_file)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                typer.echo("Commit successful!", err=True)
                typer.echo(result.stdout)
                # Invalidate cache after successful commit
                invalidate_cache(repo_root)
            else:
                typer.echo("Commit failed!", err=True)
                typer.echo(result.stderr, err=True)
                raise typer.Exit(1)

    except NoStagedChangesError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except MissingAPIKeyError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except GitError as e:
        typer.echo(f"Git error: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"LLM error: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
