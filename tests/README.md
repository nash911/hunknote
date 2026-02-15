# Hunknote Test Suite

Comprehensive test suite for the `hunknote` CLI tool.

## Overview

This test suite contains **409 unit tests** covering all modules of the hunknote project. The tests use `pytest` and `pytest-mock` for mocking external dependencies.

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
├── __init__.py             # Test package init
├── conftest.py             # Shared fixtures
├── test_cache.py           # Cache module tests (34 tests)
├── test_cli.py             # CLI command tests (42 tests)
├── test_config.py          # Configuration tests (24 tests)
├── test_formatters.py      # Formatters module tests (21 tests)
├── test_git_ctx.py         # Git context tests (31 tests)
├── test_global_config.py   # Global config tests (26 tests)
├── test_llm_base.py        # LLM base module tests (27 tests)
├── test_llm_providers.py   # LLM provider tests (25 tests)
├── test_scope.py           # Scope inference tests (54 tests)
├── test_styles.py          # Style profiles tests (55 tests)
├── test_user_config.py     # User config tests (20 tests)
└── README.md               # This file
```

## Running Tests

### Run All Tests

```bash
# From project root
pytest tests/

# Or with verbose output
pytest tests/ -v

# With coverage report (if pytest-cov is installed)
pytest tests/ --cov=hunknote
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
| `formatters.py` | `test_formatters.py` | 21 | Commit message formatting and Pydantic validation |
| `cache.py` | `test_cache.py` | 34 | Caching utilities, hash computation, metadata |
| `user_config.py` | `test_user_config.py` | 20 | Repository YAML config file management |
| `global_config.py` | `test_global_config.py` | 26 | Global user configuration (~/.hunknote/) |
| `git_ctx.py` | `test_git_ctx.py` | 31 | Git context collection and filtering |
| `styles.py` | `test_styles.py` | 87 | Commit style profiles and rendering (incl. blueprint) |
| `scope.py` | `test_scope.py` | 54 | Scope inference from file paths |
| `llm/base.py` | `test_llm_base.py` | 57 | JSON parsing, schema validation, style prompts |
| `llm/*.py` | `test_llm_providers.py` | 25 | All LLM provider classes |
| `cli.py` | `test_cli.py` | 42 | CLI commands, config, style, and ignore management |
| `config.py` | `test_config.py` | 24 | Configuration constants and enums |

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
       mocker.patch("hunknote.git_ctx.get_repo_root", return_value=Path("/mock"))
       ...
   ```

## Dependencies

- `pytest >= 8.0.0` - Test framework
- `pytest-mock >= 3.12.0` - Mocking utilities

Install with:
```bash
poetry install --with dev
```
