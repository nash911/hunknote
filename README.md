# Hunknote

Transform messy working trees into clean, atomic commit stacks with AI.

## Features

- **Compose mode**: Split working tree changes into a clean stack of atomic commits automatically — the killer feature
- **Automatic commit message generation** from staged git changes
- **Smart caching**: Reuses generated messages for the same staged changes (no redundant API calls)
- **Multi-LLM support**: Anthropic, OpenAI, Google Gemini, Mistral, Cohere, Groq, and OpenRouter
- **Commit style profiles**: Default, Blueprint (structured sections), Conventional Commits, Ticket-prefixed, and Kernel-style
- **Smart scope inference**: Automatically detect scope from file paths (monorepo, path-prefix, mapping)
- **Intelligent type selection**: Automatically selects the correct commit type (feat, fix, docs, test, merge, etc.)
- **Intent channel**: Provide explicit motivation/context with `--intent` to guide commit message framing
- **Merge state detection**: Automatically detects merge commits and conflict resolutions
- **Structured output**: Title line + bullet-point body following git best practices
- **Raw JSON debugging**: Inspect the raw LLM response with `--json` flag
- **Intelligent context**: Distinguishes between new files and modified files for accurate descriptions
- **Editor integration**: Review and edit generated messages before committing
- **One-command commits**: Generate and commit in a single step with confirmation prompt
- **Configurable ignore patterns**: Exclude lock files, build artifacts, etc. from diff analysis
- **Debug mode**: Inspect cache metadata, token usage, scope inference, and file change details
- **Comprehensive test suite**: 818+ unit tests covering all modules

## Installation

### Option 1: Install from PyPI (Recommended)

```bash
# Using pipx (recommended - installs in isolated environment)
pipx install hunknote

# Or using pip
pip install hunknote
```

### Option 2: Install from Source

```bash
# Clone the repository
git clone <repo-url>
cd hunknote

# Install with Poetry (requires Python 3.12+)
poetry install

# Or install in development mode with test dependencies
poetry install --with dev
```

### Verify Installation

```bash
# Check that hunknote is available
hunknote --help

# Check git subcommand works
git hunknote --help
```

## Quick Start

```bash
# Initialize configuration (interactive setup)
hunknote init
# This will prompt you to:
# 1. Select an LLM provider (Anthropic, OpenAI, Google, etc.)
# 2. Choose a model
# 3. Enter your API key

# Stage your changes
git add <files>

# Generate a commit message
hunknote

# Edit the message (optional)
hunknote -e

# Commit with the generated message
hunknote commit

# Or commit immediately without confirmation
hunknote commit -y
```

## Configuration

### Initial Setup

Run the interactive configuration wizard:

```bash
hunknote init
```

This creates a global configuration at `~/.hunknote/` with:
- `config.yaml` - Provider, model, and preference settings
- `credentials` - Securely stored API keys (read-only permissions)

### Managing Configuration

View current configuration:

```bash
hunknote config show
```

Change provider or model:

```bash
# Interactive model selection
hunknote config set-provider google

# Or specify model directly
hunknote config set-provider anthropic --model claude-sonnet-4-20250514
```

Update API keys:

```bash
hunknote config set-key google
hunknote config set-key anthropic
```

List available providers and models:

```bash
hunknote config list-providers
hunknote config list-models google
hunknote config list-models  # Show all providers and models
```

### Manual Configuration

Alternatively, you can manually edit `~/.hunknote/config.yaml`:

```yaml
provider: google
model: gemini-2.0-flash
max_tokens: 1500
temperature: 0.3
editor: gedit  # Optional: preferred editor for -e flag

default_ignore:  # Optional: patterns to ignore in all repos
  - poetry.lock
  - package-lock.json
  - "*.min.js"
```

And add API keys to `~/.hunknote/credentials`:

```
GOOGLE_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key
```

### Setting Up API Keys (Alternative Methods)

API keys are checked in this order:
1. Environment variables (highest priority - useful for CI/CD)
2. `~/.hunknote/credentials` file (recommended for local development)
3. Project `.env` file (lowest priority)

Set via environment variable:

