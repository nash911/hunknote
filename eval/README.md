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
python eval/cli.py run --repo marshmallow --tier 3

# Run a single test case
python eval/cli.py run --case python_httpx_tier2_move_utils_to_models

# Run only tier-3 cases
python eval/cli.py run --tier 3

# Analyze a previous run
python eval/cli.py analyze eval_results/<timestamp>/eval_results.json

# Analyze with web dashboard
python eval/cli.py analyze eval_results/<timestamp>/eval_results.json --web

# Meta-analysis across multiple runs
python eval/cli.py analyze \
    eval_results/<run1>/eval_results.json \
    eval_results/<run2>/eval_results.json \
    eval_results/<run3>/eval_results.json \
    --web
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
    ├── marshmallow_commit_pairs.json  # SHA pair definitions (marshmallow)
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
            ├── python_marshmallow_tier1_*/
            ├── python_marshmallow_tier2_*/
            ├── python_marshmallow_tier3_*/
            ├── python_marshmallow_tier4_*/
            └── python_marshmallow_tier5_*/
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
| **analysis.py** | Generates: (1) Markdown analysis report, (2) ANSI terminal report with color-coded commit dots, (3) single-page HTML dashboard with interactive drill-down, (4) multi-run meta-analysis reports (Markdown, terminal, HTML) comparing consistency and failure root causes across runs. |
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
    --repo rich \            # Filter by source repo (e.g. 'httpx', 'rich', 'marshmallow')
    --provider google \
    --model gemini-2.5-flash \
    --max-commits 8 \
    --max-retries 2 \
    --no-agent        # Use single-shot LLM (agent module not yet implemented)
```

| Flag | Description | Default |
|------|-------------|---------|
| `--suite` | Suite to run: `smoke`, `standard`, `full` | `standard` |
| `--repo` | Filter by source repo name (e.g. `httpx`, `rich`, `marshmallow`) | None (all repos) |
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
- **hunk_coverage**: Fraction of inventory hunks present in the plan (1.0 = all
  hunks assigned). Detects LLM omissions (missing hunks) and hallucinations
  (hunk IDs not in the inventory).
- **missing_hunk_ids**: Inventory hunks absent from the plan.
- **hallucinated_hunk_ids**: Plan hunk IDs not in the inventory.

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

## Meta-Analysis (Multi-Run Comparison)

When multiple `eval_results.json` files are passed to the `analyze` command,
the framework performs a **meta-analysis** — comparing per-case results across
all runs to identify consistency patterns, false positives, and root causes.

### Usage

```bash
# Meta-analysis across 3 runs (terminal + Markdown)
python eval/cli.py analyze \
    eval_results/2026-03-15_15-30-13/eval_results.json \
    eval_results/2026-03-15_16-21-06/eval_results.json \
    eval_results/2026-03-15_17-37-30/eval_results.json

# With interactive HTML dashboard
python eval/cli.py analyze \
    eval_results/run1/eval_results.json \
    eval_results/run2/eval_results.json \
    eval_results/run3/eval_results.json \
    --web

# Custom output directory
python eval/cli.py analyze \
    eval_results/run1/eval_results.json \
    eval_results/run2/eval_results.json \
    --output-dir eval_results/comparison/
