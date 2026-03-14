# Hunknote Eval — Compose Agent Evaluation Framework

An independent evaluation module for measuring the quality of hunknote's Compose
command — how well the LLM decomposes a squashed diff into a sequence of clean,
buildable, testable commits.

---

## Overview

The eval framework takes real-world commits from open-source repositories,
squashes them into a single diff, feeds that diff to the Compose command, and
then validates the resulting commit plan against multiple quality axes:

```
Real commits ──▶ Squash ──▶ Agent/LLM ──▶ Proposed plan ──▶ Validate
(reference)      (input)    (compose)     (output)          (score)
```

**Key design principles:**

- **Real repo data** — test cases are extracted from actual open-source projects,
  not synthetic diffs.
- **Isolated environments** — each target project gets its own virtual environment
  so mechanical checks (compile, import, pytest) run against the project's own
  dependencies.
- **Multi-axis scoring** — combines mechanical validation (does the code build?)
  with semantic quality metrics (does the grouping match the reference?).
- **Tiered difficulty** — test cases span five difficulty tiers, from 2-hunk bug
  fixes to 200+ hunk refactors.

---

## Quick Start

```bash
# List available test cases
python eval/cli.py list

# Run the smoke suite (Tier 1 + Tier 2)
python eval/cli.py run --suite smoke

# Run the full suite (all tiers)
python eval/cli.py run --suite full

# Run only cases from a specific repo
python eval/cli.py run --suite full --repo rich
python eval/cli.py run --suite smoke --repo httpx

# Run a single test case
python eval/cli.py run --case python_httpx_tier2_move_utils_to_models

# Run only tier-3 cases
python eval/cli.py run --tier 3

# Analyze a previous run
python eval/cli.py analyze eval_results/<timestamp>/eval_results.json

# Analyze with web dashboard
python eval/cli.py analyze eval_results/<timestamp>/eval_results.json --web
```

---

## Architecture

```
eval/
├── __init__.py          # Public API exports
├── __main__.py          # python -m eval entry point
├── cli.py               # Typer CLI commands
├── config.py            # Paths, suites, defaults, scoring weights
├── models.py            # Data models (TestCase, EvalResult, etc.)
├── registry.py          # Test case discovery and loading
├── generator.py         # Test case generation from real repos
├── environment.py       # Target project venv management
├── validation.py        # Mechanical validation engine
├── scoring.py           # Deterministic semantic quality metrics
├── judge.py             # LLM-as-judge (optional)
├── harness.py           # Eval orchestrator (run loop)
├── reporting.py         # Result serialization, comparison
├── analysis.py          # Terminal reports, markdown reports, HTML dashboards
└── test_cases/
    ├── httpx_commit_pairs.json    # SHA pair definitions (httpx)
    ├── rich_commit_pairs.json     # SHA pair definitions (rich)
    └── cases/
        └── python/
            ├── python_httpx_tier1_*/
            ├── python_httpx_tier2_*/
            ├── python_httpx_tier3_*/
            ├── python_httpx_tier4_*/
            ├── python_httpx_tier5_*/
            ├── python_rich_tier1_*/
            ├── python_rich_tier2_*/
            ├── python_rich_tier3_*/
            └── python_rich_tier4_*/
```

### Module Responsibilities