```bash
# Anthropic
export ANTHROPIC_API_KEY=your_key_here

# OpenAI
export OPENAI_API_KEY=your_key_here

# Google Gemini
export GOOGLE_API_KEY=your_key_here

# Mistral
export MISTRAL_API_KEY=your_key_here

# Cohere
export COHERE_API_KEY=your_key_here

# Groq
export GROQ_API_KEY=your_key_here

# OpenRouter (access to 200+ models)
export OPENROUTER_API_KEY=your_key_here
```

Or create a `.env` file in your project root.

### Supported Providers and Models

| Provider | Models | API Key Variable |
|----------|--------|------------------|
| **Anthropic** | claude-sonnet-4-20250514, claude-3-5-sonnet-latest, claude-3-5-haiku-latest, claude-3-opus-latest | `ANTHROPIC_API_KEY` |
| **OpenAI** | gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, gpt-4o-mini, gpt-4-turbo | `OPENAI_API_KEY` |
| **Google** | gemini-3-pro-preview, gemini-2.5-pro, gemini-3-flash-preview, gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash, gemini-2.0-flash-lite | `GOOGLE_API_KEY` |
| **Mistral** | mistral-large-latest, mistral-medium-latest, mistral-small-latest, codestral-latest | `MISTRAL_API_KEY` |
| **Cohere** | command-r-plus, command-r, command | `COHERE_API_KEY` |
| **Groq** | llama-3.3-70b-versatile, llama-3.1-8b-instant, mixtral-8x7b-32768 | `GROQ_API_KEY` |
| **OpenRouter** | 200+ models (anthropic/claude-sonnet-4, openai/gpt-4o, google/gemini-2.0-flash-exp, meta-llama/llama-3.3-70b-instruct, deepseek/deepseek-chat, qwen/qwen-2.5-72b-instruct, etc.) | `OPENROUTER_API_KEY` |

## Usage

### Basic Usage

Stage your changes and generate a commit message:

```bash
git add <files>
hunknote
```

### Command Options

| Flag | Description |
|------|-------------|
| `-e, --edit` | Open the generated message in an editor for manual edits |
| `-r, --regenerate` | Force regenerate, ignoring cached message |
| `-d, --debug` | Show full cache metadata (staged files, tokens, diff preview, scope inference) |
| `-j, --json` | Show the raw JSON response from the LLM for debugging |
| `-i, --intent` | Provide explicit intent/motivation to guide commit message framing |
| `--intent-file` | Load intent text from a file |
| `--style` | Override commit style profile (default, blueprint, conventional, ticket, kernel) |
| `--scope` | Force a scope for the commit message (use 'auto' for inference) |
| `--no-scope` | Disable scope even if profile supports it |
| `--scope-strategy` | Scope inference strategy (auto, monorepo, path-prefix, mapping, none) |
| `--ticket` | Force a ticket key (e.g., PROJ-123) for ticket-style commits |
| `--max-diff-chars` | Maximum characters for staged diff (default: 50000) |

### Commit Subcommand

Use `hunknote commit` to commit using the generated message:

```bash
# Commit with the cached message (prompts for confirmation)
hunknote commit

# Commit immediately without confirmation (for CI/scripts)
hunknote commit -y
hunknote commit --yes
```

### Scope Inference

Hunknote automatically infers scope from your staged files for consistent commit messages:

```bash
# Automatic scope inference (default)
hunknote --style conventional   # feat(api): Add endpoint

# Force a specific scope
hunknote --scope auth --style conventional

# Disable scope
hunknote --no-scope --style conventional

# Choose inference strategy
hunknote --scope-strategy monorepo --style conventional
hunknote --scope-strategy path-prefix --style conventional
```

**Supported strategies:**
- **auto** (default): Tries all strategies in order
- **monorepo**: Infer from `packages/`, `apps/`, `libs/` directories
- **path-prefix**: Use the most common path segment
- **mapping**: Use explicit path-to-scope mapping in config
- **none**: Disable scope inference

### Intent Channel

When the diff alone doesn't convey the "why" behind your changes, use the intent channel to provide context:

```bash
# Provide intent directly
hunknote --intent "Fix race condition in session handling"

# Load intent from a file
hunknote --intent-file ./commit-intent.txt

# Combine both (concatenated with blank line)
hunknote --intent "Primary motivation" --intent-file ./additional-context.txt
```

The intent guides the LLM's framing of the commit message while keeping technical claims constrained to what's actually in the diff. Useful for:
- Explaining non-obvious changes
- Providing business context
- Guiding the narrative when the diff is ambiguous

