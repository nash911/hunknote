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

### Eval Module (`eval/`)

Independent evaluation framework at the project root (NOT inside `hunknote/`). Measures the Compose command's ability to decompose squashed diffs into clean, buildable commit sequences. See `eval/README.md` for full documentation.

**Key commands:**
```bash
# Run eval tests
python -m pytest tests/eval/ -q

# List test cases
python eval/cli.py list

# Run evaluation (requires LLM API key)
python eval/cli.py run --suite smoke --no-agent
python eval/cli.py run --suite full --no-agent

# Filter by repo or tier
python eval/cli.py run --repo httpx --tier 3 --no-agent

# Analyze results
python eval/cli.py analyze eval_results/<timestamp>/eval_results.json

# Meta-analysis across multiple runs
python eval/cli.py analyze eval_results/run1/eval_results.json eval_results/run2/eval_results.json --web

# Generate test cases from commit pair definitions
python eval/cli.py generate-batch --input-file eval/test_cases/httpx_commit_pairs.json
```

**Architecture:** `models.py` (dataclasses) → `registry.py` (case discovery) → `environment.py` (isolated target venvs) → `validation.py` (mechanical checks: patch apply → py_compile → import → pytest → final state) → `scoring.py` (ARI, granularity, dependency recall) → `judge.py` (optional LLM-as-judge) → `harness.py` (orchestrator) → `reporting.py` (JSON save/load) → `analysis.py` (Markdown/terminal/HTML reports, multi-run meta-analysis) → `cli.py` (Typer CLI).

**Test cases:** 41 cases across 3 Python repos (httpx, rich, marshmallow), spanning Tiers 1-5. Stored in `eval/test_cases/cases/python/`. Each case has `case.json`, `staged.patch`, `reference.json`, and `repo.tar.gz`.

**Scoring:** 60% mechanical (patch apply, syntax, imports, tests, final state match, hunk coverage) + 40% semantic (ARI reference similarity, granularity, dependency recall).

**Current baseline (single-shot Gemini 2.5 Flash, 3 runs):**
- 51% always pass, 27% consistent fail, 20% intermittent, 2% false positive
- Primary failure modes: incorrect hunk ordering (27%), cross-file import deps (10%), hunk coverage at T5 scale (10%)
- The Compose Agent (multi-step agentic planner) is not yet implemented; `--no-agent` uses the single-shot LLM compose planner

### Testing

- Framework: pytest + pytest-mock
- Tests in `tests/` directory, integration tests in `integration_tests/`, eval tests in `tests/eval/`
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
