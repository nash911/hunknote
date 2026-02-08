# AI Commit Message Generator

A fast, reliable CLI tool that generates high-quality git commit messages from your staged changes using AI.

## Features

- **Automatic commit message generation** from staged git changes
- **Multi-LLM support**: Anthropic, OpenAI, Google Gemini, Mistral, Cohere, Groq, and OpenRouter
- **Structured output**: Title line + bullet-point body following git best practices
- **Smart caching**: Reuses generated messages for the same staged changes (no redundant API calls)
- **Editor integration**: Review and edit generated messages before committing
- **One-command commits**: Generate and commit in a single step
- **Debug mode**: Inspect cache metadata and token usage

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd ai_commit

# Install with Poetry (requires Python 3.12+)
poetry install
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
ACTIVE_PROVIDER = LLMProvider.OPENAI  # or ANTHROPIC, GOOGLE, MISTRAL, COHERE, GROQ, OPENROUTER
ACTIVE_MODEL = "gpt-4o"  # model name for the selected provider
```

### Supported Providers and Models

| Provider | Models | API Key Variable |
|----------|--------|------------------|
| **Anthropic** | claude-sonnet-4-20250514, claude-3-5-sonnet-latest, claude-3-5-haiku-latest, claude-3-opus-latest | `ANTHROPIC_API_KEY` |
| **OpenAI** | gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo | `OPENAI_API_KEY` |
| **Google** | gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash | `GOOGLE_API_KEY` |
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
| `--json` | Print raw JSON output for debugging |
| `-e, --edit` | Open the generated message in an editor for manual edits |
| `-c, --commit` | Automatically commit using the generated message |
| `-r, --regenerate` | Force regenerate, ignoring cached message |
| `-d, --debug` | Show full cache metadata (staged files, tokens, diff preview) |
| `--max-diff-chars` | Maximum characters for staged diff (default: 50000) |

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

# Debug: see raw JSON from LLM
aicommit --json
```

### Git Subcommand

You can also use it as a git subcommand:

```bash
git aicommit
git aicommit -e -c
```

## Caching Behavior

The tool caches generated commit messages to avoid redundant API calls:

- **Same staged changes** → Uses cached message (no API call)
- **Different staged changes** → Regenerates automatically
- **After commit** → Cache is invalidated
- **Use `-r` flag** → Force regeneration

Cache files are stored in `<repo>/.tmp/`:
- `aicommit_message.txt` - The cached commit message
- `aicommit_context_hash.txt` - Hash of the git context
- `aicommit_metadata.json` - Full metadata (tokens, model, timestamp)

## How It Works

1. Collects git context: branch name, status, last 5 commits, and staged diff
2. Computes a hash of the context to check cache validity
3. If cache is valid, uses cached message; otherwise calls the configured LLM
4. Parses the structured JSON response (title + bullet points)
5. Renders into standard git commit message format
6. Optionally opens editor and/or commits

## Output Format

Generated messages follow git best practices:

```
Add user authentication feature

- Implement login and logout endpoints
- Add session management middleware
- Create user model with password hashing
```

## Requirements

- Python 3.12+
- Git
- API key for at least one supported LLM provider

## License

MIT