### Commit Style Profiles

Hunknote supports multiple commit message formats to match your team's conventions:

```bash
# List available profiles
hunknote style list

# Show details about a profile
hunknote style show blueprint

# Set default style globally
hunknote style set blueprint

# Set style for current repo only
hunknote style set ticket --repo

# Override style for a single run
hunknote --style blueprint --scope api
hunknote --style conventional --scope api
hunknote --style ticket --ticket PROJ-123 -e -c
```

#### Available Profiles

| Profile | Format                       | Description |
|---------|------------------------------|-------------|
| **default** | `<Title>\n\n- <bullet>`      | Simple title + bullet points |
| **blueprint** | `<type>(<scope>): <title>\n\n<summary>\n\nChanges:\n- ...` | Structured sections (Changes, Implementation, Testing, Documentation, Notes) |
| **conventional** | `<type>(<scope>): <subject>` | Conventional Commits format |
| **ticket** | `<KEY-123> <subject>`       | Ticket-prefixed format |
| **kernel** | `<subsystem>: <subject>`     | Linux kernel style |

### Ignore Pattern Management

Manage which files are excluded from the diff sent to the LLM:

```bash
# List all ignore patterns
hunknote ignore list

# Add a new pattern
hunknote ignore add "*.log"
hunknote ignore add "build/*"
hunknote ignore add "dist/*"

# Remove a pattern
hunknote ignore remove "*.log"
```

### Configuration Commands

Manage global configuration stored in `~/.hunknote/`:

```bash
# View current configuration
hunknote config show

# Set or update API key for a provider
hunknote config set-key google
hunknote config set-key anthropic

# Change provider and model
hunknote config set-provider google
hunknote config set-provider anthropic --model claude-sonnet-4-20250514

# List available providers
hunknote config list-providers

# List models for a specific provider
hunknote config list-models google

# List all providers and their models
hunknote config list-models
```

### Examples

```bash
# Generate commit message (print only, cached for reuse)
hunknote

# Generate and open in editor
hunknote -e

# Generate commit message
hunknote

# Commit with the generated message (prompts for confirmation)
hunknote commit

# Commit immediately without confirmation (for CI/scripts)
hunknote commit -y

# Edit message before committing
hunknote -e
hunknote commit

# Force regeneration (ignore cache)
hunknote -r

# Debug: view cache metadata, token usage, and scope inference
hunknote -d

# View raw JSON response from LLM
hunknote -j

# Force regenerate and view raw JSON
hunknote -r -j

# Use conventional commits style with scope
hunknote --style conventional --scope api

# Use blueprint style for detailed commit messages
hunknote --style blueprint

# Use ticket-prefixed style
hunknote --style ticket --ticket PROJ-6767
hunknote commit

# Force kernel style for this commit
hunknote --style kernel --scope auth

# Provide intent to guide the commit message
hunknote --intent "Fix memory leak in connection pool"

# Load intent from a file
hunknote --intent-file ./intent.txt
hunknote commit -y
```

### Git Subcommand

You can also use it as a git subcommand:

```bash
git hunknote
git hunknote -e
git hunknote commit
git hunknote commit -y
```

## Compose Mode (Commit Stacking)

Split messy working tree changes into a clean stack of atomic commits:

```bash
# Preview the proposed commit stack (plan-only, no changes)
hunknote compose

# Execute the plan and create commits
hunknote compose --commit

# Skip confirmation prompt
hunknote compose --commit --yes

# Limit to 3 commits
hunknote compose --max-commits 3

# Use a specific style
hunknote compose --style conventional

# Force regenerate (ignore cache)
hunknote compose -r

# Show cached compose plan JSON
hunknote compose -j

# Load plan from external file
hunknote compose --from-plan my_plan.json --commit

# Debug mode: show inventory and patch details
hunknote compose --debug
```

### What Compose Does

1. **Collects all tracked changes** (staged + unstaged) from `git diff HEAD`
2. **Parses the diff** into files and hunks with stable IDs
3. **Asks the LLM** to split changes into logical, atomic commits
4. **Validates the plan** (no duplicate hunks, all hunks assigned, etc.)
5. **Optionally executes** by applying patches and creating commits

### Safety Features