```

### Output

Reports are saved in the directory of the most recent (lexicographically last)
result file:

```
eval_results/2026-03-15_17-37-30/
├── eval_results.json     # Original run results
├── meta_analysis.md      # Detailed Markdown meta-analysis
└── meta_dashboard.html   # Interactive HTML dashboard (with --web)
```

### What the Meta-Analysis Reports

**Consistency Summary** — classifies every case into one of four categories:

| Category | Description |
|----------|-------------|
| **Always pass** | Mechanically passes in all N runs |
| **Consistent fail** | Mechanically fails in all N runs (genuine LLM issue) |
| **Intermittent** | Passes in some runs, fails in others (LLM non-determinism) |
| **False positive** | Tests fail at the final commit in all runs — environment issue, not LLM |

**Failure Root Cause Classification** — groups genuine failures by type:

| Root Cause | Description |
|------------|-------------|
| **Ordering** | LLM puts behavior changes and their tests in different commits |
| **Import-only** | LLM splits cross-file import dependencies |
| **Import + test** | Import failures causing cascading test failures |
| **Hunk coverage** | LLM drops hunk IDs from its output (T5 scale issue) |

**Additional sections:**
- Per-tier and per-repo consistency breakdown
- Case-by-run matrix (pass/fail per run)
- Score stability analysis (range, standard deviation across runs)
- Over-splitting analysis (single-commit refs split into 3+ commits)

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
| 4 | `tier4_drop_rfc3986_and_encoding` | 29 | 9 | Drop rfc3986, URL encoding, test cleanup (multi-commit) |
| 5 | `tier5_future_annotations` | 225 | 25 | Add `from __future__ import annotations` |
| 5 | `tier5_sslcontext_release` | 168 | 44 | SSL context release + major refactor |
| 5 | `tier5_test_framework_migration` | 119 | 16 | Replace pytest-asyncio/trio with anyio (multi-commit) |

### rich (`Textualize/rich`)

| Tier | Case ID | Hunks | Files | Description |
|------|---------|-------|-------|-------------|
| 1 | `tier1_split_graphemes_loop` | 3 | 3 | Fix infinite loop in split_graphemes |
| 1 | `tier1_prompt_markup_fix` | 2 | 2 | Fix raw markup on prompt errors |
| 1 | `tier1_softwrap_background` | 3 | 2 | Fix background style with soft wrap |
| 2 | `tier2_tty_interactive` | 7 | 5 | Add TTY_INTERACTIVE env var support |
| 2 | `tier2_split_lines_terminator` | 3 | 3 | Fix split lines terminator handling |
| 3 | `tier3_traceback_locals_options` | 21 | 4 | Expose more locals rendering options in Traceback |
| 3 | `tier3_cell_tests_refactor` | 14 | 6 | Refactor cell-related tests |
| 4 | `tier4_move_to_cells` | 32 | 25 | Move cell-width logic to cells.py |
| 4 | `tier4_fixes_and_version_bump` | 21 | 10 | Whitespace fix, double-width char fix, version bump (multi-commit) |
| 5 | `tier5_formatting_and_fixes` | 73 | 39 | Black formatting + prompt/whitespace/char fixes (multi-commit) |
| 5 | `tier5_traceback_notes` | 71 | 8 | Traceback notes rendering + console + test fixes (multi-commit) |

### marshmallow (`marshmallow-code/marshmallow`)

| Tier | Case ID | Hunks | Files | Description |
|------|---------|-------|-------|-------------|
| 1 | `tier1_constant_none_fix` | 4 | 4 | Fix Constant field rejecting None values |
| 1 | `tier1_constant_len_validation` | 5 | 4 | Fix missing constant with len validation |
| 1 | `tier1_pprint_export_fix` | 4 | 3 | Fix incorrect export of 'pprint' from __all__ |
| 2 | `tier2_many_arg_consistency` | 10 | 4 | Improve consistency of many arg with nested schema |
| 2 | `tier2_url_file_handling` | 6 | 4 | Add file handling to URL fields |
| 2 | `tier2_data_key_validation_errors` | 8 | 5 | Fix data_key handling in ValidationErrors |
| 3 | `tier3_validates_multiple_fields` | 18 | 9 | @validates accepts multiple field names |
| 3 | `tier3_load_sequence` | 18 | 5 | load accepts Sequence rather than Iterable |
| 4 | `tier4_deprecation_warnings` | 77 | 11 | Deprecation warnings for marshmallow 4 |
| 4 | `tier4_rename_pass_collection` | 34 | 6 | Rename pass_many to pass_collection |
| 4 | `tier4_remove_deprecations` | 35 | 11 | Remove deprecated APIs (multi-commit) |
| 5 | `tier5_field_generic_refactor` | 118 | 13 | Make Field a generic type; refactor inheritance |
| 5 | `tier5_ruff_rules_enable` | 149 | 25 | Enable all ruff rules except explicitly ignored |
| 5 | `tier5_dev_chores_migration` | 57 | 36 | Alabaster bump + build tooling migration (multi-commit) |

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
- [ ] Tests pass at **both** the before and after SHAs with the chosen `install_commands`
- [ ] `src/`-layout projects (e.g. marshmallow) are supported — the framework automatically adds the `src/` directory to `PYTHONPATH` during validation

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

## Per-Language Checklist for Adding Evaluation Cases

This section provides detailed, actionable checklists for adding evaluation
test cases for each planned language. These checklists encode lessons learned
from the Python evaluation case development — including common pitfalls,
false-positive sources, and environment compatibility issues.

### Universal Checklist (All Languages)

Before selecting any commit pair, verify **all** of the following:

#### Candidate Selection

- [ ] **No binary files** in the diff (`git diff --numstat | grep "^-"` should
      return nothing). Binary hunks break the patch parser.
- [ ] **No merge commits** in the range (`git log --merges <from>..<to>` should
      return nothing). Merge commits produce confusing diffs.
- [ ] **Commits after January 2023** to avoid stale dependency versions that
      don't work on modern Python/Node/Go/Rust/etc.
- [ ] **Count source-code hunks separately** from lock files, changelogs, and
      config files. A range with 90 hunks where 84 are in `poetry.lock` is not
      a meaningful T4 case. Use `git diff -U0 -- ':!*.lock' ':!CHANGELOG*'`.
- [ ] **Multi-commit T4/T5 ranges**: For higher tiers, prefer ranges spanning
      3–20 consecutive non-merge commits from the real history (not just single
      giant commits). This better tests the Compose Agent's ability to recover
      original commit boundaries from a squashed diff.

#### Endpoint Validation

- [ ] **Tests pass at the parent commit** (parent of `from_sha`). If tests
      already fail before any changes, the case will produce false negatives.
- [ ] **Tests pass at the destination commit** (`to_sha`). If tests fail at
      the target state, pytest mechanical checks will fail even with a perfect
      commit plan — a false positive.
- [ ] **Install commands produce a working environment** at both endpoints.
      Test this in an isolated venv, not your development environment.
- [ ] **The test command can be run headless** (no interactive prompts, no
      GUI dependencies, no network calls that can flake).

#### Environment-Sensitive Test Exclusions

- [ ] **Identify rendering/output-sensitive tests** that produce different
      output depending on terminal width, locale, installed fonts, or library
      versions (e.g., Pygments rendering tests in rich). Exclude these via
      `-k "not (...)"` or `--deselect` in the test command.
- [ ] **Verify `--deselect` actually works** with the project's pytest version.
      Older pytest versions may silently ignore `--deselect`. Prefer `-k` for
      maximum compatibility.
- [ ] **Pin flaky transitive dependencies** where necessary (e.g.,
      `setuptools<70` for projects that import `pkg_resources`).

#### After Generation

- [ ] Run `python eval/cli.py run --repo <name> --suite smoke` to verify the
      generated cases are loadable and evaluate without errors.
- [ ] Check that `hunk_coverage` is 1.0 — the LLM should be able to assign
      all hunks. If not, the patch may be too complex or have unmappable hunks.
- [ ] Check that `final_state_matches` is `True` for at least the easy tiers.
      If the final state doesn't match even with a perfect plan, the SHA pair
      may be invalid.

---

### Python

**Status**: ✅ Implemented — 3 repos, 41 cases (httpx, rich, marshmallow)

#### Recommended Source Repositories

| Repository | License | Why it's good | Watch out for |
|-----------|---------|---------------|---------------|
| `encode/httpx` | BSD-3 | Clean commit history, good test suite, fast tests (~20s) | `requirements.txt` based install (not `pyproject.toml` extras) |
| `Textualize/rich` | MIT | Rich (pun intended) codebase, good tier distribution | Rendering-sensitive tests fail with different Pygments/terminal versions; needs `setuptools<70` for `pkg_resources` |
| `marshmallow-code/marshmallow` | MIT | Clean `src/` layout, atomic commits, fast tests (~2s) | `src/` layout needs PYTHONPATH adjustment; uses `.[tests]` extra |

#### Install Commands Patterns

```json
// Standard pyproject.toml with extras
"install_commands": ["pip install -e '.[test]'"]

