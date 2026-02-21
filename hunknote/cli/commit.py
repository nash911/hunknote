"""CLI command for committing with generated message."""

import subprocess

import typer

from hunknote.cache import (
    get_message_file,
    invalidate_cache,
    load_cache_metadata,
    load_cached_message,
)
from hunknote.git_ctx import GitError, get_repo_root


def commit_command(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Bypass confirmation prompt and commit immediately",
    ),
) -> None:
    """Commit staged changes using the generated message.

    Uses the cached commit message from the last 'hunknote' run.
    If no cached message exists, generates a new one first.
    """
    from hunknote.config import load_config
    load_config()

    try:
        repo_root = get_repo_root()

        # Check if we have a cached message
        metadata = load_cache_metadata(repo_root)
        message = load_cached_message(repo_root)
        message_file = get_message_file(repo_root)

        if metadata and message:
            # Use existing cached message
            typer.echo("Using cached commit message...", err=True)
            typer.echo("")
            typer.echo("=" * 60)
            typer.echo(message)
            typer.echo("=" * 60)

            # Ask for confirmation unless --yes flag is used
            if not yes:
                typer.echo("")
                confirm = typer.prompt(
                    "Commit with this message? [Y/n]",
                    default="y",
                    show_default=False,
                )
                if confirm.lower() not in ("y", "yes", ""):
                    typer.echo("Commit cancelled.", err=True)
                    raise typer.Exit(0)

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
                invalidate_cache(repo_root)
            else:
                typer.echo("Commit failed!", err=True)
                typer.echo(result.stderr, err=True)
                raise typer.Exit(1)
        else:
            # No cached message - prompt user to generate one first
            typer.echo("No cached commit message found.", err=True)
            typer.echo("Run 'hunknote' first to generate a commit message.", err=True)
            raise typer.Exit(1)

    except GitError as e:
        typer.echo(f"Git error: {e}", err=True)
        raise typer.Exit(1)