- **Plan-only by default**: Does not modify git state unless `--commit` is passed
- **Pre-execution snapshot**: Saves staged state before committing for recovery
- **Best-effort restore**: Attempts to restore previous state on failure
- **Binary file handling**: Skips binary files with warnings
- **Untracked file warnings**: Reminds you to stage untracked files

### Compose Options

| Flag | Description |
|------|-------------|
| `--max-commits` | Maximum commits in the plan (default: 6) |
| `--style` | Override commit style profile |
| `-c, --commit` | Execute the plan and create commits |
| `-y, --yes` | Skip confirmation prompt |
| `--dry-run` | Force plan-only even if `--commit` present |
| `-r, --regenerate` | Force regenerate the plan, ignoring cache |
| `-j, --json` | Show the cached compose plan JSON for debugging |
| `--from-plan` | Load plan from external JSON file (skip LLM) |
| `--agent` | Use the multi-phase agentic pipeline instead of single-shot planner |
| `--trace` | Show detailed agent execution trace on stderr (requires `--agent`) |
| `--debug` | Print diagnostics |

### Caching

Compose uses smart caching similar to the main command:
- Cache key is computed from: diff content + style + max_commits
- Cached files are stored in `.hunknote/`:
  - `hunknote_compose_plan.json` - The full compose plan
  - `hunknote_compose_metadata.json` - Generation metadata
  - `hunknote_hunk_ids.json` - All hunks with their diffs and commit assignments
- Use `-r` to force regeneration
- Use `-j` to inspect the cached plan
- Cache is automatically invalidated after successful commit execution

## Compose Agent (Multi-Phase Agentic Pipeline)

The Compose Agent is an advanced, multi-step agentic pipeline that replaces the single-shot LLM planner for the Compose command. It uses a 6-phase architecture with validation gates, a ReAct reasoning loop, and automatic retry with failure diagnosis to produce higher-quality atomic commit stacks.

### Enabling the Agent

```bash
# Use the agent pipeline instead of single-shot planner
hunknote compose --agent

# Enable full trace output (LLM calls, tool use, validations)
hunknote compose --agent --trace

# Combine with other compose flags
hunknote compose --agent --max-commits 4 --style conventional --commit
```

### Architecture Overview

The Compose Agent runs a deterministic state machine through 6 phases, with a validation-retry loop between phases 5 and 3:

```
Phase 1: Summarize ──→ Phase 2: Dependency Graph ──→ Phase 3: Cluster
                                                          │
                                    ┌─────────────────────┘
                                    ▼
                              Phase 4: Order ──→ Phase 5a: Validate
                                                      │
                                         ┌────────────┤
                                         ▼ (fail)     ▼ (pass)
                                   Phase 5b: ──→ Phase 6: Messages
                                   Diagnose        │
                                     │             ▼
                                     └──→    ComposePlan
                                   (retry)
```

### Phase 1: Hunk Summarization

Summarizes each hunk in the diff using LLM calls. Outputs structured `HunkSummary` objects containing:
- **Intent**: What the change does (e.g., "Add retry logic with exponential backoff")
- **Category**: feature, bugfix, refactor, test, docs, config
- **Symbols modified/referenced**: Function names, class names, variables

Uses **dynamic batching** to group hunks by file while respecting a token budget. Small files are merged into multi-file batches; large files are split into sub-batches.

### Phase 2: Dependency Graph (ReAct Agent)

A ReAct (Reasoning + Acting) agent investigates inter-hunk dependencies using tools:

| Tool | Description |
|------|-------------|
| `ripgrep` | Search the repo for patterns |
| `read_file` | Read HEAD version of a file |
| `read_staged_file` | Read staged version (HEAD + all hunks applied) |
| `get_hunk` | Get full diff and metadata for a hunk |
| `list_hunks` | Overview of all hunks with IDs and paths |

The agent follows a Thought → Action → Observation loop, producing a dependency graph with two edge types:
- **Directional** (`A → B`): A depends on B — they can be in separate commits but B must come first
- **Bidirectional** (`A ↔ B`): A and B must be in the same commit (e.g., function definition + its import)

### Phase 3: Commit Clustering

Single LLM call that groups hunks into candidate commit groups (`_G1`, `_G2`, ...) based on:
- Hunk summaries from Phase 1
- Dependency graph from Phase 2
- Bidirectional constraints (must-colocate groups)