// requirements.txt based
"install_commands": ["pip install -r requirements.txt"]

// Separate install + test deps
"install_commands": ["pip install -e .", "pip install pytest attrs 'setuptools<70'"]

// src-layout projects
"install_commands": ["pip install -e '.[tests]'"]
```

#### Test Command Patterns

```json
// Basic
"test_command": "python -m pytest -x -q --tb=short --no-header -p no:warnings"

// With flaky test exclusions
"test_command": "python -m pytest -x -q --tb=short --no-header -p no:warnings -k 'not (test_title_text or test_blank_lines)'"
```

#### Python-Specific Pitfalls

1. **`pkg_resources` removal**: `setuptools>=70` removed `pkg_resources` as a
   standalone import. Projects that use `import pkg_resources` in tests need
   `pip install 'setuptools<70'` in install commands.
2. **`src/` layout**: Projects like marshmallow use `src/marshmallow/` instead
   of `marshmallow/`. The eval framework handles this by adding `src/` to
   `PYTHONPATH` during import checks, but verify this works for new repos.
3. **Optional dependencies**: If tests import optional packages (e.g., `zstd`,
   `brotli`, `trio`), those must be in `install_commands`. Otherwise, import
   checks fail — a false positive. Run the full test suite at both endpoints
   in a clean venv to catch missing optional deps.
4. **pytest version compatibility**: Some older commits may require `pytest==5.*`
   which doesn't work with Python 3.12+. Only select commits where the test
   suite is compatible with your Python version.
5. **Rendering-sensitive tests**: Tests that assert on exact terminal output
   (ANSI escape codes, box-drawing characters) can fail due to different
   Pygments versions, terminal widths, or locale settings. Exclude these.
6. **`__init__.py` re-exports**: Python's re-export pattern through
   `__init__.py` means import checks must trace the full chain. The eval
   framework already handles this, but be aware that adding/removing re-exports
   can break intermediate commits.

#### Validation Script Template (Python)

```bash
#!/bin/bash
# Validate a Python eval candidate at both endpoints
REPO_PATH=~/.hunknote/eval_cache/repos/<name>.git
WORK=/tmp/<name>_validate

