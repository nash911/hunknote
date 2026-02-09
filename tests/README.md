# AI Commit Test Suite

Comprehensive test suite for the `aicommit` CLI tool.

## Overview

This test suite contains **197 unit tests** covering all modules of the aicommit project. The tests use `pytest` and `pytest-mock` for mocking external dependencies.

## Important Notes

### No API Calls

**The tests do NOT make any actual API calls to LLM providers.** All LLM interactions are mocked using `pytest-mock`. This means:

- Tests run quickly (typically < 3 seconds)
- No API keys are required to run tests
- No network connection is needed
- No costs are incurred from running tests

### Test Structure

```
tests/
├── __init__.py           # Test package init
├── conftest.py           # Shared fixtures
├── test_cache.py         # Cache module tests (35 tests)
├── test_cli.py           # CLI command tests (17 tests)
├── test_config.py        # Configuration tests (22 tests)
├── test_formatters.py    # Formatters module tests (25 tests)
├── test_git_ctx.py       # Git context tests (27 tests)
├── test_llm_base.py      # LLM base module tests (26 tests)
├── test_llm_providers.py # LLM provider tests (23 tests)
├── test_user_config.py   # User config tests (22 tests)
└── README.md             # This file
```

## Running Tests

### Run All Tests

```bash
# From project root
pytest tests/

# Or with verbose output
pytest tests/ -v

# With coverage report (if pytest-cov is installed)
pytest tests/ --cov=aicommit
```

### Run Specific Test File

```bash
pytest tests/test_formatters.py
pytest tests/test_cache.py -v
```

### Run Specific Test Class or Function

```bash
# Run a specific test class
pytest tests/test_formatters.py::TestCommitMessageJSON

# Run a specific test function
pytest tests/test_formatters.py::TestCommitMessageJSON::test_valid_commit_message
```

### Run Tests with Pattern Matching

```bash
# Run tests matching a pattern
pytest tests/ -k "cache"
pytest tests/ -k "provider"
```

## Test Coverage by Module

| Module | Test File | Tests | Description |
|--------|-----------|-------|-------------|
| `formatters.py` | `test_formatters.py` | 25 | Commit message formatting and Pydantic validation |
| `cache.py` | `test_cache.py` | 35 | Caching utilities, hash computation, metadata |
| `user_config.py` | `test_user_config.py` | 22 | YAML config file management |
| `git_ctx.py` | `test_git_ctx.py` | 27 | Git context collection and filtering |
| `llm/base.py` | `test_llm_base.py` | 26 | JSON parsing, schema validation, prompts |
| `llm/*.py` | `test_llm_providers.py` | 23 | All LLM provider classes |
| `cli.py` | `test_cli.py` | 17 | CLI commands and ignore management |
| `config.py` | `test_config.py` | 22 | Configuration constants and enums |

## Fixtures

Shared fixtures are defined in `conftest.py`:

- `temp_dir` - Creates a temporary directory for each test
- `mock_repo_root` - Simulates a git repository root
- `sample_context_bundle` - Sample git context for testing
- `sample_commit_json_dict` - Sample commit message as dict
- `sample_llm_response` - Sample raw LLM JSON response
- `sample_llm_response_with_markdown` - Sample response with markdown fences

## Mocking Strategy

The tests use mocking extensively to isolate units:

### Git Commands
```python
mocker.patch("subprocess.run", return_value=mock_result)
```

### LLM API Keys
```python
with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
    key = provider.get_api_key()
```

### File System
Tests use `temp_dir` fixture which provides a real temporary directory that is cleaned up after each test.

### CLI Testing
```python
from typer.testing import CliRunner
runner = CliRunner()
result = runner.invoke(app, ["ignore", "list"])
```

## Adding New Tests

1. Create test functions with descriptive names:
   ```python
   def test_function_does_expected_behavior(self):
       """Test that function does X when Y."""
       ...
   ```

2. Use fixtures for common setup:
   ```python
   def test_with_temp_dir(self, temp_dir):
       config_file = temp_dir / "config.yaml"
       ...
   ```

3. Mock external dependencies:
   ```python
   def test_with_mocked_git(self, mocker):
       mocker.patch("aicommit.git_ctx.get_repo_root", return_value=Path("/mock"))
       ...
   ```

## Dependencies

- `pytest >= 8.0.0` - Test framework
- `pytest-mock >= 3.12.0` - Mocking utilities

Install with:
```bash
poetry install --with dev
```
