"""Configuration for the eval module."""

from pathlib import Path

# Default paths
EVAL_TEST_CASES_DIR = Path(__file__).parent / "test_cases" / "cases"
EVAL_RESULTS_DIR = Path(__file__).parent.parent.parent / "eval_results"
EVAL_CACHE_DIR = Path.home() / ".hunknote" / "eval_cache"
EVAL_VENVS_CACHE_DIR = EVAL_CACHE_DIR / "venvs"
EVAL_REPOS_CACHE_DIR = EVAL_CACHE_DIR / "repos"

# Suite definitions: map suite name to glob patterns for case IDs
SUITES: dict[str, list[str]] = {
    "smoke": ["*tier1*", "*tier2*"],
    "standard": ["*tier1*", "*tier2*", "*tier3*", "*edge*"],
    "full": ["*"],
}

# Default agent configuration
DEFAULT_AGENT_CONFIG: dict = {
    "provider": "google",
    "model": "gemini-2.5-flash",
    "max_retries": 2,
    "max_commits": 8,
    "use_agent": True,  # When True, use Compose Agent (not yet implemented)
}

# Default judge configuration
DEFAULT_JUDGE_CONFIG: dict = {
    "enabled": False,
    "provider": "google",
    "model": "gemini-2.0-flash",
}

# Scoring weights
CORRECTNESS_WEIGHT = 0.6
QUALITY_WEIGHT = 0.4
