# Hunknote Features & Configuration Guide

> AI-powered git commit message generator with multi-LLM support

This documentation covers all features and configuration options available in the Hunknote CLI tool. Use this as a reference for setting up and customizing your commit message generation workflow.

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Command Reference](#command-reference)
5. [Configuration](#configuration)
6. [LLM Providers](#llm-providers)
7. [Caching System](#caching-system)
8. [Ignore Patterns](#ignore-patterns)
9. [Editor Integration](#editor-integration)
10. [Git Integration](#git-integration)
11. [Troubleshooting](#troubleshooting)

---

## Overview

Hunknote is a command-line tool that analyzes your staged git changes and generates meaningful, well-structured commit messages using AI language models. It supports multiple LLM providers and includes smart caching to minimize API calls.

### Key Features

| Feature | Description |
|---------|-------------|
| **Multi-LLM Support** | Choose from 7 providers: Anthropic, OpenAI, Google, Mistral, Cohere, Groq, OpenRouter |
| **Smart Caching** | Reuses generated messages when staged changes haven't changed |
| **Structured Output** | Generates title + bullet points following git best practices |
| **Intelligent Context** | Distinguishes between new, modified, deleted, and renamed files |
| **Editor Integration** | Review and edit messages before committing |
| **One-Command Commits** | Generate and commit in a single step with `-c` flag |
| **Configurable Ignores** | Exclude lock files, build artifacts from analysis |
| **Debug Mode** | Inspect cache metadata, tokens, and file changes |

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

### 3. Generate, Edit, and Commit

```bash
hunknote -e -c
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
| `--commit` | `-c` | Automatically commit using the generated message | `false` |
| `--regenerate` | `-r` | Force regenerate, ignoring cached message | `false` |
| `--debug` | `-d` | Show cache metadata (files, tokens, diff preview) | `false` |
| `--max-diff-chars` | | Maximum characters for staged diff | `50000` |
| `--help` | | Show help message | |

#### Examples

```bash
# Generate and print message
hunknote

# Generate, edit in editor, then commit
hunknote -e -c

# Force regeneration (bypass cache)
hunknote -r

# View debug information
hunknote -d
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

*Documentation generated for Hunknote v1.1.0*