**Validation gate** checks: no duplicate hunks, all mutable hunks assigned, frozen hunks excluded, group count within limits. If the gate fails, the LLM is re-prompted with specific violation details (up to 3 attempts).

### Phase 4: Topological Ordering

Orders commit groups using Kahn's algorithm on the group-level DAG (lifted from hunk-level directional edges). When multiple groups have zero in-degree simultaneously, an LLM tie-break decides ordering with a heuristic fallback:

**Heuristic priority**: infrastructure/refactors → features → bugfixes → tests → docs

Groups are renamed from temporary IDs (`_G1`, `_G2`) to final IDs (`C1`, `C2`, ...) reflecting commit order.

### Phase 5a: Git Worktree Validation

Creates an isolated git worktree and validates each commit sequentially through layered checks:

| Layer | Check | What it catches |
|-------|-------|-----------------|
| 1 | `git apply --check` | Patch conflicts, missing context |
| 2 | `py_compile` | Syntax errors in touched Python files |
| 3 | `import` check | Missing imports, circular dependencies |

Successfully validated commits are **frozen** — they become read-only and cannot be modified by subsequent retries. Only mutable (not-yet-validated) hunks can be rearranged.

### Phase 5b: Failure Diagnosis (ReAct Agent)

When validation fails, a ReAct agent diagnoses the root cause and proposes a remediation:

| Action | Effect |
|--------|--------|
| `recluster` | Add dependency edges, re-run Phase 3 + 4 |
| `reorder` | Re-run Phase 4 only |
| `split_commit` | Break a commit into sub-groups, re-run Phase 4 |
| `unlock_and_recluster` | Unfreeze commits from an index, recluster (last resort) |
| `fail` | Pipeline cannot be fixed by regrouping |

The retry loop runs up to `max_retries` (default: 3) times.

### Phase 6: Commit Message Generation

Generates commit messages for each ordered group. Each message includes the group's theme, category, and the full diff context. Previous commits in the stack are provided as context for coherent messaging.

Outputs `PlannedCommit` objects compatible with the existing style rendering pipeline (default, blueprint, conventional, ticket, kernel).

### Frozen/Mutable State Model

The agent maintains a clear separation between validated and pending work:

- **Frozen commits**: Passed all validation layers. Their hunks are locked — they cannot be reassigned or reordered.
- **Mutable hunks**: Not yet committed. These are the only hunks available for reclustering during retries.

This ensures that successfully validated commits are never accidentally broken by a retry cycle.

### Tracing

The `--trace` flag outputs a detailed execution trace to stderr, including:
- Phase start/end with duration
- Every LLM call (system prompt, user prompt, response, tokens, latency)
- Tool calls and results
- Validation gate checks (pass/fail/violations)
- Remediation actions applied

The trace is also saved incrementally to `.hunknote/agent_trace.json` for post-mortem analysis.

### Agent vs Single-Shot Planner

| Aspect | Single-Shot | Agent |
|--------|-------------|-------|
| LLM calls | 1 | 5+ (one per phase, more with retries) |
| Dependency analysis | None | Full graph with tool-assisted investigation |
| Validation | Post-hoc only | In-pipeline with automated retry |
| Failure recovery | None | Diagnosis + remediation loop |
| Hunk ordering | Implicit | Explicit topological sort |
| Cost | Lower | Higher (more LLM calls) |
| Quality | Good for simple diffs | Better for complex, cross-file changes |

## How It Works

1. **Collects git context**: branch name, file changes (new vs modified), last 5 commits, and staged diff
2. **Computes a hash** of the context to check cache validity
3. **Checks cache**: If valid, uses cached message; otherwise calls the configured LLM
4. **Parses the response**: Extracts structured JSON (title + bullet points) from LLM response
5. **Renders the message**: Formats into standard git commit message format
6. **Optionally opens editor** and/or commits

### Intelligent File Change Detection

The tool distinguishes between:
- **New files** (did not exist before this commit)
- **Modified files** (already existed, now changed)
- **Deleted files**
- **Renamed files**

This context helps the LLM generate accurate descriptions - for example, it won't say "implement caching" when you're just adding tests for existing caching functionality.

## Caching Behavior

The tool caches generated commit messages to avoid redundant API calls:

