# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hunknote is an AI-powered git commit message generator and atomic commit stacking tool. It uses LLMs to analyze staged git changes and produce structured commit messages, or split large diffs into clean atomic commits ("compose" feature).

## Build & Development Commands

```bash
# Install dependencies
poetry install

# Run all tests
poetry run pytest

# Run a single test file
poetry run pytest tests/test_cli.py

# Run a specific test
poetry run pytest tests/test_cli.py::test_function_name -v

# Run the CLI during development
poetry run hunknote

# Build binary with PyInstaller
poetry run pyinstaller hunknote.spec
```

## Architecture

### Package Structure

The main package is `hunknote/` with these key modules:

- **`cli/`** — Typer-based CLI layer. Entry point is `hunknote.cli:app`. Commands: `hunknote` (generate message), `commit`, `compose`, `config`, `style`, `ignore`, `init`.
- **`llm/`** — LLM abstraction. All providers (Anthropic, OpenAI, Google, Mistral, Cohere, Groq, OpenRouter) are routed through a single `LiteLLMProvider` class in `litellm_provider.py`. Prompt templates live in `llm/prompts/`.
- **`compose/`** — Multi-commit stacking. Parses unified diffs into hunk inventories, asks the LLM to partition hunks into logical commits, validates plans, and executes them with snapshot-based recovery.
- **`git/`** — Git interaction. Collects context bundles (branch, status, last commits, diff) used as LLM input. Handles merge state detection and diff exclusion patterns.
- **`cache/`** — Hash-based caching. Skips LLM calls when the context hasn't changed. Cache files stored in `.hunknote/` within the repo.
- **`styles/`** — Commit message formatting. Five profiles: default, blueprint, conventional, ticket, kernel. Renderers in `styles/renderers/`.
- **`scope.py`** — Scope inference for monorepos. Strategies: auto, monorepo, path-prefix, mapping, none.
- **`config.py`** — LLM provider/model configuration with 40+ supported models.
- **`global_config.py`** — User-level settings at `~/.hunknote/config.yaml`, API keys stored via `keyring`.
- **`user_config.py`** — Per-repo config at `.hunknote/config.yaml`.

### Backward Compatibility Shims

Top-level files `cache.py`, `compose.py`, `git_ctx.py`, `styles.py` are shims that re-export from the refactored packages. New code should import from the packages directly (e.g., `from hunknote.compose.models import ComposePlan`).

### Key Data Flow

**Generate message:** CLI → build context bundle (git/) → check cache → call LLM (llm/) → parse JSON → apply scope/style → render message → save cache

**Compose:** CLI → collect full diff → parse into hunk inventory → LLM partitions hunks → validate plan → snapshot → apply patches & create commits → cleanup on failure

### Configuration Hierarchy (highest priority first)

1. CLI flags
2. Per-repo `.hunknote/config.yaml`
3. Global `~/.hunknote/config.yaml`

### Testing

- Framework: pytest + pytest-mock
- Tests in `tests/` directory, integration tests in `integration_tests/`
- Heavy use of mocking for git commands and LLM responses
- Key fixtures: `temp_dir`, `mock_repo_root`, `sample_context_bundle`, `sample_commit_json_dict`

### Models & Data Classes

Core models use `@dataclass`: `ExtendedCommitJSON`, `ComposePlan`, `PlannedCommit`, `HunkRef`, `CacheMetadata`, `LLMResult`, `ScopeConfig`, `StyleConfig`, `ProfileConfig`.

### Code Style
- Type hints throughout
- Docstrings for all public functions/classes
- Follows PEP 8 with some flexibility for readability (e.g., longer function signatures with many parameters)
- Linting with flake8 and black formatting
- Comprehensive logging for debugging and error tracing

### DONTS:
- DO NOT use the following git commands:
  - `git add`
  - `git commit`
  - `git reset`
  - `git checkout`
  - `git merge`
  - `git rebase`
  - `git stash`
  - `git pull`
  - `git push`