git clone $REPO_PATH $WORK && cd $WORK
python -m venv .venv && source .venv/bin/activate

# Test at parent
git checkout <parent_sha>
pip install -e ".[test]" -q  # or: pip install -r requirements.txt
python -m pytest tests/ -x -q --tb=line --no-header -p no:warnings

# Test at dest
git checkout <dest_sha>
pip install -e ".[test]" -q
python -m pytest tests/ -x -q --tb=line --no-header -p no:warnings

deactivate && rm -rf $WORK
```

---

### TypeScript / JavaScript

**Status**: 🔲 Not yet implemented

#### Recommended Source Repositories

| Repository | License | Why it's good | Expected challenges |
|-----------|---------|---------------|---------------------|
| `microsoft/TypeScript` | Apache-2.0 | Canonical TS, huge codebase | Very large test suite; may need subset |
| `vercel/next.js` | MIT | Full-stack framework, monorepo | Monorepo (turbo/lerna); complex build |
| `colinhacks/zod` | MIT | Small focused library, clean commits | Good for T1-T3 |
| `trpc/trpc` | MIT | Monorepo, multiple packages | pnpm workspace; inter-package deps |
| `Effect-TS/effect` | MIT | Functional TS, deep type system | Complex types; workspace packages |
| `remix-run/react-router` | MIT | Mature, well-maintained | Monorepo (multiple packages) |

#### Install & Build Patterns

```json
// npm-based
"install_commands": ["npm ci"]
"check_command": "npx tsc --noEmit"

// pnpm workspace (monorepo)
"install_commands": ["pnpm install --frozen-lockfile"]
"check_command": "npx tsc --noEmit"

// yarn
"install_commands": ["yarn install --frozen-lockfile"]

// Monorepo with turborepo
"install_commands": ["pnpm install --frozen-lockfile", "pnpm turbo build --filter=<pkg>..."]
```

#### Test Command Patterns

```json
// Jest
"test_command": "npx jest --bail --no-coverage --silent"

// Vitest
"test_command": "npx vitest run --reporter=verbose"

// Node built-in test runner
"test_command": "node --test"
```

#### TypeScript-Specific Pitfalls

1. **Lock file churn**: `package-lock.json`, `pnpm-lock.yaml`, and `yarn.lock`
   can produce hundreds of hunks from a single `npm install`. Always count
   source hunks excluding lock files.
2. **Barrel exports** (`index.ts` files re-exporting from sub-modules): These
   are the TS equivalent of Python's `__init__.py`. A hunk that adds a new
   export to `index.ts` must co-commit with the module that defines it.
3. **Type-only imports** (`import type { Foo }`): These don't create runtime
   dependencies. The agent may incorrectly co-commit type-only imports with
   the value they reference — both orderings are valid.
4. **`node_modules` size**: Node projects can have 500MB+ `node_modules`. Use
   `npm ci` (not `npm install`) for deterministic installs, and ensure the
   repo tarball does NOT include `node_modules/`.
5. **ESM vs CommonJS**: Projects may use `"type": "module"` in `package.json`.
   Syntax checks must respect this (use `node --check` for CJS, `node
   --input-type=module` for ESM).
6. **Monorepo workspace dependencies**: In a monorepo, package A may depend on
   package B via `"workspace:*"`. Changes to B's exports must be applied before
   A can compile. The agent must detect these cross-package dependencies.
7. **Build artifacts**: Some TS projects compile to `dist/` and tests import
   from `dist/`. A `build` step may be required after applying patches.

#### Candidate Scanning Tips

```bash
# Count source-code hunks (exclude lock files, generated, config)
git diff -U0 <from>..<to> -- \
  ':!package-lock.json' ':!pnpm-lock.yaml' ':!yarn.lock' \
  ':!*.md' ':!CHANGELOG*' ':!*.json' \
  | grep "^@@" | wc -l