- **Same staged changes** → Uses cached message (no API call)
- **Different staged changes** → Regenerates automatically
- **After commit** → Cache is invalidated
- **Use `-r` flag** → Force regeneration

Cache files are stored in `<repo>/.hunknote/`:
- `hunknote_message.txt` - The cached commit message
- `hunknote_context_hash.txt` - Hash of the git context
- `hunknote_metadata.json` - Full metadata (tokens, model, timestamp)
- `hunknote_llm_response.json` - Raw JSON response from LLM (for debugging with `-j`)
- `config.yaml` - Repository-specific configuration

**Gitignore recommendation:** Add these to your `.gitignore`:
```
# hunknote cache files (but keep config.yaml for shared settings)
.hunknote/hunknote_*.txt
.hunknote/hunknote_*.json
```

## Repository Configuration

Each repository can have its own `.hunknote/config.yaml` file for customization.
The file is auto-created with defaults on first run.

### Ignore Patterns

The `ignore` section lists file patterns to exclude from the diff sent to the LLM.
This reduces token usage and focuses the commit message on actual code changes.

```yaml
ignore:
  # Lock files (auto-generated)
  - poetry.lock
  - package-lock.json
  - yarn.lock
  - pnpm-lock.yaml
  - Cargo.lock
  - Gemfile.lock
  - composer.lock
  - go.sum
  # Build artifacts
  - "*.min.js"
  - "*.min.css"
  - "*.map"
  # Binary and generated files
  - "*.pyc"
  - "*.pyo"
  - "*.so"
  - "*.dll"
  - "*.exe"
  # IDE files
  - ".idea/*"
  - ".vscode/*"
  - "*.swp"
  - "*.swo"
```

You can add custom patterns using glob syntax (e.g., `build/*`, `*.generated.ts`).

## Output Format

Generated messages follow git best practices:

```
Add user authentication feature

- Implement login and logout endpoints
- Add session management middleware
- Create user model with password hashing
```

## Development

### Running Tests

The project includes a comprehensive test suite with 553 tests:

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run specific test file
pytest tests/test_formatters.py

# Run specific test
pytest tests/test_cache.py::TestSaveCache::test_saves_all_files
```

### Test Coverage

| Module | Tests | Description |
|--------|-------|-------------|
| `cache.py` | 52 | Caching utilities, metadata, raw JSON storage |
| `cli.py` | 59 | CLI commands and subcommands |
| `compose.py` | 51 | Compose feature (diff parsing, plan validation, caching, execution) |
| `config.py` | 24 | Configuration constants and enums |
| `formatters.py` | 21 | Commit message formatting and validation |
| `git_ctx.py` | 47 | Git context collection, filtering, merge detection |
| `global_config.py` | 26 | Global user configuration (~/.hunknote/) |
| `scope.py` | 54 | Scope inference from file paths |
| `styles.py` | 102 | Commit style profiles and rendering |
| `llm/base.py` | 66 | JSON parsing, schema validation, style prompts |
| `llm/*.py` providers | 31 | All LLM provider classes |
| `user_config.py` | 20 | Repository YAML config file management |

### Project Structure

```
hunknote/
├── __init__.py
├── cli.py              # CLI entry point and commands
├── config.py           # LLM provider configuration
├── cache.py            # Caching utilities
├── formatters.py       # Commit message formatting
├── styles.py           # Commit style profiles (default, blueprint, conventional, ticket, kernel)
├── scope.py            # Scope inference (monorepo, path-prefix, mapping)
├── git_ctx.py          # Git context collection
├── user_config.py      # Repository config management
├── global_config.py    # Global user config (~/.hunknote/)
└── llm/
    ├── __init__.py     # Provider factory
    ├── base.py         # Base classes and prompts
    ├── anthropic_provider.py
    ├── openai_provider.py
    ├── google_provider.py
    ├── mistral_provider.py
    ├── cohere_provider.py
    ├── groq_provider.py
    └── openrouter_provider.py
```

## Requirements

- Python 3.12+
- Git
- API key for at least one supported LLM provider

## Dependencies

- `typer` (>=0.21.0) - CLI framework
- `pydantic` (>=2.5.0) - Data validation
- `python-dotenv` - Environment variable management
- `pyyaml` - YAML configuration
- LLM SDKs: `anthropic`, `openai`, `google-genai`, `mistralai`, `cohere`, `groq`

## License

MIT
