# Homebrew Tap for Hunknote

This is the official [Homebrew](https://brew.sh/) tap for [Hunknote](https://github.com/nash911/hunknote) — an AI-powered CLI tool for generating git commit messages and composing atomic commit stacks.

## Installation

```bash
brew install nash911/tap/hunknote
```

This is equivalent to:

```bash
brew tap nash911/tap
brew install hunknote
```

## Upgrade

```bash
brew upgrade hunknote
```

## Uninstall

```bash
brew uninstall hunknote
```

## What is Hunknote?

Hunknote is an AI-powered CLI tool that goes beyond simple commit message generation. Its standout **Compose Mode** analyzes your working tree changes and intelligently splits them into a clean stack of atomic, well-documented commits.

- **Single change?** Generate a polished commit message instantly
- **Mixed changes?** Let Compose split them into logical, atomic commits automatically
- **7 LLM providers** supported: Anthropic, OpenAI, Google Gemini, Mistral, Cohere, Groq, OpenRouter

## Quick Start

```bash
# Set up your LLM provider
hunknote init

# Stage changes and generate a commit message
git add <files>
hunknote

# Or split mixed changes into atomic commits
hunknote compose
```

## Links

- [GitHub Repository](https://github.com/nash911/hunknote)
- [Documentation](https://docs.hunknote.com)