| Module | Role |
|--------|------|
| **models.py** | Dataclasses: `TestCase`, `EvalCaseResult`, `EvalRunResult`, `MechanicalResult`, `SemanticScores`, `CommitValidation`, `BuildSystemConfig`, etc. |
| **registry.py** | Discovers and loads `case.json` files from `test_cases/cases/`. Filters by suite, tier, language, or ID. |
| **generator.py** | Clones repos, extracts commit sequences, generates squashed diffs, maps hunks to original commits, writes `case.json`, `reference.json`, `staged.patch`, and `repo.tar.gz`. |
| **environment.py** | `TargetEnvManager` creates isolated venvs for target projects. `TargetEnv` wraps subprocess calls using the venv's Python and PATH. |
| **validation.py** | Applies each proposed commit as a patch, then runs: syntax check → import check → pytest (if enabled) → final-state comparison. Produces `MechanicalResult` with per-commit drill-down. |
| **scoring.py** | Computes deterministic semantic metrics: Adjusted Rand Index (reference similarity), granularity penalty, dependency recall. No LLM calls. |
| **judge.py** | Optional LLM-as-judge for subjective quality dimensions: cohesion, separation, ordering. |
| **harness.py** | Orchestrates the full eval loop: extract repo → create venv → install deps → parse patch → run agent → validate → score → save results. |
| **reporting.py** | Serializes `EvalRunResult` to JSON, loads results, compares two runs for regressions. |
| **analysis.py** | Generates: (1) Markdown analysis report, (2) ANSI terminal report with color-coded commit dots, (3) single-page HTML dashboard with interactive drill-down. |
| **config.py** | Constants: paths, suite definitions, default agent/judge config, scoring weights. |
| **cli.py** | Typer CLI: `generate`, `generate-batch`, `run`, `list`, `report`, `analyze`, `compare`, `cleanup`. |

---

## Difficulty Tiers

| Tier | Hunks | Files | Description | Example |
|------|-------|-------|-------------|---------|
| **1** | 2–5 | 1–3 | Small bug fixes, single-concern changes | Fix `iter_text` empty string bug |
| **2** | 5–15 | 2–5 | Feature + test, config changes | URL percent-escaping refactor |
| **3** | 15–40 | 5–15 | Multi-file features, cross-cutting changes | Deprecate `app=` kwarg, lazy-load deps |
| **4** | 40–100 | 10–25 | Large refactors, API redesigns | Proxy parameter overhaul |
| **5** | 100+ | 25+ | Massive rewrites, full-stack changes | `from __future__ import annotations` rollout |

---

## Test Case Structure

Each test case is a directory containing:

```
python_httpx_tier2_example/
├── case.json        # Metadata, build config, reference info
├── staged.patch     # Squashed diff (the agent's input)
├── reference.json   # Original commit decomposition (ground truth)
└── repo.tar.gz      # Snapshot of the repo at the "before" state
```

### case.json

```json
{
  "id": "python_httpx_tier2_example",
  "language": "python",
  "tier": 2,
  "description": "Move utility functions from _utils.py to _models.py",
  "source_repo": "https://github.com/encode/httpx",
  "source_commits": ["abc123def456"],
  "stats": {
    "total_hunks": 13,
    "total_files": 5,
    "reference_commit_count": 1,
    "lines_added": 42,
    "lines_removed": 38
  },
  "build_system": {
    "type": "python",
    "install_commands": ["pip install -r requirements.txt"],
    "check_command": "python -m py_compile {file}",
    "import_check": true,
    "test_command": "python -m pytest -x -q --tb=short --no-header -p no:warnings",
    "test_enabled": true
  }
}
```

---

## Generating Test Cases

### From a commit pairs JSON file (recommended)

```bash
python eval/cli.py generate-batch \
    --input-file eval/test_cases/httpx_commit_pairs.json
```

The JSON file specifies before/after SHA pairs organized by tier:

```json
{
  "repo": "https://github.com/encode/httpx",
  "install_commands": ["pip install -r requirements.txt"],
  "test_command": "python -m pytest -x -q --tb=short --no-header -p no:warnings",
  "tiers": {
    "tier1": {
      "cases": [
        {
          "id": "python_httpx_tier1_example",
          "before": "<parent-sha>",
          "after": "<commit-sha>",
          "message": "Fix bug in ...",
          "hunks": 5,
          "files": 3
        }
      ]
    }
  }
}
```

Generate specific tiers only:

```bash
python eval/cli.py generate-batch \
    --input-file eval/test_cases/httpx_commit_pairs.json \
    --tiers 1,2
```

