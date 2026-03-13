# Compose Agent Evaluation Framework

> **Purpose**: Systematically test and measure the Compose Agent's ability to split staged changes into correct, atomic commit sequences — across multiple languages, difficulty levels, and edge cases.
> **Key insight**: The agent's output has a mechanically verifiable ground truth (does each intermediate commit compile/parse?) AND a subjective quality dimension (are the groupings logical?). The eval must measure both.

---

## Table of Contents

1. [Evaluation Philosophy](#1-evaluation-philosophy)
2. [Test Case Generation Strategy](#2-test-case-generation-strategy)
3. [Difficulty Tiers](#3-difficulty-tiers)
4. [Language Matrix](#4-language-matrix)
5. [Metrics](#5-metrics)
6. [Evaluation Harness Architecture](#6-evaluation-harness-architecture)
7. [Test Case Schema](#7-test-case-schema)
8. [Mechanical Validation (Pass/Fail)](#8-mechanical-validation-passfail)
9. [Semantic Quality Scoring](#9-semantic-quality-scoring)
10. [Edge Case Catalog](#10-edge-case-catalog)
11. [Benchmark Suite Composition](#11-benchmark-suite-composition)
12. [Reporting and Regression Tracking](#12-reporting-and-regression-tracking)
13. [Running the Eval](#13-running-the-eval)

---

## 1. Evaluation Philosophy

### The fundamental asymmetry

There is no single "correct" answer for how to split a diff into commits. A rename refactor and a feature addition that touch overlapping files could be split as "rename first, feature second" or "feature first, rename second" — both could be valid. The original developer's commit sequence is one valid decomposition, but not the only one.

This means the eval cannot simply compare the agent's output to a reference sequence and check for exact match. Instead, it must:

1. **Mechanically verify correctness**: Does every intermediate checkpoint compile, parse, and (optionally) pass tests? This is binary — pass or fail — and is the hard constraint.
2. **Score semantic quality**: How logical, cohesive, and well-ordered are the groupings? This is a continuous score based on multiple heuristics and (optionally) LLM-as-judge evaluation.
3. **Compare against reference**: How similar is the agent's decomposition to the original developer's commits? This is informational, not pass/fail — a valid decomposition that differs from the original is still good.

### What we're NOT testing

The eval framework does NOT test:
- Commit message quality (that's a separate, simpler eval on Phase 6 alone).
- Performance/latency (measured separately via the trace infrastructure).
- Token efficiency (tracked by the trace, reported alongside quality metrics).

The eval focuses exclusively on **grouping correctness** and **grouping quality**.

---

## 2. Test Case Generation Strategy

### Approach: Squash-and-recover from real repositories

The most realistic test cases come from real commit histories. The process:

1. **Select a real open-source repository** with a clean commit history (atomic commits, good practices).
2. **Pick a contiguous sequence of N commits** (e.g., 3-8 commits spanning a feature or refactor).
3. **Record the original commit sequence** as the reference: for each commit, record its message, the list of files it touched, and the full diff.
4. **Squash the N commits into a single staging area** — this produces the input diff that the agent will see. Concretely: check out the commit before the sequence, then `git diff` against the commit after the sequence to get the combined diff.
5. **Package everything** into a self-contained test case: the repo at the "before" state, the combined staged diff, and the reference commit sequence.

This approach gives us:
- Realistic diffs with natural dependency patterns.
- A reference decomposition to compare against (the original commits).
- A repo that can actually be compiled/tested at each checkpoint.

### Synthetic augmentation

For edge cases that rarely appear naturally (e.g., circular dependencies, extremely large files, binary files mixed with code), create synthetic test cases by:

1. Starting from a minimal project skeleton.
2. Writing specific changes that exercise the edge case.
3. Defining the expected grouping explicitly.

### Source repositories

Select repositories that:
- Have clean, atomic commit histories (not squash-merge repos).
- Cover different project sizes and structures.
- Have working build systems (so mechanical validation can run compilers).
- Are open-source with permissive licenses.

Recommended sources per language (see Language Matrix below).

---

## 3. Difficulty Tiers

Each test case is tagged with a difficulty tier. The tiers are defined by the combination of hunk count, file count, and dependency complexity.

### Tier 1: Trivial (2-5 hunks, 1-2 files)

**Characteristics:**
- All changes are in the same file or two closely related files.
- Dependencies are obvious (e.g., function definition + call site in the same file).
- The "correct" grouping is usually a single commit (everything together) or two clearly separable commits.
- No cross-file dependencies.

**Purpose:** Smoke test. If the agent fails these, something is fundamentally broken.

**Example:** A Python file where one hunk adds a helper function and another hunk calls it in `main()`.

### Tier 2: Simple (5-15 hunks, 2-5 files)

**Characteristics:**
- Changes span a small number of files.
- One or two clear logical groupings (e.g., a feature + its tests, or a refactor + a bug fix).
- Cross-file dependencies exist but are straightforward (import chains, test-implementation pairs).
- The reference has 2-3 commits.

**Purpose:** Validate basic multi-file dependency detection and clustering.

**Example:** A TypeScript project where one commit adds an API endpoint and another adds unit tests for it, plus a config change.

### Tier 3: Moderate (15-40 hunks, 5-15 files)

**Characteristics:**
- Multiple independent logical changes mixed together.
- Cross-file dependencies require investigation (e.g., a renamed function referenced in 4 other files).
- Some hunks are ambiguous — they could belong to more than one logical group.
- The reference has 3-6 commits.
- May include refactors alongside features.

**Purpose:** Validate the agent's ability to disentangle interleaved changes and correctly trace cross-file dependencies.

**Example:** A Go project where a developer did a rename refactor, added a new feature, fixed a bug, and updated documentation — all staged together.

### Tier 4: Complex (40-100 hunks, 10-25 files)

**Characteristics:**
- Large-scale changes: major feature additions, big refactors, dependency upgrades.
- Deep dependency chains (A depends on B depends on C depends on D).
- Behavioral coupling: changes to implementation + corresponding test changes + corresponding documentation changes.
- Some hunks involve generated files or configuration that must accompany code changes.
- The reference has 4-8 commits.
- Context window management becomes a real concern.

**Purpose:** Stress-test the agent's investigation depth, context window efficiency, and retry/remediation capabilities.

**Example:** A Rust project where a developer refactored a core trait, updated all implementors, added a new implementor, updated tests, and modified build configuration.

### Tier 5: Extreme (100+ hunks, 25+ files)

**Characteristics:**
- Repository-wide changes: major version bumps, architecture changes, monorepo-wide refactors.
- Hundreds of hunks that need to be triaged (many are mechanical/repetitive).
- Multiple interleaved concerns that are difficult even for a human to disentangle.
- The reference has 6-12+ commits.
- This tier tests whether the agent can gracefully handle scale without degenerating.

**Purpose:** Measure scalability limits. Partial success is expected — the agent should at least produce a valid (if suboptimal) sequence, rather than failing entirely.

**Example:** A Python monorepo where a developer upgraded a major dependency, updated all import paths, fixed breaking changes, added migration code, and updated CI configuration.

---

## 4. Language Matrix

The eval suite must cover at least these languages, because they exercise different dependency detection mechanisms:

| Language | Why it matters | Dependency detection challenge |
|----------|---------------|-------------------------------|
| **Python** | Dynamic imports, `__init__.py` re-exports, decorators | `import X` doesn't mean X is defined at import site; re-exports through `__init__.py`; circular imports possible |
| **TypeScript/JavaScript** | ES modules, CommonJS, barrel exports, `node_modules` | `import`/`require` with path resolution; barrel files (`index.ts`) re-exporting; type-only imports |
| **Go** | Package-level compilation, implicit interfaces | Entire package must compile together; interfaces satisfied implicitly (no `implements` keyword); init() ordering |
| **Rust** | Strict type system, borrow checker, cargo workspaces | Trait implementations must match exactly; lifetime changes cascade; workspace-level dependencies |
| **Java** | Explicit types, interfaces, classpath | Package imports are explicit; interface/implementation coupling; annotation processors |
| **C/C++** | Header files, forward declarations, compilation units | `.h`/`.c` pairing; `#include` chains; forward declarations allow partial compilation |
| **Ruby** | Dynamic loading, monkey patching, `require` | `require` is runtime; method definitions can be split across files; reopened classes |

### Minimum coverage per language

| Language | Tier 1 | Tier 2 | Tier 3 | Tier 4 | Tier 5 | Total |
|----------|--------|--------|--------|--------|--------|-------|
| Python | 3 | 3 | 3 | 2 | 1 | 12 |
| TypeScript | 3 | 3 | 3 | 2 | 1 | 12 |
| Go | 2 | 2 | 2 | 2 | 1 | 9 |
| Rust | 2 | 2 | 2 | 2 | 1 | 9 |
| Java | 2 | 2 | 2 | 1 | 0 | 7 |
| C/C++ | 2 | 2 | 2 | 1 | 0 | 7 |
| Ruby | 2 | 2 | 1 | 1 | 0 | 6 |
| **Total** | **16** | **16** | **15** | **11** | **4** | **62** |

The initial target is **~60 test cases**. This is enough to detect regressions and compare across languages/tiers while being manageable to maintain.

---

## 5. Metrics

### 5.1 Hard Metrics (Mechanical — Binary Pass/Fail)

These are computed by actually applying the agent's proposed commits in a worktree and running validation.

| Metric | Description | How computed |
|--------|-------------|-------------|
| **Build Pass Rate** | Fraction of intermediate commits that compile/parse successfully | Apply each commit in a worktree, run `py_compile`/`tsc --noEmit`/`cargo check`/`go build` etc. on touched files |
| **Full Sequence Valid** | Does the entire proposed sequence pass all checkpoints? (binary) | AND of all individual commit validations |
| **Patch Apply Rate** | Fraction of commits whose patches apply cleanly via `git apply` | Run `git apply --check` for each commit's patch |
| **Import Integrity** | Do all import/require statements resolve at each checkpoint? | Run `python -c "import X"`, `node -e "require('./X')"`, etc. |
| **Test Pass Rate** (optional) | Do tests pass at each checkpoint? | Run test suite (or targeted subset) after each commit. Only for repos with fast test suites. |

The primary hard metric is **Full Sequence Valid**. If this is True, the agent produced a correct decomposition. Everything else is diagnostic.

### 5.2 Soft Metrics (Semantic Quality — Continuous Score)

These measure how "good" the decomposition is, beyond mere correctness.

| Metric | Description | Range | How computed |
|--------|-------------|-------|-------------|
| **Commit Cohesion** | Do hunks within each commit share a single logical purpose? | 0.0 – 1.0 | LLM-as-judge: "Do these hunks form a single logical change?" |
| **Commit Separation** | Are hunks in different commits genuinely independent concerns? | 0.0 – 1.0 | LLM-as-judge: "Should any hunks from different commits be merged?" |
| **Ordering Quality** | Is the commit order logical? (infrastructure before features, etc.) | 0.0 – 1.0 | Heuristic: check if refactors precede features, features precede tests, etc. + LLM-as-judge |
| **Reference Similarity** | How similar is the agent's grouping to the original developer's? | 0.0 – 1.0 | Adjusted Rand Index (ARI) between agent's hunk-to-commit assignment and reference assignment |
| **Granularity Score** | Did the agent split to an appropriate level? (not too many commits, not too few) | 0.0 – 1.0 | Penalty for deviating significantly from reference commit count: `1 - abs(agent_count - ref_count) / ref_count`, clamped to [0, 1] |
| **Dependency Recall** | Did the agent detect the critical cross-file dependencies? | 0.0 – 1.0 | Compare agent's Phase 2 dependency graph against known-required co-commit constraints from the reference |

### 5.3 Aggregate Scores

For each test case:
```
correctness_score = 1.0 if Full Sequence Valid else Build Pass Rate
quality_score = weighted_mean(
    cohesion=0.25,
    separation=0.20,
    ordering=0.15,
    reference_similarity=0.20,
    granularity=0.10,
    dependency_recall=0.10,
)
overall_score = 0.6 * correctness_score + 0.4 * quality_score
```

Correctness is weighted higher because a valid-but-suboptimal split is strictly better than an invalid-but-pretty one.

---

## 6. Evaluation Harness Architecture

```
eval/
├── harness.py                  # Main eval runner
├── config.py                   # Eval configuration (which tiers, languages, etc.)
├── metrics/
│   ├── mechanical.py           # Hard metrics: build pass, patch apply, import integrity
│   ├── semantic.py             # Soft metrics: cohesion, separation, ordering
│   ├── reference.py            # Reference comparison: ARI, granularity
│   └── aggregate.py            # Score aggregation and weighting
├── test_cases/
│   ├── registry.py             # Test case discovery and loading
│   ├── generator.py            # Tools for generating test cases from real repos
│   └── cases/
│       ├── python/
│       │   ├── tier1_simple_rename/
│       │   │   ├── case.json           # Test case metadata
│       │   │   ├── repo.tar.gz         # Repo snapshot at "before" state
│       │   │   ├── staged.patch        # The combined staged diff (agent input)
│       │   │   └── reference.json      # Reference commit sequence
│       │   ├── tier2_feature_plus_test/
│       │   └── ...
│       ├── typescript/
│       ├── go/
│       ├── rust/
│       ├── java/
│       ├── cpp/
│       └── ruby/
├── judges/
│   ├── llm_judge.py            # LLM-as-judge for semantic quality
│   └── prompts.py              # Judge prompts for cohesion, separation, ordering
├── reports/
│   ├── reporter.py             # Generate reports from eval results
│   ├── templates/              # HTML/Markdown report templates
│   └── results/                # Stored eval results (timestamped)
└── scripts/
    ├── generate_cases.py       # Script to generate test cases from a repo
    ├── run_eval.py             # Main eval entry point
    └── compare_runs.py         # Compare two eval runs for regression detection
```

---

## 7. Test Case Schema

Each test case is a directory containing:

### `case.json` — Metadata

```json
{
  "id": "python_tier3_flask_api_refactor",
  "language": "python",
  "tier": 3,
  "description": "Refactor Flask API: extract service layer, add pagination, update tests",
  "source_repo": "https://github.com/example/flask-app",
  "source_commits": [
    "abc1234",
    "def5678",
    "ghi9012",
    "jkl3456"
  ],
  "stats": {
    "total_hunks": 28,
    "total_files": 12,
    "reference_commit_count": 4,
    "lines_added": 340,
    "lines_removed": 120
  },
  "build_system": {
    "type": "python",
    "check_command": "python -m py_compile {file}",
    "import_check": true,
    "test_command": "pytest tests/ -x --timeout=30",
    "test_enabled": true
  },
  "known_dependencies": [
    {
      "description": "Service layer extraction requires updating all route handlers",
      "hunks_must_cocommit": ["H5_abc123", "H8_def456", "H12_ghi789"],
      "reason": "Routes import ServiceLayer which is defined by H5"
    },
    {
      "description": "Pagination helper + its test",
      "hunks_must_cocommit": ["H15_aaa111", "H22_bbb222"],
      "reason": "Test asserts on paginate() behavior changed by H15"
    }
  ],
  "tags": ["refactor", "api", "test-update", "cross-file-deps"]
}
```

### `repo.tar.gz` — Repository Snapshot

A compressed tarball of the repository at the state immediately before the commit sequence. This is the "base" that the agent's proposed patches are applied on top of.

Includes:
- Full `.git` directory (so `git apply`, `git worktree`, etc. work).
- All source files at the "before" state.
- Any build system files (package.json, Cargo.toml, go.mod, etc.).
- A `.gitignore` and any other files needed for the build to work.

### `staged.patch` — Combined Diff (Agent Input)

The full unified diff of all changes, as if the developer had staged everything and run `git diff --cached`. This is what gets parsed into hunks by the agent.

Generated by:
```bash
git diff <before_commit> <after_commit> > staged.patch
```

### `reference.json` — Reference Commit Sequence

```json
{
  "commits": [
    {
      "index": 0,
      "message": "refactor(api): Extract service layer from route handlers",
      "files": ["src/services/user_service.py", "src/routes/users.py", "src/routes/admin.py"],
      "hunk_ids": ["H1_abc123", "H5_def456", "H8_ghi789", "H12_jkl012"]
    },
    {
      "index": 1,
      "message": "feat(api): Add cursor-based pagination to list endpoints",
      "files": ["src/utils/pagination.py", "src/routes/users.py"],
      "hunk_ids": ["H15_mno345", "H18_pqr678"]
    },
    {
      "index": 2,
      "message": "test(api): Update tests for service layer and pagination",
      "files": ["tests/test_users.py", "tests/test_pagination.py"],
      "hunk_ids": ["H22_stu901", "H25_vwx234", "H27_yza567"]
    },
    {
      "index": 3,
      "message": "docs: Update API documentation for new endpoints",
      "files": ["docs/api.md"],
      "hunk_ids": ["H28_bcd890"]
    }
  ]
}
```

---

## 8. Mechanical Validation (Pass/Fail)

The mechanical validation reuses the same worktree-based approach as the agent's Phase 5a, but runs independently as part of the eval harness.

### Validation flow per test case

```python
def validate_agent_output(test_case: TestCase, agent_plan: ComposePlan) -> MechanicalResult:
    """
    1. Extract repo.tar.gz to a temp directory.
    2. Parse staged.patch into hunks (same parser as the agent).
    3. Build hunk inventory.
    4. For each commit in the agent's plan:
       a. Build the patch for this commit from its hunk IDs.
       b. git apply --check (does the patch apply?)
       c. git apply (apply it)
       d. For each touched file:
          - Syntax check (tree-sitter parse, if grammar available)
          - Compile check (language-specific)
          - Import check (language-specific)
       e. git add -A && git commit (advance state)
       f. Record pass/fail for this commit.
    5. (Optional) Run test suite at the final state.
    6. Cleanup temp directory.
    """
```

### Language-specific compile commands

```python
COMPILE_COMMANDS = {
    "python": {
        "syntax": ["python", "-m", "py_compile", "{file}"],
        "import": ["python", "-c", "import {module}"],
    },
    "typescript": {
        "syntax": ["npx", "tsc", "--noEmit", "--pretty"],
    },
    "javascript": {
        "syntax": ["node", "--check", "{file}"],
    },
    "go": {
        "syntax": ["go", "build", "./..."],
    },
    "rust": {
        "syntax": ["cargo", "check"],
    },
    "java": {
        "syntax": ["javac", "-d", "/tmp/classes", "{file}"],
    },
    "c": {
        "syntax": ["gcc", "-fsyntax-only", "{file}"],
    },
    "cpp": {
        "syntax": ["g++", "-fsyntax-only", "{file}"],
    },
    "ruby": {
        "syntax": ["ruby", "-c", "{file}"],
    },
}
```

### Result structure

```python
@dataclass
class CommitValidation:
    commit_index: int
    commit_id: str              # "C1", "C2", etc.
    patch_applies: bool
    syntax_valid: bool
    compile_passes: bool
    import_resolves: bool
    tests_pass: Optional[bool]  # None if tests not run
    errors: list[str]           # Error messages from failed checks

@dataclass
class MechanicalResult:
    full_sequence_valid: bool
    build_pass_rate: float      # Fraction of commits that compiled
    patch_apply_rate: float
    import_integrity_rate: float
    test_pass_rate: Optional[float]
    per_commit: list[CommitValidation]
    first_failure_index: Optional[int]  # Which commit first failed, if any
```

---

## 9. Semantic Quality Scoring

### 9.1 Reference Comparison (Deterministic)

**Adjusted Rand Index (ARI)** measures the similarity between two clusterings. It compares the agent's hunk-to-commit assignment against the reference's assignment.

```python
from sklearn.metrics import adjusted_rand_score

def compute_reference_similarity(
    agent_assignment: dict[str, str],    # hunk_id -> commit_id
    reference_assignment: dict[str, str], # hunk_id -> commit_id
) -> float:
    """
    Compute ARI between agent and reference groupings.
    Returns: float in [-1, 1], where 1 = identical, 0 = random, <0 = worse than random.
    We normalize to [0, 1] for the eval.
    """
    # Align hunk IDs (both should cover the same set)
    common_hunks = sorted(set(agent_assignment.keys()) & set(reference_assignment.keys()))
    agent_labels = [agent_assignment[h] for h in common_hunks]
    ref_labels = [reference_assignment[h] for h in common_hunks]
    ari = adjusted_rand_score(ref_labels, agent_labels)
    return max(0.0, ari)  # Clamp negative values to 0
```

**Granularity score** penalizes producing too many or too few commits:

```python
def compute_granularity_score(agent_count: int, reference_count: int) -> float:
    if reference_count == 0:
        return 0.0
    deviation = abs(agent_count - reference_count) / reference_count
    return max(0.0, 1.0 - deviation)
```

### 9.2 Dependency Recall (Deterministic)

Each test case has `known_dependencies` — sets of hunks that must be co-committed. The eval checks whether the agent respected these constraints.

```python
def compute_dependency_recall(
    agent_assignment: dict[str, str],
    known_deps: list[dict],
) -> float:
    """
    For each known co-commit constraint, check if the agent
    placed all required hunks in the same commit.
    Returns fraction of constraints satisfied.
    """
    if not known_deps:
        return 1.0  # No constraints to violate

    satisfied = 0
    for dep in known_deps:
        required_hunks = dep["hunks_must_cocommit"]
        commits = set(agent_assignment.get(h, "?") for h in required_hunks)
        if len(commits) == 1 and "?" not in commits:
            satisfied += 1

    return satisfied / len(known_deps)
```

### 9.3 LLM-as-Judge (for Cohesion, Separation, Ordering)

An LLM evaluates the quality of the grouping. This is more expensive but captures aspects that heuristics miss.

**Cohesion prompt:**
```
You are evaluating whether a set of code changes (hunks) form a single,
cohesive logical change.

Here is commit {C1}: "{title}"
It contains these hunks:
{for each hunk: hunk_id, file_path, intent summary}

Question: Do these hunks form a single, focused logical change?
Rate from 0.0 to 1.0:
- 1.0 = All hunks clearly belong to one logical change.
- 0.5 = Mostly cohesive but one or two hunks seem unrelated.
- 0.0 = The hunks are a grab-bag of unrelated changes.

Output ONLY a JSON object: {"score": <float>, "reason": "<brief explanation>"}
```

**Separation prompt:**
```
You are evaluating whether two commits represent genuinely independent concerns.

Commit {C1}: "{title1}"
Hunks: {hunk summaries}

Commit {C2}: "{title2}"
Hunks: {hunk summaries}

Question: Are these two commits independent? Could they be applied in either
order without affecting each other? Or should some hunks be moved between them?

Rate from 0.0 to 1.0:
- 1.0 = Completely independent concerns, correct separation.
- 0.5 = Mostly independent, but some hunks might belong in the other commit.
- 0.0 = These should clearly be merged into a single commit.

Output ONLY a JSON object: {"score": <float>, "reason": "<brief explanation>"}
```

**Ordering prompt:**
```
You are evaluating the ordering of a commit sequence.

Commit sequence:
{for each commit: C{n}: type, title, files touched}

Question: Is this ordering logical? Do infrastructure changes come before
features? Do implementations come before their tests? Are there any commits
that should clearly be reordered?

Rate from 0.0 to 1.0:
- 1.0 = Perfect logical ordering.
- 0.5 = Mostly good but one or two commits seem out of place.
- 0.0 = The ordering makes no sense.

Output ONLY a JSON object: {"score": <float>, "reason": "<brief explanation>"}
```

**Implementation notes for LLM-as-judge:**
- Use a different model than the one being evaluated (e.g., if evaluating Gemini Flash, judge with Claude Sonnet or GPT-4o).
- Run cohesion on every commit, separation on every pair of adjacent commits, ordering once on the full sequence.
- Cache judge results to avoid re-running on identical inputs.
- The judge is optional — mechanical metrics alone are sufficient for CI, but semantic scores are valuable for deeper analysis.

---

## 10. Edge Case Catalog

Beyond the tier-based test cases, include targeted edge cases that exercise specific failure modes:

### 10.1 Dependency Edge Cases

| ID | Description | Expected behavior |
|----|-------------|-------------------|
| **EC-D1** | Behavior change + test update in different files | Agent must detect bidirectional dependency, co-commit |
| **EC-D2** | Function rename with 10+ call sites across files | All rename hunks must be in same commit |
| **EC-D3** | Import added in file A, definition added in file B | Agent must detect directional dependency (B before or same as A) |
| **EC-D4** | String literal dependency (API path changed + test hardcoded path) | Agent must use ripgrep to detect string-level coupling |
| **EC-D5** | Re-export chain (`__init__.py` / `index.ts` barrel file) | Agent must trace through re-exports to find real source |
| **EC-D6** | Environment variable renamed in code + Dockerfile + CI config | Agent must detect cross-format dependency |

### 10.2 Structural Edge Cases

| ID | Description | Expected behavior |
|----|-------------|-------------------|
| **EC-S1** | New file (single hunk = entire file) | All hunks of new file stay together |
| **EC-S2** | Deleted file | Deletion hunk must follow (or co-commit with) removal of all references |
| **EC-S3** | Renamed/moved file | Rename hunk must accompany import path updates |
| **EC-S4** | Binary file alongside code changes | Binary file noted but not analyzed; grouped with related code |
| **EC-S5** | Empty commit group (all hunks are one logical change) | Agent produces a single commit, not artificial splits |
| **EC-S6** | Two completely independent changes | Agent produces two clean, non-overlapping commits |

### 10.3 Scale Edge Cases

| ID | Description | Expected behavior |
|----|-------------|-------------------|
| **EC-X1** | 50+ hunks from a find-and-replace (mechanical rename) | All grouped as one commit, no unnecessary splitting |
| **EC-X2** | 100+ hunks across 30+ files (major refactor) | Agent completes without timeout; produces valid sequence even if suboptimal |
| **EC-X3** | Single file with 20+ hunks (large file rewrite) | Hunks from same file can be split across commits if independent |
| **EC-X4** | Mix of 1-line hunks and 200-line hunks | Batching handles size variance; small hunks don't dominate LLM context |

### 10.4 Validation Edge Cases

| ID | Description | Expected behavior |
|----|-------------|-------------------|
| **EC-V1** | Agent's initial grouping fails validation, remediation fixes it | Phase 5b correctly diagnoses and reclusters; retry produces valid sequence |
| **EC-V2** | Agent needs to unlock a frozen commit | `unlock_and_recluster` action works correctly |
| **EC-V3** | Agent hallucinates a hunk ID | Validation gate catches it; reprompt produces correct grouping |
| **EC-V4** | Agent references a frozen hunk without unlocking | Validation gate catches it; reprompt fixes it |

---

## 11. Benchmark Suite Composition

The full benchmark suite combines the tier-based test cases with edge cases:

```
Total test cases: ~80

Tier-based (from Language Matrix):      62 cases
Edge cases (from Edge Case Catalog):   ~18 cases
  - Dependency:                          6 cases (EC-D1 through EC-D6)
  - Structural:                          6 cases (EC-S1 through EC-S6)
  - Scale:                               4 cases (EC-X1 through EC-X4)
  - Validation:                          4 cases (EC-V1 through EC-V4) — synthetic
                                        ─────
                                        ~82 total
```

### Suite subsets for different purposes

| Suite | Cases | Use case | Runtime |
|-------|-------|----------|---------|
| **Smoke** | Tier 1 only (16 cases) | Quick sanity check, CI on every PR | ~10 min |
| **Standard** | Tiers 1-3 + edge cases (65 cases) | Regular eval, weekly runs | ~60 min |
| **Full** | All tiers + all edge cases (~82 cases) | Comprehensive eval, before releases | ~3 hours |
| **Language-X** | All cases for language X | Language-specific debugging | varies |

---

## 12. Reporting and Regression Tracking

### Per-run report

Each eval run produces a structured report:

```json
{
  "run_id": "eval_2025-03-10_14-30-00",
  "timestamp": "2025-03-10T14:30:00Z",
  "agent_config": {
    "provider": "google",
    "model": "gemini-2.5-flash",
    "max_retries": 3,
    "max_commits": 6
  },
  "suite": "standard",
  "summary": {
    "total_cases": 65,
    "fully_valid": 52,
    "fully_valid_rate": 0.80,
    "avg_build_pass_rate": 0.92,
    "avg_quality_score": 0.74,
    "avg_overall_score": 0.81,
    "total_llm_calls": 1240,
    "total_tokens": 4500000,
    "total_duration_s": 3420
  },
  "by_tier": {
    "tier1": {"count": 16, "fully_valid_rate": 1.0, "avg_quality": 0.88},
    "tier2": {"count": 16, "fully_valid_rate": 0.94, "avg_quality": 0.79},
    "tier3": {"count": 15, "fully_valid_rate": 0.73, "avg_quality": 0.68},
    "tier4": {"count": 11, "fully_valid_rate": 0.64, "avg_quality": 0.61},
    "tier5": {"count": 4, "fully_valid_rate": 0.50, "avg_quality": 0.55},
    "edge_cases": {"count": 3, "fully_valid_rate": 0.67, "avg_quality": 0.72}
  },
  "by_language": {
    "python": {"count": 12, "fully_valid_rate": 0.83, "avg_quality": 0.77},
    "typescript": {"count": 12, "fully_valid_rate": 0.75, "avg_quality": 0.72},
    ...
  },
  "failures": [
    {
      "case_id": "go_tier4_interface_refactor",
      "failure_type": "compile_error",
      "failed_at_commit": 3,
      "error": "undefined: ServiceInterface",
      "diagnosis": "Agent placed interface definition in C4 but usage in C3"
    },
    ...
  ]
}
```

### Regression detection

```python
def detect_regressions(current_run: EvalReport, baseline_run: EvalReport,
                       threshold: float = 0.05) -> list[Regression]:
    """
    Compare two eval runs and flag regressions.

    A regression is:
    - A test case that was fully_valid in baseline but not in current.
    - A metric (per-case or aggregate) that dropped by more than threshold.

    Returns list of Regression objects with case_id, metric, old_value, new_value.
    """
```

### Stored results

Eval results are stored in `eval/reports/results/` with timestamps. The `compare_runs.py` script generates a diff report between any two runs, highlighting:
- New failures (cases that regressed from pass to fail).
- New passes (cases that improved from fail to pass).
- Score changes exceeding the threshold.
- Aggregate metric changes.

---

## 13. Running the Eval

### Test case generation

```bash
# Generate a test case from a real repo
python eval/scripts/generate_cases.py \
    --repo https://github.com/example/flask-app \
    --commits abc1234..jkl3456 \
    --language python \
    --tier 3 \
    --output eval/test_cases/cases/python/tier3_flask_api_refactor/

# This will:
# 1. Clone the repo at the commit before the range.
# 2. Generate the squashed diff (staged.patch).
# 3. Parse the original commits into reference.json.
# 4. Package everything into the test case directory.
# 5. Run a quick validation that the reference sequence itself is valid.
```

### Running the eval

```bash
# Run the smoke suite (quick)
python eval/scripts/run_eval.py --suite smoke --model gemini-2.5-flash

# Run the standard suite
python eval/scripts/run_eval.py --suite standard --model gemini-2.5-flash

# Run only Python cases
python eval/scripts/run_eval.py --suite full --language python

# Run a specific tier
python eval/scripts/run_eval.py --suite full --tier 3

# Run a specific case
python eval/scripts/run_eval.py --case python_tier3_flask_api_refactor

# Run with LLM-as-judge (slower, but includes semantic scores)
python eval/scripts/run_eval.py --suite standard --judge --judge-model claude-sonnet-4-20250514

# Compare against a baseline
python eval/scripts/compare_runs.py \
    --baseline eval/reports/results/eval_2025-03-01.json \
    --current eval/reports/results/eval_2025-03-10.json
```

### CI integration

```yaml
# In CI pipeline (e.g., GitHub Actions)
- name: Run compose agent eval (smoke)
  run: python eval/scripts/run_eval.py --suite smoke --model ${{ env.EVAL_MODEL }}
  
- name: Check for regressions
  run: |
    python eval/scripts/compare_runs.py \
      --baseline eval/reports/results/latest_baseline.json \
      --current eval/reports/results/latest.json \
      --fail-on-regression
```

### Output

Each eval run produces:
1. **JSON report** in `eval/reports/results/` (machine-readable, for regression tracking).
2. **Markdown summary** in `eval/reports/` (human-readable, for review).
3. **Per-case trace files** — the agent's trace JSON for each case (for debugging failures).

The Markdown summary includes:
- Aggregate scores by tier and language.
- A table of all failures with error messages and diagnosis.
- Score distribution histograms.
- Comparison with previous run (if available).
