# Hunknote Documentation

> Transform messy working trees into clean, atomic commit stacks with AI

---

## Introduction

Hunknote is an AI-powered CLI tool that goes beyond simple commit message generation. Its standout feature, **Compose Mode**, analyzes your working tree changes and intelligently splits them into a clean stack of atomic, well-documented commits — turning hours of manual git work into seconds.

Whether you have a single focused change or a working tree full of mixed modifications, Hunknote handles it:

- **Single change?** Generate a polished commit message instantly
- **Mixed changes?** Let Compose split them into logical, atomic commits automatically

### Why Hunknote?

**The Problem**: Developers often accumulate multiple unrelated changes before committing. Manually splitting these into atomic commits is tedious — you need to carefully stage hunks, write messages for each, and ensure nothing gets lost.

**The Solution**: Hunknote's Compose Mode analyzes your entire diff, understands which changes belong together, and creates a clean commit stack automatically:

```
Your messy working tree          What Compose creates
─────────────────────────        ────────────────────
 M src/auth.py                   C1: feat(auth): Add login endpoint
 M src/api.py                    C2: fix(api): Handle null responses  
 M README.md                     C3: docs: Update API documentation
 M tests/test_auth.py            C4: test(auth): Add login tests
```

**Beyond message generation**, Hunknote offers:

- **Compose Mode** — Split changes into atomic commits with one command
- **Smart caching** — No redundant API calls, instant results for unchanged code
- **Multiple styles** — Conventional Commits, Blueprint, Ticket-prefixed, and more
- **Scope inference** — Automatic scope detection from file paths
- **7 LLM providers** — Choose Anthropic, OpenAI, Google, Mistral, Cohere, Groq, or OpenRouter

### Key Capabilities

| Capability | Description |
|------------|-------------|
| **Compose Mode** | Split working tree changes into atomic commits automatically — the killer feature |
| **Smart Caching** | No redundant API calls for unchanged changes |
| **Multi-LLM Support** | 7 providers: Anthropic, OpenAI, Google, Mistral, Cohere, Groq, OpenRouter |
| **Style Profiles** | Default, Blueprint, Conventional Commits, Ticket-prefixed, Kernel-style |
| **Smart Scope** | Automatic scope detection from file paths |
| **Intent Channel** | Guide message framing with explicit context |
| **Merge Detection** | Automatic merge commit message generation |

---

## Getting Started

### Installation

**Recommended: Install from PyPI**

```bash
# Using pipx (isolated environment)
pipx install hunknote

# Or using pip
pip install hunknote
```

**Alternative: Install from source**

```bash
git clone https://github.com/nash911/hunknote.git
cd hunknote
poetry install
```

**Verify installation**

```bash
hunknote --help
git hunknote --help
```

### Initial Setup

Run the interactive configuration wizard:

```bash
hunknote init
```

This will:
1. Prompt you to select an LLM provider
2. Let you choose a model
3. Securely store your API key

Configuration is saved to `~/.hunknote/`.

> **Tip**: You can reconfigure anytime by running `hunknote init` again.

### Your First Commit Message

```bash
# 1. Stage your changes
git add <files>

# 2. Generate a commit message
hunknote

# 3. Review and commit
hunknote commit
```

That's it! Hunknote analyzes your staged changes and generates an appropriate commit message.

---

## Core Concepts

### How Hunknote Works

1. **Collect Context**: Gathers branch name, staged files, diff, and recent commits
2. **Apply Filters**: Excludes lock files and build artifacts from analysis
3. **Check Cache**: Returns cached message if changes haven't changed
4. **Call LLM**: Sends context to your configured LLM provider
5. **Render Message**: Formats the response according to your style profile
6. **Cache Result**: Stores the message for reuse

### Message Structure

Generated messages follow git best practices:

```
<Title line - imperative mood, max 72 chars>

- <Bullet point describing a change>
- <Bullet point describing another change>
- <Additional details as needed>
```

**Example output:**

```
Add user authentication feature

- Implement login and logout endpoints
- Add session management middleware
- Create user model with password hashing
```

