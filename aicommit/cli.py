"""CLI entry point for aicommit."""

import typer

app = typer.Typer(
    name="aicommit",
    help="AI-powered git commit message generator using LLMs",
    add_completion=False,
)


@app.command()
def main(
    edit: bool = typer.Option(
        False,
        "--edit",
        "-e",
        help="Open the generated message file in an editor for manual edits",
    ),
    commit: bool = typer.Option(
        False,
        "--commit",
        "-c",
        help="Perform the commit using the generated message",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print raw JSON output for debugging",
    ),
    max_diff_chars: int = typer.Option(
        50000,
        "--max-diff-chars",
        help="Maximum characters for the staged diff",
    ),
) -> None:
    """Generate an AI-powered git commit message from staged changes."""
    typer.echo("aicommit CLI - AI Commit Message Generator")
    typer.echo("Run 'aicommit --help' for usage information.")


if __name__ == "__main__":
    app()
