"""Eval harness — orchestrates the full evaluation for a set of test cases.

For each test case:
1. Extract repo.tar.gz to a temp directory.
2. Create target venv and install deps.
3. Parse staged.patch into hunks.
4. Run the Compose Agent on the hunks.
5. Validate the agent's output mechanically.
6. Compute semantic quality scores.
7. (Optional) Run LLM-as-judge.
8. Record results.
9. Cleanup temp directory and target venv.
"""

import logging
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from hunknote.compose.inventory import build_hunk_inventory
from hunknote.compose.models import ComposePlan
from hunknote.compose.parser import parse_unified_diff
from hunknote.compose.planner import generate_compose_plan
from eval.config import DEFAULT_AGENT_CONFIG, EVAL_RESULTS_DIR
from eval.environment import TargetEnvManager
from eval.judge import run_full_judge
from eval.models import (
    DifficultyTier,
    EvalCaseResult,
    EvalRunResult,
    Language,
    MechanicalResult,
    SemanticScores,
    TestCase,
)
from eval.reporting import save_result
from eval.scoring import compute_overall_score, compute_semantic_scores
from eval.validation import validate_agent_plan

logger = logging.getLogger(__name__)


def run_eval(
    cases: list[TestCase],
    agent_config: Optional[dict] = None,
    judge_config: Optional[dict] = None,
    output_dir: Optional[Path] = None,
    llm_call_fn: Optional[Callable] = None,
    judge_llm_call_fn: Optional[Callable[[str, str], str]] = None,
) -> EvalRunResult:
    """Run the full evaluation suite.

    Args:
        cases: List of TestCase objects to evaluate.
        agent_config: Configuration for the Compose Agent.
        judge_config: Configuration for LLM-as-judge (None = skip).
        output_dir: Where to save results.
        llm_call_fn: Optional pre-built LLM call function for the agent.
        judge_llm_call_fn: Optional pre-built LLM call function for the judge.

    Returns:
        EvalRunResult with all case results.
    """
    config = agent_config or dict(DEFAULT_AGENT_CONFIG)
    out_dir = output_dir or EVAL_RESULTS_DIR

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    run_id = f"eval_{timestamp}"

    # Create the run output directory and set up file logging
    run_dir = out_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "eval_logs.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    # Attach to root logger so all eval.* loggers are captured
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    run_result = EvalRunResult(
        run_id=run_id,
        timestamp=timestamp,
        agent_config=config,
        suite="custom",
        cases=[],
    )

    logger.info("Starting eval run %s with %d cases", run_id, len(cases))

    for i, test_case in enumerate(cases):
        logger.info(
            "[%d/%d] Running case: %s (Tier %d, %s)",
            i + 1,
            len(cases),
            test_case.id,
            test_case.tier.value,
            test_case.language.value,
        )

        case_result = _run_single_case(
            test_case=test_case,
            agent_config=config,
            judge_config=judge_config,
            llm_call_fn=llm_call_fn,
            judge_llm_call_fn=judge_llm_call_fn,
        )
        run_result.cases.append(case_result)

        status = "OK" if case_result.error is None else f"ERROR: {case_result.error}"
        logger.info(
            "  Result: %s | Score: %.3f | Mechanical: %s",
            status,
            case_result.overall_score,
            "PASS" if case_result.mechanical.full_sequence_valid else "FAIL",
        )

    # Save results
    result_path = save_result(run_result, out_dir)
    logger.info("Results saved to %s", result_path)

    # Print summary
    summary = run_result.get_summary()
    logger.info(
        "Eval complete: %d/%d passed, avg score: %.3f",
        summary["passed"],
        summary["total"],
        summary["avg_score"],
    )

    # Remove file handler to avoid leaking
    root_logger.removeHandler(file_handler)
    file_handler.close()

    return run_result


