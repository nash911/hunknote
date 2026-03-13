"""CLI entry points for the eval module.

Standalone CLI — NOT integrated into hunknote's main CLI.
Run with: python -m eval.cli <command>
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from eval.config import EVAL_TEST_CASES_DIR
from eval.models import DifficultyTier, Language

eval_app = typer.Typer(
    name="eval",
    help="Compose Agent evaluation framework",
    no_args_is_help=True,
)

logger = logging.getLogger(__name__)


@eval_app.command("generate")
def generate_case_cmd(
    repo: str = typer.Option(..., help="GitHub repo URL"),
    commits: str = typer.Option(..., help="Commit range (e.g., 'abc123~4..abc123')"),
    id: str = typer.Option(..., "--id", help="Test case ID"),
    language: str = typer.Option("python", help="Language"),
    tier: int = typer.Option(3, help="Difficulty tier (1-5)"),
    description: str = typer.Option("", help="Description"),
    install_cmd: list[str] = typer.Option([], help="Pip install commands (repeatable)"),
    check_command: str = typer.Option(
        "python -m py_compile {file}", help="Syntax check command"
    ),
    test_command: Optional[str] = typer.Option(None, help="Test command"),
    output_dir: Optional[str] = typer.Option(None, help="Output directory"),
    python_version_min: Optional[str] = typer.Option(None, help="Min Python version"),
) -> None:
    """Generate a test case from a real repo commit sequence."""
    from eval.generator import generate_case
    from eval.models import BuildSystemConfig

    _setup_logging()

    build_system = BuildSystemConfig(
        type=language,
        install_commands=install_cmd,
        check_command=check_command,
        test_command=test_command,
        test_enabled=test_command is not None,
        python_version_min=python_version_min,
    )

    out = Path(output_dir) if output_dir else EVAL_TEST_CASES_DIR / language

    try:
        case = generate_case(
            repo_url=repo,
            commit_range=commits,
            case_id=id,
            language=Language(language),
            tier=DifficultyTier(tier),
            description=description,
            output_dir=out,
            build_system=build_system,
        )
        typer.echo(
            f"Generated case: {case.id}\n"
            f"  Hunks: {case.stats.total_hunks}\n"
            f"  Files: {case.stats.total_files}\n"
            f"  Reference commits: {case.stats.reference_commit_count}\n"
            f"  Output: {out / case.id}"
        )
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@eval_app.command("run")
def run_eval_cmd(
    suite: str = typer.Option("standard", help="Suite: smoke, standard, full"),
    language: Optional[str] = typer.Option(None, help="Filter by language"),
    tier: Optional[int] = typer.Option(None, help="Filter by tier"),
    case: Optional[str] = typer.Option(None, help="Run a specific case by ID"),
    model: Optional[str] = typer.Option(None, help="LLM model to use"),
    provider: Optional[str] = typer.Option(None, help="LLM provider"),
    max_retries: int = typer.Option(2, help="Max retries for agent"),
    max_commits: int = typer.Option(8, help="Max commits per plan"),
    agent: bool = typer.Option(
        True,  # Default to True to use Compose Agent if available, but allow fallback to single-shot LLM
        "--agent/--no-agent",
        help="Use Compose Agent (multi-step) instead of single-shot LLM. "
             "Requires the agent module to be available.",
    ),
    judge: bool = typer.Option(False, help="Enable LLM-as-judge"),
    judge_model: Optional[str] = typer.Option(None, help="Model for LLM-as-judge"),
    output_dir: Optional[str] = typer.Option(None, help="Output directory for results"),
) -> None:
    """Run the evaluation suite."""
    from eval.config import DEFAULT_AGENT_CONFIG, DEFAULT_JUDGE_CONFIG
    from eval.harness import run_eval
    from eval.registry import discover_cases, filter_cases_by_suite

    _setup_logging()

    # Discover and filter cases
    lang = Language(language) if language else None
    diff_tier = DifficultyTier(tier) if tier else None
    cases = discover_cases(language=lang, tier=diff_tier)

    if case:
        cases = [c for c in cases if c.id == case]
        if not cases:
            typer.echo(f"Case not found: {case}", err=True)
            raise typer.Exit(1)
    else:
        cases = filter_cases_by_suite(cases, suite)

    if not cases:
        typer.echo("No test cases found matching filters.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Found {len(cases)} test case(s) to evaluate")

    # Build agent config
    agent_config = dict(DEFAULT_AGENT_CONFIG)
    if provider:
        agent_config["provider"] = provider
    if model:
        agent_config["model"] = model
    agent_config["max_retries"] = max_retries
    agent_config["max_commits"] = max_commits

    # Handle --agent flag
    use_agent = agent
    if use_agent:
        try:
            from hunknote.compose.agents import AgentOrchestrator  # noqa: F401
        except (ImportError, ModuleNotFoundError, AttributeError):
            typer.echo(
                "Compose Agent module not available — falling back to single-shot LLM.",
                err=True,
            )
            use_agent = False
    agent_config["use_agent"] = use_agent

    # Build judge config
    judge_config = None
    if judge:
        judge_config = dict(DEFAULT_JUDGE_CONFIG)
        judge_config["enabled"] = True
        if judge_model:
            judge_config["model"] = judge_model

    out = Path(output_dir) if output_dir else None

    result = run_eval(
        cases=cases,
        agent_config=agent_config,
        judge_config=judge_config,
        output_dir=out,
    )

    # Print summary
    summary = result.get_summary()
    typer.echo(f"\nResults: {summary['passed']}/{summary['total']} passed")
    typer.echo(f"Average score: {summary['avg_score']:.3f}")
    typer.echo(f"Mechanical pass rate: {summary.get('mechanical_pass_rate', 0):.1%}")

    failures = result.get_failures()
    if failures:
        typer.echo(f"\nFailures ({len(failures)}):")
        for f in failures:
            error = f.error or "mechanical failure"
            typer.echo(f"  - {f.case_id}: {error}")


@eval_app.command("compare")
def compare_runs_cmd(
    baseline: str = typer.Argument(..., help="Path to baseline result JSON"),
    current: str = typer.Argument(..., help="Path to current result JSON"),
    fail_on_regression: bool = typer.Option(
        False, help="Exit 1 if regressions found"
    ),
    threshold: float = typer.Option(0.05, help="Regression threshold"),
) -> None:
    """Compare two eval runs and identify regressions."""
    from eval.reporting import compare_runs, load_result

    baseline_result = load_result(Path(baseline))
    current_result = load_result(Path(current))

    comparison = compare_runs(current_result, baseline_result, threshold)

    agg = comparison["aggregate_diff"]
    typer.echo(f"Baseline avg: {agg['baseline_avg']:.3f} -> Current avg: {agg['current_avg']:.3f}")
    typer.echo(f"Score diff: {agg['avg_score_diff']:+.3f}")
    typer.echo(
        f"Pass rate: {agg['baseline_pass_rate']:.1%} -> {agg['current_pass_rate']:.1%}"
    )

    if comparison["new_failures"]:
        typer.echo(f"\nNew failures ({len(comparison['new_failures'])}):")
        for case_id in comparison["new_failures"]:
            typer.echo(f"  - {case_id}")

    if comparison["new_passes"]:
        typer.echo(f"\nNew passes ({len(comparison['new_passes'])}):")
        for case_id in comparison["new_passes"]:
            typer.echo(f"  + {case_id}")

    if comparison["score_regressions"]:
        typer.echo(f"\nScore regressions ({len(comparison['score_regressions'])}):")
        for reg in comparison["score_regressions"]:
            typer.echo(
                f"  - {reg['case_id']}: {reg['baseline_score']:.3f} -> "
                f"{reg['current_score']:.3f} ({reg['diff']:+.3f})"
            )

    if comparison["score_improvements"]:
        typer.echo(f"\nScore improvements ({len(comparison['score_improvements'])}):")
        for imp in comparison["score_improvements"]:
            typer.echo(
                f"  + {imp['case_id']}: {imp['baseline_score']:.3f} -> "
                f"{imp['current_score']:.3f} ({imp['diff']:+.3f})"
            )

    if fail_on_regression and (
        comparison["new_failures"] or comparison["score_regressions"]
    ):
        raise typer.Exit(1)


@eval_app.command("list")
def list_cases_cmd(
    language: Optional[str] = typer.Option(None, help="Filter by language"),
    tier: Optional[int] = typer.Option(None, help="Filter by tier"),
    suite: Optional[str] = typer.Option(None, help="Filter by suite"),
) -> None:
    """List available test cases."""
    from eval.registry import discover_cases, filter_cases_by_suite

    lang = Language(language) if language else None
    diff_tier = DifficultyTier(tier) if tier else None
    cases = discover_cases(language=lang, tier=diff_tier)

    if suite:
        cases = filter_cases_by_suite(cases, suite)

    if not cases:
        typer.echo("No test cases found.")
        return

    typer.echo(f"Found {len(cases)} test case(s):\n")
    typer.echo(f"{'ID':<45} {'Lang':<12} {'Tier':<6} {'Hunks':<7} {'Files':<7} {'Refs':<5}")
    typer.echo("-" * 90)
    for c in cases:
        typer.echo(
            f"{c.id:<45} {c.language.value:<12} {c.tier.value:<6} "
            f"{c.stats.total_hunks:<7} {c.stats.total_files:<7} "
            f"{c.stats.reference_commit_count:<5}"
        )


@eval_app.command("report")
def report_cmd(
    result_path: str = typer.Argument(..., help="Path to result JSON"),
    output: Optional[str] = typer.Option(None, help="Output file (default: stdout)"),
) -> None:
    """Generate a Markdown report from eval results."""
    from eval.reporting import generate_report, load_result

    result = load_result(Path(result_path))
    report = generate_report(result)

    if output:
        Path(output).write_text(report)
        typer.echo(f"Report saved to {output}")
    else:
        typer.echo(report)


@eval_app.command("cleanup")
def cleanup_cmd() -> None:
    """Remove all cached venvs and bare repos."""
    from eval.config import EVAL_CACHE_DIR

    if EVAL_CACHE_DIR.exists():
        import shutil

        shutil.rmtree(EVAL_CACHE_DIR)
        typer.echo(f"Cleaned up {EVAL_CACHE_DIR}")
    else:
        typer.echo("Nothing to clean up.")


def _setup_logging() -> None:
    """Configure logging for CLI output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    """Entry point for python -m eval.cli."""
    eval_app()


if __name__ == "__main__":
    main()