```

---

### Go

**Status**: 🔲 Not yet implemented

#### Recommended Source Repositories

| Repository | License | Why it's good | Expected challenges |
|-----------|---------|---------------|---------------------|
| `gohugoio/hugo` | Apache-2.0 | Large well-maintained Go project | CGO deps on some platforms |
| `cli/cli` | MIT | GitHub CLI, good commit hygiene | Tests may call external services |
| `charmbracelet/bubbletea` | MIT | Clean, focused library | Good for T1-T3 |
| `charmbracelet/lipgloss` | MIT | Terminal styling lib, small | Good for T1-T2 |
| `hashicorp/terraform` | BSL-1.1 | Massive Go project | License; very large |
| `go-chi/chi` | MIT | Lightweight router, fast tests | Good for T1-T3 |

#### Install & Build Patterns

```json
// Standard Go module
"install_commands": ["go mod download"]
"check_command": "go build ./..."

// With test dependencies
"install_commands": ["go mod download"]
```

#### Test Command Patterns

```json
// Standard
"test_command": "go test ./... -count=1 -short"

// With race detector (slower, but catches more)
"test_command": "go test -race ./... -count=1 -short"

// Specific package
"test_command": "go test ./pkg/... -count=1"
```

#### Go-Specific Pitfalls

1. **Package-level compilation**: Go compiles entire packages at once. A single
   syntax error in any file in a package blocks the entire package. This means
   intermediate commits that add a function in one file and use it in another
   file of the same package are fine — both files are compiled together.
2. **Implicit interfaces**: Go interfaces are satisfied implicitly (no
   `implements` keyword). Adding a method to an interface requires all
   implementors to be updated in the same commit (or before).
3. **`go.sum` churn**: Like lock files in other languages, `go.sum` can produce
   many hunks. Exclude from source hunk counts.
4. **`internal/` packages**: Go's `internal/` convention restricts import
   visibility. Moving code into/out of `internal/` requires updating all
   importers.
5. **Build tags**: Files with `//go:build` tags are only compiled under specific
   conditions. The syntax check command must match the evaluation environment
   (e.g., `GOOS=linux`).
6. **`init()` functions**: Go's `init()` functions run at package load time in
   dependency order. Moving `init()` between packages can change behavior.
7. **Vendor directory**: Some Go projects vendor dependencies. If the vendor
   directory is included in the diff, exclude it from hunk counting.

#### Candidate Scanning Tips

```bash
# Count source hunks (exclude go.sum, vendor, generated)
git diff -U0 <from>..<to> -- \
  ':!go.sum' ':!vendor/' ':!*_generated.go' ':!*.pb.go' \
  ':!*.md' ':!CHANGELOG*' \
  | grep "^@@" | wc -l
```

---

### Rust

**Status**: 🔲 Not yet implemented

#### Recommended Source Repositories

| Repository | License | Why it's good | Expected challenges |
|-----------|---------|---------------|---------------------|
| `BurntSushi/ripgrep` | Unlicense/MIT | Clean code, good commits | Cross-crate deps |
| `sharkdp/bat` | Apache-2.0/MIT | Well-structured, focused | Good for T1-T3 |
| `sharkdp/fd` | Apache-2.0/MIT | Small, clean | Good for T1-T2 |
| `tokio-rs/tokio` | MIT | Async runtime, workspace | Complex workspace; many crates |
| `serde-rs/serde` | Apache-2.0/MIT | Core serialization lib | Macro-heavy; proc-macro crate |
| `clap-rs/clap` | Apache-2.0/MIT | CLI argument parser | Good for T2-T4 |

#### Install & Build Patterns

```json
// Standard Cargo project
"install_commands": []  // Cargo fetches deps on build
"check_command": "cargo check --all-targets"

// Workspace
"install_commands": []
"check_command": "cargo check --workspace --all-targets"
```

#### Test Command Patterns

```json
// Standard
"test_command": "cargo test --all-targets"

// Workspace
"test_command": "cargo test --workspace"

// Skip doc tests (often slow)
"test_command": "cargo test --lib --tests"
```

#### Rust-Specific Pitfalls

1. **Borrow checker cascades**: A lifetime annotation change in a struct can
   cascade to all functions that use it. All such changes must co-commit.
2. **Trait implementations**: Adding a method to a trait requires all `impl`
   blocks to be updated. The agent must group these together.
3. **Cargo.lock churn**: Like other lock files, `Cargo.lock` can produce many
   hunks. Exclude from source hunk counts. Some projects `.gitignore` it
   (libraries) while others commit it (binaries).