def _run_single_case(
    test_case: TestCase,
    agent_config: dict,
    judge_config: Optional[dict] = None,
    llm_call_fn: Optional[Callable] = None,
    judge_llm_call_fn: Optional[Callable[[str, str], str]] = None,
) -> EvalCaseResult:
    """Run evaluation for a single test case.

    Args:
        test_case: The test case to evaluate.
        agent_config: Agent configuration.
        judge_config: Judge configuration (None = skip).
        llm_call_fn: Pre-built LLM call function.
        judge_llm_call_fn: Pre-built judge LLM call function.

    Returns:
        EvalCaseResult with all scores and metrics.
    """
    start_time = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="hunknote_eval_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"

        try:
            # 1. Extract repo
            repo_tar = test_case.case_dir / "repo.tar.gz"
            if not repo_tar.exists():
                return _error_result(test_case, f"repo.tar.gz not found at {repo_tar}")

            repo_dir.mkdir(parents=True)
            with tarfile.open(repo_tar) as tar:
                tar.extractall(repo_dir)

            # 2. Create target venv
            target_env = TargetEnvManager.create_env(
                repo_dir=repo_dir,
                config=test_case.build_system,
            )

            # Check Python version compatibility
            if not target_env.check_python_version():
                return _error_result(
                    test_case,
                    f"Python version incompatible (requires >= {test_case.build_system.python_version_min})",
                )

            # Install dependencies
            if not target_env.install_deps():
                return _error_result(test_case, "Dependency installation failed")

            # 3. Parse staged.patch
            staged_patch_path = test_case.case_dir / "staged.patch"
            if not staged_patch_path.exists():
                return _error_result(test_case, "staged.patch not found")

            staged_patch = staged_patch_path.read_text()
            file_diffs, warnings = parse_unified_diff(staged_patch)
            inventory = build_hunk_inventory(file_diffs)

            if not inventory:
                return _error_result(test_case, "No hunks found in staged.patch")

            # 4. Stage the diff in the extracted repo
            _apply_patch_to_index(repo_dir, staged_patch)

            # 5. Run the Compose Agent
            plan, agent_stats = _run_agent(
                repo_dir=repo_dir,
                file_diffs=file_diffs,
                inventory=inventory,
                agent_config=agent_config,
                llm_call_fn=llm_call_fn,
            )

            if plan is None:
                return _error_result(
                    test_case,
                    agent_stats.get("error", "Agent failed to produce a plan"),
                )

            # 6. Mechanical validation
            mechanical = validate_agent_plan(
                test_case, plan, target_env, repo_dir, inventory, file_diffs
            )

            # 7. Semantic scoring
            semantic = compute_semantic_scores(plan, test_case, inventory)

            # 8. Optional LLM judge
            if (
                judge_config
                and judge_config.get("enabled")
                and judge_llm_call_fn is not None
            ):
                judge_scores = run_full_judge(plan, inventory, judge_llm_call_fn)
                semantic.cohesion = judge_scores.get("cohesion")
                semantic.separation = judge_scores.get("separation")
                semantic.ordering = judge_scores.get("ordering")

            # 9. Compute overall score
            overall = compute_overall_score(mechanical, semantic)

            duration = time.monotonic() - start_time

            return EvalCaseResult(
                case_id=test_case.id,
                tier=test_case.tier,
                language=test_case.language,
                mechanical=mechanical,
                semantic=semantic,
                overall_score=overall,
                agent_commit_count=len(plan.commits),
                reference_commit_count=test_case.stats.reference_commit_count,
                total_llm_calls=agent_stats.get("total_llm_calls", 0),
                total_tokens=agent_stats.get("total_tokens", 0),
                duration_s=duration,
            )

        except Exception as e:
            logger.exception("Unexpected error in case %s", test_case.id)
            return _error_result(test_case, str(e))


def _apply_patch_to_index(repo_dir: Path, patch_content: str) -> None:
    """Stage the squashed diff in the repo's git index.

    Uses git apply --cached to stage without modifying the working tree.
    """
    result = subprocess.run(
        ["git", "apply", "--cached", "-"],
        input=patch_content,
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("git apply --cached failed: %s", result.stderr)
        # Try without --cached as fallback
        subprocess.run(
            ["git", "apply", "-"],
            input=patch_content,
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )


def _run_agent(
    repo_dir: Path,
    file_diffs: list,
    inventory: dict,
    agent_config: dict,
    llm_call_fn: Optional[Callable] = None,
) -> tuple[Optional[ComposePlan], dict]:
    """Run the Compose Agent and return its plan.

    Delegates to the hunknote compose planner (single-shot LLM flow).
    When the Compose Agent module becomes available, this will be
    extended to call it instead (controlled by agent_config["use_agent"]).

    Args:
        repo_dir: Path to the repo.
        file_diffs: Parsed file diffs.
        inventory: Hunk inventory.
        agent_config: Agent configuration.
        llm_call_fn: Optional pre-built LLM call function.

    Returns:
        Tuple of (ComposePlan or None, stats dict).
    """
    stats: dict = {
        "total_llm_calls": 0,
        "total_tokens": 0,
    }

    try:
        compose_result = generate_compose_plan(
            file_diffs=file_diffs,
            inventory=inventory,
            max_commits=agent_config.get("max_commits", 8),
            max_retries=agent_config.get("max_retries", 2),
            style=agent_config.get("style", "conventional"),
            branch="eval",
            recent_commits=[],
            llm_call_fn=llm_call_fn,
            provider_name=agent_config.get("provider"),
            model_name=agent_config.get("model"),
        )

        stats["total_llm_calls"] = compose_result.total_llm_calls
        stats["total_tokens"] = compose_result.input_tokens + compose_result.output_tokens

        if not compose_result.success:
            stats["error"] = compose_result.error or "Compose plan generation failed"
            return compose_result.plan, stats

        return compose_result.plan, stats

    except Exception as e:
        stats["error"] = str(e)
        return None, stats



def _error_result(test_case: TestCase, error: str) -> EvalCaseResult:
    """Create an error EvalCaseResult."""
    return EvalCaseResult(
        case_id=test_case.id,
        tier=test_case.tier,
        language=test_case.language,
        error=error,
    )
