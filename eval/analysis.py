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
            lines.append(f"       {DIM}commits:{RST} {' '.join(dots)}  {DIM}final-state:{RST} {fs}")

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


