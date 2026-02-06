"""CLI entry point for aicommit."""

import os
import shutil
import subprocess
from pathlib import Path

import typer

from aicommit.formatters import render_commit_message
from aicommit.git_ctx import (
    GitError,
    NoStagedChangesError,
    build_context_bundle,
    get_repo_root,
)
from aicommit.llm import LLMError, MissingAPIKeyError, generate_commit_json

app = typer.Typer(
    name="aicommit",
    help="AI-powered git commit message generator using LLMs",
    add_completion=False,
)


def _get_message_file_path(repo_root: Path) -> Path:
    """Get the path for the commit message file.

    Creates .tmp directory if it does not exist.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to the message file: <repo_root>/.tmp/aicommit_<pid>.txt
    """
    tmp_dir = repo_root / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    return tmp_dir / f"aicommit_{os.getpid()}.txt"


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

        # Step 3: Generate commit message via LLM
        typer.echo("Generating commit message...", err=True)
        commit_json = generate_commit_json(context_bundle)

        # Step 4: If --json flag, print raw JSON and exit
        if json_output:
            typer.echo(commit_json.model_dump_json(indent=2))
            raise typer.Exit(0)

        # Step 5: Render the commit message
        message = render_commit_message(commit_json)

        # Step 6: Write message to file
        message_file = _get_message_file_path(repo_root)
        message_file.write_text(message)
        typer.echo(f"Message saved to: {message_file}", err=True)

        # Step 7: If --edit flag, open editor
        if edit:
            _open_editor(message_file)
            # Re-read the file after editing
            message = message_file.read_text()
            typer.echo("Message updated from editor.", err=True)

        # Step 8: Print the final message to stdout
        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(message)
        typer.echo("=" * 60)

        # Step 9: If --commit flag, perform the commit
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