### Caching

Hunknote caches messages to avoid redundant API calls:

- **Cache hit**: Same staged changes → uses cached message (no API call)
- **Cache miss**: Different changes → generates new message
- **Manual bypass**: Use `--regenerate` to force new generation
- **Auto-invalidate**: Cache clears after successful commit

Cache files are stored in `<repo>/.hunknote/`.

---

## Commands

### Generate Message

```bash
hunknote [OPTIONS]
```

Generate a commit message from staged changes.

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--edit` | `-e` | Open message in editor |
| `--regenerate` | `-r` | Force regenerate, ignore cache |
| `--debug` | `-d` | Show debug info (cache, tokens, scope) |
| `--json` | `-j` | Show raw JSON response from LLM |
| `--intent TEXT` | `-i` | Provide context to guide message framing |
| `--intent-file PATH` | | Load intent from file |
| `--style NAME` | | Override style profile |
| `--scope TEXT` | | Force a specific scope |
| `--no-scope` | | Disable scope |
| `--ticket TEXT` | | Force ticket key (e.g., PROJ-123) |

**Examples:**

```bash
# Basic generation
hunknote

# Edit before viewing
hunknote -e

# Force regeneration
hunknote -r

# Use conventional commits style
hunknote --style conventional

# Provide intent context
hunknote --intent "Fix race condition in session handling"

# Debug mode
hunknote -d
```

---

### Commit

```bash
hunknote commit [OPTIONS]
```

Commit staged changes using the generated message.

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--yes` | `-y` | Skip confirmation prompt |

**Workflow:**

```bash
# 1. Generate message
hunknote

# 2. (Optional) Edit message
hunknote -e

# 3. Commit with confirmation
hunknote commit

# Or commit immediately (for scripts)
hunknote commit -y
```

> **Note**: If no cached message exists, you'll be prompted to run `hunknote` first.

---

### Init

```bash
hunknote init
```

Initialize hunknote with interactive setup.

**What it configures:**
- LLM provider selection
- Model selection
- API key (securely stored)

**Configuration files created:**
- `~/.hunknote/config.yaml` - Settings
- `~/.hunknote/credentials` - API keys (secure permissions)

---

### Config

Manage global configuration.

#### Show Configuration

```bash
hunknote config show
```

Displays current provider, model, and settings.

#### Set Provider

```bash
# Interactive model selection
hunknote config set-provider google

# Specify model directly
hunknote config set-provider anthropic --model claude-sonnet-4-20250514
```

#### Set API Key

```bash
hunknote config set-key google
hunknote config set-key anthropic
```

#### List Providers

```bash
hunknote config list-providers
```

#### List Models

```bash
# All providers
hunknote config list-models

# Specific provider
hunknote config list-models google
```

---

### Style

Manage commit message style profiles.

#### List Styles

```bash
hunknote style list
```

Shows available profiles with descriptions.

#### Show Style Details

```bash
hunknote style show conventional
```

Shows format template and example output.

#### Set Style

```bash
# Set globally
hunknote style set conventional

# Set for current repo only
hunknote style set ticket --repo
```

---

### Scope

Manage scope inference settings.

#### Check Scope

```bash
hunknote scope check
```

Preview what scope would be inferred for current staged changes.

#### Show Scope Tree

```bash
hunknote scope tree
```

Display file structure with detected scopes.

#### JSON Output

```bash
hunknote scope json
```

Output scope analysis as JSON.

---

### Ignore

Manage ignore patterns for the current repository.

#### List Patterns

```bash
hunknote ignore list
```

#### Add Pattern

```bash
hunknote ignore add "*.log"
hunknote ignore add "build/*"
```

#### Remove Pattern

```bash
hunknote ignore remove "*.log"
```

---

## Compose Mode

Compose mode splits your working tree changes into a clean stack of atomic commits.

### Overview

Instead of one large commit, compose analyzes your changes and creates multiple focused commits:

