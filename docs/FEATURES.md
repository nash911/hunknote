# Hunknote Features & Configuration Guide

> AI-powered git commit message generator with multi-LLM support

This documentation covers all features and configuration options available in the Hunknote CLI tool. Use this as a reference for setting up and customizing your commit message generation workflow.

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Command Reference](#command-reference)
5. [Compose Mode](#compose-mode)
6. [Commit Style Profiles](#commit-style-profiles)
7. [Scope Inference](#scope-inference)
8. [Intent Channel](#intent-channel)
9. [Merge Detection](#merge-detection)
10. [Configuration](#configuration)
11. [LLM Providers](#llm-providers)
12. [Caching System](#caching-system)
13. [Ignore Patterns](#ignore-patterns)
14. [Editor Integration](#editor-integration)
15. [Git Integration](#git-integration)
16. [Troubleshooting](#troubleshooting)

---

## Overview

Hunknote is a command-line tool that analyzes your staged git changes and generates meaningful, well-structured commit messages using AI language models. It supports multiple LLM providers and includes smart caching to minimize API calls.

### Key Features

| Feature | Description |
|---------|-------------|
| **Multi-LLM Support** | Choose from 7 providers: Anthropic, OpenAI, Google, Mistral, Cohere, Groq, OpenRouter |
| **Compose Mode** | Split working tree changes into a clean stack of atomic commits |
| **Commit Style Profiles** | Support for Default, Blueprint (structured sections), Conventional Commits, Ticket-prefixed, and Kernel-style |
| **Smart Scope Inference** | Automatically detect scope from file paths (monorepo, path-prefix, mapping) |
| **Intelligent Type Selection** | Automatically selects correct commit type (feat, fix, docs, test, merge, etc.) based on changed files |
| **Intent Channel** | Provide explicit motivation with `--intent` to guide commit message framing |
| **Merge Detection** | Automatically detects merge commits and conflict resolutions |
| **Smart Caching** | Reuses generated messages when staged changes haven't changed |
| **Raw JSON Debugging** | Inspect LLM response with `--json` flag |
| **Structured Output** | Generates title + bullet points following git best practices |
| **Intelligent Context** | Distinguishes between new, modified, deleted, and renamed files |
| **Editor Integration** | Review and edit messages before committing |
| **One-Command Commits** | Generate and commit in a single step with `hunknote commit` |
| **Configurable Ignores** | Exclude lock files, build artifacts from analysis |
| **Debug Mode** | Inspect cache metadata, tokens, scope inference, and file changes |

---

## Installation

### From PyPI (Recommended)

```bash
# Using pipx (isolated environment)
pipx install hunknote

# Using pip
pip install hunknote
```

### From Source

```bash
git clone https://github.com/nash911/hunknote.git
cd hunknote
poetry install
```

### Verify Installation

```bash
hunknote --help
git hunknote --help  # Git subcommand
```

---

## Quick Start

### 1. Initialize Configuration

```bash
hunknote init
```

This interactive wizard will:
1. Ask you to select an LLM provider
2. Choose a model
3. Enter your API key

Configuration is saved to `~/.hunknote/`.

### 2. Generate Your First Commit Message

```bash
git add <files>
hunknote
```

### 3. Edit and Commit

```bash
hunknote -e
hunknote commit
```

Or commit immediately without confirmation:

```bash
hunknote commit -y
```

---

## Command Reference

### Main Command

```bash
hunknote [OPTIONS]
```

Generate an AI-powered commit message from staged changes.

#### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--edit` | `-e` | Open message in editor for manual edits | `false` |
| `--regenerate` | `-r` | Force regenerate, ignoring cached message | `false` |
| `--debug` | `-d` | Show cache metadata (files, tokens, diff preview, scope inference) | `false` |
| `--json` | `-j` | Show raw JSON response from LLM for debugging | `false` |
| `--intent` | `-i` | Provide explicit intent/motivation to guide commit message framing | |
| `--intent-file` | | Load intent text from a file | |
| `--style` | | Override commit style profile (default, blueprint, conventional, ticket, kernel) | from config |
| `--scope` | | Force a scope for the commit message (use 'auto' for inference) | auto |
| `--no-scope` | | Disable scope even if profile supports it | `false` |
| `--scope-strategy` | | Scope inference strategy (auto, monorepo, path-prefix, mapping, none) | from config |
| `--ticket` | | Force a ticket key (e.g., PROJ-123) for ticket-style commits | |
| `--max-diff-chars` | | Maximum characters for staged diff | `50000` |
| `--help` | | Show help message | |

#### Examples

```bash
# Generate and print message
hunknote

# Edit message in editor
hunknote -e

# Commit with generated message (prompts for confirmation)
hunknote commit

# Commit immediately without confirmation
hunknote commit -y

# Force regeneration (bypass cache)
hunknote -r

# View debug information (cache, tokens, scope inference)
hunknote -d

# View raw JSON response from LLM
hunknote -j

# Force regenerate and view raw JSON
hunknote -r -j

# Use conventional commits style with auto scope inference
hunknote --style conventional

# Use conventional commits style with explicit scope
hunknote --style conventional --scope api

# Use blueprint style for detailed commit messages
hunknote --style blueprint

# Use monorepo scope inference strategy
hunknote --style conventional --scope-strategy monorepo

# Disable scope inference
hunknote --style conventional --no-scope

# Use ticket-prefixed style
hunknote --style ticket --ticket PROJ-123
hunknote commit

# Kernel style with subsystem
hunknote --style kernel --scope auth

# Provide explicit intent to guide commit message
hunknote --intent "Fix race condition in connection handling"

# Load intent from a file
hunknote --intent-file ./intent.txt

# Combine intent text and file, then commit
hunknote --intent "Primary reason" --intent-file ./details.txt
hunknote commit -y
```

---

### `hunknote init`

Initialize hunknote with interactive configuration wizard.

```bash
hunknote init
```

**What it does:**
- Prompts for LLM provider selection (1-7)
- Prompts for model selection
- Prompts for API key (hidden input)
- Saves configuration to `~/.hunknote/config.yaml`
- Saves API key to `~/.hunknote/credentials` (secure permissions)

**If already configured:**
- Asks for confirmation before overwriting

---

### `hunknote commit`

Commit staged changes using the generated message.

```bash
hunknote commit [OPTIONS]
```

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--yes` | `-y` | Bypass confirmation prompt and commit immediately |

**What it does:**
- Uses the cached commit message from the last `hunknote` run
- Prompts for confirmation before committing (unless `-y` is used)
- If no cached message exists, shows an error asking to run `hunknote` first
- After successful commit, invalidates the cache

**Examples:**

```bash
# Commit with confirmation prompt
hunknote commit

# Commit immediately without prompt (for CI/scripts)
hunknote commit -y
hunknote commit --yes
```

**Workflow:**

```bash
# 1. Generate message
hunknote

# 2. (Optional) Edit message
hunknote -e

# 3. Commit
hunknote commit
```

---

### `hunknote config` Subcommands

Manage global configuration stored in `~/.hunknote/`.

#### `hunknote config show`

Display current configuration.

```bash
hunknote config show
```

**Output includes:**
- Provider and model
- Max tokens and temperature
- Editor preference (if set)
- Default ignore patterns (if set)
- API key (masked)

#### `hunknote config set-provider`

Set the active LLM provider and model.

```bash
# Interactive model selection
hunknote config set-provider google

# Specify model directly
hunknote config set-provider anthropic --model claude-sonnet-4-20250514
hunknote config set-provider anthropic -m claude-3-5-haiku-latest
```

#### `hunknote config set-key`

Set or update an API key for a provider.

```bash
hunknote config set-key google
hunknote config set-key anthropic
hunknote config set-key openai
```

API keys are stored in `~/.hunknote/credentials` with secure file permissions (owner read/write only).

#### `hunknote config list-providers`

List all available LLM providers.

```bash
hunknote config list-providers
```

**Output:**
```
Available LLM providers:

  • anthropic
  • openai
  • google
  • mistral
  • cohere
  • groq
  • openrouter
```

#### `hunknote config list-models`

List available models for a provider (or all providers).

```bash
# Models for specific provider
hunknote config list-models google

# All providers and models
hunknote config list-models
```

---

### `hunknote ignore` Subcommands

Manage ignore patterns in the repository's `.hunknote/config.yaml`.

#### `hunknote ignore list`

Show all ignore patterns.

```bash
hunknote ignore list
```

#### `hunknote ignore add`

Add a pattern to the ignore list.

```bash
hunknote ignore add "*.log"
hunknote ignore add "build/*"
hunknote ignore add "dist/*"
hunknote ignore add "package-lock.json"
```

#### `hunknote ignore remove`

Remove a pattern from the ignore list.

```bash
hunknote ignore remove "*.log"
```

---

### `hunknote style` Subcommands

Manage commit message style profiles.

#### `hunknote style list`

List all available style profiles and show the current active profile.

```bash
hunknote style list
```

**Output:**
```
Available commit style profiles:

  • default ← active
    Standard Hunknote format with title and bullet points

  • conventional
    Conventional Commits format (type(scope): subject)

  • ticket
    Ticket-prefixed format (PROJ-6767 subject)

  • kernel
    Linux kernel style (subsystem: subject)

Current profile: default (from global config)
```

#### `hunknote style show`

Show details about a specific style profile.

```bash
hunknote style show conventional
```

**Output includes:**
- Format template
- Example output
- Profile-specific configuration options

#### `hunknote style set`

Set the active style profile.

```bash
# Set globally (applies to all repos)
hunknote style set conventional

# Set for current repo only
hunknote style set ticket --repo
```

---

## Compose Mode

Compose mode takes a messy working tree (tracked text changes) and produces a clean **commit stack** — splitting your changes into coherent, atomic commits.

### Basic Usage

```bash
# Preview the proposed commit stack (plan-only mode)
hunknote compose

# Execute the plan and create commits
hunknote compose --commit

# Skip confirmation prompt
hunknote compose --commit --yes
```

### What Compose Does

1. **Collects all tracked changes** (staged + unstaged) from `git diff HEAD`
2. **Parses the diff** into files and hunks with stable IDs
3. **Asks the LLM** to split changes into logical, atomic commits
4. **Validates the plan** (no duplicate hunks, all hunks assigned, etc.)
5. **Optionally executes** by applying patches and creating commits

### Compose Options

| Option | Default | Description |
|--------|---------|-------------|
| `--max-commits` | 6 | Maximum number of commits in the plan |
| `--style` | (from config) | Override commit style profile |
| `-c, --commit` | false | Execute the plan and create commits |
| `-y, --yes` | false | Skip confirmation prompt in commit mode |
| `--dry-run` | false | Force plan-only even if `--commit` present |
| `-r, --regenerate` | false | Force regenerate the plan, ignoring cache |
| `-j, --json` | false | Show the cached compose plan JSON for debugging |
| `--from-plan` | none | Load plan from external JSON file (skip LLM) |
| `--debug` | false | Print diagnostics (inventory, patch paths) |

### Caching

Compose uses smart caching to avoid redundant LLM calls:
- Cache key is computed from: diff content + style + max_commits
- Cached files are stored in `.hunknote/`:
  - `hunknote_compose_hash.txt` - Cache key hash
  - `hunknote_compose_plan.json` - The full compose plan
  - `hunknote_compose_metadata.json` - Generation metadata
  - `hunknote_hunk_ids.json` - All hunks with diffs and commit assignments
- Use `-r` or `--regenerate` to force regeneration
- Use `-j` or `--json` to inspect the cached plan
- Cache is automatically invalidated after successful commit execution

### Hunk IDs File

The `hunknote_hunk_ids.json` file contains detailed information about each hunk:

```json
[
  {
    "hunk_id": "H1_abc123",
    "file": "src/main.py",
    "commit_id": "C1",
    "header": "@@ -10,6 +10,8 @@ def main():",
    "diff": "@@ -10,6 +10,8 @@ def main():\n     print(\"Hello\")\n+    print(\"World\")\n     return 0"
  },
  {
    "hunk_id": "H2_def456",
    "file": "src/util.py",
    "commit_id": "unassigned",
    "header": "@@ -1,3 +1,4 @@",
    "diff": "..."
  }
]
```

This file is useful for:
- Debugging unassigned hunk warnings
- Understanding how changes are grouped
- Reviewing the actual diff content for each hunk

### Safety Features

**Plan mode (default)** does not modify git state:
- No `git add`
- No `git reset`
- No `git apply`
- No `git commit`

**Commit mode** includes recovery mechanisms:
- Saves current staged patch before execution
- Saves current HEAD reference
- Attempts best-effort restore on failure
- Prints manual recovery instructions

### Limitations (v1)

- **Untracked files**: Not included by default. Add them first with `git add -N <file>`
- **Binary files**: Detected and skipped with warnings
- **Large diffs**: May hit token limits; use `--max-diff-chars` to control

### Examples

```bash
# Preview split without executing
hunknote compose

# Use conventional commits style
hunknote compose --style conventional

# Limit to 3 commits max
hunknote compose --max-commits 3

# Execute without confirmation (for scripts)
hunknote compose -c -y

# Force regenerate (ignore cache)
hunknote compose -r

# Show cached compose plan JSON
hunknote compose -j

# Load a previously saved plan
hunknote compose --from-plan plan.json --commit

# Debug: see inventory and patch details
hunknote compose --debug
```

---

## Commit Style Profiles

Hunknote supports multiple commit message formats to match your team's conventions. The style determines how the generated commit message is formatted.

### Available Profiles

#### 1. `default` (Standard Hunknote Format)

The original Hunknote format with a title and bullet points.

**Format:**
```
<Title>

- <bullet>
- <bullet>
```

**Example:**
```
Add user authentication feature

- Implement login and logout endpoints
- Add session management middleware
- Create user model with password hashing
```

#### 2. `blueprint` (Structured Sections)

A comprehensive format with summary paragraph and structured sections. Ideal for detailed commit messages that document changes, implementation, testing, and more.

**Format:**
```
<type>(<scope>): <title>

<summary paragraph>

Changes:
- <bullet>
- <bullet>

Implementation:
- <bullet>

Testing:
- <bullet>

Documentation:
- <bullet>

Notes:
- <bullet>
```

**Example:**
```
feat(auth): Add user authentication

Implement secure user authentication with JWT tokens and session
management for the API. This enables users to log in and maintain
persistent sessions.

Changes:
- Add login and logout endpoints
- Implement JWT token validation
- Add session management middleware

Implementation:
- Create auth middleware in hunknote/auth.py
- Add user session storage with Redis backend

Testing:
- Add unit tests for auth flow
- Add integration tests for login endpoint

Notes:
- Requires REDIS_URL environment variable for production
```

**Allowed section titles:** `Changes`, `Implementation`, `Testing`, `Documentation`, `Notes`, `Performance`, `Security`, `Config`, `API`

**Usage:**
```bash
hunknote --style blueprint
hunknote --style blueprint --scope api
hunknote --style blueprint --no-scope
```

#### 3. `conventional` (Conventional Commits)

Following the [Conventional Commits](https://www.conventionalcommits.org/) specification.

**Format:**
```
<type>(<scope>): <subject>

- <bullet>
- <bullet>

BREAKING CHANGE: <description>
Refs: <ticket>
```

**Example:**
```
feat(auth): Add user authentication

- Implement login and logout endpoints
- Add session management middleware

Refs: PROJ-123
```

**Valid types:** `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `style`, `revert`

**Usage:**
```bash
hunknote --style conventional
hunknote --style conventional --scope api
hunknote --style conventional --no-scope  # Disable scope
```

#### 4. `ticket` (Ticket-Prefixed)

For teams that require ticket/issue references in commit messages.

**Format (prefix - default):**
```
<KEY-123> <subject>

- <bullet>
```

**Format (prefix with scope):**
```
<KEY-123> (<scope>) <subject>

- <bullet>
```

**Format (suffix):**
```
<subject> (<KEY-123>)

- <bullet>
```

**Example:**
```
PROJ-123 Add user authentication

- Implement login endpoint
- Add session management
```

**Usage:**
```bash
hunknote --style ticket --ticket PROJ-123
hunknote --style ticket --ticket PROJ-123 --scope api
```

**Automatic ticket extraction:** If `--ticket` is not provided, Hunknote will attempt to extract a ticket from the branch name using the configured regex pattern.

#### 5. `kernel` (Linux Kernel Style)

Following the Linux kernel commit message format.

**Format:**
```
<subsystem>: <subject>

- <bullet> (optional)
```

**Example:**
```
auth: Add user authentication

- Implement login endpoint
```

**Usage:**
```bash
hunknote --style kernel --scope auth
```

### Style Configuration

Style settings can be configured in `~/.hunknote/config.yaml` (global) or `<repo>/.hunknote/config.yaml` (per-repo):

```yaml
style:
  profile: blueprint       # default | blueprint | conventional | ticket | kernel
  include_body: true       # Whether to include bullet body
  max_bullets: 6           # Maximum number of bullets
  wrap_width: 72           # Line wrap width

  # Blueprint style options
  blueprint:
    section_titles: [Changes, Implementation, Testing, Documentation, Notes]

  # Conventional commits options
  conventional:
    types: [feat, fix, docs, refactor, perf, test, build, ci, chore]
    breaking_footer: true

  # Ticket style options
  ticket:
    key_regex: "([A-Z][A-Z0-9]+-\\d+)"  # Regex for ticket extraction
    placement: prefix                    # prefix | suffix

  # Kernel style options
  kernel:
    subsystem_from_scope: true  # Use --scope as subsystem
```

### Style Precedence

Style settings are applied in this order (later overrides earlier):

1. **Built-in defaults**
2. **Global config** (`~/.hunknote/config.yaml`)
3. **Repo config** (`<repo>/.hunknote/config.yaml`)
4. **CLI flags** (`--style`, `--scope`, `--ticket`, `--no-scope`)

### Automatic Type Inference

When using `conventional` or `blueprint` style, Hunknote can automatically infer the commit type based on the files being changed:

| Changed Files | Inferred Type |
|---------------|---------------|
| Only `.md`, `.rst`, docs files | `docs` |
| Only test files | `test` |
| Only CI files (`.github/workflows/`, etc.) | `ci` |
| Only build/config files (`pyproject.toml`, etc.) | `build` |
| Mixed changes | LLM determines type |

### Intelligent Type Selection

The LLM uses smart rules to select the correct commit type:

**File Extension Priority:**
- If ANY `.py/.js/.ts/.go/.rs/.java` file is modified → type is `feat`/`fix`/`refactor`/`perf` (never `docs`)
- `docs` type is ONLY used when ALL changed files are `.md`/`.rst` documentation files
- `test` type is ONLY used when ALL changed files are test files

**Fix vs Refactor:**
- `fix` = change improves/corrects behavior, fixes a problem, or makes something work better
- `refactor` = ONLY when behavior stays exactly the same, just internal code structure changes
- If changing prompts/templates to improve output quality → `fix` (behavior is improved)

**Avoiding Redundant Scopes:**
- `type="test"` with `scope="tests"` → scope is set to null (redundant)
- `type="docs"` with `scope="docs"` → scope is set to null (redundant)

---

## Scope Inference

Hunknote can automatically infer the scope from your staged files, ensuring consistent and accurate commit headers like `feat(api): ...` or `fix(ui): ...`.

### How It Works

Scope inference analyzes your staged file paths to determine the most appropriate scope. It runs **before** the LLM call and provides deterministic, consistent results.

### Inference Strategies

#### 1. **auto** (Default)

Tries all strategies in order and uses the best match:
1. Mapping (if configured)
2. Monorepo
3. Path-prefix

```bash
hunknote --scope-strategy auto --style conventional
```

#### 2. **monorepo**

Detects scope from monorepo directory structures:

```
packages/auth/src/login.py    → scope: auth
apps/web/components/Button.js → scope: web
libs/shared-ui/src/Input.tsx  → scope: shared-ui
```

**Recognized roots:** `packages/`, `apps/`, `libs/`, `modules/`, `services/`, `plugins/`, `workspaces/`

```bash
hunknote --scope-strategy monorepo --style conventional
```

#### 3. **path-prefix**

Uses the most common path segment (excluding stop words like `src`, `lib`, `tests`):

```
api/routes.py      → scope: api
api/models.py      → scope: api
api/utils.py       → scope: api
```

```bash
hunknote --scope-strategy path-prefix --style conventional
```

#### 4. **mapping**

Uses explicit path-to-scope mapping defined in config:

```yaml
scope:
  strategy: mapping
  mapping:
    "src/api/": api
    "src/web/": ui
    "infra/": infra
```

```bash
hunknote --scope-strategy mapping --style conventional
```

#### 5. **none**

Disables scope inference entirely:

```bash
hunknote --scope-strategy none --style conventional
```

### Special Cases

| Scenario | Default Behavior |
|----------|------------------|
| All documentation files | Scope: `docs` |
| All test files | Infer from test path or configured scope |
| Mixed changes (low confidence) | No scope (avoids wrong scope) |

### Configuration

Scope settings can be configured in `~/.hunknote/config.yaml` or `<repo>/.hunknote/config.yaml`:

```yaml
scope:
  enabled: true               # Enable/disable scope inference
  strategy: auto              # auto | monorepo | path-prefix | mapping | none
  min_files: 1                # Minimum files to consider a cluster
  max_depth: 2                # How deep into paths to look
  dominant_threshold: 0.6     # Required confidence for dominant scope

  # Explicit path-to-scope mapping
  mapping:
    "src/api/": api
    "src/web/": ui
    "infra/": infra

  # Monorepo root directories
  monorepo_roots:
    - "packages/"
    - "apps/"
    - "libs/"

  # Scope for docs-only changes
  docs_scope: docs

  # Scope for tests-only changes (null to infer from path)
  tests_scope: null
```

### Precedence

Scope is determined in this order (first non-null wins):

1. `--scope <value>` CLI flag (explicit scope)
2. `--no-scope` CLI flag (disables scope)
3. LLM suggested scope (from the AI's analysis of the changes)
4. Heuristics-based scope inference (if enabled)
5. No scope

### Debug Output

Use `--debug` to see scope inference details:

```bash
hunknote --debug --style conventional
```

Output includes:
- Strategy used
- Inferred scope (from heuristics)
- Confidence level
- Reason for decision
- LLM suggested scope
- CLI override (if any)
- Final scope used

---

## Intent Channel

The intent channel allows you to provide explicit motivation or context that guides how the LLM frames your commit message. This is useful when the diff alone doesn't convey the "why" behind your changes.

### Usage

```bash
# Provide intent directly via CLI
hunknote --intent "Fix race condition in session handling"

# Load intent from a file
hunknote --intent-file ./commit-intent.txt

# Combine both (concatenated with blank line)
hunknote --intent "Primary motivation" --intent-file ./additional-context.txt
```

### How It Works

1. **Intent is injected into the LLM prompt** as a dedicated `[INTENT]` section
2. **The intent guides framing**, not technical facts - the LLM still constrains claims to what's in the diff
3. **If intent contradicts the diff**, the diff takes precedence
4. **Intent is included in the cache key** - different intents generate different messages

### When to Use Intent

| Scenario | Example Intent |
|----------|----------------|
| Non-obvious fix | "Fix memory leak that only occurs under high load" |
| Business context | "Requested by security team for compliance" |
| Refactor motivation | "Prepare for upcoming API v2 migration" |
| Bug reference | "Fixes issue reported in support ticket #1234" |
| Performance reason | "Optimize for 10x increase in concurrent users" |

### Debug Output

In debug mode (`-d`), the intent is displayed:

```
Intent: Fix race condition in session han... (48 chars)
```

Only the first 80 characters are shown, along with the total length.

### Validation

- Whitespace-only intent is treated as "not provided"
- If `--intent-file` points to a non-existent file, hunknote exits with an error
- Empty intent content is ignored

---

## Merge Detection

Hunknote automatically detects when you're in a merge state (during `git merge`) and generates appropriate commit messages.

### Detected States

| State | Detection | Commit Type |
|-------|-----------|-------------|
| **Merge in progress** | `.git/MERGE_HEAD` exists | `merge` |
| **Merge conflict resolution** | `.git/MERGE_HEAD` + resolved conflicts staged | `merge` |
| **Normal commit** | No `.git/MERGE_HEAD` | feat/fix/docs/etc. |

### Merge Message Format

When a merge is detected, the commit message follows this format:

```
merge: Merge branch feature-auth

- Integrate user authentication module
- Add login and logout endpoints
- Include session management
```

For conventional/blueprint styles:

```
merge(auth): Merge branch feature-auth into main

Integrate the feature-auth branch which adds user authentication
with JWT tokens and session management.

Changes:
- Add login and logout endpoints
- Implement JWT token validation
- Add session management middleware
```

### Source Branch Detection

Hunknote extracts the source branch name from:
1. `.git/MERGE_MSG` (e.g., "Merge branch 'feature-auth'")
2. `git name-rev` of the merge head commit

This ensures the commit message accurately reflects what's being merged.

### Context Bundle

The merge state is included in the `[MERGE_STATE]` section of the context sent to the LLM:

```
[MERGE_STATE]
MERGE IN PROGRESS
Merging branch: feature-auth
Merging commit: abc123def456
```

Or for conflict resolution:

```
[MERGE_STATE]
MERGE CONFLICT - Resolving conflicts
Merging branch: feature-auth
Merging commit: abc123def456
Files with resolved conflicts:
  ! src/auth.py
  ! tests/test_auth.py
```

---

## Configuration

Hunknote uses two configuration locations:

### Global Configuration (`~/.hunknote/`)

User-level settings that apply to all repositories.

| File | Purpose |
|------|---------|
| `config.yaml` | Provider, model, and preference settings |
| `credentials` | API keys (secure permissions) |

#### `config.yaml` Options

```yaml
# LLM Provider (required)
provider: google  # anthropic, openai, google, mistral, cohere, groq, openrouter

# Model name (required)
model: gemini-2.0-flash

# Maximum tokens for LLM response
max_tokens: 1500

# Temperature for response generation (0.0-1.0)
temperature: 0.3

# Preferred editor for -e flag (optional)
editor: gedit  # or vim, nano, code, etc.

# Default ignore patterns applied to all repos (optional)
default_ignore:
  - poetry.lock
  - package-lock.json
  - "*.min.js"
```

#### `credentials` File Format

```
# hunknote API credentials
GOOGLE_API_KEY=your-google-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
OPENAI_API_KEY=your-openai-api-key
```

### Repository Configuration (`<repo>/.hunknote/`)

Repository-specific settings that override or extend global settings.

| File | Purpose |
|------|---------|
| `config.yaml` | Repository-specific ignore patterns |
| `hunknote_message.txt` | Cached commit message |
| `hunknote_context_hash.txt` | Cache validity hash |
| `hunknote_metadata.json` | Cache metadata (tokens, model, etc.) |

#### Repository `config.yaml`

```yaml
ignore:
  # Lock files
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
  # Binary files
  - "*.pyc"
  - "*.so"
  - "*.dll"
  # IDE files
  - ".idea/*"
  - ".vscode/*"
```

### API Key Resolution Order

API keys are resolved in this order (first found wins):

1. **Environment variables** (highest priority)
2. **`~/.hunknote/credentials` file**
3. **Project `.env` file** (lowest priority)

This allows CI/CD systems to use environment variables while developers use the credentials file.

---

## LLM Providers

### Supported Providers

| Provider | API Key Variable | Best For |
|----------|------------------|----------|
| **Anthropic** | `ANTHROPIC_API_KEY` | High-quality, nuanced messages |
| **OpenAI** | `OPENAI_API_KEY` | Versatile, widely used |
| **Google** | `GOOGLE_API_KEY` | Fast, cost-effective |
| **Mistral** | `MISTRAL_API_KEY` | European provider, good performance |
| **Cohere** | `COHERE_API_KEY` | Enterprise-focused |
| **Groq** | `GROQ_API_KEY` | Ultra-fast inference |
| **OpenRouter** | `OPENROUTER_API_KEY` | Access 200+ models via single API |

### Available Models

#### Anthropic
- `claude-sonnet-4-20250514`
- `claude-3-5-sonnet-latest`
- `claude-3-5-haiku-latest`
- `claude-3-opus-latest`

#### OpenAI
- `gpt-4.1`
- `gpt-4.1-mini`
- `gpt-4.1-nano`
- `gpt-4o`
- `gpt-4o-mini`
- `gpt-4-turbo`

#### Google
- `gemini-3-pro-preview`
- `gemini-2.5-pro`
- `gemini-3-flash-preview`
- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`
- `gemini-2.0-flash`
- `gemini-2.0-flash-lite`

#### Mistral
- `mistral-large-latest`
- `mistral-medium-latest`
- `mistral-small-latest`
- `codestral-latest`

#### Cohere
- `command-r-plus`
- `command-r`
- `command`

#### Groq
- `llama-3.3-70b-versatile`
- `llama-3.1-8b-instant`
- `mixtral-8x7b-32768`

#### OpenRouter
Access 200+ models through a single API:
- `anthropic/claude-sonnet-4`
- `anthropic/claude-3.5-sonnet`
- `openai/gpt-4o`
- `google/gemini-2.0-flash-exp`
- `meta-llama/llama-3.3-70b-instruct`
- `deepseek/deepseek-chat`
- `qwen/qwen-2.5-72b-instruct`
- And many more...

---

## Caching System

Hunknote caches generated messages to avoid redundant API calls and costs.

### How It Works

1. **Context Hash**: A SHA256 hash is computed from the git context (branch, staged files, diff)
2. **Cache Check**: If the hash matches the stored hash, the cached message is used
3. **Automatic Invalidation**: Cache is invalidated after a successful commit

### Cache Behavior

| Scenario | Action |
|----------|--------|
| Same staged changes | Uses cached message (no API call) |
| Different staged changes | Regenerates automatically |
| After successful commit | Cache invalidated |
| `--regenerate` flag | Bypasses cache, forces new generation |

### Cache Files

Located in `<repo>/.hunknote/`:

| File | Content |
|------|---------|
| `hunknote_message.txt` | The cached commit message |
| `hunknote_context_hash.txt` | SHA256 hash of the git context |
| `hunknote_metadata.json` | Metadata (tokens, model, timestamp, files) |
| `hunknote_llm_response.json` | Raw JSON response from LLM (for `-j` debugging) |

### Gitignore Recommendation

Add to your `.gitignore`:

```gitignore
# Hunknote cache (keep config.yaml for shared settings)
.hunknote/hunknote_*.txt
.hunknote/hunknote_*.json
```

---

## Ignore Patterns

Ignore patterns exclude files from the diff sent to the LLM. This:
- Reduces token usage
- Focuses messages on actual code changes
- Avoids noise from auto-generated files

### Pattern Syntax

Uses glob pattern matching:

| Pattern | Matches |
|---------|---------|
| `poetry.lock` | Exact file name |
| `*.log` | Any file ending in .log |
| `build/*` | Any file in build directory |
| `.idea/*` | Any file in .idea directory |

### Default Patterns

New repositories get these defaults:

```yaml
ignore:
  # Lock files
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
  # Binary files
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

---

## Editor Integration

### Default Editor Selection

Hunknote looks for editors in this order:

1. **gedit** (with `--wait` flag)
2. **`$EDITOR`** environment variable
3. **nano**
4. **vi** (fallback)

### Setting a Preferred Editor

In `~/.hunknote/config.yaml`:

```yaml
editor: code --wait  # VS Code
# editor: gedit --wait
# editor: vim
# editor: nano
```

### Using the Editor

```bash
# Open generated message in editor
hunknote -e

# Edit then commit
hunknote -e -c
```

---

## Git Integration

### Git Subcommand

Hunknote registers as a git subcommand:

```bash
git hunknote
git hunknote -e -c
git hunknote -r
```

### Context Collected

Hunknote analyzes:

1. **Branch name** - Current branch
2. **Staged status** - Files staged for commit
3. **File change types** - New, modified, deleted, renamed
4. **Last 5 commits** - Recent commit history for context
5. **Staged diff** - Actual code changes

### Intelligent File Detection

The tool distinguishes:
- **New files** - Files that didn't exist before
- **Modified files** - Existing files with changes
- **Deleted files** - Files being removed
- **Renamed files** - Files moved or renamed

This helps the LLM generate accurate descriptions.

---

## Troubleshooting

### Common Issues

#### "No staged changes"

**Problem:** Running `hunknote` with no staged files.

**Solution:**
```bash
git add <files>
hunknote
```

#### "API key not found"

**Problem:** Missing API key for the configured provider.

**Solutions:**
1. Run `hunknote config set-key <provider>`
2. Set environment variable: `export GOOGLE_API_KEY=your-key`
3. Add to `~/.hunknote/credentials`

#### "Invalid provider"

**Problem:** Typo in provider name.

**Solution:** Check valid providers with `hunknote config list-providers`

#### Cache not updating

**Problem:** Getting old cached message despite changes.

**Solution:**
```bash
hunknote -r  # Force regeneration
```

### Debug Mode

Use `-d` flag to inspect:

```bash
hunknote -d
```

**Shows:**
- Cache status (valid/invalid)
- Context hash
- Generated timestamp
- Model used
- Token usage (input/output)
- Staged files list
- Diff preview
- Message edit status
- Scope inference details (strategy, inferred scope, confidence, LLM suggested scope)

### Raw JSON Mode

Use `-j` flag to inspect the raw LLM response:

```bash
hunknote -j
```

**Shows:**
- Raw JSON response from the LLM
- Useful for debugging type/scope selection issues
- Helps understand what the LLM returned before rendering

### Getting Help

```bash
hunknote --help
hunknote config --help
hunknote ignore --help
```

---

## Output Format

Generated messages follow git best practices:

```
<Title line - imperative mood, max 72 chars>

- <Bullet point 1>
- <Bullet point 2>
- <Bullet point 3>
```

**Example:**

```
Add user authentication feature

- Implement login and logout endpoints
- Add session management middleware
- Create user model with password hashing
- Add JWT token generation and validation
```

---

## Requirements

- **Python**: 3.12+
- **Git**: Any recent version
- **API Key**: At least one LLM provider

## License

MIT License - see [LICENSE](LICENSE) for details.

---

*Documentation generated for Hunknote v1.4.0*

