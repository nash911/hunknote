# AI Commit Message Generator

A fast, reliable CLI tool that generates high-quality git commit messages from your staged changes using Claude AI.

## Features

- **Automatic commit message generation** from staged git changes
- **Structured output**: Title line + bullet-point body following git best practices
- **Editor integration**: Review and edit generated messages before committing
- **One-command commits**: Generate and commit in a single step

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd ai_commit

# Install with Poetry (requires Python 3.12+)
poetry install
```

## Configuration

Set your Anthropic API key as an environment variable:

```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

Or create a `.env` file in your project root:

```
ANTHROPIC_API_KEY=your_api_key_here
```

### Optional Environment Variables

- `ANTHROPIC_MODEL`: Override the default model (default: `claude-sonnet-4-20250514`)

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
| `--max-diff-chars` | Maximum characters for staged diff (default: 50000) |

### Examples

```bash
# Generate commit message (print only)
aicommit

# Generate and open in editor
aicommit -e

# Generate and commit directly
aicommit -c

# Edit message then commit
aicommit -e -c

# Debug: see raw JSON from LLM
aicommit --json
```

### Git Subcommand

You can also use it as a git subcommand:

```bash
git aicommit
git aicommit -e -c
```

## How It Works

1. Collects git context: branch name, status, last 5 commits, and staged diff
2. Sends context to Claude AI with a prompt optimized for commit messages
3. Parses the structured JSON response (title + bullet points)
4. Renders into standard git commit message format
5. Optionally opens editor and/or commits

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
- Anthropic API key

## License

MIT