```
Working tree with mixed changes
         ↓
    hunknote compose
         ↓
┌─────────────────────┐
│ C1: feat(auth): ... │
│ C2: fix(api): ...   │
│ C3: docs: ...       │
└─────────────────────┘
```

### Basic Usage

```bash
# Preview the proposed commit stack
hunknote compose

# Execute and create commits
hunknote compose --commit

# Skip confirmation
hunknote compose --commit --yes
```

### How It Works

1. **Collects changes**: Gets all tracked changes from `git diff HEAD`
2. **Parses diff**: Breaks down into files and hunks with stable IDs
3. **Plans commits**: LLM determines how to split changes logically
4. **Validates plan**: Ensures all hunks are assigned, no duplicates
5. **Executes**: Applies patches and creates commits (if `--commit`)

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--max-commits` | 6 | Maximum commits in the plan |
| `--style` | config | Style profile for messages |
| `-c, --commit` | false | Execute and create commits |
| `-y, --yes` | false | Skip confirmation |
| `--dry-run` | false | Force preview mode |
| `-r, --regenerate` | false | Ignore cache, regenerate plan |
| `-j, --json` | false | Show cached plan JSON |
| `--from-plan PATH` | | Load plan from file |
| `--debug` | false | Show diagnostics |

### Caching

Compose caches plans to avoid redundant LLM calls:

- Cache key: `diff content + style + max_commits`
- Use `-r` to force regeneration
- Use `-j` to inspect cached plan
- Cache invalidates after successful execution

### Safety

**Preview mode (default)**: No git modifications

**Commit mode**: Includes recovery mechanisms
- Saves current state before execution
- Attempts restore on failure
- Prints recovery instructions

### Limitations

- **Untracked files**: Add with `git add -N <file>` first
- **Binary files**: Detected and skipped
- **Large diffs**: May hit token limits

### Examples

```bash
# Preview only
hunknote compose

# Use conventional style
hunknote compose --style conventional

# Limit to 3 commits
hunknote compose --max-commits 3

# Execute without confirmation
hunknote compose -c -y

# Force regenerate
hunknote compose -r

# Debug mode
hunknote compose --debug
```

---

## Style Profiles

Hunknote supports multiple commit message formats.

### Default

Standard format with title and bullet points.

```
Add user authentication feature

- Implement login and logout endpoints
- Add session management middleware
```

**Usage:** `hunknote` or `hunknote --style default`

---

### Blueprint

Comprehensive format with structured sections.

```
feat(auth): Add user authentication

Implement secure user authentication with JWT tokens
and session management for the API.

Changes:
- Add login and logout endpoints
- Implement JWT token validation

Implementation:
- Create auth middleware in hunknote/auth.py

Testing:
- Add unit tests for auth flow

Notes:
- Requires REDIS_URL for production
```

**Allowed sections:** Changes, Implementation, Testing, Documentation, Notes, Performance, Security, Config, API

**Usage:** `hunknote --style blueprint`

---

### Conventional

[Conventional Commits](https://www.conventionalcommits.org/) specification.

```
feat(auth): Add user authentication

- Implement login and logout endpoints
- Add session management middleware

Refs: PROJ-123
```

**Valid types:** feat, fix, docs, refactor, perf, test, build, ci, chore, style, revert

**Usage:** `hunknote --style conventional`

---

### Ticket

Ticket-prefixed format for issue tracking.

```
PROJ-123 Add user authentication

- Implement login endpoint
- Add session management
```

**Formats:**
- Prefix (default): `PROJ-123 subject`
- Prefix with scope: `PROJ-123 (auth) subject`
- Suffix: `subject (PROJ-123)`

**Usage:** `hunknote --style ticket --ticket PROJ-123`

> **Tip**: Hunknote can extract tickets from branch names automatically.

---

### Kernel

Linux kernel commit style.

```
auth: Add user authentication