### From a single commit range

```bash
python eval/cli.py generate \
    --repo https://github.com/encode/httpx \
    --commits "abc123^..abc123" \
    --id python_httpx_tier2_example \
    --tier 2 \
    --description "Move utility functions"
```

---

## Running Evaluations

### Suites

| Suite | Tiers Included | Use Case |
|-------|----------------|----------|
| `smoke` | 1, 2 | Quick sanity check |
| `standard` | 1, 2, 3 | Regular CI |
| `full` | All | Comprehensive evaluation |

### CLI Options

```bash
python eval/cli.py run \
    --suite full \
    --repo rich \            # Filter by source repo (e.g. 'httpx', 'rich')
    --provider google \
    --model gemini-2.5-flash \
    --max-commits 8 \
    --max-retries 2 \
    --no-agent        # Use single-shot LLM (agent module not yet implemented)
```

| Flag | Description | Default |
|------|-------------|---------|
| `--suite` | Suite to run: `smoke`, `standard`, `full` | `standard` |
| `--repo` | Filter by source repo name (e.g. `httpx`, `rich`) | None (all repos) |
| `--tier` | Filter by difficulty tier (1-5) | None (all tiers) |
| `--case` | Run a single test case by ID | None |
| `--language` | Filter by language | None |
| `--provider` | LLM provider | From config |
| `--model` | LLM model | From config |
| `--max-commits` | Max commits per plan | 8 |
| `--max-retries` | Max retries for agent | 2 |
| `--agent/--no-agent` | Use Compose Agent or single-shot LLM | `--agent` (falls back if unavailable) |
| `--judge` | Enable LLM-as-judge scoring | Off |
| `--judge-model` | Model for LLM-as-judge | From config |
| `--output-dir` | Custom output directory for results | Auto-generated |

### Output

Results are saved under `eval_results/<timestamp>/`:

```
eval_results/2026-03-14_17-17-01/
├── eval_results.json    # Machine-readable results
├── eval_logs.log        # Full evaluation logs
├── eval_analysis.md     # Detailed Markdown report
└── eval_dashboard.html  # Interactive HTML dashboard
```

---

## Validation Pipeline

For each proposed commit in the agent's plan, the validation engine runs:

```
┌─────────────────────────────────────────────────┐
│  For each commit C1..CN in the proposed plan:   │
│                                                 │
│  1. Apply patch      ──▶ patch_applies          │
│  2. Syntax check     ──▶ syntax_valid           │
│  3. Import check     ──▶ import_resolves        │
│  4. Run pytest       ──▶ tests_pass             │
│                                                 │
│  After final commit:                            │
│  5. Compare state    ──▶ final_state_matches    │
└─────────────────────────────────────────────────┘
```

- **Patch apply**: `git apply` with the commit's hunks.
- **Syntax check**: `python -m py_compile` on all touched files.
- **Import check**: `python -c "import {module}"` for all touched modules.
- **Test execution**: Full pytest run (if `test_enabled` and prior steps pass).
- **Final state**: `git diff` between the repo after all commits and the
  destination SHA. Empty diff = perfect reconstruction.

### Mechanical Pass

A case is a **mechanical pass** only if **all** commits pass **all** checks and
the final state matches the destination.

---

## Scoring

### Mechanical (60% weight)

- **full_sequence_valid**: Boolean — all commits pass all checks.
- **patch_apply_rate**: Fraction of commits where the patch applies.
- **build_pass_rate**: Fraction passing syntax checks.
- **import_integrity_rate**: Fraction passing import checks.
- **test_pass_rate**: Fraction passing pytest.
- **final_state_matches**: Whether the final repo state matches the target.

### Semantic (40% weight)

- **Reference Similarity (ARI)**: Adjusted Rand Index comparing the agent's
  hunk-to-commit grouping against the reference decomposition.