4. **Procedural macros**: `proc-macro` crates must compile before their
   consumers. In a workspace, changes to a proc-macro crate must come before
   changes to crates that use it.
5. **Feature flags**: Cargo features can enable/disable code. Tests may require
   specific features: `cargo test --features full`.
6. **Build scripts** (`build.rs`): Changes to `build.rs` can affect compilation
   of the entire crate. Group with related source changes.
7. **Workspace dependency sharing**: Workspace members may share dependencies
   via `[workspace.dependencies]`. Changes to shared deps affect all members.

#### Candidate Scanning Tips

```bash
# Count source hunks (exclude Cargo.lock, target/)
git diff -U0 <from>..<to> -- \
  ':!Cargo.lock' ':!target/' ':!*.md' ':!CHANGELOG*' \
  | grep "^@@" | wc -l
```

---

### Java

**Status**: 🔲 Not yet implemented

#### Recommended Source Repositories

| Repository | License | Why it's good | Expected challenges |
|-----------|---------|---------------|---------------------|
| `google/guava` | Apache-2.0 | Clean code, excellent tests | Large; Maven build |
| `square/okhttp` | Apache-2.0 | Well-maintained HTTP client | Gradle build; Kotlin mixed in |
| `google/gson` | Apache-2.0 | Small, focused library | Good for T1-T3 |
| `apache/commons-lang` | Apache-2.0 | Utility library, clean history | Maven; straightforward |
| `spring-projects/spring-boot` | Apache-2.0 | Huge framework | Very large; complex build |
| `junit-team/junit5` | EPL-2.0 | Test framework itself | Gradle; multi-module |

#### Install & Build Patterns

```json
// Maven
"install_commands": ["mvn dependency:resolve -q"]
"check_command": "mvn compile -q -pl {module}"

// Gradle
"install_commands": ["./gradlew dependencies --quiet"]
"check_command": "./gradlew compileJava --quiet"

// Gradle wrapper
"install_commands": ["./gradlew build -x test --quiet"]
```

#### Test Command Patterns

```json
// Maven
"test_command": "mvn test -q -pl {module}"

// Gradle
"test_command": "./gradlew test --quiet"
```

#### Java-Specific Pitfalls

1. **Package imports are explicit**: Java's `import` statements explicitly name
   every class used. Adding a class in one file and importing it in another
   creates a clear dependency the agent can trace.
2. **Interface/implementation coupling**: Adding a method to a Java interface
   requires all implementing classes to add that method. The agent must detect
   this from the type hierarchy.
3. **Annotation processors**: Projects using Lombok, Dagger, or MapStruct
   generate code at compile time. The generated code isn't in the diff but
   affects compilation.