- Implement login endpoint
```

**Usage:** `hunknote --style kernel --scope auth`

---

### Style Configuration

Configure in `~/.hunknote/config.yaml`:

```yaml
style:
  profile: conventional
  include_body: true
  max_bullets: 6
  wrap_width: 72

  # Blueprint options
  blueprint:
    section_titles: [Changes, Implementation, Testing]

  # Conventional options
  conventional:
    types: [feat, fix, docs, refactor, test]

  # Ticket options
  ticket:
    key_regex: "([A-Z][A-Z0-9]+-\\d+)"
    placement: prefix
```

---

## Scope Inference

Hunknote automatically detects scope from your staged files.

### Strategies

#### Auto (Default)

Tries all strategies and uses the best match.

```bash
hunknote --scope-strategy auto
```

#### Monorepo

Detects scope from monorepo directory structures.

```
packages/auth/src/login.py → scope: auth
apps/web/components/Button.js → scope: web
```

**Recognized roots:** packages/, apps/, libs/, modules/, services/

```bash
hunknote --scope-strategy monorepo
```

#### Path-Prefix

Uses the most common path segment.

```
api/routes.py → scope: api
api/models.py → scope: api
```

```bash
hunknote --scope-strategy path-prefix
```

#### Mapping

Uses explicit path-to-scope configuration.

```yaml
scope:
  strategy: mapping
  mapping:
    "src/api/": api
    "src/web/": ui
```

```bash
hunknote --scope-strategy mapping
```

#### None

Disables scope inference.

```bash
hunknote --scope-strategy none
# or
hunknote --no-scope
```

### Precedence

Scope is determined in order (first wins):

1. `--scope <value>` CLI flag
2. `--no-scope` CLI flag
3. LLM suggested scope
4. Heuristics-based inference
5. No scope

### Debug

```bash
hunknote --debug
```

Shows: strategy used, inferred scope, confidence, final scope.

---

## Intent Channel

Provide explicit context to guide commit message framing.

### Usage

```bash
# Direct text
hunknote --intent "Fix race condition in session handling"

# From file
hunknote --intent-file ./context.txt

# Both combined
hunknote --intent "Primary reason" --intent-file ./details.txt
```

### How It Works

- Intent is injected into the LLM prompt
- Guides framing, not technical facts
- Diff content takes precedence over intent
- Different intents generate different messages (cached separately)

### When to Use

| Scenario | Example |
|----------|---------|
| Non-obvious fix | "Fix memory leak under high load" |
| Business context | "Requested by security team" |
| Refactor motivation | "Prepare for API v2 migration" |
| Bug reference | "Fixes support ticket #1234" |

---

## Merge Detection

Hunknote automatically detects merge states.

### Detected States

| State | Detection | Behavior |
|-------|-----------|----------|
| Merge in progress | `.git/MERGE_HEAD` exists | Type: `merge` |
| Conflict resolution | MERGE_HEAD + resolved conflicts | Type: `merge` |
| Normal commit | No MERGE_HEAD | Normal type selection |

### Merge Message Format

```
merge(auth): Merge branch feature-auth into main

Integrate the feature-auth branch which adds user
authentication with JWT tokens.

Changes:
- Add login and logout endpoints
- Implement JWT token validation
```

---

## LLM Providers

### Supported Providers

| Provider | API Key Variable | Description |
|----------|------------------|-------------|
| **Anthropic** | `ANTHROPIC_API_KEY` | Claude models, high quality |
| **OpenAI** | `OPENAI_API_KEY` | GPT models, versatile |
| **Google** | `GOOGLE_API_KEY` | Gemini models, fast |
| **Mistral** | `MISTRAL_API_KEY` | European provider |
| **Cohere** | `COHERE_API_KEY` | Enterprise focused |
| **Groq** | `GROQ_API_KEY` | Ultra-fast inference |
| **OpenRouter** | `OPENROUTER_API_KEY` | 200+ models via single API |

### Popular Models

**Anthropic**
- claude-sonnet-4-20250514
- claude-3-5-sonnet-latest
- claude-3-5-haiku-latest

**OpenAI**
- gpt-4.1
- gpt-4.1-mini
- gpt-4o

**Google**
- gemini-2.5-pro
- gemini-2.5-flash
- gemini-2.0-flash

**Mistral**
- mistral-large-latest
- codestral-latest

**Groq**
- llama-3.3-70b-versatile
- llama-3.1-8b-instant

### API Key Resolution

Keys are resolved in order:

1. Environment variables (highest priority)
2. `~/.hunknote/credentials` file
3. Project `.env` file

---

## Configuration

### Global Configuration

Location: `~/.hunknote/`

**config.yaml**

```yaml
# Required
provider: google
model: gemini-2.0-flash