- **Granularity**: Penalizes over-splitting via `exp(1 - agent_commits / ref_commits)`.
- **Dependency Recall**: Fraction of known co-commit constraints satisfied.

### Optional: LLM-as-Judge

- **Cohesion**: Does each commit contain one logical change?
- **Separation**: Are unrelated changes in separate commits?
- **Ordering**: Are commits in a logical build order?

---

## Analysis Reports

### Terminal Report

```
══════════════════════════════════════════════════════════════════════════
  🔬  Evaluation Analysis Report
══════════════════════════════════════════════════════════════════════════
  Run:   eval_2026-03-14_17-17-01
  Agent: google/gemini-2.5-flash (Single-shot)

  Summary
  ┌──────────────┬──────────────┬──────────────┬──────────────┐
  │ Cases        │ Avg Score    │ Mech Pass    │ Score Range  │
  ├──────────────┼──────────────┼──────────────┼──────────────┤
  │ 12/12 passed │  0.753       │  4/12 (33%)  │ 0.729–0.768  │
  └──────────────┴──────────────┴──────────────┴──────────────┘

  Per-Case Results
  Legend: ● all pass  ● tests fail (build ok)  ● build/import fail
  ───────────────────────────────────────────────────────────────
   ✓   python_httpx_tier1_iter_text_fix        T  1   0.768
       commits: ● ● ●  final-state: ✓
   ✗   python_httpx_tier2_url_percent_escaping T  2   0.740
       commits: ● ● ● ● ●  final-state: ✓
```

### Markdown Report

Detailed per-case breakdown with per-commit tables, error messages, semantic
scores, and failure analysis.

### HTML Dashboard

Single-page interactive dashboard (open `eval_dashboard.html` in a browser).
Click on tiers or cases to drill down into per-commit results.

---

## Regression Tracking

Compare two runs to detect regressions:

```bash
python eval/cli.py compare \
    --current eval_results/2026-03-14_17-17-01/eval_results.json \
    --baseline eval_results/2026-03-13_22-36-26/eval_results.json
```

Reports:
- New failures (cases that passed before but fail now)
- Score regressions (score dropped by > 0.05)
- Score improvements

---

## Current Test Cases

### httpx (`encode/httpx`)

| Tier | Case ID | Hunks | Files | Description |
|------|---------|-------|-------|-------------|
| 1 | `tier1_digest_auth_cookies` | 5 | 2 | Digest auth cookie handling fix |
| 1 | `tier1_iter_text_fix` | 5 | 3 | Fix `iter_text` empty string bug |
| 1 | `tier1_streaming_multipart` | 5 | 2 | Streaming multipart content length |
| 2 | `tier2_move_utils_to_models` | 13 | 5 | Move utility functions between modules |
| 2 | `tier2_url_percent_escaping` | 8 | 2 | URL percent-escaping refactor |
| 2 | `tier2_urlescape_review` | 9 | 3 | URL escape percent-safe set review |
| 3 | `tier3_deprecate_app_kwarg` | 20 | 6 | Deprecate `app=` for WSGITransport/ASGITransport |
| 3 | `tier3_lazy_load_deps` | 16 | 7 | Lazy-load certifi and httpcore |
| 3 | `tier3_zstd_decoding` | 35 | 15 | Add zstd decoding support |
| 4 | `tier4_proxy_parameter` | 52 | 11 | Proxy parameter API overhaul |
| 4 | `tier4_url_signature_cleanup` | 41 | 5 | URL class signature cleanup |
| 5 | `tier5_future_annotations` | 225 | 25 | Add `from __future__ import annotations` |
| 5 | `tier5_sslcontext_release` | 168 | 44 | SSL context release + major refactor |

### rich (`Textualize/rich`)

