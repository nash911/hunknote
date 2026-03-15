"""Evaluation analysis — detailed reports and interactive web dashboard.

Generates detailed terminal reports and single-page HTML dashboards
from eval result JSON files.

Usage:
    # From CLI
    python eval/cli.py analyze eval_results/<timestamp>/eval_results.json
    python eval/cli.py analyze eval_results/<timestamp>/eval_results.json --web

    # Programmatic
    from eval.analysis import generate_analysis_report, generate_web_report
"""

import json
import logging
from pathlib import Path
from typing import Optional

from eval.models import EvalRunResult
from eval.reporting import load_result

logger = logging.getLogger(__name__)


# ── Terminal / Markdown report ──────────────────────────────────────────────


def generate_analysis_report(result: EvalRunResult) -> str:
    """Generate a detailed analysis report (Markdown).

    Covers:
    - Run metadata & configuration
    - Aggregate summary
    - Per-tier breakdown with mechanical sub-rates
    - Per-case details with per-commit drill-down
    - Failure analysis
    """
    lines: list[str] = []
    summary = result.get_summary()

    # ── Header ──
    lines.append(f"# Evaluation Analysis Report")
    lines.append("")
    lines.append(f"**Run ID**: `{result.run_id}`")
    lines.append(f"**Timestamp**: {result.timestamp}")
    lines.append(f"**Suite**: {result.suite}")
    provider = result.agent_config.get("provider", "?")
    model = result.agent_config.get("model", "?")
    lines.append(f"**Agent**: {provider}/{model}")
    use_agent = result.agent_config.get("use_agent", False)
    lines.append(f"**Mode**: {'Agentic (multi-step)' if use_agent else 'Single-shot LLM'}")
    lines.append("")

    # ── Aggregate summary ──
    lines.append("## Aggregate Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total cases | {summary['total']} |")
    lines.append(f"| Passed (no error) | {summary['passed']} |")
    lines.append(f"| Failed (error) | {summary['failed']} |")
    lines.append(f"| Average score | {summary['avg_score']:.3f} |")
    lines.append(f"| Min score | {summary.get('min_score', 0):.3f} |")
    lines.append(f"| Max score | {summary.get('max_score', 0):.3f} |")
    lines.append(f"| Mechanical pass rate | {summary.get('mechanical_pass_rate', 0):.1%} |")

    # Compute total duration and tokens
    total_duration = sum(c.duration_s for c in result.cases)
    total_tokens = sum(c.total_tokens for c in result.cases)
    total_llm_calls = sum(c.total_llm_calls for c in result.cases)
    lines.append(f"| Total duration | {total_duration:.1f}s |")
    lines.append(f"| Total LLM calls | {total_llm_calls} |")
    lines.append(f"| Total tokens | {total_tokens:,} |")
    lines.append("")

    # ── Per-tier breakdown ──
    by_tier = result.get_by_tier()
    if by_tier:
        lines.append("## Per-Tier Breakdown")
        lines.append("")
        lines.append(
            "| Tier | Cases | Avg Score | Mech Pass | Patch Rate "
            "| Syntax Rate | Import Rate | Test Rate | Final State |"
        )
        lines.append(
            "|------|-------|-----------|-----------|------------"
            "|-------------|-------------|-----------|-------------|"
        )
        for tier in sorted(by_tier.keys(), key=lambda t: t.value):
            cases = by_tier[tier]
            valid = [c for c in cases if c.error is None]
            n = len(valid) or 1
            avg = sum(c.overall_score for c in valid) / n
            mech = sum(1 for c in valid if c.mechanical.full_sequence_valid) / n
            patch = sum(c.mechanical.patch_apply_rate for c in valid) / n
            syntax = sum(c.mechanical.build_pass_rate for c in valid) / n
            imp = sum(c.mechanical.import_integrity_rate for c in valid) / n
            test_rates = [c.mechanical.test_pass_rate for c in valid if c.mechanical.test_pass_rate is not None]
            test_avg = sum(test_rates) / len(test_rates) if test_rates else None
            final = sum(1 for c in valid if c.mechanical.final_state_matches is True) / n
            test_str = f"{test_avg:.1%}" if test_avg is not None else "n/a"
            lines.append(
                f"| Tier {tier.value} | {len(cases)} | {avg:.3f} | {mech:.1%} "
                f"| {patch:.1%} | {syntax:.1%} | {imp:.1%} | {test_str} | {final:.1%} |"
            )
        lines.append("")

    # ── Per-case details ──
    lines.append("## Per-Case Details")
    lines.append("")
    for case in result.cases:
        mech = case.mechanical
        sem = case.semantic
        status_icon = "✅" if mech.full_sequence_valid else "❌"
        lines.append(f"### {status_icon} {case.case_id}")
        lines.append("")
        lines.append(f"- **Tier**: {case.tier.value}")
        lines.append(f"- **Language**: {case.language.value}")
        lines.append(f"- **Overall Score**: {case.overall_score:.3f}")
        lines.append(f"- **Agent Commits**: {case.agent_commit_count} (reference: {case.reference_commit_count})")
        lines.append(f"- **Duration**: {case.duration_s:.1f}s")
        lines.append(f"- **Tokens**: {case.total_tokens:,}")
        if case.error:
            lines.append(f"- **Error**: {case.error}")
        lines.append("")

        # Mechanical
        lines.append(f"**Mechanical Validation**")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Full sequence valid | {mech.full_sequence_valid} |")
        lines.append(f"| Patch apply rate | {mech.patch_apply_rate:.1%} |")
        lines.append(f"| Syntax/compile rate | {mech.build_pass_rate:.1%} |")
        lines.append(f"| Import integrity rate | {mech.import_integrity_rate:.1%} |")
        test_str = f"{mech.test_pass_rate:.1%}" if mech.test_pass_rate is not None else "n/a"
        lines.append(f"| Test pass rate | {test_str} |")
        fs = "✅" if mech.final_state_matches is True else ("❌" if mech.final_state_matches is False else "n/a")
        lines.append(f"| Final state matches | {fs} |")
        hc = f"{mech.hunk_coverage:.1%}" if mech.hunk_coverage is not None else "n/a"
        lines.append(f"| Hunk coverage | {hc} |")
        if mech.missing_hunk_ids:
            ids_str = ", ".join(mech.missing_hunk_ids[:5])
            if len(mech.missing_hunk_ids) > 5:
                ids_str += f" (+{len(mech.missing_hunk_ids) - 5} more)"
            lines.append(f"| Missing hunks | {ids_str} |")
        if mech.hallucinated_hunk_ids:
            ids_str = ", ".join(mech.hallucinated_hunk_ids[:5])
            if len(mech.hallucinated_hunk_ids) > 5:
                ids_str += f" (+{len(mech.hallucinated_hunk_ids) - 5} more)"
            lines.append(f"| Hallucinated hunks | {ids_str} |")
        lines.append("")

        # Per-commit table
        if mech.per_commit:
            lines.append("**Per-Commit Breakdown**")
            lines.append("")
            lines.append("| Commit | Patch | Syntax | Import | Tests | Errors |")
            lines.append("|--------|-------|--------|--------|-------|--------|")
            for cv in mech.per_commit:
                p = "✅" if cv.patch_applies else "❌"
                s = "✅" if cv.syntax_valid else "❌"
                i = "✅" if cv.import_resolves else "❌"
                t = "✅" if cv.tests_pass is True else ("❌" if cv.tests_pass is False else "—")
                errs = "; ".join(e[:80] for e in cv.errors) if cv.errors else "—"
                lines.append(f"| {cv.commit_id} | {p} | {s} | {i} | {t} | {errs} |")
            lines.append("")

        # Semantic
        lines.append(f"**Semantic Scores**")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Reference similarity (ARI) | {sem.reference_similarity:.3f} |")
        lines.append(f"| Granularity | {sem.granularity:.3f} |")
        lines.append(f"| Dependency recall | {sem.dependency_recall:.3f} |")
        if sem.cohesion is not None:
            lines.append(f"| Cohesion (LLM judge) | {sem.cohesion:.3f} |")
        if sem.separation is not None:
            lines.append(f"| Separation (LLM judge) | {sem.separation:.3f} |")
        if sem.ordering is not None:
            lines.append(f"| Ordering (LLM judge) | {sem.ordering:.3f} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Failure analysis ──
    failures = result.get_failures()
    if failures:
        lines.append("## Failure Analysis")
        lines.append("")
        for case in failures:
            lines.append(f"### {case.case_id}")
            if case.error:
                lines.append(f"**Error**: `{case.error}`")
                lines.append("")
            elif not case.mechanical.full_sequence_valid:
                # Summarize why mechanical failed
                reasons = []
                if case.mechanical.final_state_matches is False:
                    reasons.append("Final state does not match expected after-state")
                for cv in case.mechanical.per_commit:
                    if not cv.patch_applies:
                        reasons.append(f"{cv.commit_id}: Patch does not apply")
                    if not cv.syntax_valid:
                        reasons.append(f"{cv.commit_id}: Syntax errors")
                    if not cv.import_resolves:
                        reasons.append(f"{cv.commit_id}: Import failures")
                    if cv.tests_pass is False:
                        reasons.append(f"{cv.commit_id}: Tests failed")
                for r in reasons:
                    lines.append(f"- {r}")
                lines.append("")

                # Show error details
                for cv in case.mechanical.per_commit:
                    if cv.errors:
                        lines.append(f"**{cv.commit_id} errors:**")
                        lines.append("```")
                        for e in cv.errors:
                            lines.append(e[:500])
                        lines.append("```")
                        lines.append("")

    return "\n".join(lines)


# ── Web report (single-page HTML dashboard) ─────────────────────────────────


def generate_web_report(result: EvalRunResult) -> str:
    """Generate a single-page HTML evaluation dashboard.

    The HTML is entirely self-contained (inline CSS/JS, no external deps)
    with clickable tier/case navigation and collapsible details.
    """
    summary = result.get_summary()
    by_tier = result.get_by_tier()
    failures = result.get_failures()

    total_duration = sum(c.duration_s for c in result.cases)
    total_tokens = sum(c.total_tokens for c in result.cases)

    provider = result.agent_config.get("provider", "?")
    model = result.agent_config.get("model", "?")
    use_agent = result.agent_config.get("use_agent", False)

    # Build per-case JSON for JS interactivity
    cases_json = []
    for c in result.cases:
        m = c.mechanical
        s = c.semantic
        per_commit = []
        for cv in m.per_commit:
            per_commit.append({
                "id": cv.commit_id,
                "patch": cv.patch_applies,
                "syntax": cv.syntax_valid,
                "import": cv.import_resolves,
                "tests": cv.tests_pass,
                "errors": cv.errors,
            })
        cases_json.append({
            "id": c.case_id,
            "tier": c.tier.value,
            "language": c.language.value,
            "score": round(c.overall_score, 3),
            "mech_pass": m.full_sequence_valid,
            "patch_rate": round(m.patch_apply_rate, 3),
            "syntax_rate": round(m.build_pass_rate, 3),
            "import_rate": round(m.import_integrity_rate, 3),
            "test_rate": round(m.test_pass_rate, 3) if m.test_pass_rate is not None else None,
            "final_state": m.final_state_matches,
            "final_state_diff": m.final_state_diff,
            "hunk_coverage": round(m.hunk_coverage, 3) if m.hunk_coverage is not None else None,
            "missing_hunks": m.missing_hunk_ids,
            "hallucinated_hunks": m.hallucinated_hunk_ids,
            "ref_sim": round(s.reference_similarity, 3),
            "granularity": round(s.granularity, 3),
            "dep_recall": round(s.dependency_recall, 3),
            "cohesion": round(s.cohesion, 3) if s.cohesion is not None else None,
            "separation": round(s.separation, 3) if s.separation is not None else None,
            "ordering": round(s.ordering, 3) if s.ordering is not None else None,
            "agent_commits": c.agent_commit_count,
            "ref_commits": c.reference_commit_count,
            "duration": round(c.duration_s, 1),
            "tokens": c.total_tokens,
            "llm_calls": c.total_llm_calls,
            "error": c.error,
            "per_commit": per_commit,
        })

    # Build tier summary for JS
    tier_summary = []
    for tier in sorted(by_tier.keys(), key=lambda t: t.value):
        cases = by_tier[tier]
        valid = [c for c in cases if c.error is None]
        n = len(valid) or 1
        avg = sum(c.overall_score for c in valid) / n
        mech = sum(1 for c in valid if c.mechanical.full_sequence_valid) / n
        test_rates = [c.mechanical.test_pass_rate for c in valid if c.mechanical.test_pass_rate is not None]
        test_avg = sum(test_rates) / len(test_rates) if test_rates else None
        final = sum(1 for c in valid if c.mechanical.final_state_matches is True) / n
        tier_summary.append({
            "tier": tier.value,
            "count": len(cases),
            "avg_score": round(avg, 3),
            "mech_pass": round(mech, 3),
            "test_rate": round(test_avg, 3) if test_avg is not None else None,
            "final_state": round(final, 3),
        })

    data_json = json.dumps({
        "cases": cases_json,
        "tiers": tier_summary,
        "summary": summary,
        "meta": {
            "run_id": result.run_id,
            "timestamp": result.timestamp,
            "suite": result.suite,
            "provider": provider,
            "model": model,
            "use_agent": use_agent,
            "total_duration": round(total_duration, 1),
            "total_tokens": total_tokens,
        },
    })

    return _HTML_TEMPLATE.replace("/*__DATA__*/", f"const DATA = {data_json};")


# ── Meta-analysis (multi-run comparison) ─────────────────────────────────────


def _collect_meta_data(results: list[EvalRunResult]) -> dict:
    """Aggregate per-case data across multiple runs.

    Returns a dict keyed by case_id, each value is a list of
    EvalCaseResult objects (one per run).
    """
    per_case: dict[str, list] = {}
    for result in results:
        for case in result.cases:
            per_case.setdefault(case.case_id, []).append(case)
    return per_case


def _classify_failure(
    case_id: str, runs: list, n_runs: int
) -> dict:
    """Classify a case's failure pattern across runs.

    Returns a dict with classification, counts, and details.
    """
    fail_count = sum(1 for c in runs if not c.mechanical.full_sequence_valid)
    pass_count = n_runs - fail_count

    # Check if last commit also fails tests (false positive indicator)
    last_commit_test_fails = 0
    for c in runs:
        commits = c.mechanical.per_commit
        if commits:
            last = commits[-1]
            if last.tests_pass is False:
                last_commit_test_fails += 1

    # Failure type analysis
    has_import_fail = any(
        not cv.import_resolves
        for c in runs
        for cv in c.mechanical.per_commit
    )
    has_test_fail = any(
        cv.tests_pass is False
        for c in runs
        for cv in c.mechanical.per_commit
    )
    has_hunk_miss = any(
        (c.mechanical.hunk_coverage or 1.0) < 1.0
        for c in runs
    )
    has_fs_fail = any(
        c.mechanical.final_state_matches is False
        for c in runs
    )

    # Classify
    if fail_count == 0:
        category = "always_pass"
    elif last_commit_test_fails == n_runs and fail_count == n_runs:
        category = "false_positive"
    elif has_hunk_miss or has_fs_fail:
        category = "hunk_coverage"
    elif has_import_fail and not has_test_fail:
        category = "import_only"
    elif has_import_fail:
        category = "import_and_test"
    elif has_test_fail:
        category = "ordering"
    else:
        category = "other"

    stability = "consistent" if fail_count == 0 or fail_count == n_runs else "intermittent"

    avg_score = sum(c.overall_score for c in runs) / len(runs)
    avg_tpr = sum((c.mechanical.test_pass_rate or 0) for c in runs) / len(runs)
    agent_counts = [c.agent_commit_count for c in runs]
    ref_count = runs[0].reference_commit_count
    tier = runs[0].tier.value

    return {
        "case_id": case_id,
        "tier": tier,
        "ref_commits": ref_count,
        "agent_counts": agent_counts,
        "fail_count": fail_count,
        "pass_count": pass_count,
        "category": category,
        "stability": stability,
        "avg_score": avg_score,
        "avg_tpr": avg_tpr,
        "has_import_fail": has_import_fail,
        "has_test_fail": has_test_fail,
        "has_hunk_miss": has_hunk_miss,
        "has_fs_fail": has_fs_fail,
        "last_commit_test_fails": last_commit_test_fails,
        "mech_pass_per_run": [c.mechanical.full_sequence_valid for c in runs],
        "hunk_coverages": [(c.mechanical.hunk_coverage or 1.0) for c in runs],
        "scores": [c.overall_score for c in runs],
    }


def generate_meta_analysis_json(results: list[EvalRunResult]) -> dict:
    """Generate a complete JSON-serialisable meta-analysis dictionary.

    Contains all the data needed to reconstruct the Markdown/HTML reports
    and to compare this group of runs against another group.
    """
    per_case = _collect_meta_data(results)
    n_runs = len(results)

    # Classify every case
    classifications: list[dict] = []
    for cid in sorted(per_case.keys()):
        runs = per_case[cid]
        classifications.append(_classify_failure(cid, runs, n_runs))

    # Per-tier aggregates
    tiers_map: dict[int, list[dict]] = {}
    for c in classifications:
        tiers_map.setdefault(c["tier"], []).append(c)

    tiers_summary = []
    for t in sorted(tiers_map.keys()):
        tc = tiers_map[t]
        ap = sum(1 for c in tc if c["category"] == "always_pass")
        cf = sum(1 for c in tc if c["stability"] == "consistent" and c["category"] not in ("always_pass", "false_positive"))
        inter = sum(1 for c in tc if c["stability"] == "intermittent")
        fp = sum(1 for c in tc if c["category"] == "false_positive")
        avg_s = sum(c["avg_score"] for c in tc) / len(tc)
        avg_t = sum(c["avg_tpr"] for c in tc) / len(tc)
        tiers_summary.append({
            "tier": t,
            "total": len(tc),
            "always_pass": ap,
            "consistent_fail": cf,
            "intermittent": inter,
            "false_positive": fp,
            "avg_score": round(avg_s, 4),
            "avg_tpr": round(avg_t, 4),
        })

    # Per-repo aggregates
    repos_map: dict[str, list[dict]] = {}
    for c in classifications:
        cid = c["case_id"]
        if "httpx" in cid:
            repo = "httpx"
        elif "rich" in cid:
            repo = "rich"
        elif "marshmallow" in cid:
            repo = "marshmallow"
        else:
            repo = "other"
        repos_map.setdefault(repo, []).append(c)

    repos_summary = []
    for repo in sorted(repos_map.keys()):
        rc = repos_map[repo]
        ap = sum(1 for c in rc if c["category"] == "always_pass")
        cf = sum(1 for c in rc if c["stability"] == "consistent" and c["category"] not in ("always_pass", "false_positive"))
        inter = sum(1 for c in rc if c["stability"] == "intermittent")
        avg_s = sum(c["avg_score"] for c in rc) / len(rc)
        repos_summary.append({
            "repo": repo,
            "total": len(rc),
            "always_pass": ap,
            "consistent_fail": cf,
            "intermittent": inter,
            "avg_score": round(avg_s, 4),
        })

    # Failure root cause breakdown
    genuine_fail = [c for c in classifications if c["category"] not in ("always_pass", "false_positive")]
    root_causes: dict[str, dict] = {}
    for c in genuine_fail:
        cat = c["category"]
        if cat not in root_causes:
            root_causes[cat] = {"category": cat, "total": 0, "consistent": 0, "intermittent": 0, "cases": []}
        root_causes[cat]["total"] += 1
        if c["stability"] == "consistent":
            root_causes[cat]["consistent"] += 1
        else:
            root_causes[cat]["intermittent"] += 1
        root_causes[cat]["cases"].append(c["case_id"])

    # Over-splitting
    over_split_cases = []
    for c in classifications:
        if c["ref_commits"] == 1 and all(a >= 3 for a in c["agent_counts"]):
            over_split_cases.append({
                "case_id": c["case_id"],
                "tier": c["tier"],
                "agent_counts": c["agent_counts"],
                "category": c["category"],
                "avg_tpr": round(c["avg_tpr"], 4),
            })

    # Score stability
    score_stability = []
    for c in sorted(classifications, key=lambda x: (x["tier"], x["case_id"])):
        scores = c["scores"]
        mean = sum(scores) / len(scores)
        std = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5
        score_stability.append({
            "case_id": c["case_id"],
            "tier": c["tier"],
            "scores": [round(s, 4) for s in scores],
            "mean": round(mean, 4),
            "range": round(max(scores) - min(scores), 4),
            "std_dev": round(std, 4),
        })

    # Per-case full details (the core data)
    cases_detail = []
    for c in sorted(classifications, key=lambda x: (x["tier"], x["case_id"])):
        cases_detail.append({
            "case_id": c["case_id"],
            "tier": c["tier"],
            "ref_commits": c["ref_commits"],
            "agent_counts": c["agent_counts"],
            "fail_count": c["fail_count"],
            "pass_count": c["pass_count"],
            "category": c["category"],
            "stability": c["stability"],
            "avg_score": round(c["avg_score"], 4),
            "avg_tpr": round(c["avg_tpr"], 4),
            "has_import_fail": c["has_import_fail"],
            "has_test_fail": c["has_test_fail"],
            "has_hunk_miss": c["has_hunk_miss"],
            "has_fs_fail": c["has_fs_fail"],
            "last_commit_test_fails": c["last_commit_test_fails"],
            "mech_pass_per_run": c["mech_pass_per_run"],
            "hunk_coverages": [round(h, 4) for h in c["hunk_coverages"]],
            "scores": [round(s, 4) for s in c["scores"]],
        })

    # Runs metadata
    runs_meta = []
    for i, r in enumerate(results):
        summary = r.get_summary()
        runs_meta.append({
            "index": i + 1,
            "run_id": r.run_id,
            "timestamp": r.timestamp,
            "provider": r.agent_config.get("provider", "?"),
            "model": r.agent_config.get("model", "?"),
            "suite": r.suite,
            "use_agent": r.agent_config.get("use_agent", False),
            "total_cases": summary["total"],
            "avg_score": round(summary["avg_score"], 4),
            "mechanical_pass_rate": round(summary.get("mechanical_pass_rate", 0), 4),
            "total_duration_s": round(sum(c.duration_s for c in r.cases), 1),
            "total_tokens": sum(c.total_tokens for c in r.cases),
        })

    total = len(classifications)
    return {
        "meta_analysis_version": 1,
        "n_runs": n_runs,
        "runs": runs_meta,
        "summary": {
            "total_cases": total,
            "always_pass": sum(1 for c in classifications if c["category"] == "always_pass"),
            "always_pass_rate": round(sum(1 for c in classifications if c["category"] == "always_pass") / total, 4) if total else 0,
            "false_positive": sum(1 for c in classifications if c["category"] == "false_positive"),
            "consistent_fail": sum(1 for c in classifications if c["stability"] == "consistent" and c["category"] not in ("always_pass", "false_positive")),
            "intermittent": sum(1 for c in classifications if c["stability"] == "intermittent"),
            "avg_score": round(sum(c["avg_score"] for c in classifications) / total, 4) if total else 0,
            "avg_tpr": round(sum(c["avg_tpr"] for c in classifications) / total, 4) if total else 0,
            "avg_mechanical_pass_rate": round(
                sum(sum(c["mech_pass_per_run"]) / n_runs for c in classifications) / total, 4
            ) if total else 0,
        },
        "by_tier": tiers_summary,
        "by_repo": repos_summary,
        "root_causes": list(root_causes.values()),
        "over_splitting": over_split_cases,
        "score_stability": score_stability,
        "cases": cases_detail,
    }


def generate_meta_analysis_report(results: list[EvalRunResult]) -> str:
    """Generate a Markdown meta-analysis report comparing multiple runs."""
    per_case = _collect_meta_data(results)
    n_runs = len(results)
    lines: list[str] = []

    # Classify all cases
    classifications: list[dict] = []
    for cid in sorted(per_case.keys()):
        runs = per_case[cid]
        classifications.append(_classify_failure(cid, runs, n_runs))

    always_pass = [c for c in classifications if c["category"] == "always_pass"]
    false_pos = [c for c in classifications if c["category"] == "false_positive"]
    genuine_fail = [c for c in classifications if c["category"] not in ("always_pass", "false_positive")]
    consistent_fail = [c for c in genuine_fail if c["stability"] == "consistent"]
    intermittent = [c for c in genuine_fail if c["stability"] == "intermittent"]

    # ── Header ──
    lines.append("# Meta-Analysis Report")
    lines.append("")
    lines.append(f"**Runs compared**: {n_runs}")
    for i, r in enumerate(results):
        provider = r.agent_config.get("provider", "?")
        model = r.agent_config.get("model", "?")
        lines.append(f"  - Run {i+1}: `{r.run_id}` — {provider}/{model}, suite={r.suite}")
    lines.append(f"**Total unique cases**: {len(per_case)}")
    lines.append("")

    # ── Overall stats ──
    lines.append("## Overall Consistency")
    lines.append("")
    lines.append("| Category | Count | Percentage |")
    lines.append("|----------|-------|------------|")
    lines.append(f"| Always pass ({n_runs}/{n_runs}) | {len(always_pass)} | {len(always_pass)/len(classifications)*100:.0f}% |")
    lines.append(f"| False positive | {len(false_pos)} | {len(false_pos)/len(classifications)*100:.0f}% |")
    lines.append(f"| Consistent genuine failure | {len(consistent_fail)} | {len(consistent_fail)/len(classifications)*100:.0f}% |")
    lines.append(f"| Intermittent failure | {len(intermittent)} | {len(intermittent)/len(classifications)*100:.0f}% |")
    lines.append("")

    # ── Per-tier consistency ──
    tiers: dict[int, list[dict]] = {}
    for c in classifications:
        tiers.setdefault(c["tier"], []).append(c)

    lines.append("## Per-Tier Consistency")
    lines.append("")
    lines.append("| Tier | Cases | Always Pass | Consistent Fail | Intermittent | Avg Score | Avg TPR |")
    lines.append("|------|-------|-------------|-----------------|--------------|-----------|---------|")
    for t in sorted(tiers.keys()):
        tc = tiers[t]
        ap = sum(1 for c in tc if c["category"] == "always_pass")
        cf = sum(1 for c in tc if c["stability"] == "consistent" and c["category"] not in ("always_pass", "false_positive"))
        inter = sum(1 for c in tc if c["stability"] == "intermittent")
        avg_s = sum(c["avg_score"] for c in tc) / len(tc)
        avg_t = sum(c["avg_tpr"] for c in tc) / len(tc)
        lines.append(f"| T{t} | {len(tc)} | {ap} ({ap/len(tc)*100:.0f}%) | {cf} | {inter} | {avg_s:.3f} | {avg_t:.2f} |")
    lines.append("")

    # ── Per-repo consistency ──
    repos: dict[str, list[dict]] = {}
    for c in classifications:
        if "httpx" in c["case_id"]:
            repo = "httpx"
        elif "rich" in c["case_id"]:
            repo = "rich"
        elif "marshmallow" in c["case_id"]:
            repo = "marshmallow"
        else:
            repo = "other"
        repos.setdefault(repo, []).append(c)

    lines.append("## Per-Repo Consistency")
    lines.append("")
    lines.append("| Repo | Cases | Always Pass | Consistent Fail | Intermittent | Avg Score |")
    lines.append("|------|-------|-------------|-----------------|--------------|-----------|")
    for repo in sorted(repos.keys()):
        rc = repos[repo]
        ap = sum(1 for c in rc if c["category"] == "always_pass")
        cf = sum(1 for c in rc if c["stability"] == "consistent" and c["category"] not in ("always_pass", "false_positive"))
        inter = sum(1 for c in rc if c["stability"] == "intermittent")
        avg_s = sum(c["avg_score"] for c in rc) / len(rc)
        lines.append(f"| {repo} | {len(rc)} | {ap} ({ap/len(rc)*100:.0f}%) | {cf} | {inter} | {avg_s:.3f} |")
    lines.append("")

    # ── Full case matrix ──
    lines.append("## Case-by-Run Matrix")
    lines.append("")
    run_hdrs = " | ".join(f"R{i+1}" for i in range(n_runs))
    lines.append(f"| Case ID | {run_hdrs} | Avg Score | HC | FS | TPR | Category |")
    lines.append(f"|---------|{'---|' * n_runs} ---------|-----|-----|------|----------|")
    for c in sorted(classifications, key=lambda x: (x["tier"], x["case_id"])):
        run_cells = " | ".join("PASS" if p else "FAIL" for p in c["mech_pass_per_run"])
        hc_min = min(c["hunk_coverages"])
        fs_all = not c["has_fs_fail"]
        lines.append(
            f"| `{c['case_id']}` | {run_cells} | {c['avg_score']:.3f} "
            f"| {hc_min:.2f} | {'Y' if fs_all else 'N'} | {c['avg_tpr']:.2f} | {c['category']} |"
        )
    lines.append("")

    # ── False positives ──
    if false_pos:
        lines.append("## False Positives")
        lines.append("")
        for c in false_pos:
            lines.append(f"### `{c['case_id']}`")
            lines.append(f"- Tests fail at **every** commit including the final commit, across all {n_runs} runs")
            lines.append(f"- Final state matches: {'Yes' if not c['has_fs_fail'] else 'No'}")
            lines.append(f"- This is an environment-specific issue, not an LLM composition issue")
            lines.append(f"- **Recommendation**: Exclude failing tests from test command or replace this eval case")
            lines.append("")

    # ── Failure root cause analysis ──
    if genuine_fail:
        lines.append("## Failure Root Cause Analysis")
        lines.append("")

        # Group by category
        by_cat: dict[str, list[dict]] = {}
        for c in genuine_fail:
            by_cat.setdefault(c["category"], []).append(c)

        cat_labels = {
            "ordering": "Incorrect Hunk Ordering (test failures at intermediate commits)",
            "import_only": "Cross-File Import Dependencies (import failures, no test failures)",
            "import_and_test": "Import + Test Failures (cross-file deps causing cascading failures)",
            "hunk_coverage": "Hunk Coverage Issues (LLM dropped hunks)",
            "other": "Other Failures",
        }
        for cat, label in cat_labels.items():
            if cat not in by_cat:
                continue
            cases = by_cat[cat]
            lines.append(f"### {label} ({len(cases)} cases)")
            lines.append("")
            lines.append("| Case | Tier | Ref | Agent Commits | Fails | Avg Score | TPR |")
            lines.append("|------|------|-----|---------------|-------|-----------|-----|")
            for c in cases:
                ac = "/".join(str(x) for x in c["agent_counts"])
                lines.append(
                    f"| `{c['case_id']}` | T{c['tier']} | {c['ref_commits']} "
                    f"| [{ac}] | {c['fail_count']}/{n_runs} | {c['avg_score']:.3f} | {c['avg_tpr']:.2f} |"
                )
            lines.append("")

    # ── Over-splitting analysis ──
    over_split = [c for c in classifications if c["ref_commits"] == 1 and all(a >= 3 for a in c["agent_counts"])]
    if over_split:
        lines.append("## Over-Splitting Analysis")
        lines.append("")
        lines.append("Cases where reference = 1 commit but LLM consistently produces 3+ commits:")
        lines.append("")
        lines.append("| Case | Tier | Agent Commits | Result | Avg TPR |")
        lines.append("|------|------|---------------|--------|---------|")
        for c in over_split:
            ac = "/".join(str(x) for x in c["agent_counts"])
            status = "PASS" if c["category"] == "always_pass" else f"FAIL({c['fail_count']}/{n_runs})"
            lines.append(f"| `{c['case_id']}` | T{c['tier']} | [{ac}] | {status} | {c['avg_tpr']:.2f} |")
        lines.append("")

    # ── Score stability ──
    lines.append("## Score Stability Across Runs")
    lines.append("")
    lines.append("| Case | Tier | Scores | Range | Std Dev |")
    lines.append("|------|------|--------|-------|---------|")
    for c in sorted(classifications, key=lambda x: (x["tier"], x["case_id"])):
        scores = c["scores"]
        score_str = " / ".join(f"{s:.3f}" for s in scores)
        rng = max(scores) - min(scores)
        mean = sum(scores) / len(scores)
        std = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5
        lines.append(f"| `{c['case_id']}` | T{c['tier']} | {score_str} | {rng:.3f} | {std:.3f} |")
    lines.append("")

    return "\n".join(lines)


def generate_meta_terminal_report(results: list[EvalRunResult]) -> str:
    """Generate a compact terminal report for meta-analysis across runs."""
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RST = "\033[0m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"

    per_case = _collect_meta_data(results)
    n_runs = len(results)

    classifications: list[dict] = []
    for cid in sorted(per_case.keys()):
        runs = per_case[cid]
        classifications.append(_classify_failure(cid, runs, n_runs))

    always_pass = [c for c in classifications if c["category"] == "always_pass"]
    false_pos = [c for c in classifications if c["category"] == "false_positive"]
    genuine_fail = [c for c in classifications if c["category"] not in ("always_pass", "false_positive")]
    consistent_fail = [c for c in genuine_fail if c["stability"] == "consistent"]
    intermittent = [c for c in genuine_fail if c["stability"] == "intermittent"]

    lines: list[str] = []

    # ── Header ──
    lines.append("")
    lines.append(f"{BOLD}{'═' * 78}{RST}")
    lines.append(f"{BOLD}  🔬  Meta-Analysis Report — {n_runs} Runs × {len(per_case)} Cases{RST}")
    lines.append(f"{BOLD}{'═' * 78}{RST}")
    for i, r in enumerate(results):
        provider = r.agent_config.get("provider", "?")
        model = r.agent_config.get("model", "?")
        lines.append(f"  {DIM}Run {i+1}:{RST} {r.run_id} ({provider}/{model})")
    lines.append("")

    # ── Summary bar ──
    total = len(classifications)
    lines.append(f"  {BOLD}Consistency Summary{RST}")
    lines.append(f"  ┌────────────────────┬────────────────────┬────────────────────┬────────────────────┐")
    lines.append(f"  │ {BOLD}Always Pass{RST}        │ {BOLD}Consistent Fail{RST}    │ {BOLD}Intermittent{RST}       │ {BOLD}False Positive{RST}     │")
    lines.append(f"  ├────────────────────┼────────────────────┼────────────────────┼────────────────────┤")
    ap_pct = len(always_pass) / total * 100
    cf_pct = len(consistent_fail) / total * 100
    it_pct = len(intermittent) / total * 100
    fp_pct = len(false_pos) / total * 100
    ap_c = GREEN if ap_pct >= 50 else YELLOW
    cf_c = RED if cf_pct > 30 else YELLOW
    lines.append(
        f"  │ {ap_c}{len(always_pass):>2}/{total}{RST} ({ap_pct:>4.0f}%)      "
        f"│ {cf_c}{len(consistent_fail):>2}/{total}{RST} ({cf_pct:>4.0f}%)      "
        f"│ {YELLOW}{len(intermittent):>2}/{total}{RST} ({it_pct:>4.0f}%)      "
        f"│ {RED if false_pos else GREEN}{len(false_pos):>2}/{total}{RST} ({fp_pct:>4.0f}%)      │"
    )
    lines.append(f"  └────────────────────┴────────────────────┴────────────────────┴────────────────────┘")
    lines.append("")

    # ── Per-tier table ──
    tiers: dict[int, list[dict]] = {}
    for c in classifications:
        tiers.setdefault(c["tier"], []).append(c)

    lines.append(f"  {BOLD}Per-Tier Breakdown{RST}")
    lines.append(f"  {DIM}{'─' * 74}{RST}")
    lines.append(f"  {DIM}{'Tier':>6}  {'Cases':>5}  {'Pass':>8}  {'ConsFail':>9}  {'Interm':>7}  {'Avg Score':>9}  {'Avg TPR':>8}{RST}")
    lines.append(f"  {DIM}{'─' * 74}{RST}")
    for t in sorted(tiers.keys()):
        tc = tiers[t]
        ap = sum(1 for c in tc if c["category"] == "always_pass")
        cf = sum(1 for c in tc if c["stability"] == "consistent" and c["category"] not in ("always_pass", "false_positive"))
        inter = sum(1 for c in tc if c["stability"] == "intermittent")
        avg_s = sum(c["avg_score"] for c in tc) / len(tc)
        avg_t = sum(c["avg_tpr"] for c in tc) / len(tc)
        ap_str = f"{ap}/{len(tc)}"
        s_color = GREEN if avg_s >= 0.8 else (YELLOW if avg_s >= 0.6 else RED)
        lines.append(
            f"  {'T'+str(t):>6}  {len(tc):>5}  {GREEN}{ap_str:>8}{RST}  {cf:>9}  {inter:>7}  "
            f"{s_color}{avg_s:.3f}{RST}     {avg_t:.2f}"
        )
    lines.append(f"  {DIM}{'─' * 74}{RST}")
    lines.append("")

    # ── Case matrix ──
    lines.append(f"  {BOLD}Case-by-Run Matrix{RST}")
    run_hdr = "  ".join(f"R{i+1}" for i in range(n_runs))
    lines.append(f"  {DIM}{'─' * 78}{RST}")
    lines.append(f"  {DIM}{'':>3}  {'Case':<45} {'T':>2}  {run_hdr}  {'Score':>6}  {'Category'}{RST}")
    lines.append(f"  {DIM}{'─' * 78}{RST}")
    for c in sorted(classifications, key=lambda x: (x["tier"], x["case_id"])):
        name = c["case_id"]
        if len(name) > 45:
            name = name[:42] + "..."
        run_dots = []
        for p in c["mech_pass_per_run"]:
            if p:
                run_dots.append(f"{GREEN}✓{RST} ")
            else:
                run_dots.append(f"{RED}✗{RST} ")
        dots_str = "".join(run_dots)
        s_color = GREEN if c["avg_score"] >= 0.8 else (YELLOW if c["avg_score"] >= 0.6 else RED)
        cat = c["category"]
        cat_color = GREEN if cat == "always_pass" else (RED if cat == "false_positive" else YELLOW)
        lines.append(
            f"   {'':>1}  {name:<45} T{c['tier']}  {dots_str} {s_color}{c['avg_score']:.3f}{RST}  {cat_color}{cat}{RST}"
        )
    lines.append(f"  {DIM}{'─' * 78}{RST}")
    lines.append("")

    # ── Failure root cause digest ──
    if genuine_fail:
        by_cat: dict[str, list[dict]] = {}
        for c in genuine_fail:
            by_cat.setdefault(c["category"], []).append(c)

        lines.append(f"  {BOLD}Failure Root Causes{RST}")
        lines.append(f"  {DIM}{'─' * 74}{RST}")
        cat_labels = {
            "ordering": "Incorrect ordering",
            "import_only": "Import-only failures",
            "import_and_test": "Import + test failures",
            "hunk_coverage": "Hunk coverage drops",
            "other": "Other",
        }
        for cat, label in cat_labels.items():
            if cat not in by_cat:
                continue
            cases = by_cat[cat]
            n_cons = sum(1 for c in cases if c["stability"] == "consistent")
            n_int = sum(1 for c in cases if c["stability"] == "intermittent")
            lines.append(
                f"  {YELLOW}▸{RST} {label}: {len(cases)} cases "
                f"({n_cons} consistent, {n_int} intermittent)"
            )
            for c in cases:
                status = f"{RED}always{RST}" if c["stability"] == "consistent" else f"{YELLOW}interm{RST}"
                lines.append(
                    f"    {DIM}•{RST} {c['case_id']} T{c['tier']} [{status}] "
                    f"fails={c['fail_count']}/{n_runs} TPR={c['avg_tpr']:.2f}"
                )
        lines.append("")

    # ── False positives ──
    if false_pos:
        lines.append(f"  {BOLD}{RED}False Positives{RST}")
        lines.append(f"  {DIM}{'─' * 74}{RST}")
        for c in false_pos:
            lines.append(f"  {RED}⚠{RST} {c['case_id']} — tests fail at final commit in all {n_runs} runs")
        lines.append("")

    lines.append(f"{BOLD}{'═' * 78}{RST}")
    lines.append("")
    return "\n".join(lines)


def generate_meta_web_report(results: list[EvalRunResult]) -> str:
    """Generate a single-page HTML meta-analysis dashboard."""
    per_case = _collect_meta_data(results)
    n_runs = len(results)

    classifications: list[dict] = []
    for cid in sorted(per_case.keys()):
        runs = per_case[cid]
        classifications.append(_classify_failure(cid, runs, n_runs))

    # Build data for JS
    runs_meta = []
    for i, r in enumerate(results):
        runs_meta.append({
            "index": i + 1,
            "run_id": r.run_id,
            "timestamp": r.timestamp,
            "provider": r.agent_config.get("provider", "?"),
            "model": r.agent_config.get("model", "?"),
            "suite": r.suite,
        })

    cases_data = []
    for c in classifications:
        cases_data.append({
            "case_id": c["case_id"],
            "tier": c["tier"],
            "ref_commits": c["ref_commits"],
            "agent_counts": c["agent_counts"],
            "fail_count": c["fail_count"],
            "pass_count": c["pass_count"],
            "category": c["category"],
            "stability": c["stability"],
            "avg_score": round(c["avg_score"], 3),
            "avg_tpr": round(c["avg_tpr"], 3),
            "has_import_fail": c["has_import_fail"],
            "has_test_fail": c["has_test_fail"],
            "has_hunk_miss": c["has_hunk_miss"],
            "has_fs_fail": c["has_fs_fail"],
            "mech_pass_per_run": c["mech_pass_per_run"],
            "hunk_coverages": [round(h, 3) for h in c["hunk_coverages"]],
            "scores": [round(s, 3) for s in c["scores"]],
        })

    # Per-tier summary
    tiers_data: dict[int, dict] = {}
    for c in classifications:
        t = c["tier"]
        if t not in tiers_data:
            tiers_data[t] = {"tier": t, "total": 0, "always_pass": 0, "consistent_fail": 0, "intermittent": 0, "false_positive": 0, "scores": [], "tprs": []}
        td = tiers_data[t]
        td["total"] += 1
        td["scores"].append(c["avg_score"])
        td["tprs"].append(c["avg_tpr"])
        if c["category"] == "always_pass":
            td["always_pass"] += 1
        elif c["category"] == "false_positive":
            td["false_positive"] += 1
        elif c["stability"] == "consistent":
            td["consistent_fail"] += 1
        else:
            td["intermittent"] += 1

    tiers_summary = []
    for t in sorted(tiers_data.keys()):
        td = tiers_data[t]
        td["avg_score"] = round(sum(td["scores"]) / len(td["scores"]), 3) if td["scores"] else 0
        td["avg_tpr"] = round(sum(td["tprs"]) / len(td["tprs"]), 3) if td["tprs"] else 0
        del td["scores"]
        del td["tprs"]
        tiers_summary.append(td)

    data = json.dumps({
        "n_runs": n_runs,
        "runs": runs_meta,
        "cases": cases_data,
        "tiers": tiers_summary,
        "summary": {
            "total": len(classifications),
            "always_pass": sum(1 for c in classifications if c["category"] == "always_pass"),
            "false_positive": sum(1 for c in classifications if c["category"] == "false_positive"),
            "consistent_fail": sum(1 for c in classifications if c["stability"] == "consistent" and c["category"] not in ("always_pass", "false_positive")),
            "intermittent": sum(1 for c in classifications if c["stability"] == "intermittent"),
        },
    })

    return _META_HTML_TEMPLATE.replace("/*__META_DATA__*/", f"const DATA = {data};")


def run_meta_analysis(
    result_paths: list[Path],
    web: bool = False,
    output_dir: Optional[Path] = None,
) -> tuple[Path, str]:
    """Run meta-analysis across multiple eval runs.

    Writes JSON data, Markdown report (and optionally HTML dashboard) to
    the output directory, which defaults to the directory of the most
    recent (last) result file.

    Returns:
        Tuple of (path to Markdown report, terminal report string).
    """
    results = [load_result(p) for p in result_paths]

    # Default output to the most-recent result's directory
    if output_dir is None:
        # Pick the directory with the lexicographically largest name (most recent timestamp)
        candidates = [p.parent for p in result_paths]
        out_dir = max(candidates, key=lambda d: d.name)
    else:
        out_dir = output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON (structured data — used by meta_analysis.py for cross-group comparison)
    meta_json = generate_meta_analysis_json(results)
    json_path = out_dir / "meta_analysis.json"
    with open(json_path, "w") as f:
        json.dump(meta_json, f, indent=2)
    logger.info("Meta-analysis JSON saved to %s", json_path)

    # Markdown
    md_report = generate_meta_analysis_report(results)
    md_path = out_dir / "meta_analysis.md"
    md_path.write_text(md_report)
    logger.info("Meta-analysis report saved to %s", md_path)

    # HTML
    if web:
        html_report = generate_meta_web_report(results)
        html_path = out_dir / "meta_dashboard.html"
        html_path.write_text(html_report)
        logger.info("Meta-analysis dashboard saved to %s", html_path)

    # Terminal
    terminal_report = generate_meta_terminal_report(results)

    return md_path, terminal_report


# ── Convenience helpers ──────────────────────────────────────────────────────


def generate_terminal_report(result: EvalRunResult) -> str:
    """Generate a compact, terminal-friendly analysis report.

    Uses Unicode box-drawing characters and ANSI color codes for
    readability in a terminal.  Keeps output concise: summary cards,
    per-tier table, per-case table, and a short failure digest.
    """
    # ANSI helpers
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RST = "\033[0m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"

    def ok(v: bool | None) -> str:
        if v is True:
            return f"{GREEN}✓{RST}"
        if v is False:
            return f"{RED}✗{RST}"
        return f"{DIM}—{RST}"

    def pct(v: float | None, width: int = 6) -> str:
        if v is None:
            return "  n/a ".rjust(width)
        return f"{v * 100:.1f}%".rjust(width)

    def score_colored(v: float) -> str:
        if v >= 0.8:
            return f"{GREEN}{v:.3f}{RST}"
        if v >= 0.6:
            return f"{YELLOW}{v:.3f}{RST}"
        return f"{RED}{v:.3f}{RST}"

    lines: list[str] = []
    summary = result.get_summary()
    by_tier = result.get_by_tier()
    failures = result.get_failures()

    total_duration = sum(c.duration_s for c in result.cases)
    total_duration = f"{int(total_duration // 3600):02d}:{int((total_duration % 3600) // 60):02d}:{int(total_duration % 60):02d}"
    total_tokens = sum(c.total_tokens for c in result.cases)
    provider = result.agent_config.get("provider", "?")
    model = result.agent_config.get("model", "?")
    use_agent = result.agent_config.get("use_agent", False)
    mode = "Agentic" if use_agent else "Single-shot"

    # ── Header ──
    lines.append("")
    lines.append(f"{BOLD}{'═' * 72}{RST}")
    lines.append(f"{BOLD}  🔬  Evaluation Analysis Report{RST}")
    lines.append(f"{BOLD}{'═' * 72}{RST}")
    lines.append(f"  {DIM}Run:{RST}   {result.run_id}")
    lines.append(f"  {DIM}Agent:{RST} {provider}/{model} ({mode})")
    lines.append(f"  {DIM}Suite:{RST} {result.suite}   {DIM}Time:{RST} {total_duration}   {DIM}Tokens:{RST} {total_tokens:,}")
    lines.append("")

    # ── Summary bar ──
    passed = summary["passed"]
    total = summary["total"]
    mech_pass = sum(1 for c in result.cases if c.error is None and c.mechanical.full_sequence_valid)
    avg = summary["avg_score"]
    mech_rate = summary.get("mechanical_pass_rate", 0)

    pass_color = GREEN if passed == total else YELLOW
    mech_color = GREEN if mech_rate >= 0.8 else (YELLOW if mech_rate >= 0.5 else RED)

    lines.append(f"  {BOLD}Summary{RST}")
    lines.append(f"  ┌──────────────┬──────────────┬──────────────┬──────────────┐")
    lines.append(f"  │ {BOLD}Cases{RST}        │ {BOLD}Avg Score{RST}    │ {BOLD}Mech Pass{RST}    │ {BOLD}Score Range{RST}  │")
    lines.append(f"  ├──────────────┼──────────────┼──────────────┼──────────────┤")
    lines.append(
        f"  │ {pass_color}{passed}/{total} passed{RST}   "
        f"│  {score_colored(avg)}       "
        f"│  {mech_color}{mech_pass}/{total}{RST} ({pct(mech_rate).strip()}) "
        f"│ {summary.get('min_score', 0):.3f}–{summary.get('max_score', 0):.3f}  │"
    )
    lines.append(f"  └──────────────┴──────────────┴──────────────┴──────────────┘")
    lines.append("")

    # ── Per-tier table ──
    if by_tier:
        lines.append(f"  {BOLD}Per-Tier Breakdown{RST}")
        hdr = (
            f"  {'Tier':>6}  {'Cases':>5}  {'Avg Score':>9}  {'Mech':>6}  "
            f"{'Patch':>6}  {'Syntax':>6}  {'Import':>6}  {'Tests':>6}  {'Final':>6}"
        )
        lines.append(f"  {DIM}{'─' * 75}{RST}")
        lines.append(f"{DIM}{hdr}{RST}")
        lines.append(f"  {DIM}{'─' * 75}{RST}")
        for tier in sorted(by_tier.keys(), key=lambda t: t.value):
            cases = by_tier[tier]
            valid = [c for c in cases if c.error is None]
            n = len(valid) or 1
            avg_t = sum(c.overall_score for c in valid) / n
            mech_t = sum(1 for c in valid if c.mechanical.full_sequence_valid) / n
            patch_t = sum(c.mechanical.patch_apply_rate for c in valid) / n
            syntax_t = sum(c.mechanical.build_pass_rate for c in valid) / n
            imp_t = sum(c.mechanical.import_integrity_rate for c in valid) / n
            test_rates = [c.mechanical.test_pass_rate for c in valid if c.mechanical.test_pass_rate is not None]
            test_t = sum(test_rates) / len(test_rates) if test_rates else None
            final_t = sum(1 for c in valid if c.mechanical.final_state_matches is True) / n
            lines.append(
                f"  {'T' + str(tier.value):>6}  {len(cases):>5}  "
                f"{score_colored(avg_t):>18}  {pct(mech_t)}  "
                f"{pct(patch_t)}  {pct(syntax_t)}  {pct(imp_t)}  "
                f"{pct(test_t)}  {pct(final_t)}"
            )
        lines.append(f"  {DIM}{'─' * 75}{RST}")
        lines.append("")

    # ── Per-case table ──
    lines.append(f"  {BOLD}Per-Case Results{RST}")
    lines.append(f"  {DIM}Legend: {GREEN}●{RST}{DIM} all pass  {YELLOW}●{RST}{DIM} tests fail (build ok)  {RED}●{RST}{DIM} build/import fail{RST}")
    lines.append(f"  {DIM}{'─' * 75}{RST}")
    hdr2 = f"  {'Status':>3}  {'Case':<38} {'Tier':>4}  {'Score':>6}  {'Tests':>6}  {'Commits':>7}"
    lines.append(f"{DIM}{hdr2}{RST}")
    lines.append(f"  {DIM}{'─' * 75}{RST}")
    for c in result.cases:
        m = c.mechanical
        status = f"{GREEN}✓{RST}" if m.full_sequence_valid else f"{RED}✗{RST}"
        # Truncate case name
        name = c.case_id
        if len(name) > 42:
            name = name[:39] + "..."
        test_str = pct(m.test_pass_rate)
        commit_str = f"{c.agent_commit_count}/{c.reference_commit_count}"
        lines.append(
            f"   {status}   {name:<42} T{c.tier.value:>3}  "
            f"{score_colored(c.overall_score):>15}  {test_str}  {commit_str:>7}"
        )
        # Show per-commit dots on a second line
        if m.per_commit:
            dots = []
            for cv in m.per_commit:
                all_ok = cv.patch_applies and cv.syntax_valid and cv.import_resolves and cv.tests_pass is not False
                if all_ok:
                    dots.append(f"{GREEN}●{RST}")
                elif cv.tests_pass is False and cv.patch_applies and cv.syntax_valid and cv.import_resolves:
                    dots.append(f"{YELLOW}●{RST}")
                else:
                    dots.append(f"{RED}●{RST}")
            fs = ok(m.final_state_matches)
            hc_str = ""
            if m.hunk_coverage is not None and m.hunk_coverage < 1.0:
                hc_str = f"  {DIM}hunks:{RST} {YELLOW}{m.hunk_coverage:.0%}{RST}"
            lines.append(f"       {DIM}commits:{RST} {' '.join(dots)}  {DIM}final-state:{RST} {fs}{hc_str}")

    lines.append(f"  {DIM}{'─' * 75}{RST}")
    lines.append("")

    # ── Failure digest ──
    if failures:
        lines.append(f"  {BOLD}{RED}Failure Digest{RST}")
        lines.append(f"  {DIM}{'─' * 75}{RST}")
        for c in failures:
            m = c.mechanical
            lines.append(f"  {RED}✗{RST} {BOLD}{c.case_id}{RST}")
            if c.error:
                lines.append(f"    {RED}Error: {c.error}{RST}")
            else:
                reasons = []
                if m.final_state_matches is False:
                    reasons.append("final state mismatch")
                if m.hunk_coverage is not None and m.hunk_coverage < 1.0:
                    n_missing = len(m.missing_hunk_ids) if m.missing_hunk_ids else 0
                    n_halluc = len(m.hallucinated_hunk_ids) if m.hallucinated_hunk_ids else 0
                    parts = [f"hunk coverage {m.hunk_coverage:.0%}"]
                    if n_missing:
                        parts.append(f"{n_missing} missing")
                    if n_halluc:
                        parts.append(f"{n_halluc} hallucinated")
                    reasons.append(", ".join(parts))
                for cv in m.per_commit:
                    if not cv.patch_applies:
                        reasons.append(f"{cv.commit_id}: patch failed")
                    elif not cv.syntax_valid:
                        reasons.append(f"{cv.commit_id}: syntax error")
                    elif not cv.import_resolves:
                        reasons.append(f"{cv.commit_id}: import failure")
                    elif cv.tests_pass is False:
                        # Extract first failing test name
                        first_err = cv.errors[0] if cv.errors else ""
                        # Try to find the test function name
                        test_name = ""
                        for line in first_err.split("\n"):
                            stripped = line.strip()
                            if stripped.startswith("_") and stripped.endswith("_"):
                                test_name = stripped.strip("_ ")
                                break
                        suffix = f" ({test_name})" if test_name else ""
                        reasons.append(f"{cv.commit_id}: tests failed{suffix}")
                if reasons:
                    for r in reasons:
                        lines.append(f"    {DIM}•{RST} {r}")
            lines.append("")
        lines.append(f"  {DIM}{'─' * 75}{RST}")
    else:
        lines.append(f"  {GREEN}✓ All cases passed mechanical validation{RST}")

    lines.append("")
    lines.append(f"{BOLD}{'═' * 72}{RST}")
    lines.append("")
    return "\n".join(lines)


def run_analysis(
    result_path: Path,
    web: bool = False,
    output_dir: Optional[Path] = None,
) -> tuple[Path, str]:
    """Run analysis on a saved eval result and write output files.

    Always writes the Markdown report and returns a terminal-friendly
    report string.  With ``web=True``, also writes the HTML dashboard.

    Args:
        result_path: Path to ``eval_results.json``.
        web: Whether to generate the HTML dashboard as well.
        output_dir: Where to write reports.  Defaults to the same
            directory as ``result_path``.

    Returns:
        Tuple of (path to Markdown report, terminal report string).
    """
    result = load_result(result_path)
    out_dir = output_dir or result_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Markdown report
    md_report = generate_analysis_report(result)
    md_path = out_dir / "eval_analysis.md"
    md_path.write_text(md_report)
    logger.info("Analysis report saved to %s", md_path)

    # HTML dashboard
    if web:
        html_report = generate_web_report(result)
        html_path = out_dir / "eval_dashboard.html"
        html_path.write_text(html_report)
        logger.info("Web dashboard saved to %s", html_path)

    # Terminal report
    terminal_report = generate_terminal_report(result)

    return md_path, terminal_report


# ── HTML template ────────────────────────────────────────────────────────────

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Evaluation Dashboard</title>
<style>
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d29922; --orange: #db6d28;
  --radius: 8px; --shadow: 0 1px 3px rgba(0,0,0,.3);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.5; padding: 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Header */
.header { background: var(--surface); border-bottom: 1px solid var(--border);
           padding: 16px 24px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.header h1 { font-size: 1.3rem; font-weight: 600; }
.header .meta { color: var(--text-dim); font-size: .85rem; }
.header .meta span { margin-right: 16px; }

/* Container */
.container { max-width: 1400px; margin: 0 auto; padding: 24px; }

/* Cards */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
        padding: 16px; text-align: center; }
.card .value { font-size: 1.8rem; font-weight: 700; }
.card .label { color: var(--text-dim); font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; }

/* Tabs */
.tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
.tab { padding: 8px 18px; cursor: pointer; border-bottom: 2px solid transparent;
       color: var(--text-dim); font-size: .9rem; transition: all .15s; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: .88rem; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th { color: var(--text-dim); font-weight: 600; font-size: .8rem; text-transform: uppercase;
     letter-spacing: .03em; background: var(--surface); position: sticky; top: 0; }
tr:hover { background: rgba(88,166,255,.04); }
tr.clickable { cursor: pointer; }

/* Status badges */
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: .75rem; font-weight: 600; }
.badge.pass { background: rgba(63,185,80,.15); color: var(--green); }
.badge.fail { background: rgba(248,81,73,.15); color: var(--red); }
.badge.warn { background: rgba(210,153,34,.15); color: var(--yellow); }
.badge.na { background: rgba(139,148,158,.15); color: var(--text-dim); }

/* Score bar */
.score-bar { display: inline-flex; align-items: center; gap: 6px; }
.score-bar .bar { width: 60px; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
.score-bar .bar .fill { height: 100%; border-radius: 3px; transition: width .3s; }

/* Detail panel */
.detail-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
                padding: 20px; margin-top: 16px; display: none; }
.detail-panel.visible { display: block; }
.detail-panel h3 { margin-bottom: 12px; font-size: 1.1rem; }
.detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.detail-section { background: rgba(255,255,255,.02); border: 1px solid var(--border);
                  border-radius: var(--radius); padding: 14px; }
.detail-section h4 { color: var(--accent); font-size: .85rem; margin-bottom: 8px; text-transform: uppercase;
                     letter-spacing: .04em; }
.kv { display: flex; justify-content: space-between; padding: 3px 0; font-size: .85rem; }
.kv .k { color: var(--text-dim); }

/* Commit timeline */
.commit-timeline { display: flex; gap: 4px; margin: 10px 0; flex-wrap: wrap; }
.commit-dot { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center;
              justify-content: center; font-size: .7rem; font-weight: 700; cursor: pointer;
              transition: transform .15s; border: 2px solid transparent; }
.commit-dot:hover { transform: scale(1.2); }
.commit-dot.pass { background: var(--green); color: #000; }
.commit-dot.fail { background: var(--red); color: #fff; }
.commit-dot.partial { background: var(--yellow); color: #000; }

/* Error box */
.error-box { background: rgba(248,81,73,.08); border: 1px solid rgba(248,81,73,.3);
             border-radius: var(--radius); padding: 10px; margin-top: 8px;
             font-family: monospace; font-size: .78rem; white-space: pre-wrap;
             max-height: 200px; overflow-y: auto; color: var(--red); }

/* Filter bar */
.filter-bar { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.filter-bar label { color: var(--text-dim); font-size: .8rem; }
.filter-bar select, .filter-bar input { background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; font-size: .85rem; }

/* Responsive */
@media (max-width: 768px) {
  .container { padding: 12px; }
  .cards { grid-template-columns: repeat(2, 1fr); }
  .detail-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="header">
  <h1>🔬 Evaluation Dashboard</h1>
  <div class="meta" id="header-meta"></div>
</div>

<div class="container">
  <!-- Summary cards -->
  <div class="cards" id="summary-cards"></div>

  <!-- Tabs -->
  <div class="tabs" id="main-tabs">
    <div class="tab active" data-tab="overview">Overview</div>
    <div class="tab" data-tab="tiers">By Tier</div>
    <div class="tab" data-tab="cases">All Cases</div>
    <div class="tab" data-tab="failures">Failures</div>
  </div>

  <!-- Tab: Overview -->
  <div class="tab-content active" id="tab-overview">
    <h3 style="margin-bottom:12px">Per-Tier Summary</h3>
    <table id="tier-table"></table>
  </div>

  <!-- Tab: Tiers (drill-down) -->
  <div class="tab-content" id="tab-tiers">
    <div class="filter-bar">
      <label>Tier:</label>
      <select id="tier-filter"><option value="all">All</option></select>
    </div>
    <table id="tier-cases-table"></table>
    <div class="detail-panel" id="tier-detail"></div>
  </div>

  <!-- Tab: All Cases -->
  <div class="tab-content" id="tab-cases">
    <div class="filter-bar">
      <label>Status:</label>
      <select id="status-filter">
        <option value="all">All</option>
        <option value="pass">Pass</option>
        <option value="fail">Fail</option>
      </select>
      <label>Sort:</label>
      <select id="sort-select">
        <option value="tier">Tier</option>
        <option value="score">Score</option>
        <option value="name">Name</option>
      </select>
    </div>
    <table id="cases-table"></table>
    <div class="detail-panel" id="case-detail"></div>
  </div>

  <!-- Tab: Failures -->
  <div class="tab-content" id="tab-failures">
    <div id="failures-list"></div>
  </div>
</div>

<script>
/*__DATA__*/

// ── Helpers ──
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function pct(v) { return v == null ? 'n/a' : (v * 100).toFixed(1) + '%'; }
function badge(ok, label) {
  if (ok === true) return `<span class="badge pass">${label || 'PASS'}</span>`;
  if (ok === false) return `<span class="badge fail">${label || 'FAIL'}</span>`;
  return `<span class="badge na">${label || 'n/a'}</span>`;
}
function scoreColor(v) {
  if (v >= 0.8) return 'var(--green)';
  if (v >= 0.6) return 'var(--yellow)';
  return 'var(--red)';
}
function scoreBar(v) {
  const c = scoreColor(v);
  return `<span class="score-bar"><span class="bar"><span class="fill" style="width:${v*100}%;background:${c}"></span></span>${v.toFixed(3)}</span>`;
}

// ── Render header ──
const meta = DATA.meta;
document.getElementById('header-meta').innerHTML =
  `<span>Run: <b>${esc(meta.run_id)}</b></span>` +
  `<span>${esc(meta.provider)}/${esc(meta.model)}</span>` +
  `<span>${meta.use_agent ? 'Agentic' : 'Single-shot'}</span>` +
  `<span>${meta.total_duration}s</span>` +
  `<span>${meta.total_tokens.toLocaleString()} tokens</span>`;

// ── Summary cards ──
const s = DATA.summary;
document.getElementById('summary-cards').innerHTML = [
  {v: s.total, l: 'Total Cases'},
  {v: s.passed + '/' + s.total, l: 'Passed'},
  {v: s.avg_score.toFixed(3), l: 'Avg Score'},
  {v: pct(s.mechanical_pass_rate), l: 'Mech Pass Rate'},
  {v: s.min_score.toFixed(3), l: 'Min Score'},
  {v: s.max_score.toFixed(3), l: 'Max Score'},
].map(c => `<div class="card"><div class="value">${c.v}</div><div class="label">${c.l}</div></div>`).join('');

// ── Tabs ──
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});

// ── Tier table (overview) ──
function renderTierTable() {
  const rows = DATA.tiers.map(t =>
    `<tr><td>Tier ${t.tier}</td><td>${t.count}</td><td>${scoreBar(t.avg_score)}</td>` +
    `<td>${pct(t.mech_pass)}</td><td>${t.test_rate != null ? pct(t.test_rate) : 'n/a'}</td>` +
    `<td>${pct(t.final_state)}</td></tr>`
  ).join('');
  document.getElementById('tier-table').innerHTML =
    `<thead><tr><th>Tier</th><th>Cases</th><th>Avg Score</th><th>Mech Pass</th><th>Test Rate</th><th>Final State</th></tr></thead><tbody>${rows}</tbody>`;
}
renderTierTable();

// ── Tier filter (tiers tab) ──
const tierFilter = document.getElementById('tier-filter');
DATA.tiers.forEach(t => {
  const opt = document.createElement('option');
  opt.value = t.tier;
  opt.textContent = 'Tier ' + t.tier;
  tierFilter.appendChild(opt);
});

function renderTierCases() {
  const sel = tierFilter.value;
  const cases = sel === 'all' ? DATA.cases : DATA.cases.filter(c => c.tier == sel);
  renderCaseTable(cases, 'tier-cases-table', 'tier-detail');
}
tierFilter.addEventListener('change', renderTierCases);
renderTierCases();

// ── All cases tab ──
function renderAllCases() {
  const statusF = document.getElementById('status-filter').value;
  const sortF = document.getElementById('sort-select').value;
  let cases = [...DATA.cases];
  if (statusF === 'pass') cases = cases.filter(c => c.mech_pass);
  if (statusF === 'fail') cases = cases.filter(c => !c.mech_pass);
  if (sortF === 'score') cases.sort((a, b) => b.score - a.score);
  else if (sortF === 'name') cases.sort((a, b) => a.id.localeCompare(b.id));
  else cases.sort((a, b) => a.tier - b.tier || a.id.localeCompare(b.id));
  renderCaseTable(cases, 'cases-table', 'case-detail');
}
document.getElementById('status-filter').addEventListener('change', renderAllCases);
document.getElementById('sort-select').addEventListener('change', renderAllCases);
renderAllCases();

// ── Shared case table renderer ──
function renderCaseTable(cases, tableId, detailId) {
  const rows = cases.map(c =>
    `<tr class="clickable" data-id="${esc(c.id)}">` +
    `<td>${esc(c.id)}</td><td>T${c.tier}</td><td>${scoreBar(c.score)}</td>` +
    `<td>${badge(c.mech_pass)}</td><td>${pct(c.test_rate)}</td>` +
    `<td>${badge(c.final_state)}</td>` +
    `<td>${c.agent_commits}</td><td>${c.duration}s</td></tr>`
  ).join('');
  const table = document.getElementById(tableId);
  table.innerHTML =
    `<thead><tr><th>Case</th><th>Tier</th><th>Score</th><th>Mechanical</th>` +
    `<th>Tests</th><th>Final State</th><th>Commits</th><th>Duration</th></tr></thead><tbody>${rows}</tbody>`;
  table.querySelectorAll('tr.clickable').forEach(row => {
    row.addEventListener('click', () => showDetail(row.dataset.id, detailId));
  });
}

// ── Detail panel ──
function showDetail(caseId, panelId) {
  const c = DATA.cases.find(x => x.id === caseId);
  if (!c) return;
  const panel = document.getElementById(panelId);
  panel.classList.add('visible');

  // Commit timeline
  const timeline = c.per_commit.map(cv => {
    const ok = cv.patch && cv.syntax && cv.import && cv.tests !== false;
    const cls = ok ? 'pass' : (cv.tests === false && cv.patch && cv.syntax && cv.import ? 'partial' : 'fail');
    return `<div class="commit-dot ${cls}" title="${esc(cv.id)}">${cv.id.replace('C','')}</div>`;
  }).join('');

  // Per-commit table
  const commitRows = c.per_commit.map(cv => {
    const errHtml = cv.errors.length
      ? `<div class="error-box">${esc(cv.errors.join('\n').substring(0, 1000))}</div>` : '';
    return `<tr><td>${esc(cv.id)}</td><td>${badge(cv.patch)}</td><td>${badge(cv.syntax)}</td>` +
           `<td>${badge(cv.import)}</td><td>${badge(cv.tests)}</td></tr>` +
           (errHtml ? `<tr><td colspan="5">${errHtml}</td></tr>` : '');
  }).join('');

  panel.innerHTML = `
    <h3>${badge(c.mech_pass)} ${esc(c.id)}</h3>
    <div class="commit-timeline">${timeline}</div>
    <div class="detail-grid">
      <div class="detail-section">
        <h4>Mechanical Validation</h4>
        <div class="kv"><span class="k">Full sequence valid</span>${badge(c.mech_pass)}</div>
        <div class="kv"><span class="k">Patch apply rate</span>${pct(c.patch_rate)}</div>
        <div class="kv"><span class="k">Syntax rate</span>${pct(c.syntax_rate)}</div>
        <div class="kv"><span class="k">Import rate</span>${pct(c.import_rate)}</div>
        <div class="kv"><span class="k">Test pass rate</span>${c.test_rate != null ? pct(c.test_rate) : 'n/a'}</div>
        <div class="kv"><span class="k">Final state</span>${badge(c.final_state)}</div>
        ${c.final_state_diff ? `<div class="error-box">${esc(c.final_state_diff)}</div>` : ''}
      </div>
      <div class="detail-section">
        <h4>Semantic Scores</h4>
        <div class="kv"><span class="k">Reference similarity (ARI)</span>${c.ref_sim}</div>
        <div class="kv"><span class="k">Granularity</span>${c.granularity}</div>
        <div class="kv"><span class="k">Dependency recall</span>${c.dep_recall}</div>
        ${c.cohesion != null ? `<div class="kv"><span class="k">Cohesion</span>${c.cohesion}</div>` : ''}
        ${c.separation != null ? `<div class="kv"><span class="k">Separation</span>${c.separation}</div>` : ''}
        ${c.ordering != null ? `<div class="kv"><span class="k">Ordering</span>${c.ordering}</div>` : ''}
      </div>
      <div class="detail-section">
        <h4>Metadata</h4>
        <div class="kv"><span class="k">Agent commits</span>${c.agent_commits}</div>
        <div class="kv"><span class="k">Reference commits</span>${c.ref_commits}</div>
        <div class="kv"><span class="k">Duration</span>${c.duration}s</div>
        <div class="kv"><span class="k">Tokens</span>${c.tokens.toLocaleString()}</div>
        <div class="kv"><span class="k">LLM calls</span>${c.llm_calls}</div>
        ${c.error ? `<div class="kv"><span class="k">Error</span><span style="color:var(--red)">${esc(c.error)}</span></div>` : ''}
      </div>
    </div>
    <h4 style="margin-top:16px;color:var(--accent);font-size:.85rem;">Per-Commit Breakdown</h4>
    <table>
      <thead><tr><th>Commit</th><th>Patch</th><th>Syntax</th><th>Import</th><th>Tests</th></tr></thead>
      <tbody>${commitRows}</tbody>
    </table>
  `;
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ── Failures tab ──
function renderFailures() {
  const failures = DATA.cases.filter(c => !c.mech_pass || c.error);
  if (!failures.length) {
    document.getElementById('failures-list').innerHTML = '<p style="color:var(--green)">🎉 No failures!</p>';
    return;
  }
  const html = failures.map(c => {
    const reasons = [];
    if (c.error) reasons.push(`Error: ${c.error}`);
    if (c.final_state === false) reasons.push('Final state mismatch');
    c.per_commit.forEach(cv => {
      if (!cv.patch) reasons.push(`${cv.id}: patch failed`);
      if (!cv.syntax) reasons.push(`${cv.id}: syntax errors`);
      if (!cv.import) reasons.push(`${cv.id}: import failure`);
      if (cv.tests === false) reasons.push(`${cv.id}: tests failed`);
    });
    const errorDetails = c.per_commit
      .filter(cv => cv.errors.length)
      .map(cv => `<div><b>${esc(cv.id)}</b><div class="error-box">${esc(cv.errors.join('\n').substring(0, 800))}</div></div>`)
      .join('');
    return `<div style="margin-bottom:20px">` +
      `<h4>${badge(false)} ${esc(c.id)} <span style="color:var(--text-dim);font-weight:400"> — Tier ${c.tier}, Score ${c.score}</span></h4>` +
      `<ul style="margin:6px 0 6px 20px;color:var(--text-dim);font-size:.85rem">${reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` +
      errorDetails + `</div>`;
  }).join('');
  document.getElementById('failures-list').innerHTML = html;
}
renderFailures();
</script>
</body>
</html>"""


# ── Meta-analysis HTML template ──────────────────────────────────────────────

_META_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Meta-Analysis Dashboard</title>
<style>
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d29922; --orange: #db6d28;
  --radius: 8px; --shadow: 0 1px 3px rgba(0,0,0,.3);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Noto Sans,Helvetica,Arial,sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.5; padding: 24px; }
.container { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin-bottom: 4px; }
h2 { font-size: 1.2rem; margin: 24px 0 12px; color: var(--accent); }
h3 { font-size: 1rem; margin: 16px 0 8px; }
.subtitle { color: var(--text-dim); font-size: .9rem; margin-bottom: 20px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
        padding: 16px; text-align: center; }
.card .value { font-size: 1.8rem; font-weight: 700; }
.card .label { font-size: .8rem; color: var(--text-dim); margin-top: 4px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: .85rem; }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--surface); color: var(--text-dim); font-weight: 600; position: sticky; top: 0; z-index: 1; }
tr:hover { background: rgba(88,166,255,.06); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: .75rem; font-weight: 600; }
.badge-pass { background: rgba(63,185,80,.15); color: var(--green); }
.badge-fail { background: rgba(248,81,73,.15); color: var(--red); }
.badge-fp { background: rgba(219,109,40,.15); color: var(--orange); }
.badge-interm { background: rgba(210,153,34,.15); color: var(--yellow); }
.dot { display: inline-block; width: 18px; text-align: center; font-weight: 700; }
.dot-pass { color: var(--green); }
.dot-fail { color: var(--red); }
.score-bar { display: inline-block; width: 60px; height: 8px; background: var(--border); border-radius: 4px; vertical-align: middle; overflow: hidden; }
.score-bar-inner { height: 100%; border-radius: 4px; }
.tab-group { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.tab { padding: 6px 14px; border-radius: var(--radius); border: 1px solid var(--border); background: var(--surface);
       color: var(--text-dim); cursor: pointer; font-size: .85rem; }
.tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.section { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
           padding: 16px; margin-bottom: 16px; }
.hidden { display: none; }
</style>
</head>
<body>
<div class="container">
<h1>🔬 Meta-Analysis Dashboard</h1>
<div class="subtitle" id="meta-subtitle"></div>

<!-- Summary Cards -->
<div class="cards" id="summary-cards"></div>

<!-- Tabs -->
<div class="tab-group" id="tabs"></div>

<!-- Tab Content: Overview -->
<div id="tab-overview" class="tab-content">
  <h2>Per-Tier Consistency</h2>
  <div class="section"><table><thead id="tier-hdr"></thead><tbody id="tier-body"></tbody></table></div>
  <h2>Failure Root Causes</h2>
  <div class="section" id="root-causes"></div>
</div>

<!-- Tab Content: Case Matrix -->
<div id="tab-matrix" class="tab-content hidden">
  <h2>Case-by-Run Matrix</h2>
  <div class="section"><table><thead id="matrix-hdr"></thead><tbody id="matrix-body"></tbody></table></div>
</div>

<!-- Tab Content: Score Stability -->
<div id="tab-scores" class="tab-content hidden">
  <h2>Score Stability Across Runs</h2>
  <div class="section"><table><thead id="score-hdr"></thead><tbody id="score-body"></tbody></table></div>
</div>

<!-- Tab Content: Over-Splitting -->
<div id="tab-split" class="tab-content hidden">
  <h2>Over-Splitting Analysis</h2>
  <p style="color:var(--text-dim);margin-bottom:12px;font-size:.9rem">Cases where reference = 1 commit but LLM consistently produces 3+ commits</p>
  <div class="section"><table><thead id="split-hdr"></thead><tbody id="split-body"></tbody></table></div>
</div>

</div>

<script>
/*__META_DATA__*/

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function pct(v) { return v == null ? 'n/a' : (v * 100).toFixed(1) + '%'; }
function scoreColor(v) { return v >= 0.8 ? 'var(--green)' : v >= 0.6 ? 'var(--yellow)' : 'var(--red)'; }
function scoreBar(v) {
  const c = scoreColor(v);
  return `<span style="color:${c};font-weight:600;margin-right:6px">${v.toFixed(3)}</span>` +
    `<span class="score-bar"><span class="score-bar-inner" style="width:${v*100}%;background:${c}"></span></span>`;
}
function badge(pass) { return pass ? '<span class="badge badge-pass">PASS</span>' : '<span class="badge badge-fail">FAIL</span>'; }
function catBadge(cat) {
  const map = {
    always_pass: ['PASS', 'badge-pass'],
    false_positive: ['FALSE POS', 'badge-fp'],
    ordering: ['ORDERING', 'badge-interm'],
    import_only: ['IMPORT', 'badge-fail'],
    import_and_test: ['IMPORT+TEST', 'badge-fail'],
    hunk_coverage: ['HUNK DROP', 'badge-fail'],
    other: ['OTHER', 'badge-interm'],
  };
  const [label, cls] = map[cat] || ['?', 'badge-interm'];
  return `<span class="badge ${cls}">${label}</span>`;
}

// Subtitle
const runDescs = DATA.runs.map(r => `<b>Run ${r.index}</b>: ${esc(r.run_id)} (${r.provider}/${r.model})`).join(' &nbsp;·&nbsp; ');
document.getElementById('meta-subtitle').innerHTML = `${DATA.n_runs} runs × ${DATA.summary.total} cases &nbsp;|&nbsp; ${runDescs}`;

// Summary cards
const s = DATA.summary;
document.getElementById('summary-cards').innerHTML = [
  { v: `${s.always_pass}/${s.total}`, l: 'Always Pass', c: 'var(--green)' },
  { v: `${s.consistent_fail}/${s.total}`, l: 'Consistent Fail', c: 'var(--red)' },
  { v: `${s.intermittent}/${s.total}`, l: 'Intermittent', c: 'var(--yellow)' },
  { v: `${s.false_positive}/${s.total}`, l: 'False Positive', c: 'var(--orange)' },
].map(c => `<div class="card"><div class="value" style="color:${c.c}">${c.v}</div><div class="label">${c.l}</div></div>`).join('');

// Tabs
const tabs = ['Overview', 'Case Matrix', 'Score Stability', 'Over-Splitting'];
const tabIds = ['tab-overview', 'tab-matrix', 'tab-scores', 'tab-split'];
document.getElementById('tabs').innerHTML = tabs.map((t, i) =>
  `<div class="tab${i===0?' active':''}" data-tab="${tabIds[i]}">${t}</div>`
).join('');
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.add('hidden'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.remove('hidden');
  });
});

// Per-Tier table
document.getElementById('tier-hdr').innerHTML = '<tr><th>Tier</th><th>Cases</th><th>Always Pass</th><th>Cons. Fail</th><th>Intermittent</th><th>Avg Score</th><th>Avg TPR</th></tr>';
document.getElementById('tier-body').innerHTML = DATA.tiers.map(t =>
  `<tr><td>T${t.tier}</td><td>${t.total}</td><td>${t.always_pass}/${t.total}</td>` +
  `<td>${t.consistent_fail}</td><td>${t.intermittent}</td>` +
  `<td>${scoreBar(t.avg_score)}</td><td>${pct(t.avg_tpr)}</td></tr>`
).join('');

// Root causes
const cats = {};
DATA.cases.filter(c => c.category !== 'always_pass' && c.category !== 'false_positive').forEach(c => {
  if (!cats[c.category]) cats[c.category] = [];
  cats[c.category].push(c);
});
const catLabels = {
  ordering: 'Incorrect Hunk Ordering',
  import_only: 'Import-Only Failures',
  import_and_test: 'Import + Test Failures',
  hunk_coverage: 'Hunk Coverage Drops',
  other: 'Other',
};
let rcHtml = '';
for (const [cat, label] of Object.entries(catLabels)) {
  if (!cats[cat]) continue;
  const items = cats[cat];
  const cons = items.filter(c => c.stability === 'consistent').length;
  const interm = items.filter(c => c.stability === 'intermittent').length;
  rcHtml += `<h3>${label} (${items.length} cases: ${cons} consistent, ${interm} intermittent)</h3>`;
  rcHtml += '<table><thead><tr><th>Case</th><th>Tier</th><th>Fails</th><th>Stability</th><th>Score</th><th>TPR</th></tr></thead><tbody>';
  items.forEach(c => {
    const stabBadge = c.stability === 'consistent' ? '<span class="badge badge-fail">CONSISTENT</span>' : '<span class="badge badge-interm">INTERMITTENT</span>';
    rcHtml += `<tr><td>${esc(c.case_id)}</td><td>T${c.tier}</td><td>${c.fail_count}/${DATA.n_runs}</td>` +
      `<td>${stabBadge}</td><td>${scoreBar(c.avg_score)}</td><td>${pct(c.avg_tpr)}</td></tr>`;
  });
  rcHtml += '</tbody></table>';
}
if (DATA.cases.some(c => c.category === 'false_positive')) {
  rcHtml += '<h3 style="color:var(--orange)">False Positives</h3>';
  DATA.cases.filter(c => c.category === 'false_positive').forEach(c => {
    rcHtml += `<p style="margin:4px 0 4px 12px;font-size:.9rem"><span class="badge badge-fp">FALSE POSITIVE</span> ${esc(c.case_id)} — tests fail at final commit in all runs</p>`;
  });
}
if (!rcHtml) rcHtml = '<p style="color:var(--green)">No failures detected.</p>';
document.getElementById('root-causes').innerHTML = rcHtml;

// Case Matrix
const runHdrs = DATA.runs.map(r => `<th>R${r.index}</th>`).join('');
document.getElementById('matrix-hdr').innerHTML = `<tr><th>Case</th><th>Tier</th>${runHdrs}<th>Avg Score</th><th>TPR</th><th>Category</th></tr>`;
document.getElementById('matrix-body').innerHTML = DATA.cases.map(c => {
  const dots = c.mech_pass_per_run.map(p =>
    `<td><span class="dot ${p ? 'dot-pass' : 'dot-fail'}">${p ? '✓' : '✗'}</span></td>`
  ).join('');
  return `<tr><td>${esc(c.case_id)}</td><td>T${c.tier}</td>${dots}` +
    `<td>${scoreBar(c.avg_score)}</td><td>${pct(c.avg_tpr)}</td><td>${catBadge(c.category)}</td></tr>`;
}).join('');

// Score Stability
const scoreHdrs = DATA.runs.map(r => `<th>R${r.index} Score</th>`).join('');
document.getElementById('score-hdr').innerHTML = `<tr><th>Case</th><th>Tier</th>${scoreHdrs}<th>Range</th><th>Std Dev</th></tr>`;
document.getElementById('score-body').innerHTML = DATA.cases.map(c => {
  const scoreCells = c.scores.map(s => `<td style="color:${scoreColor(s)}">${s.toFixed(3)}</td>`).join('');
  const range = (Math.max(...c.scores) - Math.min(...c.scores)).toFixed(3);
  const mean = c.scores.reduce((a,b) => a+b, 0) / c.scores.length;
  const std = Math.sqrt(c.scores.reduce((a,s) => a + (s-mean)**2, 0) / c.scores.length).toFixed(3);
  return `<tr><td>${esc(c.case_id)}</td><td>T${c.tier}</td>${scoreCells}<td>${range}</td><td>${std}</td></tr>`;
}).join('');

// Over-Splitting
const overSplit = DATA.cases.filter(c => c.ref_commits === 1 && c.agent_counts.every(a => a >= 3));
document.getElementById('split-hdr').innerHTML = '<tr><th>Case</th><th>Tier</th><th>Agent Commits</th><th>Result</th><th>TPR</th></tr>';
document.getElementById('split-body').innerHTML = overSplit.map(c => {
  const ac = c.agent_counts.join('/');
  const result = c.category === 'always_pass'
    ? '<span class="badge badge-pass">PASS</span>'
    : `<span class="badge badge-fail">FAIL (${c.fail_count}/${DATA.n_runs})</span>`;
  return `<tr><td>${esc(c.case_id)}</td><td>T${c.tier}</td><td>[${ac}]</td><td>${result}</td><td>${pct(c.avg_tpr)}</td></tr>`;
}).join('');
</script>
</body>
</html>"""