4. **Multi-module Maven/Gradle**: Large Java projects are often multi-module.
   A change in a parent module may require rebuilding child modules. The
   `check_command` must handle this (e.g., `mvn compile -pl module -am` for
   Maven's "also make" flag).
5. **JDK version**: Ensure the evaluation machine has a compatible JDK.
   Projects may require JDK 17+, 21+, etc.
6. **Resource files**: Java projects often have resources in `src/main/resources/`
   that are loaded at runtime. Changes to resources + code that reads them
   should co-commit.
7. **Test resources**: Similarly, `src/test/resources/` may contain test
   fixtures. Changes to fixtures + test code should co-commit.

#### Candidate Scanning Tips

```bash
# Count source hunks (exclude build output, IDE files, generated)
git diff -U0 <from>..<to> -- \
  ':!*.class' ':!target/' ':!build/' ':!.gradle/' \
  ':!*.md' ':!CHANGELOG*' ':!*.xml' \
  | grep "^@@" | wc -l
```

---

### C / C++

**Status**: 🔲 Not yet implemented

#### Recommended Source Repositories

| Repository | License | Why it's good | Expected challenges |
|-----------|---------|---------------|---------------------|
| `jqlang/jq` | MIT | Small C project, clean | Autotools build |
| `redis/redis` | BSD-3 | Well-structured C project | Custom Makefile; no cmake |
| `curl/curl` | MIT-like | Widely used, active history | Autotools; many #ifdefs |
| `nlohmann/json` | MIT | Header-only C++ library | Good for T1-T3 |
| `gabime/spdlog` | MIT | C++ logging, clean code | cmake build |
| `fmtlib/fmt` | MIT | C++ formatting library | cmake; good tests |

#### Install & Build Patterns

```json
// CMake
"install_commands": ["cmake -B build -DCMAKE_BUILD_TYPE=Debug", "cmake --build build -j$(nproc)"]
"check_command": "gcc -fsyntax-only -I include {file}"

// Autotools
"install_commands": ["./autogen.sh && ./configure && make -j$(nproc)"]

// Header-only (no build required for syntax check)
"install_commands": []
"check_command": "g++ -std=c++17 -fsyntax-only -I include {file}"
```

#### Test Command Patterns

```json
// CTest (cmake)
"test_command": "cd build && ctest --output-on-failure -j$(nproc)"

// Make
"test_command": "make test"

// Custom
"test_command": "./run_tests.sh"
```

#### C/C++-Specific Pitfalls

1. **Header/source pairing**: Changes to a `.h` file must co-commit with
   changes to the corresponding `.c`/`.cpp` file and all files that `#include`
   the changed header (if the header's API changed).
2. **Forward declarations**: C/C++ allows forward declarations, which means
   a function can be used before its full definition appears. This complicates
   dependency detection — the agent must understand `#include` chains.
3. **`#ifdef` conditionals**: Platform-specific code blocks mean some hunks
   are only compiled on certain platforms. The syntax check command must match
   the evaluation platform.
4. **Build system complexity**: C/C++ projects use diverse build systems
   (cmake, autotools, meson, make, bazel). Each has different incremental
   build behavior.
5. **Compilation units**: Each `.c`/`.cpp` file is compiled independently.
   A change to a `.c` file only requires recompiling that file (and relinking),
   not the entire project. But header changes cascade.
6. **Static/dynamic linking**: Library changes may require relinking. The
   eval framework should run `make` or `cmake --build` rather than just
   `gcc -fsyntax-only` for full validation.
7. **Generated files**: Some C/C++ projects generate headers (e.g., from
   `.proto` files, `.y`/`.l` parser files). These should be excluded from
   the diff or regenerated as part of the build.

#### Candidate Scanning Tips

```bash
# Count source hunks (exclude build artifacts, generated)
git diff -U0 <from>..<to> -- \
  '*.c' '*.cpp' '*.h' '*.hpp' \
  ':!build/' ':!*.o' ':!*.a' ':!*.so' \
  | grep "^@@" | wc -l
```

---

### Ruby

**Status**: 🔲 Not yet implemented

#### Recommended Source Repositories

| Repository | License | Why it's good | Expected challenges |
|-----------|---------|---------------|---------------------|
| `rails/rails` | MIT | The Ruby framework; massive | Monorepo; very large |
| `jekyll/jekyll` | MIT | Static site generator | Good size, active |
| `rubocop/rubocop` | MIT | Linter, well-structured | Good for T2-T4 |
| `rspec/rspec-core` | MIT | Testing framework itself | Multiple gems |
| `faker-ruby/faker` | MIT | Data generation, simple | Good for T1-T3 |
| `sidekiq/sidekiq` | LGPL-3.0 | Background jobs | Redis dependency |

#### Install & Build Patterns

```json
// Bundler
"install_commands": ["bundle install --quiet"]
"check_command": "ruby -c {file}"

// With specific Ruby version
"install_commands": ["bundle install --quiet"]
```

#### Test Command Patterns

```json
// RSpec
"test_command": "bundle exec rspec --fail-fast --format progress"

// Minitest
"test_command": "bundle exec rake test"

// Rails
"test_command": "bundle exec rails test"
```

#### Ruby-Specific Pitfalls

1. **Dynamic loading** (`require` is runtime): Ruby's `require` executes at
   runtime, not compile time. A missing `require` may not cause an error until
   the code path is exercised. Syntax checks (`ruby -c`) only validate syntax,
   not that all required files exist.
2. **Monkey patching / open classes**: Ruby allows reopening classes across
   files. A hunk in `core_ext/string.rb` that adds methods to `String` can
   affect any file that uses strings. The agent may not detect this coupling.
3. **Gemfile.lock churn**: Like other lock files, `Gemfile.lock` can produce
   many hunks. Exclude from source hunk counts.
4. **Rails autoloading**: Rails projects use autoloading (Zeitwerk) which
   resolves dependencies lazily. The syntax check (`ruby -c`) won't catch
   missing constants — only the test suite will.
5. **RSpec shared contexts**: RSpec shared contexts/examples can create
   non-obvious dependencies between test files. Changes to shared contexts
   must co-commit with tests that use them.
6. **Bundler platform issues**: `Gemfile.lock` may have platform-specific
   entries. Running `bundle install` on a different platform may fail.
   Use `bundle lock --add-platform x86_64-linux` if needed.
7. **Ruby version sensitivity**: Ruby projects may require specific Ruby
   versions. Check `.ruby-version` or `Gemfile` for version constraints.

#### Candidate Scanning Tips

```bash
# Count source hunks (exclude lock files, vendor)
git diff -U0 <from>..<to> -- \
  ':!Gemfile.lock' ':!vendor/' ':!*.md' ':!CHANGELOG*' \
  | grep "^@@" | wc -l
```

---

### Monorepo Considerations

Monorepos present unique challenges not covered by single-package checklists.
Many popular open-source projects use monorepo structures (e.g., Next.js, trpc,
Rails, Tokio, Terraform).

#### Monorepo Types

| Type | Examples | Package Manager | Key Challenge |
|------|----------|-----------------|---------------|
| **JS/TS workspace** | next.js, trpc, effect | pnpm/yarn/npm workspaces | Inter-package dependency resolution |
| **Cargo workspace** | tokio, serde | Cargo | Workspace-level `Cargo.toml` dependencies |
| **Go modules** | terraform | Go modules | Multiple `go.mod` files |
| **Rails engines** | rails/rails | Bundler | Each engine is a separate gem |
| **Bazel** | Various Google-style | Bazel | Build graph; BUILD files |
| **Python namespace pkgs** | Various | pip/poetry | Namespace packages; shared deps |

#### Monorepo-Specific Checklist

- [ ] **Identify the package manager and workspace tool** (pnpm, yarn,
      turbo, lerna, cargo, etc.) and use the correct install command.
- [ ] **Test command must target the right packages**: In a monorepo, running
      tests for the entire workspace may be too slow. Use filters:
      - pnpm: `pnpm --filter <pkg> test`
      - turbo: `turbo test --filter=<pkg>`
      - cargo: `cargo test -p <crate>`
      - go: `go test ./<module>/...`
- [ ] **Cross-package dependencies**: If a commit range touches multiple
      packages, the build order matters. Package A may depend on package B —
      changes to B's API must be applied before A can compile.
- [ ] **Shared configuration**: Monorepos often have root-level config files
      (`tsconfig.base.json`, `[workspace.dependencies]` in Cargo.toml,
      `.eslintrc`). Changes to these affect all packages but are logically
      distinct from package-specific changes.
- [ ] **Independent packages**: If a commit range touches packages that have
      no dependency relationship, changes to each package can be in separate
      commits in any order. The agent should detect this independence.
- [ ] **Lock file impact**: In a monorepo, lock file changes can be massive
      (thousands of lines). Always exclude lock files from hunk counting.
- [ ] **Selective testing**: Only test packages that are touched by the diff,
      not the entire workspace. This keeps test times manageable and avoids
      flaky tests from unrelated packages.
- [ ] **Build dependency graph**: Before selecting candidates, understand the
      workspace's dependency graph. Use `pnpm ls --json`, `cargo tree`, or
      equivalent to map inter-package dependencies.
- [ ] **Root vs package changes**: Distinguish between changes to root-level
      files (CI config, root package.json, workspace config) and package-level
      changes. Root changes should typically be in their own commit.

#### Monorepo Validation Script Template

```bash
#!/bin/bash
# Validate a monorepo eval candidate

# For a pnpm workspace:
git checkout <parent_sha>
pnpm install --frozen-lockfile
pnpm --filter "<affected-pkg>..." test  # Test affected packages + dependents

# For a Cargo workspace:
git checkout <parent_sha>
cargo test -p <affected-crate>

# For a Go multi-module:
git checkout <parent_sha>
cd <module-dir>
go test ./...
```

---

### Language Maturity Roadmap

The following table tracks which languages have evaluation cases and their
recommended next steps:

| Language | Status | Repos | Cases | Next Step |
|----------|--------|-------|-------|-----------|
| Python | ✅ Done | 3 | 41 | Maintain; add edge cases |
| TypeScript | 🔲 Planned | 0 | 0 | Select repos; add T1-T3 first |
| Go | 🔲 Planned | 0 | 0 | Select repos; add T1-T3 first |
| Rust | 🔲 Planned | 0 | 0 | Select repos; add T1-T3 first |
| Java | 🔲 Planned | 0 | 0 | Select repos; add T1-T3 first |
| C/C++ | 🔲 Planned | 0 | 0 | Select repos; add T1-T3 first |
| Ruby | 🔲 Planned | 0 | 0 | Select repos; add T1-T3 first |

**Recommended addition order**: TypeScript → Go → Rust → Java → C/C++ → Ruby.
TypeScript is the highest priority because it exercises the barrel-export and
ESM/CJS dependency detection paths that are fundamentally different from Python.

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

