# Hunknote

A fast, reliable CLI tool that generates high-quality git commit messages from your staged changes using AI.

## Features

- **Automatic commit message generation** from staged git changes
- **Multi-LLM support**: Anthropic, OpenAI, Google Gemini, Mistral, Cohere, Groq, and OpenRouter
- **Commit style profiles**: Default, Blueprint (structured sections), Conventional Commits, Ticket-prefixed, and Kernel-style
- **Smart scope inference**: Automatically detect scope from file paths (monorepo, path-prefix, mapping)
- **Intelligent type selection**: Automatically selects the correct commit type (feat, fix, docs, test, etc.)
- **Structured output**: Title line + bullet-point body following git best practices
- **Smart caching**: Reuses generated messages for the same staged changes (no redundant API calls)
- **Raw JSON debugging**: Inspect the raw LLM response with `--json` flag
- **Intelligent context**: Distinguishes between new files and modified files for accurate descriptions
- **Editor integration**: Review and edit generated messages before committing
- **One-command commits**: Generate and commit in a single step
- **Configurable ignore patterns**: Exclude lock files, build artifacts, etc. from diff analysis
- **Debug mode**: Inspect cache metadata, token usage, scope inference, and file change details
- **Comprehensive test suite**: 436 unit tests covering all modules

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

# Or generate, edit, and commit in one step
hunknote -e -c
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
| `-c, --commit` | Automatically commit using the generated message |
| `-r, --regenerate` | Force regenerate, ignoring cached message |
| `-d, --debug` | Show full cache metadata (staged files, tokens, diff preview, scope inference) |
| `-j, --json` | Show the raw JSON response from the LLM for debugging |
| `--style` | Override commit style profile (default, blueprint, conventional, ticket, kernel) |
| `--scope` | Force a scope for the commit message (use 'auto' for inference) |
| `--no-scope` | Disable scope even if profile supports it |
| `--scope-strategy` | Scope inference strategy (auto, monorepo, path-prefix, mapping, none) |
| `--ticket` | Force a ticket key (e.g., PROJ-123) for ticket-style commits |
| `--max-diff-chars` | Maximum characters for staged diff (default: 50000) |

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

# Generate and commit directly
hunknote -c

# Edit message then commit
hunknote -e -c

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
hunknote --style ticket --ticket PROJ-6767 -e -c

# Force kernel style for this commit
hunknote --style kernel --scope auth
```

### Git Subcommand

You can also use it as a git subcommand:

```bash
git hunknote
git hunknote -e -c
```

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

The project includes a comprehensive test suite with 436 tests:

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
| `cache.py` | 40 | Caching utilities, metadata, raw JSON storage |
| `cli.py` | 42 | CLI commands and subcommands |
| `config.py` | 24 | Configuration constants and enums |
| `formatters.py` | 21 | Commit message formatting and validation |
| `git_ctx.py` | 31 | Git context collection and filtering |
| `global_config.py` | 26 | Global user configuration (~/.hunknote/) |
| `scope.py` | 54 | Scope inference from file paths |
| `styles.py` | 96 | Commit style profiles and rendering |
| `llm/base.py` | 51 | JSON parsing, schema validation, style prompts |
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
