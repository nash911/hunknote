"""Tests for eval.generator — utility functions (no git operations)."""

import pytest

from eval.generator import (
    _build_reference_commits,
    _content_similarity,
    _extract_change_content,
    _write_case_json,
    _write_reference_json,
)
from eval.models import (
    BuildSystemConfig,
    DifficultyTier,
    KnownDependency,
    Language,
    ReferenceCommit,
    TestCase,
    TestCaseStats,
)


# ── _extract_change_content ─────────────────────────────────────────────────


class TestExtractChangeContent:
    def test_extracts_additions(self):
        lines = ["+added line 1", "+added line 2", " context line"]
        result = _extract_change_content(lines)
        assert "+added line 1" in result
        assert "+added line 2" in result
        assert " context line" not in result

    def test_extracts_deletions(self):
        lines = ["-deleted line", " context", "+added"]
        result = _extract_change_content(lines)
        assert "-deleted line" in result
        assert "+added" in result
        assert " context" not in result

    def test_empty_lines(self):
        result = _extract_change_content([])
        assert result == ""

    def test_context_only(self):
        lines = [" ctx1", " ctx2", " ctx3"]
        result = _extract_change_content(lines)
        assert result == ""


# ── _content_similarity ─────────────────────────────────────────────────────


class TestContentSimilarity:
    def test_identical_content(self):
        assert _content_similarity("a\nb\nc", "a\nb\nc") == 1.0

    def test_completely_different(self):
        assert _content_similarity("a\nb", "x\ny") == 0.0

    def test_partial_overlap(self):
        score = _content_similarity("a\nb\nc", "a\nb\nd")
        assert 0.0 < score < 1.0

    def test_both_empty(self):
        assert _content_similarity("", "") == 1.0

    def test_one_empty(self):
        assert _content_similarity("a\nb", "") == 0.0
        assert _content_similarity("", "a\nb") == 0.0

    def test_symmetric(self):
        a = "line1\nline2\nline3"
        b = "line2\nline3\nline4"
        assert _content_similarity(a, b) == _content_similarity(b, a)


# ── _build_reference_commits ────────────────────────────────────────────────


class TestBuildReferenceCommits:
    def test_basic_mapping(self):
        commit_sequence = [
            {"sha": "aaa111", "message": "First commit", "files": ["a.py"]},
            {"sha": "bbb222", "message": "Second commit", "files": ["b.py"]},
        ]
        hunk_to_commit = {
            "H1_abc": "aaa111",
            "H2_def": "aaa111",
            "H3_ghi": "bbb222",
        }
        refs = _build_reference_commits(commit_sequence, hunk_to_commit)
        assert len(refs) == 2
        assert refs[0].index == 0
        assert sorted(refs[0].hunk_ids) == ["H1_abc", "H2_def"]
        assert refs[1].hunk_ids == ["H3_ghi"]

    def test_commits_without_hunks_are_skipped(self):
        commit_sequence = [
            {"sha": "aaa111", "message": "First", "files": ["a.py"]},
            {"sha": "bbb222", "message": "Second", "files": ["b.py"]},
        ]
        hunk_to_commit = {"H1_abc": "aaa111"}
        refs = _build_reference_commits(commit_sequence, hunk_to_commit)
        assert len(refs) == 1
        assert refs[0].message == "First"

    def test_empty_mapping(self):
        commit_sequence = [
            {"sha": "aaa111", "message": "First", "files": ["a.py"]},
        ]
        refs = _build_reference_commits(commit_sequence, {})
        assert len(refs) == 0

    def test_preserves_commit_order(self):
        commit_sequence = [
            {"sha": "ccc333", "message": "Third", "files": ["c.py"]},
            {"sha": "aaa111", "message": "First", "files": ["a.py"]},
            {"sha": "bbb222", "message": "Second", "files": ["b.py"]},
        ]
        hunk_to_commit = {
            "H1": "ccc333",
            "H2": "aaa111",
            "H3": "bbb222",
        }
        refs = _build_reference_commits(commit_sequence, hunk_to_commit)
        assert [r.index for r in refs] == [0, 1, 2]


# ── _write_case_json / _write_reference_json ────────────────────────────────


class TestWriteCaseJson:
    def test_writes_valid_json(self, tmp_path):
        case = TestCase(
            id="python_test_case",
            language=Language.PYTHON,
            tier=DifficultyTier.TIER1,
            description="Test case",
            source_repo="https://github.com/test/repo",
            source_commits=["abc123"],
            stats=TestCaseStats(
                total_hunks=5, total_files=2,
                reference_commit_count=1,
                lines_added=20, lines_removed=10,
            ),
            build_system=BuildSystemConfig(
                type="python",
                install_commands=["pip install -r requirements.txt"],
                check_command="python -m py_compile {file}",
                import_check=True,
                test_command="python -m pytest -x",
                test_enabled=True,
            ),
        )
        _write_case_json(case, tmp_path)

        case_json_path = tmp_path / "case.json"
        assert case_json_path.exists()

        import json
        with open(case_json_path) as f:
            data = json.load(f)

        assert data["id"] == "python_test_case"
        assert data["language"] == "python"
        assert data["tier"] == 1
        assert data["stats"]["total_hunks"] == 5

    def test_includes_known_dependencies(self, tmp_path):
        case = TestCase(
            id="test_with_deps",
            language=Language.PYTHON,
            tier=DifficultyTier.TIER2,
            description="Test with deps",
            source_repo="https://github.com/test/repo",
            source_commits=["abc123"],
            stats=TestCaseStats(
                total_hunks=10, total_files=3,
                reference_commit_count=1,
                lines_added=30, lines_removed=15,
            ),
            build_system=BuildSystemConfig(
                type="python",
                install_commands=["pip install -e ."],
                check_command="python -m py_compile {file}",
            ),
            known_dependencies=[
                KnownDependency(
                    description="Test dependency",
                    hunks_must_cocommit=["H1", "H2"],
                    reason="Coupled change",
                )
            ],
        )
        _write_case_json(case, tmp_path)

        import json
        with open(tmp_path / "case.json") as f:
            data = json.load(f)

        assert len(data["known_dependencies"]) == 1
        assert data["known_dependencies"][0]["description"] == "Test dependency"


class TestWriteReferenceJson:
    def test_writes_valid_json(self, tmp_path):
        refs = [
            ReferenceCommit(
                index=0, message="First commit",
                files=["a.py"], hunk_ids=["H1", "H2"],
            ),
            ReferenceCommit(
                index=1, message="Second commit",
                files=["b.py", "c.py"], hunk_ids=["H3"],
            ),
        ]
        _write_reference_json(refs, tmp_path)

        ref_path = tmp_path / "reference.json"
        assert ref_path.exists()

        import json
        with open(ref_path) as f:
            data = json.load(f)

        assert len(data["commits"]) == 2
        assert data["commits"][0]["message"] == "First commit"
        assert data["commits"][1]["hunk_ids"] == ["H3"]

    def test_empty_references(self, tmp_path):
        _write_reference_json([], tmp_path)

        import json
        with open(tmp_path / "reference.json") as f:
            data = json.load(f)

        assert data["commits"] == []