| Tier | Case ID | Hunks | Files | Description |
|------|---------|-------|-------|-------------|
| 1 | `tier1_split_graphemes_loop` | 3 | 3 | Fix infinite loop in split_graphemes |
| 1 | `tier1_prompt_markup_fix` | 2 | 2 | Fix raw markup on prompt errors |
| 1 | `tier1_softwrap_background` | 3 | 2 | Fix background style with soft wrap |
| 2 | `tier2_zwj_edge_cases` | 5 | 4 | Fix ZWJ and edge cases in cell width |
| 2 | `tier2_tty_interactive` | 7 | 5 | Add TTY_INTERACTIVE env var support |
| 2 | `tier2_split_lines_terminator` | 3 | 3 | Fix split lines terminator handling |
| 3 | `tier3_markdown_styles` | 16 | 6 | Update to markdown styles |
| 3 | `tier3_cell_tests_refactor` | 14 | 6 | Refactor cell-related tests |
| 4 | `tier4_move_to_cells` | 32 | 25 | Move cell-width logic to cells.py |

---

## Adding a New Repository

1. **Clone the repo** into the eval cache:
   ```bash
   git clone --bare <url> ~/.hunknote/eval_cache/repos/<name>.git
   ```

2. **Research commit pairs** — find before/after SHAs for each tier by counting
   hunks and files in the diff.

3. **Create a commit pairs JSON** in `eval/test_cases/`:
   ```json
   {
     "repo": "https://github.com/org/repo",
     "install_commands": ["pip install -r requirements.txt"],
     "test_command": "python -m pytest -x -q --tb=short",
     "tiers": { ... }
   }
   ```

4. **Generate test cases**:
   ```bash
   python eval/cli.py generate-batch --input-file eval/test_cases/<name>_commit_pairs.json
   ```

5. **Validate** — run a smoke test to ensure deps install and tests pass:
   ```bash
   python eval/cli.py run --suite smoke
   ```

### Checklist for new test cases

- [ ] No binary files in the diff
- [ ] pytest version compatible with Python 3.12+
- [ ] All required dependencies available via `pip install`
- [ ] All optional deps that tests import are listed in `install_commands`
- [ ] Tests pass at the destination SHA with the chosen `install_commands`

---

## Tests

Unit tests live in `tests/eval/`:

```
tests/eval/
├── conftest.py          # Shared fixtures
├── test_analysis.py     # Analysis reports (markdown, terminal, HTML, run_analysis)
├── test_config.py       # Config constants and defaults
├── test_environment.py  # TargetEnv, TargetEnvManager
├── test_generator.py    # Generator utilities (content similarity, hunk mapping, JSON writes)
├── test_harness.py      # Harness helpers (_error_result)
├── test_judge.py        # LLM-as-judge
├── test_models.py       # Data model construction and serialization
├── test_registry.py     # Test case discovery and filtering
├── test_reporting.py    # Result save/load, run comparison
├── test_scoring.py      # Semantic scoring metrics
└── test_validation.py   # Mechanical validation logic
```

Run eval tests only:

```bash
python -m pytest tests/eval/ -q
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Required for OpenAI models |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Required for Google models |
| `ANTHROPIC_API_KEY` | Required for Anthropic models |

The eval module uses hunknote's LLM provider infrastructure via `litellm`.
Set the API key for whichever provider you want to use.

---

## Design Notes

- The eval module lives at the repo root (`eval/`), **not** inside `hunknote/`,
  to maintain independence. It imports from `hunknote.compose` for the compose
  planner but is otherwise self-contained.
- Target projects are validated in isolated venvs — never in hunknote's own
  environment. This prevents dependency conflicts and ensures correct mechanical
  validation.
- The Compose Agent (multi-step agentic planner) is not yet implemented. The
  eval harness falls back to the single-shot LLM compose planner with a log
  message. The `--agent/--no-agent` flag controls this.
- Test execution uses `pytest -x` (stop on first failure) with `--tb=short`
  for concise error output. Tests run after every commit, not just the final
  one, to validate that intermediate states are also buildable and testable.

