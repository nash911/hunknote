"""Tests for test case registry and discovery."""

import json

import pytest

from eval.models import DifficultyTier, Language
from eval.registry import (
    discover_cases,
    filter_cases_by_suite,
    get_suites,
    load_case,
)


class TestLoadCase:
    def test_load_valid_case(self, sample_case_dir, sample_test_case):
        case_dir = (
            sample_case_dir
            / sample_test_case.language.value
            / sample_test_case.id
        )
        case = load_case(case_dir)

        assert case.id == sample_test_case.id
        assert case.language == Language.PYTHON
        assert case.tier == DifficultyTier.TIER2
        assert case.stats.total_hunks == 10
        assert case.stats.total_files == 3
        assert len(case.known_dependencies) == 1
        assert len(case.reference_commits) == 3
        assert case.tags == ["test", "sample"]

    def test_load_case_missing_json(self, temp_dir):
        with pytest.raises(FileNotFoundError):
            load_case(temp_dir / "nonexistent")

    def test_load_case_build_system(self, sample_case_dir, sample_test_case):
        case_dir = (
            sample_case_dir
            / sample_test_case.language.value
            / sample_test_case.id
        )
        case = load_case(case_dir)

        assert case.build_system.type == "python"
        assert case.build_system.install_commands == ["pip install -e ."]
        assert case.build_system.import_check is True


class TestDiscoverCases:
    def test_discover_all(self, sample_case_dir):
        cases = discover_cases(base_dir=sample_case_dir)
        assert len(cases) == 1
        assert cases[0].id == "python_test_tier2_sample"

    def test_discover_filter_language(self, sample_case_dir):
        cases = discover_cases(base_dir=sample_case_dir, language=Language.PYTHON)
        assert len(cases) == 1

        cases = discover_cases(base_dir=sample_case_dir, language=Language.GO)
        assert len(cases) == 0

    def test_discover_filter_tier(self, sample_case_dir):
        cases = discover_cases(base_dir=sample_case_dir, tier=DifficultyTier.TIER2)
        assert len(cases) == 1

        cases = discover_cases(base_dir=sample_case_dir, tier=DifficultyTier.TIER5)
        assert len(cases) == 0

    def test_discover_filter_tags(self, sample_case_dir):
        cases = discover_cases(base_dir=sample_case_dir, tags=["test"])
        assert len(cases) == 1

        cases = discover_cases(base_dir=sample_case_dir, tags=["nonexistent"])
        assert len(cases) == 0

    def test_discover_empty_dir(self, temp_dir):
        cases = discover_cases(base_dir=temp_dir)
        assert len(cases) == 0

    def test_discover_nonexistent_dir(self, temp_dir):
        cases = discover_cases(base_dir=temp_dir / "nope")
        assert len(cases) == 0


class TestFilterCasesBySuite:
    def test_smoke_suite(self, sample_case_dir):
        cases = discover_cases(base_dir=sample_case_dir)
        filtered = filter_cases_by_suite(cases, "smoke")
        # "python_test_tier2_sample" matches "*tier2*"
        assert len(filtered) == 1

    def test_full_suite(self, sample_case_dir):
        cases = discover_cases(base_dir=sample_case_dir)
        filtered = filter_cases_by_suite(cases, "full")
        assert len(filtered) == 1

    def test_unknown_suite_matches_all(self, sample_case_dir):
        cases = discover_cases(base_dir=sample_case_dir)
        filtered = filter_cases_by_suite(cases, "nonexistent")
        assert len(filtered) == 1  # Default pattern is "*"


class TestGetSuites:
    def test_returns_dict(self):
        suites = get_suites()
        assert "smoke" in suites
        assert "standard" in suites
        assert "full" in suites
        assert isinstance(suites["smoke"], list)
