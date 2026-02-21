"""CLI commands for ignore pattern management."""

import typer

from hunknote.git_ctx import GitError, get_repo_root
from hunknote.user_config import (
    add_ignore_pattern,
    get_ignore_patterns,
    remove_ignore_pattern,
)

# Subcommand group for ignore pattern management
ignore_app = typer.Typer(
    name="ignore",
    help="Manage ignore patterns in .hunknote/config.yaml",
    add_completion=False,
)


@ignore_app.command("list")
def ignore_list() -> None:
    """Show all ignore patterns in .hunknote/config.yaml."""
    try:
        repo_root = get_repo_root()
        patterns = get_ignore_patterns(repo_root)

        typer.echo("Ignore patterns in .hunknote/config.yaml:")
        typer.echo()
        if patterns:
            for pattern in patterns:
                typer.echo(f"  - {pattern}")
            typer.echo()
            typer.echo(f"Total: {len(patterns)} pattern(s)")
        else:
            typer.echo("  (no patterns configured)")
        typer.echo()
        typer.echo("These files are excluded from the diff sent to the LLM.")

    except GitError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@ignore_app.command("add")
def ignore_add(
    pattern: str = typer.Argument(
        ...,
        help="File pattern to add (e.g., *.log, build/*, package-lock.json)",
    ),
) -> None:
    """Add a pattern to the ignore list."""
    try:
        repo_root = get_repo_root()

        # Check if pattern already exists
        patterns = get_ignore_patterns(repo_root)
        if pattern in patterns:
            typer.echo(f"Pattern already exists: {pattern}")
            raise typer.Exit(0)

        add_ignore_pattern(repo_root, pattern)
        typer.echo(f"Added ignore pattern: {pattern}")

    except GitError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@ignore_app.command("remove")
def ignore_remove(
    pattern: str = typer.Argument(
        ...,
        help="File pattern to remove from the ignore list",
    ),
) -> None:
    """Remove a pattern from the ignore list."""
    try:
        repo_root = get_repo_root()

        if remove_ignore_pattern(repo_root, pattern):
            typer.echo(f"Removed ignore pattern: {pattern}")
        else:
            typer.echo(f"Pattern not found: {pattern}", err=True)
            raise typer.Exit(1)

    except GitError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

