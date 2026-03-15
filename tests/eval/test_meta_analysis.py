"""Tests for eval.meta_analysis — cross-group comparison."""

import json
from pathlib import Path

import pytest

from eval.meta_analysis import (
    compare_groups,
    generate_comparison_html,
    generate_comparison_report,
    generate_comparison_terminal_report,
    load_meta,
    run_comparison,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def group_a() -> dict:
    """A meta_analysis.json dict representing group A (e.g., Gemini)."""
    return {
        "meta_analysis_version": 1,
        "n_runs": 2,
        "runs": [
            {"index": 1, "run_id": "run_a1", "timestamp": "2026-03-15_10-00-00",
             "provider": "google", "model": "gemini-2.5-flash", "suite": "full",
             "use_agent": False, "total_cases": 3, "avg_score": 0.80,
             "mechanical_pass_rate": 0.67, "total_duration_s": 100.0, "total_tokens": 5000},
            {"index": 2, "run_id": "run_a2", "timestamp": "2026-03-15_11-00-00",
             "provider": "google", "model": "gemini-2.5-flash", "suite": "full",
             "use_agent": False, "total_cases": 3, "avg_score": 0.82,
             "mechanical_pass_rate": 0.67, "total_duration_s": 110.0, "total_tokens": 5200},
        ],
        "summary": {
            "total_cases": 3,
            "always_pass": 2,
            "always_pass_rate": 0.6667,
            "false_positive": 0,
            "consistent_fail": 1,
            "intermittent": 0,
            "avg_score": 0.81,
            "avg_tpr": 0.90,
            "avg_mechanical_pass_rate": 0.67,
        },
        "by_tier": [
            {"tier": 1, "total": 2, "always_pass": 2, "consistent_fail": 0,
             "intermittent": 0, "false_positive": 0, "avg_score": 0.85, "avg_tpr": 1.0},
            {"tier": 2, "total": 1, "always_pass": 0, "consistent_fail": 1,
             "intermittent": 0, "false_positive": 0, "avg_score": 0.73, "avg_tpr": 0.70},
        ],
        "by_repo": [
            {"repo": "httpx", "total": 3, "always_pass": 2,
             "consistent_fail": 1, "intermittent": 0, "avg_score": 0.81},
        ],
        "root_causes": [
            {"category": "ordering", "total": 1, "consistent": 1,
             "intermittent": 0, "cases": ["case_c"]},
        ],
        "over_splitting": [],
        "score_stability": [
            {"case_id": "case_a", "tier": 1, "scores": [0.85, 0.87],
             "mean": 0.86, "range": 0.02, "std_dev": 0.01},
            {"case_id": "case_b", "tier": 1, "scores": [0.84, 0.86],
             "mean": 0.85, "range": 0.02, "std_dev": 0.01},
            {"case_id": "case_c", "tier": 2, "scores": [0.73, 0.73],
             "mean": 0.73, "range": 0.0, "std_dev": 0.0},
        ],
        "cases": [
            {"case_id": "case_a", "tier": 1, "ref_commits": 1, "agent_counts": [2, 2],
             "fail_count": 0, "pass_count": 2, "category": "always_pass",
             "stability": "consistent", "avg_score": 0.86, "avg_tpr": 1.0,
             "has_import_fail": False, "has_test_fail": False,
             "has_hunk_miss": False, "has_fs_fail": False,
             "last_commit_test_fails": 0, "mech_pass_per_run": [True, True],
             "hunk_coverages": [1.0, 1.0], "scores": [0.85, 0.87]},
            {"case_id": "case_b", "tier": 1, "ref_commits": 1, "agent_counts": [3, 3],
             "fail_count": 0, "pass_count": 2, "category": "always_pass",
             "stability": "consistent", "avg_score": 0.85, "avg_tpr": 1.0,
             "has_import_fail": False, "has_test_fail": False,
             "has_hunk_miss": False, "has_fs_fail": False,
             "last_commit_test_fails": 0, "mech_pass_per_run": [True, True],
             "hunk_coverages": [1.0, 1.0], "scores": [0.84, 0.86]},
            {"case_id": "case_c", "tier": 2, "ref_commits": 1, "agent_counts": [4, 4],
             "fail_count": 2, "pass_count": 0, "category": "ordering",
             "stability": "consistent", "avg_score": 0.73, "avg_tpr": 0.70,
             "has_import_fail": False, "has_test_fail": True,
             "has_hunk_miss": False, "has_fs_fail": False,
             "last_commit_test_fails": 0, "mech_pass_per_run": [False, False],
             "hunk_coverages": [1.0, 1.0], "scores": [0.73, 0.73]},
        ],
    }


@pytest.fixture
def group_b() -> dict:
    """A meta_analysis.json dict representing group B (e.g., Claude)."""
    return {
        "meta_analysis_version": 1,
        "n_runs": 2,
        "runs": [
            {"index": 1, "run_id": "run_b1", "timestamp": "2026-03-15_12-00-00",
             "provider": "anthropic", "model": "claude-sonnet-4", "suite": "full",
             "use_agent": False, "total_cases": 3, "avg_score": 0.88,
             "mechanical_pass_rate": 1.0, "total_duration_s": 150.0, "total_tokens": 8000},
            {"index": 2, "run_id": "run_b2", "timestamp": "2026-03-15_13-00-00",
             "provider": "anthropic", "model": "claude-sonnet-4", "suite": "full",
             "use_agent": False, "total_cases": 3, "avg_score": 0.90,
             "mechanical_pass_rate": 1.0, "total_duration_s": 140.0, "total_tokens": 7800},
        ],
        "summary": {
            "total_cases": 3,
            "always_pass": 3,
            "always_pass_rate": 1.0,
            "false_positive": 0,
            "consistent_fail": 0,
            "intermittent": 0,
            "avg_score": 0.89,
            "avg_tpr": 1.0,
            "avg_mechanical_pass_rate": 1.0,
        },
        "by_tier": [
            {"tier": 1, "total": 2, "always_pass": 2, "consistent_fail": 0,
             "intermittent": 0, "false_positive": 0, "avg_score": 0.90, "avg_tpr": 1.0},
            {"tier": 2, "total": 1, "always_pass": 1, "consistent_fail": 0,
             "intermittent": 0, "false_positive": 0, "avg_score": 0.87, "avg_tpr": 1.0},
        ],
        "by_repo": [
            {"repo": "httpx", "total": 3, "always_pass": 3,
             "consistent_fail": 0, "intermittent": 0, "avg_score": 0.89},
        ],
        "root_causes": [],
        "over_splitting": [],
        "score_stability": [
            {"case_id": "case_a", "tier": 1, "scores": [0.90, 0.92],
             "mean": 0.91, "range": 0.02, "std_dev": 0.01},
            {"case_id": "case_b", "tier": 1, "scores": [0.88, 0.90],
             "mean": 0.89, "range": 0.02, "std_dev": 0.01},
            {"case_id": "case_c", "tier": 2, "scores": [0.86, 0.88],
             "mean": 0.87, "range": 0.02, "std_dev": 0.01},
        ],
        "cases": [
            {"case_id": "case_a", "tier": 1, "ref_commits": 1, "agent_counts": [2, 2],
             "fail_count": 0, "pass_count": 2, "category": "always_pass",
             "stability": "consistent", "avg_score": 0.91, "avg_tpr": 1.0,
             "has_import_fail": False, "has_test_fail": False,
             "has_hunk_miss": False, "has_fs_fail": False,
             "last_commit_test_fails": 0, "mech_pass_per_run": [True, True],
             "hunk_coverages": [1.0, 1.0], "scores": [0.90, 0.92]},
            {"case_id": "case_b", "tier": 1, "ref_commits": 1, "agent_counts": [2, 2],
             "fail_count": 0, "pass_count": 2, "category": "always_pass",
             "stability": "consistent", "avg_score": 0.89, "avg_tpr": 1.0,
             "has_import_fail": False, "has_test_fail": False,
             "has_hunk_miss": False, "has_fs_fail": False,
             "last_commit_test_fails": 0, "mech_pass_per_run": [True, True],
             "hunk_coverages": [1.0, 1.0], "scores": [0.88, 0.90]},
            {"case_id": "case_c", "tier": 2, "ref_commits": 1, "agent_counts": [3, 3],
             "fail_count": 0, "pass_count": 2, "category": "always_pass",
             "stability": "consistent", "avg_score": 0.87, "avg_tpr": 1.0,
             "has_import_fail": False, "has_test_fail": False,
             "has_hunk_miss": False, "has_fs_fail": False,
             "last_commit_test_fails": 0, "mech_pass_per_run": [True, True],
             "hunk_coverages": [1.0, 1.0], "scores": [0.86, 0.88]},
        ],
    }


@pytest.fixture
def saved_group_a(tmp_path, group_a) -> Path:
    """Save group_a as a JSON file and return its path."""
    p = tmp_path / "group_a" / "meta_analysis.json"
    p.parent.mkdir()
    p.write_text(json.dumps(group_a))
    return p


@pytest.fixture
def saved_group_b(tmp_path, group_b) -> Path:
    """Save group_b as a JSON file and return its path."""
    p = tmp_path / "group_b" / "meta_analysis.json"
    p.parent.mkdir()
    p.write_text(json.dumps(group_b))
    return p


# ── load_meta ──────────────────────────────────────────────────────────────


class TestLoadMeta:
    def test_loads_valid_json(self, saved_group_a):
        data = load_meta(saved_group_a)
        assert data["meta_analysis_version"] == 1
        assert data["n_runs"] == 2

    def test_returns_dict(self, saved_group_a):
        data = load_meta(saved_group_a)
        assert isinstance(data, dict)


# ── compare_groups ──────────────────────────────────────────────────────────


class TestCompareGroups:
    def test_returns_dict(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        assert isinstance(result, dict)

    def test_n_groups(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        assert result["n_groups"] == 2

    def test_labels_auto_derived(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        assert "gemini" in result["labels"][0].lower()
        assert "claude" in result["labels"][1].lower()

    def test_labels_custom(self, group_a, group_b):
        result = compare_groups([group_a, group_b], labels=["Model A", "Model B"])
        assert result["labels"] == ["Model A", "Model B"]

    def test_group_summaries(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        assert len(result["group_summaries"]) == 2
        assert result["group_summaries"][0]["avg_score"] == group_a["summary"]["avg_score"]
        assert result["group_summaries"][1]["avg_score"] == group_b["summary"]["avg_score"]

    def test_rankings(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        assert len(result["rankings"]) > 0
        for r in result["rankings"]:
            assert "metric" in r
            assert "winner" in r
            assert "ranking" in r

    def test_avg_score_winner_is_group_b(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        score_ranking = next(r for r in result["rankings"] if r["metric"] == "avg_score")
        assert "claude" in score_ranking["winner"].lower()

    def test_head_to_head(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        assert len(result["head_to_head"]) == 3  # case_a, case_b, case_c
        for entry in result["head_to_head"]:
            assert "case_id" in entry
            assert "groups" in entry
            assert len(entry["groups"]) == 2

    def test_case_deltas_detected(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        # case_c changed from ordering to always_pass
        deltas = result["case_deltas"]
        assert len(deltas) > 0
        delta_c = next(d for d in deltas if d["case_id"] == "case_c")
        assert delta_c["group_0_category"] == "ordering"
        assert delta_c["group_1_category"] == "always_pass"

    def test_by_tier(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        assert len(result["by_tier"]) == 2  # T1, T2
        for td in result["by_tier"]:
            assert len(td["groups"]) == 2

    def test_by_repo(self, group_a, group_b):
        result = compare_groups([group_a, group_b])
        assert len(result["by_repo"]) == 1  # httpx only

    def test_three_groups(self, group_a, group_b):
        result = compare_groups([group_a, group_b, group_a], labels=["A", "B", "A2"])
        assert result["n_groups"] == 3
        assert len(result["group_summaries"]) == 3


# ── Report generators ──────────────────────────────────────────────────────


class TestGenerateComparisonReport:
    def test_returns_markdown(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_report(comparison)
        assert isinstance(report, str)
        assert "Cross-Group Comparison Report" in report

    def test_contains_group_names(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_report(comparison)
        assert "gemini" in report.lower()
        assert "claude" in report.lower()

    def test_contains_rankings(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_report(comparison)
        assert "Rankings" in report

    def test_contains_head_to_head(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_report(comparison)
        assert "Head-to-Head" in report
        assert "case_a" in report

    def test_contains_category_changes(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_report(comparison)
        assert "Category Changes" in report


class TestGenerateComparisonTerminalReport:
    def test_returns_string(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_terminal_report(comparison)
        assert isinstance(report, str)

    def test_contains_header(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_terminal_report(comparison)
        assert "Cross-Group Comparison" in report

    def test_contains_ansi(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_terminal_report(comparison)
        assert "\033[" in report

    def test_contains_winner(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        report = generate_comparison_terminal_report(comparison)
        assert "Overall Winner" in report


class TestGenerateComparisonHtml:
    def test_returns_html(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        html = generate_comparison_html(comparison)
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_contains_data_json(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        html = generate_comparison_html(comparison)
        assert "const DATA" in html

    def test_contains_dashboard_title(self, group_a, group_b):
        comparison = compare_groups([group_a, group_b])
        html = generate_comparison_html(comparison)
        assert "Cross-Group Comparison Dashboard" in html


# ── run_comparison ──────────────────────────────────────────────────────────


class TestRunComparison:
    def test_creates_all_files(self, saved_group_a, saved_group_b, tmp_path):
        out = tmp_path / "comparison_out"
        md_path, terminal = run_comparison(
            [saved_group_a, saved_group_b], web=True, output_dir=out
        )
        assert md_path.exists()
        assert md_path.name == "group_comparison.md"
        assert (out / "group_comparison.json").exists()
        assert (out / "group_comparison.html").exists()

    def test_no_web_no_html(self, saved_group_a, saved_group_b, tmp_path):
        out = tmp_path / "no_web"
        md_path, _ = run_comparison(
            [saved_group_a, saved_group_b], web=False, output_dir=out
        )
        assert not (out / "group_comparison.html").exists()
        assert (out / "group_comparison.json").exists()

    def test_returns_terminal_report(self, saved_group_a, saved_group_b, tmp_path):
        out = tmp_path / "term_test"
        _, terminal = run_comparison(
            [saved_group_a, saved_group_b], output_dir=out
        )
        assert "Cross-Group Comparison" in terminal

    def test_custom_labels(self, saved_group_a, saved_group_b, tmp_path):
        out = tmp_path / "labels_test"
        md_path, terminal = run_comparison(
            [saved_group_a, saved_group_b],
            output_dir=out,
            labels=["Alpha", "Beta"],
        )
        content = md_path.read_text()
        assert "Alpha" in content
        assert "Beta" in content

    def test_default_output_dir(self, saved_group_a, saved_group_b):
        md_path, _ = run_comparison([saved_group_a, saved_group_b])
        # Should go to the lexicographically largest parent dir name
        expected = max(saved_group_a.parent, saved_group_b.parent, key=lambda d: d.name)
        assert md_path.parent == expected

