"""Tests for eval.config — configuration constants and defaults."""

from pathlib import Path

from eval.config import (
    CORRECTNESS_WEIGHT,
    DEFAULT_AGENT_CONFIG,
    DEFAULT_JUDGE_CONFIG,
    EVAL_CACHE_DIR,
    EVAL_REPOS_CACHE_DIR,
    EVAL_RESULTS_DIR,
    EVAL_TEST_CASES_DIR,
    EVAL_VENVS_CACHE_DIR,
    QUALITY_WEIGHT,
    SUITES,
)


class TestPaths:
    def test_paths_are_path_objects(self):
        for p in [EVAL_TEST_CASES_DIR, EVAL_RESULTS_DIR, EVAL_CACHE_DIR,
                   EVAL_VENVS_CACHE_DIR, EVAL_REPOS_CACHE_DIR]:
            assert isinstance(p, Path)

    def test_test_cases_dir_ends_with_cases(self):
        assert EVAL_TEST_CASES_DIR.name == "cases"

    def test_cache_under_home(self):
        assert ".hunknote" in str(EVAL_CACHE_DIR)

    def test_venvs_cache_under_eval_cache(self):
        assert str(EVAL_VENVS_CACHE_DIR).startswith(str(EVAL_CACHE_DIR))

    def test_repos_cache_under_eval_cache(self):
        assert str(EVAL_REPOS_CACHE_DIR).startswith(str(EVAL_CACHE_DIR))


class TestSuites:
    def test_smoke_suite_exists(self):
        assert "smoke" in SUITES

    def test_standard_suite_exists(self):
        assert "standard" in SUITES

    def test_full_suite_exists(self):
        assert "full" in SUITES

    def test_full_suite_matches_all(self):
        assert "*" in SUITES["full"]

    def test_smoke_suite_has_patterns(self):
        patterns = SUITES["smoke"]
        assert len(patterns) > 0
        assert all(isinstance(p, str) for p in patterns)


class TestDefaultConfigs:
    def test_agent_config_has_provider(self):
        assert "provider" in DEFAULT_AGENT_CONFIG

    def test_agent_config_has_model(self):
        assert "model" in DEFAULT_AGENT_CONFIG

    def test_agent_config_has_max_retries(self):
        assert "max_retries" in DEFAULT_AGENT_CONFIG
        assert isinstance(DEFAULT_AGENT_CONFIG["max_retries"], int)

    def test_agent_config_has_max_commits(self):
        assert "max_commits" in DEFAULT_AGENT_CONFIG
        assert isinstance(DEFAULT_AGENT_CONFIG["max_commits"], int)

    def test_judge_config_has_enabled(self):
        assert "enabled" in DEFAULT_JUDGE_CONFIG
        assert isinstance(DEFAULT_JUDGE_CONFIG["enabled"], bool)


class TestWeights:
    def test_weights_sum_to_one(self):
        assert CORRECTNESS_WEIGHT + QUALITY_WEIGHT == 1.0

    def test_correctness_weight_positive(self):
        assert CORRECTNESS_WEIGHT > 0

    def test_quality_weight_positive(self):
        assert QUALITY_WEIGHT > 0

