# Compose Agent Evaluation Module — Build Plan

> **Target**: Add `hunknote/eval/` as an independent module for evaluating the Compose Agent's grouping accuracy and quality across multiple tiers and languages.
> **Initial scope**: Python-only evaluation using real open-source repos. Other languages are supported in code but test cases are added later.
> **Critical design constraint**: The eval harness runs in hunknote's own environment, but target projects need isolated virtual environments for mechanical validation (compile checks, import resolution, test execution).

---

## Table of Contents

1. [Python Source Repositories](#1-python-source-repositories)
2. [Virtual Environment Architecture](#2-virtual-environment-architecture)
3. [Module Map](#3-module-map)
4. [Module 1: Data Models](#module-1-data-models)
5. [Module 2: Test Case Schema and Registry](#module-2-test-case-schema-and-registry)
6. [Module 3: Test Case Generator](#module-3-test-case-generator)
7. [Module 4: Target Project Environment Manager](#module-4-target-project-environment-manager)
8. [Module 5: Mechanical Validation Engine](#module-5-mechanical-validation-engine)
9. [Module 6: Semantic Quality Scoring](#module-6-semantic-quality-scoring)
10. [Module 7: LLM-as-Judge](#module-7-llm-as-judge)
11. [Module 8: Eval Harness (Runner)](#module-8-eval-harness-runner)
12. [Module 9: Reporting and Regression Tracking](#module-9-reporting-and-regression-tracking)
13. [Module 10: CLI Entry Points](#module-10-cli-entry-points)
14. [Build Order](#build-order)
15. [Testing Strategy](#testing-strategy)

---

## 1. Python Source Repositories

These repos were selected because they have clean commit histories with atomic commits, comprehensive pytest suites, standard Python packaging (pip/poetry installable), and commit sizes ranging from trivial to massive — enabling Tier 1 through Tier 5 test case extraction from a single repo.

### Primary: `encode/httpx`

| Property | Value |
|----------|-------|
| **URL** | `https://github.com/encode/httpx` |
| **License** | BSD-3 |
| **Source files** | ~15 Python modules in `httpx/` |
| **Test files** | ~20 test files in `tests/` |
| **Test framework** | pytest |
| **Dependencies** | httpcore, certifi, idna, sniffio (minimal, pip-installable) |
| **Build tool** | hatchling (pyproject.toml) |
| **Python version** | 3.9+ |
| **Commit style** | Clean, atomic — maintainer Tom Christie writes focused single-concern commits |

**Why httpx:**
- Medium-sized codebase — large enough for interesting dependency patterns, small enough for fast validation.
- Minimal external dependencies — venv setup is fast and reliable.
- No C extensions or Rust components — pure Python, so `py_compile` and `import` checks work perfectly.
- Commit history has excellent variety: tiny doc fixes (Tier 1), feature additions with tests (Tier 2-3), transport layer refactors touching 10+ files (Tier 4), and major API redesigns (Tier 5).
- Well-tested: pytest suite runs in seconds, not minutes. This makes test-execution-as-validation practical.

**Tier coverage from httpx:**
- **Tier 1** (2-5 hunks): Bug fixes, docstring updates, single-function changes.
- **Tier 2** (5-15 hunks): New feature + test file, config changes.
- **Tier 3** (15-40 hunks): Multi-file refactors (e.g., URL model redesign, auth flow rework).
- **Tier 4** (40-100 hunks): Transport layer changes, client API redesigns touching models + transports + tests.

### Secondary: `Textualize/rich`

| Property | Value |
|----------|-------|
| **URL** | `https://github.com/Textualize/rich` |
| **License** | MIT |
| **Source files** | ~70 Python modules in `rich/` |
| **Test files** | ~50 test files in `tests/` |
| **Test framework** | pytest |
| **Dependencies** | markdown-it-py, pygments, typing-extensions (minimal) |
| **Build tool** | poetry (pyproject.toml) |
| **Python version** | 3.8+ |
| **Commit style** | Exceptionally clean — Will McGuigan writes textbook atomic commits |

**Why rich:**
- Larger codebase with deep internal cross-module dependencies (Console → Panel → Table → Text → Style — long chains).
- Will McGuigan's commit history is among the cleanest in the Python ecosystem — each commit genuinely represents one logical change.
- Tests use snapshot-based comparison (golden files), which creates interesting dependency patterns: changing rendering logic requires updating test snapshots.
- Pure Python, fast tests, easy venv setup.

**Tier coverage from rich:**
- **Tier 2-3**: New widget additions (e.g., adding `Tree` widget + tests + docs).
- **Tier 3-4**: Rendering pipeline changes (touching Console, many renderable classes, and their tests).
- **Tier 4-5**: Major refactors (e.g., Style system rework, Console API changes).

### Tertiary: `pydantic/pydantic`

| Property | Value |
|----------|-------|
| **URL** | `https://github.com/pydantic/pydantic` |
| **License** | MIT |
| **Source files** | ~50 Python modules in `pydantic/` |
| **Test files** | ~40 test files in `tests/` |
| **Test framework** | pytest |
| **Dependencies** | pydantic-core (Rust extension), typing-extensions, annotated-types |
| **Build tool** | hatchling (pyproject.toml) |
| **Python version** | 3.9+ |

**Why pydantic:**
- Large, complex codebase with deep type system interactions.
- v2 rewrite history contains massive refactors perfect for Tier 5.
- **Caveat**: pydantic-core is a Rust extension. For mechanical validation, we use `py_compile` and import checks (which work as long as pydantic-core is pip-installed). We do NOT need to compile Rust.

**Tier coverage from pydantic:**
- **Tier 4-5**: Large-scale refactors, validator system reworks, v2 migration commits.

### Summary coverage target

| Tier | httpx | rich | pydantic | Total |
|------|-------|------|----------|-------|
| 1 | 3 | 0 | 0 | 3 |
| 2 | 3 | 2 | 0 | 5 |
| 3 | 3 | 3 | 1 | 7 |
| 4 | 2 | 2 | 2 | 6 |
| 5 | 0 | 1 | 1 | 2 |
| **Total** | **11** | **8** | **4** | **23** |

23 real-repo test cases for the initial Python eval suite. Synthetic edge cases (from the Eval Framework doc) add ~10 more for ~33 total.

---

## 2. Virtual Environment Architecture

This is the critical design section. There are two distinct Python environments in play, and confusing them causes subtle, hard-to-debug failures.

### The two environments

```
┌─────────────────────────────────────────────────────┐
│ HUNKNOTE ENVIRONMENT (the eval harness runs here)   │
│                                                     │
│  Python: hunknote's own Python - venv in:           │
           ~/.cache/pypoetry/virtualenvs/hunknote...  │
│  Packages: hunknote, litellm, typer, pydantic, etc. │
│  Purpose: Runs the eval harness, the Compose Agent, │
│           LLM calls, metric computation, reporting  │
│                                                     │
│  ❌ Does NOT have httpx/rich/pydantic as deps       │
│  ❌ Cannot run target project's tests               │
│  ❌ Cannot do import checks for target project      │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ TARGET PROJECT ENVIRONMENT (per test case)          │
│                                                     │
│  Python: isolated venv created by the harness       │
│  Packages: target project's own deps                │
│            (e.g., httpcore, certifi for httpx)      │
│  Purpose: Mechanical validation ONLY                │
│           - py_compile                              │
│           - python -c "import X"                    │
│           - pytest (optional)                       │
│                                                     │
│  ❌ Does NOT have hunknote installed                │
│  ❌ Only used via subprocess calls from harness     │
└─────────────────────────────────────────────────────┘
```

### How it works in practice

```python
# The eval harness (running in hunknote's environment) does this:

# 1. Extract target repo to a temp directory
repo_dir = extract_repo("eval/test_cases/cases/python/httpx_tier3_url_model/repo.tar.gz")

# 2. Create an isolated venv for the target project
target_venv = TargetEnvManager.create_venv(
    repo_dir=repo_dir,
    project_config=test_case.build_system,
)
# This creates: {repo_dir}/.eval_venv/

# 3. Install target project dependencies
target_venv.install_deps()
# Runs: {venv_python} -m pip install -e ".[test]"
# or:   {venv_python} -m pip install -r requirements.txt
# or:   {venv_python} -m pip install httpcore certifi idna sniffio pytest

# 4. Mechanical validation uses the TARGET venv's Python
target_venv.run(["python", "-m", "py_compile", "httpx/_models.py"])
target_venv.run(["python", "-c", "import httpx._models"])
target_venv.run(["python", "-m", "pytest", "tests/", "-x", "--timeout=30"])

# 5. Cleanup
target_venv.destroy()
```

### Key design decisions

**a) Venv location**: Inside the extracted repo directory as `.eval_venv/`. This keeps everything self-contained and makes cleanup trivial (just delete the repo directory).

**b) Venv creation**: Use `python -m venv` (stdlib). No conda, no poetry, no uv — these may not be available on the evaluator's machine. The stdlib venv is always available.

**c) Dependency installation**: Each test case's `case.json` specifies how to install deps via a `build_system.install_commands` field. This is a list of pip commands that the harness runs inside the target venv. For example:
```json
{
  "build_system": {
    "type": "python",
    "install_commands": [
      "pip install -e .",
      "pip install pytest httpcore certifi idna sniffio anyio"
    ],
    "check_command": "python -m py_compile {file}",
    "import_check": true,
    "test_command": "python -m pytest tests/ -x --timeout=60",
    "test_enabled": false
  }
}
```

This is explicit rather than auto-detected. Different commits of the same project may need different deps (e.g., an older httpx version might not have had `anyio` as a dependency). The test case generator captures the correct deps at case creation time.

**d) The harness NEVER imports target project code directly.** All interaction is via subprocess calls using the target venv's Python. This prevents import conflicts (e.g., hunknote depends on pydantic v2, but the target project might be pydantic v1).

**e) Venv caching**: Creating a venv + installing deps takes 10-30 seconds. For large eval suites, we cache the base venv per project (all test cases from the same repo share the same deps). The per-case worktree is created fresh, but the venv is copied from the cached base.

```
~/.hunknote/eval_cache/
├── venvs/
│   ├── httpx_abc123/          # Cached venv for httpx at commit abc123
│   │   └── .eval_venv/
│   ├── rich_def456/
│   └── pydantic_ghi789/
└── repos/
    ├── httpx.git              # Bare clone (shared across all httpx cases)
    ├── rich.git
    └── pydantic.git
```

**f) Python version**: The target venv uses the SAME Python interpreter as hunknote (i.e., `sys.executable`). We do not attempt to use a different Python version for the target. If the target requires Python 3.12 but hunknote is on 3.11, the case is skipped with a warning.

---

## 3. Module Map

```
hunknote/eval/
├── __init__.py                 # Package exports
├── models.py                   # Data models (TestCase, EvalResult, MechanicalResult, etc.)
├── config.py                   # Eval configuration (suites, defaults)
├── registry.py                 # Test case discovery and loading
├── generator.py                # Generate test cases from real repos
├── environment.py              # Target project venv management (TargetEnvManager)
├── validation.py               # Mechanical validation engine
├── scoring.py                  # Deterministic semantic quality metrics
├── judge.py                    # LLM-as-judge scoring
├── harness.py                  # Main eval runner (orchestrates everything)
├── reporting.py                # Report generation and regression detection
├── cli.py                      # CLI entry points (generate, run, compare)
└── test_cases/
    └── cases/
        └── python/
            └── .gitkeep        # Test cases are generated, not committed
```

Additionally, eval data is stored at runtime under:
```
~/.hunknote/eval_cache/         # Cached venvs and bare repo clones
hunknote/eval_results/          # Timestamped eval run results (JSON)
```

---

## Module 1: Data Models

**File**: `hunknote/eval/models.py`

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path


class DifficultyTier(Enum):
    TIER1 = 1  # 2-5 hunks, 1-2 files
    TIER2 = 2  # 5-15 hunks, 2-5 files
    TIER3 = 3  # 15-40 hunks, 5-15 files
    TIER4 = 4  # 40-100 hunks, 10-25 files
    TIER5 = 5  # 100+ hunks, 25+ files


class Language(Enum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    CPP = "cpp"
    RUBY = "ruby"


# ── Test case definition ──

@dataclass
class BuildSystemConfig:
    """How to build and validate the target project."""
    type: str                           # "python", "typescript", etc.
    install_commands: list[str]         # Commands to install deps in target venv
    check_command: str                  # e.g. "python -m py_compile {file}"
    import_check: bool = True           # Whether to run import resolution checks
    import_command: str = 'python -c "import {module}"'
    test_command: Optional[str] = None  # e.g. "python -m pytest tests/ -x"
    test_enabled: bool = False          # Whether to run tests during validation
    python_version_min: Optional[str] = None  # e.g. "3.9"


@dataclass
class KnownDependency:
    """A known co-commit constraint in the test case."""
    description: str
    hunks_must_cocommit: list[str]  # Hunk IDs that must be in the same commit
    reason: str


@dataclass
class ReferenceCommit:
    """A single commit in the reference decomposition."""
    index: int
    message: str
    files: list[str]
    hunk_ids: list[str]


@dataclass
class TestCaseStats:
    total_hunks: int
    total_files: int
    reference_commit_count: int
    lines_added: int
    lines_removed: int


@dataclass
class TestCase:
    """A complete eval test case."""
    id: str                             # e.g. "python_httpx_tier3_url_model"
    language: Language
    tier: DifficultyTier
    description: str
    source_repo: str                    # GitHub URL
    source_commits: list[str]          # Original commit SHAs
    stats: TestCaseStats
    build_system: BuildSystemConfig
    known_dependencies: list[KnownDependency] = field(default_factory=list)
    reference_commits: list[ReferenceCommit] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def case_dir(self) -> Path:
        """Path to this test case's directory."""
        ...


# ── Eval results ──

@dataclass
class CommitValidation:
    """Validation result for a single commit in the agent's plan."""
    commit_index: int
    commit_id: str                  # "C1", "C2", etc.
    patch_applies: bool
    syntax_valid: bool
    compile_passes: bool
    import_resolves: bool
    tests_pass: Optional[bool] = None
    errors: list[str] = field(default_factory=list)


@dataclass
class MechanicalResult:
    """Mechanical validation results for the full sequence."""
    full_sequence_valid: bool
    build_pass_rate: float
    patch_apply_rate: float
    import_integrity_rate: float
    test_pass_rate: Optional[float] = None
    per_commit: list[CommitValidation] = field(default_factory=list)
    first_failure_index: Optional[int] = None


@dataclass
class SemanticScores:
    """Semantic quality scores for the agent's output."""
    reference_similarity: float     # ARI score (0-1)
    granularity: float              # Commit count deviation penalty (0-1)
    dependency_recall: float        # Fraction of known deps satisfied (0-1)
    cohesion: Optional[float] = None        # LLM-judge (0-1), None if judge not run
    separation: Optional[float] = None      # LLM-judge (0-1)
    ordering: Optional[float] = None        # LLM-judge (0-1)


@dataclass
class EvalCaseResult:
    """Complete eval result for one test case."""
    case_id: str
    tier: DifficultyTier
    language: Language
    mechanical: MechanicalResult
    semantic: SemanticScores
    overall_score: float            # Weighted combination
    agent_commit_count: int
    reference_commit_count: int
    agent_trace_path: Optional[str] = None  # Path to the agent's trace JSON
    total_llm_calls: int = 0
    total_tokens: int = 0
    duration_s: float = 0.0
    error: Optional[str] = None     # If the agent failed entirely


@dataclass
class EvalRunResult:
    """Complete eval result for one run of the suite."""
    run_id: str                     # e.g. "eval_2025-03-10_14-30-00"
    timestamp: str
    agent_config: dict              # provider, model, max_retries, etc.
    suite: str                      # "smoke", "standard", "full"
    cases: list[EvalCaseResult] = field(default_factory=list)

    def get_summary(self) -> dict: ...
    def get_by_tier(self) -> dict: ...
    def get_by_language(self) -> dict: ...
    def get_failures(self) -> list[EvalCaseResult]: ...
```

---

## Module 2: Test Case Schema and Registry

**File**: `hunknote/eval/registry.py`

Discovers and loads test cases from the file system.

```python
def discover_cases(
    base_dir: Path = None,
    language: Language = None,
    tier: DifficultyTier = None,
    tags: list[str] = None,
) -> list[TestCase]:
    """Discover test cases matching the given filters.

    Scans {base_dir}/cases/{language}/ directories for case.json files.
    Each case.json is validated against the TestCase schema.

    Args:
        base_dir: Root of test_cases directory. Default: hunknote/eval/test_cases/
        language: Filter by language (None = all).
        tier: Filter by tier (None = all).
        tags: Filter by tags (all specified tags must be present).

    Returns:
        List of TestCase objects sorted by (language, tier, id).
    """
    ...

def load_case(case_dir: Path) -> TestCase:
    """Load a single test case from its directory."""
    ...

def get_suites() -> dict[str, list[str]]:
    """Return predefined suite definitions.

    Returns:
        {"smoke": ["tier1_*"], "standard": ["tier1_*", "tier2_*", "tier3_*", "edge_*"],
         "full": ["*"]}
    """
    ...
```

### Test case directory structure (per case)

```
hunknote/eval/test_cases/cases/python/httpx_tier3_url_model/
├── case.json            # Metadata, build system config, known dependencies
├── repo.tar.gz          # Repo snapshot at "before" state (includes .git/)
├── staged.patch         # Combined diff (the agent's input)
└── reference.json       # Reference commit sequence with hunk IDs
```

**`case.json` example:**
```json
{
  "id": "python_httpx_tier3_url_model",
  "language": "python",
  "tier": 3,
  "description": "Refactor URL model: add code comments, restructure properties, update tests",
  "source_repo": "https://github.com/encode/httpx",
  "source_commits": ["e67b0dd", "c927f3e", "a1b2c3d", "f4e5d6c"],
  "stats": {
    "total_hunks": 22,
    "total_files": 8,
    "reference_commit_count": 4,
    "lines_added": 180,
    "lines_removed": 45
  },
  "build_system": {
    "type": "python",
    "install_commands": [
      "pip install -e '.[test]'",
      "pip install pytest trio trustme"
    ],
    "check_command": "python -m py_compile {file}",
    "import_check": true,
    "import_command": "python -c \"import {module}\"",
    "test_command": "python -m pytest tests/ -x --timeout=60 -q",
    "test_enabled": false,
    "python_version_min": "3.9"
  },
  "known_dependencies": [
    {
      "description": "URL.netloc property refactor + test update",
      "hunks_must_cocommit": ["H5_abc123", "H18_def456"],
      "reason": "Test asserts on new netloc format introduced by H5"
    }
  ],
  "tags": ["refactor", "model", "test-update", "cross-file-deps"]
}
```

---

## Module 3: Test Case Generator

**File**: `hunknote/eval/generator.py`

Generates test cases from real repo commit sequences using the squash-and-recover approach.

```python
def generate_case(
    repo_url: str,
    commit_range: str,          # "abc123..def456" or "abc123~4..abc123"
    case_id: str,
    language: Language,
    tier: DifficultyTier,
    description: str,
    output_dir: Path,
    build_system: BuildSystemConfig,
    known_dependencies: list[KnownDependency] = None,
    tags: list[str] = None,
) -> TestCase:
    """Generate a test case from a real repo commit sequence.

    Steps:
    1. Clone the repo (or use cached bare clone from ~/.hunknote/eval_cache/repos/).
    2. Identify the "before" commit (first parent of the range).
    3. Identify the "after" commit (last commit in the range).
    4. Extract the individual commits in the range with their diffs.
    5. Parse each commit's diff into hunks using hunknote's parser.
    6. Assign hunk IDs (H1_xxx, H2_xxx, ...) to the squashed diff.
    7. Map each hunk to its original commit (the reference assignment).
    8. Generate staged.patch: git diff <before> <after>
    9. Create repo.tar.gz: snapshot of repo at <before> state with .git included.
    10. Write case.json and reference.json.
    11. Validate: check that the reference sequence itself is valid
        (apply each original commit's hunks in order and verify).

    Returns:
        The generated TestCase object.
    """
    ...


def _clone_or_use_cached(repo_url: str) -> Path:
    """Clone repo as bare or return existing cached clone.

    Cached at ~/.hunknote/eval_cache/repos/{repo_name}.git
    """
    ...


def _extract_commit_sequence(repo_dir: Path, commit_range: str) -> list[dict]:
    """Extract individual commits with their file lists and diffs.

    Returns list of:
    {
        "sha": "abc123",
        "message": "Refactor URL model",
        "files": ["httpx/_models.py", "tests/test_models.py"],
        "diff": "<full unified diff for this commit>"
    }
    """
    ...


def _map_hunks_to_commits(
    squashed_hunks: dict,
    commit_diffs: list[dict],
) -> dict[str, str]:
    """Map each hunk in the squashed diff to its original commit.

    This is the tricky part: hunks in the squashed diff don't have a 1:1
    mapping to original commit hunks because line numbers shift. The mapping
    uses a fuzzy match strategy:

    1. Group hunks by file path.
    2. For each file, iterate through the original commits in order.
    3. For each original commit's hunks in that file, find the best-matching
       squashed hunk by comparing the changed line content (ignoring line numbers).
    4. Use Levenshtein distance on the +/- lines as the matching metric.

    Returns:
        Dict mapping squashed hunk_id -> original commit SHA.
    """
    ...
```

### CLI usage for generating cases

```bash
# Generate a Tier 3 case from httpx
python -m hunknote.eval.cli generate \
    --repo https://github.com/encode/httpx \
    --commits "e67b0dd~4..e67b0dd" \
    --id "python_httpx_tier3_url_model" \
    --language python \
    --tier 3 \
    --description "Refactor URL model with code comments and test updates" \
    --install-cmd "pip install -e '.[test]'" \
    --install-cmd "pip install pytest trio trustme"
```

**Implementation notes:**
- The generator needs network access to clone repos. It should cache bare clones to avoid re-cloning.
- Hunk-to-commit mapping is fuzzy because the squashed diff may have different line numbers than the individual commit diffs. The matching algorithm compares the actual changed content (the `+` and `-` lines), not the `@@` headers.
- The generator should validate its own output: take the reference sequence, apply each commit's hunks in order, and verify the repo compiles at each step. If the reference itself is invalid (e.g., the original commits aren't truly atomic), the case should be flagged.
- repo.tar.gz MUST include the `.git/` directory so that `git apply`, `git worktree`, etc. work.

---

## Module 4: Target Project Environment Manager

**File**: `hunknote/eval/environment.py`

This is the critical module that manages isolated virtual environments for target projects.

```python
import subprocess
import sys
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from hunknote.eval.models import BuildSystemConfig


@dataclass
class TargetEnv:
    """An isolated virtual environment for a target project."""
    repo_dir: Path              # The extracted repo directory
    venv_dir: Path              # Path to .eval_venv/ inside repo_dir
    python_path: Path           # Path to the venv's Python interpreter
    config: BuildSystemConfig
    is_ready: bool = False      # True after deps are installed

    def run(self, cmd: list[str], timeout: int = 120,
            cwd: Path = None, env_override: dict = None) -> subprocess.CompletedProcess:
        """Run a command using the target venv's Python.

        All subprocess calls for validation go through this method.
        It prepends the venv's bin/ to PATH and sets VIRTUAL_ENV.

        Args:
            cmd: Command to run. If the first element is "python", it is
                 replaced with the venv's Python interpreter path.
            timeout: Timeout in seconds.
            cwd: Working directory (default: repo_dir).
            env_override: Additional environment variables.

        Returns:
            CompletedProcess with stdout, stderr, returncode.
        """
        import os

        env = os.environ.copy()
        env["VIRTUAL_ENV"] = str(self.venv_dir)
        env["PATH"] = str(self.venv_dir / "bin") + ":" + env.get("PATH", "")
        # Remove PYTHONHOME if set (can interfere with venv activation)
        env.pop("PYTHONHOME", None)

        if env_override:
            env.update(env_override)

        # Replace "python" with the venv's Python
        if cmd and cmd[0] == "python":
            cmd = [str(self.python_path)] + cmd[1:]

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd or self.repo_dir,
            timeout=timeout,
            env=env,
        )

    def check_python_version(self) -> bool:
        """Verify the venv Python meets the minimum version requirement."""
        if not self.config.python_version_min:
            return True
        result = self.run(["python", "--version"])
        # Parse "Python 3.11.5" and compare with config.python_version_min
        ...

    def install_deps(self) -> bool:
        """Install target project dependencies in the venv.

        Runs each command from config.install_commands using the venv's pip.
        Returns True if all installations succeeded.
        """
        for cmd_str in self.config.install_commands:
            # Split the command string and run with the venv's pip
            parts = cmd_str.split()
            if parts[0] == "pip":
                parts = ["python", "-m", "pip"] + parts[1:]
            result = self.run(parts, timeout=300)  # 5 min timeout for installs
            if result.returncode != 0:
                return False
        self.is_ready = True
        return True

    def destroy(self) -> None:
        """Remove the venv directory."""
        if self.venv_dir.exists():
            shutil.rmtree(self.venv_dir)


class TargetEnvManager:
    """Manages creation, caching, and cleanup of target project environments."""

    CACHE_DIR = Path.home() / ".hunknote" / "eval_cache" / "venvs"

    @classmethod
    def create_env(cls, repo_dir: Path, config: BuildSystemConfig,
                   use_cache: bool = True) -> TargetEnv:
        """Create (or restore from cache) an isolated venv for the target project.

        Steps:
        1. Check if a cached venv exists for this repo+deps combination.
        2. If cached, copy the venv into repo_dir/.eval_venv/.
        3. If not cached:
           a. Create a new venv: python -m venv {repo_dir}/.eval_venv
           b. Upgrade pip: {venv_python} -m pip install --upgrade pip
           c. Install deps: run config.install_commands
           d. Cache the venv for future use.
        4. Return a TargetEnv instance.
        """
        venv_dir = repo_dir / ".eval_venv"

        if venv_dir.exists():
            shutil.rmtree(venv_dir)

        # Create venv using the same Python that runs hunknote
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True, capture_output=True,
        )

        # Determine Python path in the venv
        python_path = venv_dir / "bin" / "python"
        if not python_path.exists():
            python_path = venv_dir / "Scripts" / "python.exe"  # Windows

        target_env = TargetEnv(
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            python_path=python_path,
            config=config,
        )

        # Upgrade pip silently
        target_env.run(["python", "-m", "pip", "install", "--upgrade", "pip", "-q"])

        return target_env

    @classmethod
    def cleanup_all(cls) -> None:
        """Remove all cached venvs."""
        if cls.CACHE_DIR.exists():
            shutil.rmtree(cls.CACHE_DIR)
```

**Implementation notes:**
- `TargetEnv.run()` is the ONLY way validation commands interact with the target project. Every `py_compile`, `import`, and `pytest` call goes through it.
- The `run()` method replaces `"python"` in the command with the venv's actual Python path. This ensures we never accidentally use hunknote's Python.
- On Windows, the venv Python is at `Scripts/python.exe` instead of `bin/python`. Handle both.
- `install_deps` has a 5-minute timeout per command (some packages take time to install).
- The venv uses `sys.executable` (hunknote's Python) as the base interpreter. This means target projects must be compatible with hunknote's Python version. If not, the case is skipped.

---

## Module 5: Mechanical Validation Engine

**File**: `hunknote/eval/validation.py`

Applies the agent's proposed commits in a worktree and runs layered validation using the target venv.

```python
def validate_agent_plan(
    test_case: TestCase,
    agent_plan: ComposePlan,
    target_env: TargetEnv,
    repo_dir: Path,
) -> MechanicalResult:
    """Validate the agent's proposed commit sequence.

    Uses a git worktree (inside the extracted repo) to apply commits
    one at a time and run validation at each checkpoint.

    The worktree is at: {repo_dir}/.eval_worktree/
    Validation commands use target_env.run() to execute in the target venv.

    Validation layers (bail on first failure per commit):
    1. git apply --check (patch applies?)
    2. py_compile on touched .py files
    3. python -c "import X" for each touched module
    4. pytest (optional, if test_case.build_system.test_enabled)
    """
    ...

def _file_path_to_module(file_path: str, repo_dir: Path) -> Optional[str]:
    """Convert a file path to a Python module name.

    Examples:
        "httpx/_models.py"          → "httpx._models"
        "httpx/__init__.py"         → "httpx"
        "tests/test_models.py"      → "tests.test_models"
        "setup.py"                  → None (not a module)
        "docs/conf.py"              → None (not importable)

    Returns None if the file is not importable (no __init__.py chain,
    or is a top-level script).
    """
    ...

def _get_touched_files(commit, inventory) -> list[str]:
    """Get list of files touched by a commit."""
    ...
```

**Implementation notes:**
- The worktree is created at `{repo_dir}/.eval_worktree/` (not `~/.hunknote/tmp/`). This keeps it inside the test case's extracted directory for easy cleanup.
- ALL validation subprocess calls go through `target_env.run()`. This ensures they use the target venv's Python, not hunknote's.
- `_file_path_to_module()` must check that the full `__init__.py` chain exists before attempting an import. If `httpx/__init__.py` doesn't exist at the current checkpoint (because it hasn't been committed yet), don't try to import `httpx._models`.
- For `py_compile`, we compile individual files (not the whole project). This runs in <1 second.
- For import checks, set `PYTHONPATH={worktree_path}` in the env so that `import httpx` resolves to the worktree's version.
- For pytest, use `--timeout=60` and `-x` (stop on first failure) to avoid long-running test suites.

---

## Module 6: Semantic Quality Scoring

**File**: `hunknote/eval/scoring.py`

Deterministic metrics computed without LLM calls.

```python
def compute_reference_similarity(
    agent_assignment: dict[str, str],       # hunk_id -> commit_id
    reference_assignment: dict[str, str],   # hunk_id -> commit_id
) -> float:
    """Adjusted Rand Index between agent and reference groupings."""
    from sklearn.metrics import adjusted_rand_score
    ...

def compute_granularity_score(agent_count: int, reference_count: int) -> float:
    """Penalize deviation from reference commit count."""
    ...

def compute_dependency_recall(
    agent_assignment: dict[str, str],
    known_deps: list[KnownDependency],
) -> float:
    """Fraction of known co-commit constraints satisfied."""
    ...

def compute_semantic_scores(
    agent_plan: ComposePlan,
    test_case: TestCase,
    inventory: dict,
) -> SemanticScores:
    """Compute all deterministic semantic scores."""
    ...

def compute_overall_score(
    mechanical: MechanicalResult,
    semantic: SemanticScores,
) -> float:
    """Weighted combination: 60% correctness + 40% quality."""
    correctness = 1.0 if mechanical.full_sequence_valid else mechanical.build_pass_rate
    quality_components = [
        (0.25, semantic.reference_similarity),
        (0.20, semantic.dependency_recall),
        (0.20, semantic.granularity),
    ]
    # Add LLM-judge scores if available
    if semantic.cohesion is not None:
        quality_components.append((0.15, semantic.cohesion))
    if semantic.separation is not None:
        quality_components.append((0.10, semantic.separation))
    if semantic.ordering is not None:
        quality_components.append((0.10, semantic.ordering))

    # Normalize weights
    total_weight = sum(w for w, _ in quality_components)
    quality = sum(w * s for w, s in quality_components) / total_weight if total_weight > 0 else 0

    return 0.6 * correctness + 0.4 * quality
```

**Implementation notes:**
- `sklearn.metrics.adjusted_rand_score` is the only sklearn dependency. Add `scikit-learn` as an optional eval dependency.
- If sklearn is not installed, `compute_reference_similarity` returns 0.0 with a warning.

---

## Module 7: LLM-as-Judge

**File**: `hunknote/eval/judge.py`

Optional LLM-based quality scoring. Uses a different model than the one being evaluated.

```python
def judge_cohesion(
    commit_hunks: list[dict],   # [{hunk_id, file_path, intent}]
    commit_title: str,
    llm_call_fn: Callable,
) -> tuple[float, str]:
    """Rate how cohesive a single commit's hunks are (0-1)."""
    ...

def judge_separation(
    commit_a: dict,
    commit_b: dict,
    llm_call_fn: Callable,
) -> tuple[float, str]:
    """Rate whether two adjacent commits are properly separated (0-1)."""
    ...

def judge_ordering(
    commits: list[dict],
    llm_call_fn: Callable,
) -> tuple[float, str]:
    """Rate the logical ordering of the commit sequence (0-1)."""
    ...

def run_full_judge(
    agent_plan: ComposePlan,
    summaries: dict,
    llm_call_fn: Callable,
) -> dict:
    """Run all LLM-as-judge evaluations. Returns {cohesion, separation, ordering}."""
    ...
```

**Implementation notes:**
- The judge model should be different from the model being evaluated. Use `--judge-model` CLI option.
- Cache judge results keyed on the input content hash. If the same commit grouping is judged twice, return the cached score.
- Each judge call is independent and can be parallelized.

---

## Module 8: Eval Harness (Runner)

**File**: `hunknote/eval/harness.py`

Orchestrates the full evaluation for a set of test cases.

```python
def run_eval(
    cases: list[TestCase],
    agent_config: dict,         # {provider, model, max_retries, max_commits}
    judge_config: dict = None,  # {enabled, model, provider} or None
    output_dir: Path = None,
) -> EvalRunResult:
    """Run the full evaluation suite.

    For each test case:
    1. Extract repo.tar.gz to a temp directory.
    2. Create target venv and install deps.
    3. Parse staged.patch into hunks.
    4. Run the Compose Agent on the hunks.
    5. Validate the agent's output mechanically.
    6. Compute semantic quality scores.
    7. (Optional) Run LLM-as-judge.
    8. Record results.
    9. Cleanup temp directory and target venv.

    Args:
        cases: List of TestCase objects to evaluate.
        agent_config: Configuration for the Compose Agent.
        judge_config: Configuration for LLM-as-judge (None = skip).
        output_dir: Where to save results (default: hunknote/eval_results/).

    Returns:
        EvalRunResult with all case results.
    """
    ...

def _run_single_case(
    test_case: TestCase,
    agent_config: dict,
    judge_config: dict = None,
) -> EvalCaseResult:
    """Run evaluation for a single test case.

    This is the per-case logic:
    1. Extract repo to temp dir.
    2. Create TargetEnv, install deps.
    3. Parse staged.patch → file_diffs, inventory.
    4. Create LLM call function (via LiteLLM).
    5. Create and run AgentOrchestrator.
    6. If agent succeeds:
       a. Run mechanical validation (using target_env).
       b. Compute semantic scores.
       c. Optionally run LLM judge.
    7. If agent fails:
       a. Record the error and return partial result.
    8. Cleanup.
    """
    ...
```

**Per-case flow in detail:**

```python
def _run_single_case(test_case, agent_config, judge_config=None):
    import tempfile, tarfile

    # 1. Extract repo
    with tempfile.TemporaryDirectory(prefix="hunknote_eval_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"

        with tarfile.open(test_case.case_dir / "repo.tar.gz") as tar:
            tar.extractall(repo_dir)

        # 2. Create target venv
        target_env = TargetEnvManager.create_env(
            repo_dir=repo_dir,
            config=test_case.build_system,
        )

        # Check Python version compatibility
        if not target_env.check_python_version():
            return EvalCaseResult(case_id=test_case.id, error="Python version incompatible")

        # Install dependencies
        if not target_env.install_deps():
            return EvalCaseResult(case_id=test_case.id, error="Dep install failed")

        # 3. Parse staged.patch (reuse hunknote's parser)
        staged_patch = (test_case.case_dir / "staged.patch").read_text()
        from hunknote.compose import parse_unified_diff, build_hunk_inventory
        file_diffs, warnings = parse_unified_diff(staged_patch)
        inventory = build_hunk_inventory(file_diffs)

        # 4. Stage the diff in the extracted repo
        # (so the agent sees it as staged changes)
        _apply_patch_to_index(repo_dir, staged_patch)

        # 5. Run the Compose Agent
        from hunknote.compose.agent.orchestrator import AgentOrchestrator, OrchestratorConfig
        from hunknote.compose.agent.tracing import AgentTrace
        from hunknote.compose.agent.llm import create_llm_call_fn

        llm_call_fn = create_llm_call_fn(
            provider=agent_config["provider"],
            model=agent_config["model"],
            api_key=agent_config["api_key"],
        )
        trace = AgentTrace()
        orchestrator = AgentOrchestrator(
            file_diffs=file_diffs,
            inventory=inventory,
            repo_root=repo_dir,
            llm_call_fn=llm_call_fn,
            config=OrchestratorConfig(
                max_retries=agent_config.get("max_retries", 3),
                max_commits=agent_config.get("max_commits", 8),
            ),
            trace=trace,
        )

        try:
            plan = orchestrator.run()
        except Exception as e:
            return EvalCaseResult(case_id=test_case.id, error=str(e))

        # 6. Mechanical validation (using target_env!)
        mechanical = validate_agent_plan(test_case, plan, target_env, repo_dir)

        # 7. Semantic scoring
        semantic = compute_semantic_scores(plan, test_case, inventory)

        # 8. Optional LLM judge
        if judge_config and judge_config.get("enabled"):
            # ... run judge, update semantic scores
            pass

        # 9. Compute overall score
        overall = compute_overall_score(mechanical, semantic)

        return EvalCaseResult(
            case_id=test_case.id,
            tier=test_case.tier,
            language=test_case.language,
            mechanical=mechanical,
            semantic=semantic,
            overall_score=overall,
            agent_commit_count=len(plan.commits),
            reference_commit_count=test_case.stats.reference_commit_count,
            total_llm_calls=trace.get_summary()["total_llm_calls"],
            total_tokens=trace.get_summary()["total_input_tokens"] + trace.get_summary()["total_output_tokens"],
            duration_s=trace.get_summary()["total_duration_ms"] / 1000,
        )
```

---

## Module 9: Reporting and Regression Tracking

**File**: `hunknote/eval/reporting.py`

```python
def generate_report(result: EvalRunResult) -> str:
    """Generate a Markdown report from eval results."""
    ...

def save_result(result: EvalRunResult, output_dir: Path = None) -> Path:
    """Save eval result as JSON to hunknote/eval_results/{run_id}.json."""
    ...

def load_result(path: Path) -> EvalRunResult:
    """Load a previously saved eval result."""
    ...

def compare_runs(
    current: EvalRunResult,
    baseline: EvalRunResult,
    regression_threshold: float = 0.05,
) -> dict:
    """Compare two eval runs and identify regressions.

    Returns:
    {
        "new_failures": [...],     # Cases that passed in baseline but failed now
        "new_passes": [...],       # Cases that failed in baseline but pass now
        "score_regressions": [...], # Cases where score dropped > threshold
        "score_improvements": [...],
        "aggregate_diff": {...},    # Overall metric changes
    }
    """
    ...
```

---

## Module 10: CLI Entry Points

**File**: `hunknote/eval/cli.py`

Standalone CLI for the eval module. NOT integrated into hunknote's main CLI (the eval module is independent).

```python
import typer

eval_app = typer.Typer(name="eval", help="Compose Agent evaluation framework")

@eval_app.command("generate")
def generate_case_cmd(
    repo: str = typer.Option(..., help="GitHub repo URL"),
    commits: str = typer.Option(..., help="Commit range (e.g., 'abc123~4..abc123')"),
    id: str = typer.Option(..., help="Test case ID"),
    language: str = typer.Option("python", help="Language"),
    tier: int = typer.Option(3, help="Difficulty tier (1-5)"),
    description: str = typer.Option("", help="Description"),
    install_cmd: list[str] = typer.Option([], help="Pip install commands (repeatable)"),
    output_dir: str = typer.Option(None, help="Output directory"),
): ...

@eval_app.command("run")
def run_eval_cmd(
    suite: str = typer.Option("standard", help="Suite: smoke, standard, full"),
    language: str = typer.Option(None, help="Filter by language"),
    tier: int = typer.Option(None, help="Filter by tier"),
    case: str = typer.Option(None, help="Run a specific case by ID"),
    model: str = typer.Option(None, help="LLM model to use"),
    provider: str = typer.Option(None, help="LLM provider"),
    judge: bool = typer.Option(False, help="Enable LLM-as-judge"),
    judge_model: str = typer.Option(None, help="Model for LLM-as-judge"),
): ...

@eval_app.command("compare")
def compare_runs_cmd(
    baseline: str = typer.Argument(..., help="Path to baseline result JSON"),
    current: str = typer.Argument(..., help="Path to current result JSON"),
    fail_on_regression: bool = typer.Option(False, help="Exit 1 if regressions found"),
): ...

@eval_app.command("list")
def list_cases_cmd(
    language: str = typer.Option(None),
    tier: int = typer.Option(None),
): ...

# Run with: python -m hunknote.eval.cli <command>
```

---

## Build Order

Implement in this order. Each module is independently testable after completion.

| Step | Module | Depends On | Estimated Complexity |
|------|--------|------------|---------------------|
| 1 | Module 1: Data Models | Nothing | Low |
| 2 | Module 2: Registry | Module 1 | Low |
| 3 | Module 4: Environment Manager | Module 1 | High |
| 4 | Module 5: Mechanical Validation | Modules 1, 4 | High |
| 5 | Module 6: Semantic Scoring | Module 1 | Medium |
| 6 | Module 3: Test Case Generator | Modules 1, 2 | High |
| 7 | Module 7: LLM-as-Judge | Module 1 | Medium |
| 8 | Module 8: Eval Harness | All above | High |
| 9 | Module 9: Reporting | Module 1 | Medium |
| 10 | Module 10: CLI | All above | Low |
| 11 | Generate initial Python test cases | Module 3 | Manual work |

Step 3 (Environment Manager) is the highest-risk module. Get it right and test it thoroughly before building the validation engine on top of it.

---

## Testing Strategy

**Unit tests** (`tests/eval/`):

1. **Models**: Serialize/deserialize TestCase, EvalResult.
2. **Registry**: Discover cases from fixture directories, filter by language/tier.
3. **Environment Manager**: Create venv, install a trivial package, run a command, destroy. This test creates a REAL venv (not mocked) — it's the most important test.
4. **Validation**: Mock git commands and target_env.run() to test the validation loop logic. Also: one integration test with a tiny real Python project (3 files, 2 commits) that creates a real venv and validates.
5. **Scoring**: Test ARI computation, granularity score, dependency recall with fixture data.
6. **Generator**: Test commit extraction, hunk mapping. Requires network (clone a small repo).
7. **Harness**: Integration test with a minimal case (mocked agent, real venv, real validation).

**Key test fixture**: A tiny Python project (3 source files, 2 test files, pytest) with 2 known commits that can be squashed and recovered. This fixture is used for integration testing the full pipeline without network access or large repos.

**Test location**: `tests/eval/` mirroring the source structure.

---

## Additional Notes for Implementation

1. **The eval module is fully independent of the compose agent module.** It imports from `hunknote.compose` (for the parser, inventory builder, and agent orchestrator) but has no circular dependencies. It could be extracted into a separate package if needed.

2. **Network access is needed for test case generation** (cloning repos) but NOT for running the eval suite (all data is local in test_cases/).

3. **The eval module does NOT modify hunknote's CLI.** It has its own CLI entry point at `python -m hunknote.eval.cli`. It is not added to the main `hunknote` Typer app.

4. **All target project interaction goes through `TargetEnv.run()`.** Never import target project code directly. Never use hunknote's Python to compile or test target project code.

5. **venv creation uses `python -m venv` (stdlib only).** No conda, no poetry, no uv. These may not be available. The stdlib venv is guaranteed to exist.

6. **Python version compatibility**: The target venv uses the same Python interpreter as hunknote. If a target project requires a different Python version, the case is skipped with a clear warning message.

7. **`scikit-learn` is an optional dependency.** It's only needed for the Adjusted Rand Index in `scoring.py`. If not installed, reference_similarity returns 0.0 with a warning. Add it as `hunknote[eval]` optional dependency in pyproject.toml.

8. **Test case storage**: Test cases (repo.tar.gz, staged.patch, etc.) can be large (10-50 MB each). They should NOT be committed to the hunknote repo. Instead, they are generated locally by the developer and stored in `hunknote/eval/test_cases/cases/` which is in `.gitignore`. A separate distribution mechanism (e.g., a GitHub Release with test case tarballs, or a `download-cases` CLI command) can be added later.

9. **Eval results** are stored at `hunknote/eval_results/` as timestamped JSON files. These persist across runs and are used for regression detection.

10. **Parallelism**: The harness can run test cases in parallel (they are fully independent — each has its own temp directory and venv). Use `concurrent.futures.ProcessPoolExecutor` with a configurable worker count. Default to 1 (sequential) for initial implementation; add `--parallel N` CLI flag.

11. **The `_apply_patch_to_index` helper** in the harness stages the squashed diff in the extracted repo's git index so the agent sees it as staged changes. This uses:
    ```bash
    cd {repo_dir}
    git apply --cached staged.patch
    ```
    This modifies only the index (staged area), not the working tree — exactly what the agent expects.

12. **Cleanup strategy**: Each test case runs in a `tempfile.TemporaryDirectory`. If the eval crashes mid-case, the temp directory is automatically cleaned up by Python's context manager. The cached venvs and bare clones in `~/.hunknote/eval_cache/` persist and must be cleaned manually with `python -m hunknote.eval.cli cleanup`.
