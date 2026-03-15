"""Cross-group meta-analysis — compare evaluation runs across different configurations.

Given two or more ``meta_analysis.json`` files (each produced by
``eval/cli.py analyze`` with multiple result paths), this script compares
the groups to determine which configuration (model, provider, agent mode,
etc.) performs better.

Typical use-case: comparing Gemini-2.5-Flash vs Claude Sonnet vs GPT-4o
on the same evaluation suite.

Usage:
    # Compare two model groups
    python eval/meta_analysis.py \\
        eval_results/gemini_runs/meta_analysis.json \\
        eval_results/claude_runs/meta_analysis.json

    # With web dashboard
    python eval/meta_analysis.py --web \\
        eval_results/gemini_runs/meta_analysis.json \\
        eval_results/claude_runs/meta_analysis.json

    # Custom output directory
    python eval/meta_analysis.py --output-dir eval_results/comparison/ \\
        eval_results/group_a/meta_analysis.json \\
        eval_results/group_b/meta_analysis.json \\
        eval_results/group_c/meta_analysis.json

Also invocable via:
    python eval/cli.py compare-groups \\
        eval_results/group_a/meta_analysis.json \\
        eval_results/group_b/meta_analysis.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data loading ─────────────────────────────────────────────────────────────


def load_meta(path: Path) -> dict:
    """Load a meta_analysis.json file and return the parsed dict."""
    with open(path) as f:
        data = json.load(f)
    if data.get("meta_analysis_version") != 1:
        logger.warning("Unknown meta_analysis_version in %s", path)
    return data


def _group_label(meta: dict) -> str:
    """Derive a human-readable label for a group from its runs metadata."""
    runs = meta.get("runs", [])
    if not runs:
        return "unknown"
    providers = set(r.get("provider", "?") for r in runs)
    models = set(r.get("model", "?") for r in runs)
    if len(models) == 1:
        model = next(iter(models))
        provider = next(iter(providers))
        return f"{provider}/{model}"
    return " + ".join(sorted(models))


# ── Comparison logic ─────────────────────────────────────────────────────────


def compare_groups(metas: list[dict], labels: Optional[list[str]] = None) -> dict:
    """Compare two or more meta-analysis groups.

    Returns a structured comparison dict with:
    - group_summaries: high-level stats per group
    - head_to_head: per-case comparison across groups
    - rankings: which group wins on each metric
    - by_tier: per-tier comparison
    - by_repo: per-repo comparison
    - case_deltas: per-case score/pass deltas between groups
    """
    n_groups = len(metas)
    if labels is None:
        labels = [_group_label(m) for m in metas]
    # Disambiguate duplicate labels
    seen: dict[str, int] = {}
    for i, lbl in enumerate(labels):
        if lbl in seen:
            seen[lbl] += 1
            labels[i] = f"{lbl} ({seen[lbl]})"
        else:
            seen[lbl] = 1

    # ── Group summaries ──
    group_summaries = []
    for i, (meta, label) in enumerate(zip(metas, labels)):
        s = meta["summary"]
        runs = meta.get("runs", [])
        total_tokens = sum(r.get("total_tokens", 0) for r in runs)
        total_duration = sum(r.get("total_duration_s", 0) for r in runs)
        group_summaries.append({
            "index": i,
            "label": label,
            "n_runs": meta["n_runs"],
            "total_cases": s["total_cases"],
            "always_pass": s["always_pass"],
            "always_pass_rate": s["always_pass_rate"],
            "consistent_fail": s["consistent_fail"],
            "intermittent": s["intermittent"],
            "false_positive": s["false_positive"],
            "avg_score": s["avg_score"],
            "avg_tpr": s["avg_tpr"],
            "avg_mechanical_pass_rate": s["avg_mechanical_pass_rate"],
            "total_tokens": total_tokens,
            "total_duration_s": round(total_duration, 1),
        })

    # ── Head-to-head per-case comparison ──
    # Build case lookup per group
    case_maps: list[dict[str, dict]] = []
    for meta in metas:
        cm: dict[str, dict] = {}
        for c in meta.get("cases", []):
            cm[c["case_id"]] = c
        case_maps.append(cm)

    # All unique case IDs
    all_case_ids = sorted(set(
        cid for cm in case_maps for cid in cm.keys()
    ))

    head_to_head = []
    for cid in all_case_ids:
        entry: dict = {"case_id": cid}
        per_group = []
        for i, cm in enumerate(case_maps):
            c = cm.get(cid)
            if c is None:
                per_group.append({
                    "group_index": i,
                    "present": False,
                })
            else:
                per_group.append({
                    "group_index": i,
                    "present": True,
                    "tier": c["tier"],
                    "avg_score": c["avg_score"],
                    "avg_tpr": c["avg_tpr"],
                    "category": c["category"],
                    "stability": c["stability"],
                    "fail_count": c["fail_count"],
                    "pass_count": c["pass_count"],
                    "mech_pass_per_run": c["mech_pass_per_run"],
                    "has_hunk_miss": c["has_hunk_miss"],
                    "has_import_fail": c["has_import_fail"],
                    "has_test_fail": c["has_test_fail"],
                })
        entry["groups"] = per_group

        # Determine winner (highest avg_score among present groups)
        present = [g for g in per_group if g.get("present")]
        if len(present) >= 2:
            best_score = max(g["avg_score"] for g in present)
            worst_score = min(g["avg_score"] for g in present)
            entry["score_delta"] = round(best_score - worst_score, 4)
            entry["best_group"] = next(g["group_index"] for g in present if g["avg_score"] == best_score)
            # Mechanical winner: most passes
            pass_rates = [(g["group_index"], g["pass_count"] / (g["pass_count"] + g["fail_count"]) if (g["pass_count"] + g["fail_count"]) > 0 else 0) for g in present]
            best_mech = max(pass_rates, key=lambda x: x[1])
            entry["best_mechanical_group"] = best_mech[0]
        else:
            entry["score_delta"] = 0
            entry["best_group"] = present[0]["group_index"] if present else None
            entry["best_mechanical_group"] = present[0]["group_index"] if present else None

        head_to_head.append(entry)

    # ── Per-tier comparison ──
    by_tier: dict[int, dict] = {}
    for meta_i, meta in enumerate(metas):
        for td in meta.get("by_tier", []):
            t = td["tier"]
            if t not in by_tier:
                by_tier[t] = {"tier": t, "groups": []}
            by_tier[t]["groups"].append({
                "group_index": meta_i,
                "label": labels[meta_i],
                "total": td["total"],
                "always_pass": td["always_pass"],
                "consistent_fail": td["consistent_fail"],
                "intermittent": td["intermittent"],
                "avg_score": td["avg_score"],
                "avg_tpr": td["avg_tpr"],
            })
    tier_comparison = [by_tier[t] for t in sorted(by_tier.keys())]

    # ── Per-repo comparison ──
    by_repo: dict[str, dict] = {}
    for meta_i, meta in enumerate(metas):
        for rd in meta.get("by_repo", []):
            repo = rd["repo"]
            if repo not in by_repo:
                by_repo[repo] = {"repo": repo, "groups": []}
            by_repo[repo]["groups"].append({
                "group_index": meta_i,
                "label": labels[meta_i],
                "total": rd["total"],
                "always_pass": rd["always_pass"],
                "avg_score": rd["avg_score"],
            })
    repo_comparison = [by_repo[r] for r in sorted(by_repo.keys())]

    # ── Rankings ──
    metrics = [
        ("avg_score", "higher"),
        ("avg_tpr", "higher"),
        ("always_pass_rate", "higher"),
        ("avg_mechanical_pass_rate", "higher"),
        ("consistent_fail", "lower"),
        ("false_positive", "lower"),
        ("total_tokens", "lower"),
        ("total_duration_s", "lower"),
    ]
    rankings = []
    for metric, direction in metrics:
        values = [(gs["label"], gs.get(metric, 0)) for gs in group_summaries]
        if direction == "higher":
            ranked = sorted(values, key=lambda x: x[1], reverse=True)
        else:
            ranked = sorted(values, key=lambda x: x[1])
        rankings.append({
            "metric": metric,
            "direction": direction,
            "ranking": [{"label": lbl, "value": round(v, 4) if isinstance(v, float) else v} for lbl, v in ranked],
            "winner": ranked[0][0],
        })

    # ── Case deltas (which cases changed category between groups) ──
    case_deltas = []
    if n_groups == 2:
        for entry in head_to_head:
            g0 = next((g for g in entry["groups"] if g["group_index"] == 0 and g.get("present")), None)
            g1 = next((g for g in entry["groups"] if g["group_index"] == 1 and g.get("present")), None)
            if g0 and g1 and g0["category"] != g1["category"]:
                case_deltas.append({
                    "case_id": entry["case_id"],
                    "group_0_category": g0["category"],
                    "group_1_category": g1["category"],
                    "group_0_score": g0["avg_score"],
                    "group_1_score": g1["avg_score"],
                    "score_delta": round(g1["avg_score"] - g0["avg_score"], 4),
                })

    return {
        "comparison_version": 1,
        "n_groups": n_groups,
        "labels": labels,
        "group_summaries": group_summaries,
        "rankings": rankings,
        "head_to_head": head_to_head,
        "by_tier": tier_comparison,
        "by_repo": repo_comparison,
        "case_deltas": case_deltas,
    }


# ── Report generators ────────────────────────────────────────────────────────


def generate_comparison_report(comparison: dict) -> str:
    """Generate a Markdown comparison report from the comparison dict."""
    lines: list[str] = []
    labels = comparison["labels"]
    n_groups = comparison["n_groups"]

    lines.append("# Cross-Group Comparison Report")
    lines.append("")
    lines.append(f"**Groups compared**: {n_groups}")
    for i, gs in enumerate(comparison["group_summaries"]):
        lines.append(f"  - **{gs['label']}**: {gs['n_runs']} runs, {gs['total_cases']} cases")
    lines.append("")

    # ── Group summary table ──
    lines.append("## Group Summary")
    lines.append("")
    hdr = "| Metric | " + " | ".join(labels) + " |"
    sep = "|--------|" + "|".join("--------|" for _ in labels)
    lines.append(hdr)
    lines.append(sep)

    display_metrics = [
        ("Runs", "n_runs", "d"),
        ("Avg Score", "avg_score", ".4f"),
        ("Avg TPR", "avg_tpr", ".4f"),
        ("Always Pass Rate", "always_pass_rate", ".1%"),
        ("Mech Pass Rate", "avg_mechanical_pass_rate", ".1%"),
        ("Always Pass", "always_pass", "d"),
        ("Consistent Fail", "consistent_fail", "d"),
        ("Intermittent", "intermittent", "d"),
        ("False Positive", "false_positive", "d"),
        ("Total Tokens", "total_tokens", ",d"),
        ("Total Duration (s)", "total_duration_s", ".1f"),
    ]
    for label_m, key, fmt in display_metrics:
        vals = [gs.get(key, 0) for gs in comparison["group_summaries"]]
        cells = " | ".join(f"{v:{fmt}}" for v in vals)
        lines.append(f"| {label_m} | {cells} |")
    lines.append("")

    # ── Rankings ──
    lines.append("## Rankings")
    lines.append("")
    lines.append("| Metric | Direction | Winner | " + " | ".join(f"#{i+1}" for i in range(n_groups)) + " |")
    lines.append("|--------|-----------|--------|" + "|".join("------|" for _ in range(n_groups)))
    for r in comparison["rankings"]:
        rank_cells = " | ".join(f"{rv['label']} ({rv['value']})" for rv in r["ranking"])
        lines.append(f"| {r['metric']} | {r['direction']} | **{r['winner']}** | {rank_cells} |")
    lines.append("")

    # ── Per-tier comparison ──
    lines.append("## Per-Tier Comparison")
    lines.append("")
    for td in comparison["by_tier"]:
        lines.append(f"### Tier {td['tier']}")
        lines.append("")
        lines.append("| Group | Cases | Always Pass | Cons. Fail | Interm. | Avg Score | Avg TPR |")
        lines.append("|-------|-------|-------------|------------|---------|-----------|---------|")
        for g in td["groups"]:
            lines.append(
                f"| {g['label']} | {g['total']} | {g['always_pass']}/{g['total']} "
                f"| {g['consistent_fail']} | {g['intermittent']} "
                f"| {g['avg_score']:.4f} | {g['avg_tpr']:.4f} |"
            )
        lines.append("")

    # ── Per-repo comparison ──
    lines.append("## Per-Repo Comparison")
    lines.append("")
    for rd in comparison["by_repo"]:
        lines.append(f"### {rd['repo']}")
        lines.append("")
        lines.append("| Group | Cases | Always Pass | Avg Score |")
        lines.append("|-------|-------|-------------|-----------|")
        for g in rd["groups"]:
            lines.append(
                f"| {g['label']} | {g['total']} | {g['always_pass']}/{g['total']} "
                f"| {g['avg_score']:.4f} |"
            )
        lines.append("")

    # ── Head-to-head per-case ──
    lines.append("## Head-to-Head Per-Case")
    lines.append("")
    group_hdrs = " | ".join(f"{lbl} Score" for lbl in labels)
    group_cat_hdrs = " | ".join(f"{lbl} Cat" for lbl in labels)
    lines.append(f"| Case | Tier | {group_hdrs} | {group_cat_hdrs} | Winner |")
    lines.append(f"|------|------|{'|'.join('-------|' for _ in labels)} {'|'.join('-------|' for _ in labels)} --------|")
    for entry in comparison["head_to_head"]:
        groups = entry["groups"]
        scores = []
        cats = []
        for g in groups:
            if g.get("present"):
                scores.append(f"{g['avg_score']:.4f}")
                cats.append(g["category"])
            else:
                scores.append("—")
                cats.append("—")
        winner_idx = entry.get("best_group")
        winner = labels[winner_idx] if winner_idx is not None else "—"
        tier = next((g.get("tier", "?") for g in groups if g.get("present")), "?")
        lines.append(
            f"| `{entry['case_id']}` | T{tier} "
            f"| {' | '.join(scores)} | {' | '.join(cats)} | {winner} |"
        )
    lines.append("")

    # ── Case category deltas (2-group only) ──
    if comparison["case_deltas"]:
        lines.append("## Category Changes Between Groups")
        lines.append("")
        lines.append("Cases that changed failure category between the two groups:")
        lines.append("")
        lines.append(f"| Case | {labels[0]} | {labels[1]} | Score Δ |")
        lines.append("|------|--------|--------|---------|")
        for d in comparison["case_deltas"]:
            direction = "↑" if d["score_delta"] > 0 else "↓" if d["score_delta"] < 0 else "="
            lines.append(
                f"| `{d['case_id']}` | {d['group_0_category']} | {d['group_1_category']} "
                f"| {direction} {d['score_delta']:+.4f} |"
            )
        lines.append("")

    return "\n".join(lines)


def generate_comparison_terminal_report(comparison: dict) -> str:
    """Generate an ANSI-colored terminal report for cross-group comparison."""
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RST = "\033[0m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"

    labels = comparison["labels"]
    n_groups = comparison["n_groups"]

    def score_c(v: float) -> str:
        c = GREEN if v >= 0.8 else (YELLOW if v >= 0.6 else RED)
        return f"{c}{v:.4f}{RST}"

    def pct_c(v: float) -> str:
        c = GREEN if v >= 0.8 else (YELLOW if v >= 0.5 else RED)
        return f"{c}{v*100:.1f}%{RST}"

    lines: list[str] = []

    # Header
    lines.append("")
    lines.append(f"{BOLD}{'═' * 80}{RST}")
    lines.append(f"{BOLD}  ⚖  Cross-Group Comparison — {n_groups} Groups{RST}")
    lines.append(f"{BOLD}{'═' * 80}{RST}")
    for gs in comparison["group_summaries"]:
        lines.append(f"  {DIM}Group:{RST} {BOLD}{gs['label']}{RST} ({gs['n_runs']} runs, {gs['total_cases']} cases)")
    lines.append("")

    # Summary table
    lines.append(f"  {BOLD}Group Summary{RST}")
    lines.append(f"  {DIM}{'─' * 76}{RST}")
    # Dynamic column widths
    max_lbl = max(len(l) for l in labels)
    col = max(max_lbl + 2, 18)
    hdr = f"  {'Metric':<22}" + "".join(f"{lbl:>{col}}" for lbl in labels)
    lines.append(f"{DIM}{hdr}{RST}")
    lines.append(f"  {DIM}{'─' * 76}{RST}")

    rows = [
        ("Avg Score", "avg_score", score_c),
        ("Always Pass Rate", "always_pass_rate", pct_c),
        ("Mech Pass Rate", "avg_mechanical_pass_rate", pct_c),
        ("Avg TPR", "avg_tpr", lambda v: score_c(v)),
        ("Always Pass", "always_pass", lambda v: f"{int(v):>5}"),
        ("Consistent Fail", "consistent_fail", lambda v: f"{RED}{int(v):>5}{RST}" if v > 0 else f"{GREEN}{int(v):>5}{RST}"),
        ("Intermittent", "intermittent", lambda v: f"{YELLOW}{int(v):>5}{RST}" if v > 0 else f"{int(v):>5}"),
        ("False Positive", "false_positive", lambda v: f"{RED}{int(v):>5}{RST}" if v > 0 else f"{GREEN}{int(v):>5}{RST}"),
    ]
    for label_m, key, fmt_fn in rows:
        cells = ""
        vals = [gs.get(key, 0) for gs in comparison["group_summaries"]]
        for v in vals:
            cell = fmt_fn(v)
            # Need to account for ANSI codes when right-justifying
            raw_len = len(str(v)[:col])
            pad = col - raw_len
            cells += " " * max(0, pad) + cell
        lines.append(f"  {label_m:<22}{cells}")
    lines.append(f"  {DIM}{'─' * 76}{RST}")
    lines.append("")

    # Rankings
    lines.append(f"  {BOLD}Rankings{RST} {DIM}(🏆 = best){RST}")
    lines.append(f"  {DIM}{'─' * 76}{RST}")
    for r in comparison["rankings"]:
        winner = r["winner"]
        ranked_str = " > ".join(f"{rv['label']}" for rv in r["ranking"])
        lines.append(f"  {CYAN}{r['metric']:<28}{RST} 🏆 {GREEN}{winner}{RST}  {DIM}({ranked_str}){RST}")
    lines.append(f"  {DIM}{'─' * 76}{RST}")
    lines.append("")

    # Per-tier comparison (compact)
    lines.append(f"  {BOLD}Per-Tier Comparison{RST}")
    lines.append(f"  {DIM}{'─' * 76}{RST}")
    for td in comparison["by_tier"]:
        tier_label = f"  Tier {td['tier']}:"
        parts = []
        for g in td["groups"]:
            ap_rate = g["always_pass"] / g["total"] if g["total"] else 0
            parts.append(f"{g['label']} {score_c(g['avg_score'])} (pass {pct_c(ap_rate)})")
        lines.append(f"{tier_label:<12} {' │ '.join(parts)}")
    lines.append(f"  {DIM}{'─' * 76}{RST}")
    lines.append("")

    # Case category changes (2-group only)
    if comparison["case_deltas"]:
        lines.append(f"  {BOLD}Category Changes{RST}")
        lines.append(f"  {DIM}{'─' * 76}{RST}")
        improved = [d for d in comparison["case_deltas"] if d["score_delta"] > 0]
        regressed = [d for d in comparison["case_deltas"] if d["score_delta"] < 0]
        unchanged = [d for d in comparison["case_deltas"] if d["score_delta"] == 0]
        if improved:
            lines.append(f"  {GREEN}Improved ({labels[0]} → {labels[1]}): {len(improved)} cases{RST}")
            for d in improved:
                lines.append(f"    {GREEN}↑{RST} {d['case_id']}: {d['group_0_category']} → {d['group_1_category']} ({d['score_delta']:+.4f})")
        if regressed:
            lines.append(f"  {RED}Regressed ({labels[0]} → {labels[1]}): {len(regressed)} cases{RST}")
            for d in regressed:
                lines.append(f"    {RED}↓{RST} {d['case_id']}: {d['group_0_category']} → {d['group_1_category']} ({d['score_delta']:+.4f})")
        if unchanged:
            lines.append(f"  {DIM}Changed category (same score): {len(unchanged)} cases{RST}")
        lines.append(f"  {DIM}{'─' * 76}{RST}")
        lines.append("")

    # Overall winner
    lines.append(f"  {BOLD}Overall Winner{RST}")
    lines.append(f"  {DIM}{'─' * 76}{RST}")
    # Count how many ranking metrics each group wins
    win_counts: dict[str, int] = {}
    for r in comparison["rankings"]:
        w = r["winner"]
        win_counts[w] = win_counts.get(w, 0) + 1
    if win_counts:
        top_winner = max(win_counts, key=lambda k: win_counts[k])
        lines.append(f"  🏆 {BOLD}{GREEN}{top_winner}{RST} wins {win_counts[top_winner]}/{len(comparison['rankings'])} metrics")
        for lbl, cnt in sorted(win_counts.items(), key=lambda x: -x[1]):
            bar = "█" * cnt + "░" * (len(comparison["rankings"]) - cnt)
            lines.append(f"     {lbl:<20} {bar}  {cnt}/{len(comparison['rankings'])}")
    lines.append("")
    lines.append(f"{BOLD}{'═' * 80}{RST}")
    lines.append("")
    return "\n".join(lines)


def generate_comparison_html(comparison: dict) -> str:
    """Generate a single-page HTML dashboard for cross-group comparison."""
    data_json = json.dumps(comparison)
    return _COMPARISON_HTML_TEMPLATE.replace("/*__COMPARISON_DATA__*/", f"const DATA = {data_json};")


# ── Orchestrator ─────────────────────────────────────────────────────────────


def run_comparison(
    meta_paths: list[Path],
    web: bool = False,
    output_dir: Optional[Path] = None,
    labels: Optional[list[str]] = None,
) -> tuple[Path, str]:
    """Run cross-group comparison and write output files.

    Args:
        meta_paths: Paths to ``meta_analysis.json`` files.
        web: Whether to generate an HTML dashboard.
        output_dir: Where to write reports. Defaults to the directory
            of the most recent (last) meta_analysis.json.
        labels: Optional labels for each group. Auto-derived if omitted.

    Returns:
        Tuple of (path to Markdown report, terminal report string).
    """
    metas = [load_meta(p) for p in meta_paths]

    if output_dir is None:
        candidates = [p.parent for p in meta_paths]
        out_dir = max(candidates, key=lambda d: d.name)
    else:
        out_dir = output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    comparison = compare_groups(metas, labels=labels)

    # JSON
    json_path = out_dir / "group_comparison.json"
    with open(json_path, "w") as f:
        json.dump(comparison, f, indent=2)
    logger.info("Comparison JSON saved to %s", json_path)

    # Markdown
    md_report = generate_comparison_report(comparison)
    md_path = out_dir / "group_comparison.md"
    md_path.write_text(md_report)
    logger.info("Comparison report saved to %s", md_path)

    # HTML
    if web:
        html_report = generate_comparison_html(comparison)
        html_path = out_dir / "group_comparison.html"
        html_path.write_text(html_report)
        logger.info("Comparison dashboard saved to %s", html_path)

    # Terminal
    terminal_report = generate_comparison_terminal_report(comparison)

    return md_path, terminal_report


# ── HTML template ────────────────────────────────────────────────────────────

_COMPARISON_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Cross-Group Comparison</title>
<style>
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d29922; --orange: #db6d28;
  --radius: 8px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Noto Sans,Helvetica,Arial,sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.5; padding: 24px; }
.container { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin-bottom: 4px; }
h2 { font-size: 1.2rem; margin: 24px 0 12px; color: var(--accent); }
.subtitle { color: var(--text-dim); font-size: .9rem; margin-bottom: 20px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
.card h3 { font-size: 1rem; margin-bottom: 8px; }
.card .stat { font-size: 1.8rem; font-weight: 700; }
.card .label { font-size: .8rem; color: var(--text-dim); }
table { width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: .85rem; }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--surface); color: var(--text-dim); font-weight: 600; position: sticky; top: 0; z-index: 1; }
tr:hover { background: rgba(88,166,255,.06); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: .75rem; font-weight: 600; }
.badge-win { background: rgba(63,185,80,.15); color: var(--green); }
.badge-lose { background: rgba(248,81,73,.15); color: var(--red); }
.section { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; margin-bottom: 16px; }
.bar-container { display: flex; gap: 4px; align-items: center; }
.bar { height: 20px; border-radius: 3px; display: flex; align-items: center; justify-content: center; font-size: .7rem; font-weight: 600; color: #fff; }
.score-bar { display: inline-block; width: 60px; height: 8px; background: var(--border); border-radius: 4px; vertical-align: middle; overflow: hidden; }
.score-bar-inner { height: 100%; border-radius: 4px; }
</style>
</head>
<body>
<div class="container">
<h1>⚖ Cross-Group Comparison Dashboard</h1>
<div class="subtitle" id="subtitle"></div>

<div class="cards" id="group-cards"></div>

<h2>Rankings</h2>
<div class="section"><table><thead id="rank-hdr"></thead><tbody id="rank-body"></tbody></table></div>

<h2>Per-Tier Comparison</h2>
<div class="section" id="tier-section"></div>

<h2>Head-to-Head Per-Case</h2>
<div class="section"><table><thead id="h2h-hdr"></thead><tbody id="h2h-body"></tbody></table></div>

<div id="deltas-section"></div>
</div>

<script>
/*__COMPARISON_DATA__*/

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function scoreColor(v) { return v >= 0.8 ? 'var(--green)' : v >= 0.6 ? 'var(--yellow)' : 'var(--red)'; }
function scoreBar(v) {
  const c = scoreColor(v);
  return `<span style="color:${c};font-weight:600;margin-right:6px">${v.toFixed(4)}</span>` +
    `<span class="score-bar"><span class="score-bar-inner" style="width:${v*100}%;background:${c}"></span></span>`;
}
function pct(v) { return v == null ? 'n/a' : (v * 100).toFixed(1) + '%'; }

// Subtitle
document.getElementById('subtitle').innerHTML =
  `Comparing ${DATA.n_groups} groups: ` + DATA.labels.map(l => `<b>${esc(l)}</b>`).join(' vs ');

// Group cards
document.getElementById('group-cards').innerHTML = DATA.group_summaries.map(gs => `
  <div class="card">
    <h3>${esc(gs.label)}</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">
      <div><div class="stat" style="color:${scoreColor(gs.avg_score)}">${gs.avg_score.toFixed(4)}</div><div class="label">Avg Score</div></div>
      <div><div class="stat" style="color:${scoreColor(gs.avg_mechanical_pass_rate)}">${pct(gs.avg_mechanical_pass_rate)}</div><div class="label">Mech Pass Rate</div></div>
      <div><div class="stat">${gs.always_pass}/${gs.total_cases}</div><div class="label">Always Pass</div></div>
      <div><div class="stat" style="color:var(--red)">${gs.consistent_fail}</div><div class="label">Consistent Fail</div></div>
    </div>
  </div>
`).join('');

// Rankings
document.getElementById('rank-hdr').innerHTML = '<tr><th>Metric</th><th>Direction</th><th>Winner</th>' +
  DATA.labels.map((l,i) => `<th>#${i+1}</th>`).join('') + '</tr>';
document.getElementById('rank-body').innerHTML = DATA.rankings.map(r => {
  const cells = r.ranking.map(rv =>
    `<td>${rv.label === r.winner ? '<span class="badge badge-win">🏆 ' : ''}${esc(rv.label)} (${typeof rv.value === 'number' && rv.value < 10 ? rv.value.toFixed(4) : rv.value})${rv.label === r.winner ? '</span>' : ''}</td>`
  ).join('');
  return `<tr><td>${esc(r.metric)}</td><td>${r.direction}</td><td><b>${esc(r.winner)}</b></td>${cells}</tr>`;
}).join('');

// Per-tier
let tierHtml = '';
DATA.by_tier.forEach(td => {
  tierHtml += `<h3 style="margin:12px 0 6px">Tier ${td.tier}</h3>`;
  tierHtml += '<table><thead><tr><th>Group</th><th>Cases</th><th>Always Pass</th><th>Cons. Fail</th><th>Avg Score</th><th>Avg TPR</th></tr></thead><tbody>';
  td.groups.forEach(g => {
    tierHtml += `<tr><td>${esc(g.label)}</td><td>${g.total}</td><td>${g.always_pass}/${g.total}</td>` +
      `<td>${g.consistent_fail}</td><td>${scoreBar(g.avg_score)}</td><td>${pct(g.avg_tpr)}</td></tr>`;
  });
  tierHtml += '</tbody></table>';
});
document.getElementById('tier-section').innerHTML = tierHtml;

// Head-to-head
const h2hScoreHdrs = DATA.labels.map(l => `<th>${esc(l)} Score</th>`).join('');
const h2hCatHdrs = DATA.labels.map(l => `<th>${esc(l)} Cat</th>`).join('');
document.getElementById('h2h-hdr').innerHTML = `<tr><th>Case</th><th>Tier</th>${h2hScoreHdrs}${h2hCatHdrs}<th>Winner</th></tr>`;
document.getElementById('h2h-body').innerHTML = DATA.head_to_head.map(e => {
  const scoreCells = e.groups.map(g =>
    g.present ? `<td>${scoreBar(g.avg_score)}</td>` : '<td>—</td>'
  ).join('');
  const catCells = e.groups.map(g =>
    g.present ? `<td>${g.category}</td>` : '<td>—</td>'
  ).join('');
  const tier = e.groups.find(g => g.present)?.tier || '?';
  const winner = e.best_group != null ? DATA.labels[e.best_group] : '—';
  return `<tr><td>${esc(e.case_id)}</td><td>T${tier}</td>${scoreCells}${catCells}<td>${esc(winner)}</td></tr>`;
}).join('');

// Category deltas
if (DATA.case_deltas && DATA.case_deltas.length > 0) {
  let dHtml = `<h2>Category Changes</h2><div class="section">`;
  dHtml += `<table><thead><tr><th>Case</th><th>${esc(DATA.labels[0])}</th><th>${esc(DATA.labels[1])}</th><th>Score Δ</th></tr></thead><tbody>`;
  DATA.case_deltas.forEach(d => {
    const arrow = d.score_delta > 0 ? '↑' : d.score_delta < 0 ? '↓' : '=';
    const color = d.score_delta > 0 ? 'var(--green)' : d.score_delta < 0 ? 'var(--red)' : 'var(--text-dim)';
    dHtml += `<tr><td>${esc(d.case_id)}</td><td>${d.group_0_category}</td><td>${d.group_1_category}</td>` +
      `<td style="color:${color}">${arrow} ${d.score_delta.toFixed(4)}</td></tr>`;
  });
  dHtml += '</tbody></table></div>';
  document.getElementById('deltas-section').innerHTML = dHtml;
}
</script>
</body>
</html>"""


