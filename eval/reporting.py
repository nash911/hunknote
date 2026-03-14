"""Report generation and regression detection.

Saves eval results as JSON, generates Markdown reports, and
compares runs to identify regressions and improvements.
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from eval.config import EVAL_RESULTS_DIR
from eval.models import (
    CommitValidation,
    DifficultyTier,
    EvalCaseResult,
    EvalRunResult,
    Language,
    MechanicalResult,
    SemanticScores,
)

logger = logging.getLogger(__name__)


def generate_report(result: EvalRunResult) -> str:
    """Generate a Markdown report from eval results.

    Args:
        result: The eval run result.

    Returns:
        Markdown string.
    """
    lines: list[str] = []
    summary = result.get_summary()

    lines.append(f"# Eval Report: {result.run_id}")
    lines.append("")
    lines.append(f"**Timestamp**: {result.timestamp}")
    lines.append(f"**Suite**: {result.suite}")
    lines.append(
        f"**Agent**: {result.agent_config.get('provider', '?')}/{result.agent_config.get('model', '?')}"
    )
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total cases | {summary['total']} |")
    lines.append(f"| Passed | {summary['passed']} |")
    lines.append(f"| Failed | {summary['failed']} |")
    lines.append(f"| Avg score | {summary['avg_score']:.3f} |")
    lines.append(f"| Min score | {summary.get('min_score', 0):.3f} |")
    lines.append(f"| Max score | {summary.get('max_score', 0):.3f} |")
    lines.append(
        f"| Mechanical pass rate | {summary.get('mechanical_pass_rate', 0):.1%} |"
    )
    lines.append("")

    # Per-tier breakdown
    by_tier = result.get_by_tier()
    if by_tier:
        lines.append("## By Tier")
        lines.append("")
        lines.append("| Tier | Cases | Avg Score | Mechanical Pass |")
        lines.append("|------|-------|-----------|-----------------|")
        for tier in sorted(by_tier.keys(), key=lambda t: t.value):
            cases = by_tier[tier]
            valid = [c for c in cases if c.error is None]
            avg = sum(c.overall_score for c in valid) / len(valid) if valid else 0
            mech = (
                sum(1 for c in valid if c.mechanical.full_sequence_valid) / len(valid)
                if valid
                else 0
            )
            lines.append(
                f"| Tier {tier.value} | {len(cases)} | {avg:.3f} | {mech:.1%} |"
            )
        lines.append("")

    # Per-case details
    lines.append("## Case Details")
    lines.append("")
    lines.append(
        "| Case | Tier | Score | Mechanical | ARI | Granularity | Dep Recall | Error |"
    )
    lines.append(
        "|------|------|-------|------------|-----|-------------|------------|-------|"
    )
    for case in result.cases:
        mech_str = "PASS" if case.mechanical.full_sequence_valid else "FAIL"
        error_str = case.error[:40] if case.error else ""
        lines.append(
            f"| {case.case_id} | {case.tier.value} | {case.overall_score:.3f} "
            f"| {mech_str} | {case.semantic.reference_similarity:.3f} "
            f"| {case.semantic.granularity:.3f} | {case.semantic.dependency_recall:.3f} "
            f"| {error_str} |"
        )
    lines.append("")

    # Failures section
    failures = result.get_failures()
    if failures:
        lines.append("## Failures")
        lines.append("")
        for case in failures:
            lines.append(f"### {case.case_id}")
            if case.error:
                lines.append(f"**Error**: {case.error}")
            if case.mechanical.per_commit:
                for cv in case.mechanical.per_commit:
                    if cv.errors:
                        lines.append(f"- **{cv.commit_id}**: {'; '.join(cv.errors)}")
            lines.append("")

    return "\n".join(lines)


def save_result(result: EvalRunResult, output_dir: Optional[Path] = None) -> Path:
    """Save eval result as JSON.

    Results are stored under ``{output_dir}/{timestamp}/eval_results.json``.

    Args:
        result: The eval run result.
        output_dir: Root output directory. Default: eval_results/

    Returns:
        Path to the saved JSON file.
    """
    root_dir = output_dir or EVAL_RESULTS_DIR
    run_dir = root_dir / result.timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    file_path = run_dir / "eval_results.json"

    data = _result_to_dict(result)
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Saved eval result to %s", file_path)
    return file_path


def load_result(path: Path) -> EvalRunResult:
    """Load a previously saved eval result.

    Args:
        path: Path to the JSON file.

    Returns:
        EvalRunResult object.
    """
    with open(path) as f:
        data = json.load(f)

    cases = []
    for cd in data.get("cases", []):
        # Parse mechanical result
        mech_data = cd.get("mechanical", {})
        per_commit = [
            CommitValidation(
                commit_index=cv["commit_index"],
                commit_id=cv["commit_id"],
                patch_applies=cv["patch_applies"],
                syntax_valid=cv["syntax_valid"],
                compile_passes=cv["compile_passes"],
                import_resolves=cv["import_resolves"],
                tests_pass=cv.get("tests_pass"),
                errors=cv.get("errors", []),
            )
            for cv in mech_data.get("per_commit", [])
        ]
        mechanical = MechanicalResult(
            full_sequence_valid=mech_data.get("full_sequence_valid", False),
            build_pass_rate=mech_data.get("build_pass_rate", 0.0),
            patch_apply_rate=mech_data.get("patch_apply_rate", 0.0),
            import_integrity_rate=mech_data.get("import_integrity_rate", 0.0),
            test_pass_rate=mech_data.get("test_pass_rate"),
            final_state_matches=mech_data.get("final_state_matches"),
            final_state_diff=mech_data.get("final_state_diff"),
            per_commit=per_commit,
            first_failure_index=mech_data.get("first_failure_index"),
        )

        # Parse semantic scores
        sem_data = cd.get("semantic", {})
        semantic = SemanticScores(
            reference_similarity=sem_data.get("reference_similarity", 0.0),
            granularity=sem_data.get("granularity", 0.0),
            dependency_recall=sem_data.get("dependency_recall", 0.0),
            cohesion=sem_data.get("cohesion"),
            separation=sem_data.get("separation"),
            ordering=sem_data.get("ordering"),
        )

        cases.append(
            EvalCaseResult(
                case_id=cd["case_id"],
                tier=DifficultyTier(cd.get("tier", 1)),
                language=Language(cd.get("language", "python")),
                mechanical=mechanical,
                semantic=semantic,
                overall_score=cd.get("overall_score", 0.0),
                agent_commit_count=cd.get("agent_commit_count", 0),
                reference_commit_count=cd.get("reference_commit_count", 0),
                agent_trace_path=cd.get("agent_trace_path"),
                total_llm_calls=cd.get("total_llm_calls", 0),
                total_tokens=cd.get("total_tokens", 0),
                duration_s=cd.get("duration_s", 0.0),
                error=cd.get("error"),
            )
        )

    return EvalRunResult(
        run_id=data["run_id"],
        timestamp=data["timestamp"],
        agent_config=data.get("agent_config", {}),
        suite=data.get("suite", "unknown"),
        cases=cases,
    )


def compare_runs(
    current: EvalRunResult,
    baseline: EvalRunResult,
    regression_threshold: float = 0.05,
) -> dict:
    """Compare two eval runs and identify regressions.

    Args:
        current: The current eval run.
        baseline: The baseline eval run.
        regression_threshold: Minimum score drop to flag as regression.

    Returns:
        Dict with new_failures, new_passes, score_regressions,
        score_improvements, and aggregate_diff.
    """
    baseline_map = {c.case_id: c for c in baseline.cases}
    current_map = {c.case_id: c for c in current.cases}

    common_ids = set(baseline_map.keys()) & set(current_map.keys())

    new_failures: list[str] = []
    new_passes: list[str] = []
    score_regressions: list[dict] = []
    score_improvements: list[dict] = []

    for case_id in sorted(common_ids):
        b = baseline_map[case_id]
        c = current_map[case_id]

        b_ok = b.error is None and b.mechanical.full_sequence_valid
        c_ok = c.error is None and c.mechanical.full_sequence_valid

        if b_ok and not c_ok:
            new_failures.append(case_id)
        elif not b_ok and c_ok:
            new_passes.append(case_id)

        score_diff = c.overall_score - b.overall_score
        if score_diff < -regression_threshold:
            score_regressions.append({
                "case_id": case_id,
                "baseline_score": b.overall_score,
                "current_score": c.overall_score,
                "diff": score_diff,
            })
        elif score_diff > regression_threshold:
            score_improvements.append({
                "case_id": case_id,
                "baseline_score": b.overall_score,
                "current_score": c.overall_score,
                "diff": score_diff,
            })

    # Aggregate diff
    b_summary = baseline.get_summary()
    c_summary = current.get_summary()

    return {
        "new_failures": new_failures,
        "new_passes": new_passes,
        "score_regressions": score_regressions,
        "score_improvements": score_improvements,
        "aggregate_diff": {
            "avg_score_diff": c_summary["avg_score"] - b_summary["avg_score"],
            "baseline_avg": b_summary["avg_score"],
            "current_avg": c_summary["avg_score"],
            "baseline_pass_rate": b_summary.get("mechanical_pass_rate", 0),
            "current_pass_rate": c_summary.get("mechanical_pass_rate", 0),
        },
        "only_in_baseline": sorted(set(baseline_map.keys()) - set(current_map.keys())),
        "only_in_current": sorted(set(current_map.keys()) - set(baseline_map.keys())),
    }


def _result_to_dict(result: EvalRunResult) -> dict:
    """Convert an EvalRunResult to a JSON-serializable dict."""
    cases_data = []
    for case in result.cases:
        per_commit_data = [
            {
                "commit_index": cv.commit_index,
                "commit_id": cv.commit_id,
                "patch_applies": cv.patch_applies,
                "syntax_valid": cv.syntax_valid,
                "compile_passes": cv.compile_passes,
                "import_resolves": cv.import_resolves,
                "tests_pass": cv.tests_pass,
                "errors": cv.errors,
            }
            for cv in case.mechanical.per_commit
        ]

        cases_data.append({
            "case_id": case.case_id,
            "tier": case.tier.value,
            "language": case.language.value,
            "mechanical": {
                "full_sequence_valid": case.mechanical.full_sequence_valid,
                "build_pass_rate": case.mechanical.build_pass_rate,
                "patch_apply_rate": case.mechanical.patch_apply_rate,
                "import_integrity_rate": case.mechanical.import_integrity_rate,
                "test_pass_rate": case.mechanical.test_pass_rate,
                "final_state_matches": case.mechanical.final_state_matches,
                "final_state_diff": case.mechanical.final_state_diff,
                "per_commit": per_commit_data,
                "first_failure_index": case.mechanical.first_failure_index,
            },
            "semantic": {
                "reference_similarity": case.semantic.reference_similarity,
                "granularity": case.semantic.granularity,
                "dependency_recall": case.semantic.dependency_recall,
                "cohesion": case.semantic.cohesion,
                "separation": case.semantic.separation,
                "ordering": case.semantic.ordering,
            },
            "overall_score": case.overall_score,
            "agent_commit_count": case.agent_commit_count,
            "reference_commit_count": case.reference_commit_count,
            "agent_trace_path": case.agent_trace_path,
            "total_llm_calls": case.total_llm_calls,
            "total_tokens": case.total_tokens,
            "duration_s": case.duration_s,
            "error": case.error,
        })

    return {
        "run_id": result.run_id,
        "timestamp": result.timestamp,
        "agent_config": result.agent_config,
        "suite": result.suite,
        "cases": cases_data,
    }
