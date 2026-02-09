# AI Commit Message Generator

A fast, reliable CLI tool that generates high-quality git commit messages from your staged changes using AI.

## Features

- **Automatic commit message generation** from staged git changes
- **Multi-LLM support**: Anthropic, OpenAI, Google Gemini, Mistral, Cohere, Groq, and OpenRouter
- **Structured output**: Title line + bullet-point body following git best practices
- **Smart caching**: Reuses generated messages for the same staged changes (no redundant API calls)
- **Intelligent context**: Distinguishes between new files and modified files for accurate descriptions
- **Editor integration**: Review and edit generated messages before committing
- **One-command commits**: Generate and commit in a single step
- **Configurable ignore patterns**: Exclude lock files, build artifacts, etc. from diff analysis
- **Debug mode**: Inspect cache metadata, token usage, and file change details
- **Comprehensive test suite**: 199 unit tests covering all modules

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd ai_commit

# Install with Poetry (requires Python 3.12+)
poetry install

# Or install in development mode with test dependencies
poetry install --with dev
```

## Quick Start

```bash
# Set your API key (example with Anthropic)
export ANTHROPIC_API_KEY=your_key_here

# Stage your changes
git add <files>

# Generate a commit message
aicommit

# Or generate, edit, and commit in one step
aicommit -e -c
```

## Configuration

### Setting Up API Keys

Set the API key for your chosen provider as an environment variable:

```bash
# Anthropic (default)
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

Or create a `.env` file in your project root with the appropriate key.

### Changing the LLM Provider

Edit `aicommit/config.py` to change the provider and model:

```python
from aicommit.config import LLMProvider

# Change these values to switch providers
ACTIVE_PROVIDER = LLMProvider.GOOGLE  # or ANTHROPIC, OPENAI, MISTRAL, COHERE, GROQ, OPENROUTER
ACTIVE_MODEL = "gemini-2.0-flash"     # model name for the selected provider
```

### Supported Providers and Models

| Provider | Models | API Key Variable |
|----------|--------|------------------|
| **Anthropic** | claude-sonnet-4-20250514, claude-3-5-sonnet-latest, claude-3-5-haiku-latest, claude-3-opus-latest | `ANTHROPIC_API_KEY` |
| **OpenAI** | gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo | `OPENAI_API_KEY` |
| **Google** | gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash | `GOOGLE_API_KEY` |
| **Mistral** | mistral-large-latest, mistral-medium-latest, mistral-small-latest, codestral-latest | `MISTRAL_API_KEY` |
| **Cohere** | command-r-plus, command-r, command | `COHERE_API_KEY` |
| **Groq** | llama-3.3-70b-versatile, llama-3.1-8b-instant, mixtral-8x7b-32768 | `GROQ_API_KEY` |
| **OpenRouter** | 200+ models (anthropic/claude-sonnet-4, openai/gpt-4o, meta-llama/llama-3.3-70b-instruct, etc.) | `OPENROUTER_API_KEY` |

## Usage

### Basic Usage

Stage your changes and generate a commit message:

```bash
git add <files>
aicommit
```

### Command Options

| Flag | Description |
|------|-------------|
| `-e, --edit` | Open the generated message in an editor for manual edits |
| `-c, --commit` | Automatically commit using the generated message |
| `-r, --regenerate` | Force regenerate, ignoring cached message |
| `-d, --debug` | Show full cache metadata (staged files, tokens, diff preview) |
| `--max-diff-chars` | Maximum characters for staged diff (default: 50000) |

### Ignore Pattern Management

Manage which files are excluded from the diff sent to the LLM:

```bash
# List all ignore patterns
aicommit ignore list

# Add a new pattern
aicommit ignore add "*.log"
aicommit ignore add "build/*"
aicommit ignore add "dist/*"

# Remove a pattern
aicommit ignore remove "*.log"
```

### Examples

```bash
# Generate commit message (print only, cached for reuse)
aicommit

# Generate and open in editor
aicommit -e

# Generate and commit directly
aicommit -c

# Edit message then commit
aicommit -e -c

# Force regeneration (ignore cache)
aicommit -r

# Debug: view cache metadata and token usage
aicommit -d
```

### Git Subcommand

You can also use it as a git subcommand:

```bash
git aicommit
git aicommit -e -c
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

Cache files are stored in `<repo>/.aicommit/`:
- `aicommit_message.txt` - The cached commit message
- `aicommit_context_hash.txt` - Hash of the git context
- `aicommit_metadata.json` - Full metadata (tokens, model, timestamp)
- `config.yaml` - Repository-specific configuration

**Gitignore recommendation:** Add these to your `.gitignore`:
```
# aicommit cache files (but keep config.yaml for shared settings)
.aicommit/aicommit_*.txt
.aicommit/aicommit_*.json
```

## Repository Configuration

Each repository can have its own `.aicommit/config.yaml` file for customization.
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

The project includes a comprehensive test suite with 199 tests:

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
| `formatters.py` | 25 | Commit message formatting and validation |
| `cache.py` | 35 | Caching utilities and metadata |
| `user_config.py` | 22 | YAML config file management |
| `git_ctx.py` | 29 | Git context collection and filtering |
| `llm/base.py` | 27 | JSON parsing, schema validation |
| `llm/*.py` providers | 23 | All LLM provider classes |
| `cli.py` | 17 | CLI commands |
| `config.py` | 22 | Configuration constants |

### Project Structure

```
aicommit/
├── __init__.py
├── cli.py              # CLI entry point and commands
├── config.py           # LLM provider configuration
├── cache.py            # Caching utilities
├── formatters.py       # Commit message formatting
├── git_ctx.py          # Git context collection
├── user_config.py      # Repository config management
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