# ── CLI entry point ──────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point for cross-group comparison."""
    parser = argparse.ArgumentParser(
        description="Compare evaluation runs across different configurations",
        epilog="Example: python eval/meta_analysis.py group_a/meta_analysis.json group_b/meta_analysis.json",
    )
    parser.add_argument(
        "meta_files",
        nargs="+",
        help="Paths to meta_analysis.json files (one per group)",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Generate interactive HTML dashboard",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: directory of most recent input file)",
    )
    parser.add_argument(
        "--labels",
        nargs="*",
        default=None,
        help="Custom labels for each group (one per meta_analysis.json)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    paths = [Path(f) for f in args.meta_files]
    for p in paths:
        if not p.exists():
            print(f"File not found: {p}", file=sys.stderr)
            sys.exit(1)

    if len(paths) < 2:
        print("Error: At least 2 meta_analysis.json files are required.", file=sys.stderr)
        sys.exit(1)

    if args.labels and len(args.labels) != len(paths):
        print(f"Error: --labels must have {len(paths)} entries, got {len(args.labels)}.", file=sys.stderr)
        sys.exit(1)

    out = Path(args.output_dir) if args.output_dir else None
    md_path, terminal_report = run_comparison(paths, web=args.web, output_dir=out, labels=args.labels)

    print(terminal_report)
    print(f"Comparison report: {md_path}")
    if args.web:
        print(f"Comparison dashboard: {md_path.parent / 'group_comparison.html'}")


if __name__ == "__main__":
    main()