# Optional
max_tokens: 1500
temperature: 0.3
editor: code --wait

# Default ignores for all repos
default_ignore:
  - poetry.lock
  - package-lock.json
```

**credentials**

```
GOOGLE_API_KEY=your-api-key
ANTHROPIC_API_KEY=your-api-key
```

### Repository Configuration

Location: `<repo>/.hunknote/`

**config.yaml**

```yaml
# Style settings
style:
  profile: conventional

# Scope settings
scope:
  strategy: monorepo

# Ignore patterns
ignore:
  - poetry.lock
  - "*.min.js"
  - ".idea/*"
```

### Precedence

Settings apply in order (later overrides earlier):

1. Built-in defaults
2. Global config
3. Repository config
4. CLI flags

---

## Ignore Patterns

Exclude files from LLM analysis to reduce tokens and focus on code.

### Pattern Syntax

| Pattern | Matches |
|---------|---------|
| `poetry.lock` | Exact filename |
| `*.log` | Files ending in .log |
| `build/*` | Files in build directory |

### Default Patterns

```yaml
ignore:
  # Lock files
  - poetry.lock
  - package-lock.json
  - yarn.lock
  - Cargo.lock
  - go.sum

  # Build artifacts
  - "*.min.js"
  - "*.min.css"
  - "*.map"

  # Binary/compiled
  - "*.pyc"
  - "*.so"
  - "*.dll"

  # IDE
  - ".idea/*"
  - ".vscode/*"
```

### Managing Patterns

```bash
# List current patterns
hunknote ignore list

# Add pattern
hunknote ignore add "*.log"

# Remove pattern
hunknote ignore remove "*.log"
```

---

## Editor Integration

### Default Editor Selection

Hunknote looks for editors in order:

1. `editor` setting in config
2. gedit (with --wait)
3. `$EDITOR` environment variable
4. nano
5. vi

### Configuration

```yaml
# In ~/.hunknote/config.yaml
editor: code --wait
```

### Usage

```bash
# Edit generated message
hunknote -e
```

---

## Git Integration

### Git Subcommand

Hunknote works as a git subcommand:

```bash
git hunknote
git hunknote -e
git hunknote commit -y
```

### Context Collected

Hunknote analyzes:

- **Branch name** - Current branch
- **Staged files** - Files staged for commit
- **Change types** - New, modified, deleted, renamed
- **Recent commits** - Last 5 commits for context
- **Staged diff** - Actual code changes

---

## Troubleshooting

### No Staged Changes

```bash
# Error: No staged changes
git add <files>
hunknote
```

### API Key Not Found

```bash
# Option 1: Set via CLI
hunknote config set-key google

# Option 2: Environment variable
export GOOGLE_API_KEY=your-key

# Option 3: Credentials file
echo "GOOGLE_API_KEY=your-key" >> ~/.hunknote/credentials
```

### Cache Not Updating

```bash
# Force regeneration
hunknote -r
```

### Debug Mode

```bash
hunknote -d
```

Shows: cache status, tokens, staged files, scope inference.

### Raw JSON

```bash
hunknote -j
```

Shows the raw LLM response for debugging.

### Help

```bash
hunknote --help
hunknote config --help
hunknote compose --help
```

---

## Requirements

- **Python**: 3.12+
- **Git**: Any recent version
- **API Key**: At least one LLM provider

---

## License

MIT License - see [LICENSE](https://github.com/nash911/hunknote/blob/main/LICENSE) for details.

---

<p align="center">
  <strong>Hunknote</strong> — AI-powered commit messages
</p>
