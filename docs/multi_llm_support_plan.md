# Multi-LLM Support Plan

## Overview

This plan outlines the addition of support for multiple LLM providers, both directly via their native APIs and through OpenRouter as a unified gateway.

## Supported LLM Providers

### Direct API Support

| Provider | Models | SDK/Library | Environment Variable |
|----------|--------|-------------|---------------------|
| **Anthropic** | claude-sonnet-4-20250514, claude-3-5-sonnet-latest, claude-3-5-haiku-latest, claude-3-opus-latest | `anthropic` | `ANTHROPIC_API_KEY` |
| **OpenAI** | gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo | `openai` | `OPENAI_API_KEY` |
| **Google** | gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash | `google-generativeai` | `GOOGLE_API_KEY` |
| **Mistral** | mistral-large-latest, mistral-medium-latest, mistral-small-latest, codestral-latest | `mistralai` | `MISTRAL_API_KEY` |
| **Cohere** | command-r-plus, command-r, command | `cohere` | `COHERE_API_KEY` |
| **Groq** | llama-3.3-70b-versatile, llama-3.1-8b-instant, mixtral-8x7b-32768 | `groq` | `GROQ_API_KEY` |

### OpenRouter Support (Unified Gateway)

OpenRouter provides access to 200+ models through a single API. Key models available:

| Provider via OpenRouter | Models |
|------------------------|--------|
| **Anthropic** | anthropic/claude-sonnet-4, anthropic/claude-3.5-sonnet, anthropic/claude-3-opus |
| **OpenAI** | openai/gpt-4o, openai/gpt-4-turbo, openai/gpt-3.5-turbo |
| **Google** | google/gemini-2.0-flash-exp, google/gemini-pro-1.5 |
| **Meta** | meta-llama/llama-3.3-70b-instruct, meta-llama/llama-3.1-405b-instruct |
| **Mistral** | mistralai/mistral-large, mistralai/mixtral-8x22b-instruct |
| **DeepSeek** | deepseek/deepseek-chat, deepseek/deepseek-coder |
| **Qwen** | qwen/qwen-2.5-72b-instruct, qwen/qwen-2.5-coder-32b-instruct |

**OpenRouter Environment Variable:** `OPENROUTER_API_KEY`

---

## Configuration System

### New File: `hunknote/config.py`

The active provider and model are configured directly in `config.py`. Users edit this file to change providers.

```python
from enum import Enum

class LLMProvider(Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    MISTRAL = "mistral"
    COHERE = "cohere"
    GROQ = "groq"
    OPENROUTER = "openrouter"

# ============================================================
# USER CONFIGURATION - Edit these values to change LLM provider
# ============================================================
ACTIVE_PROVIDER = LLMProvider.ANTHROPIC
ACTIVE_MODEL = "claude-sonnet-4-20250514"
```

### Future Enhancement (Not in MVP)
- Support `~/.config/hunknote/config` file for user configuration
- CLI command to configure provider/model

---

## Architecture

### Provider Abstraction Layer

```
hunknote/
├── llm/
│   ├── __init__.py       # Factory function + exports
│   ├── base.py           # Abstract base class for LLM providers
│   ├── anthropic.py      # Anthropic implementation
│   ├── openai_provider.py # OpenAI implementation
│   ├── google.py         # Google Gemini implementation
│   ├── mistral.py        # Mistral implementation
│   ├── cohere.py         # Cohere implementation
│   ├── groq.py           # Groq implementation
│   └── openrouter.py     # OpenRouter unified gateway
├── config.py             # Configuration (user edits this)
└── ...
```

### Base Provider Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class LLMResult:
    commit_json: CommitMessageJSON
    model: str
    input_tokens: int
    output_tokens: int

class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, context_bundle: str) -> LLMResult:
        """Generate commit message from context."""
        pass
    
    @abstractmethod
    def get_api_key(self) -> str:
        """Get API key from environment."""
        pass
```

---

## Implementation Plan

### Phase 1: Refactor Existing Code
1. Create `config.py` with provider/model configuration
2. Create `llm/base.py` with abstract base class and shared prompts
3. Move current Anthropic code to `llm/anthropic.py`
4. Create `llm/__init__.py` with factory function
5. Update `cli.py` to use the new provider system

### Phase 2: Add Direct Provider Support
1. Implement `llm/openai_provider.py`
2. Implement `llm/google.py`
3. Implement `llm/mistral.py`
4. Implement `llm/cohere.py`
5. Implement `llm/groq.py`

### Phase 3: Add OpenRouter Support
1. Implement `llm/openrouter.py` (uses OpenAI-compatible API)

### Phase 4: Update Dependencies and Test
1. Add required packages to pyproject.toml
2. Test with available providers

---

## Dependencies to Add

```toml
[tool.poetry.dependencies]
# Existing
anthropic = "^0.78.0"

# New
openai = "^1.0.0"
google-generativeai = "^0.5.0"
mistralai = "^1.0.0"
cohere = "^5.0.0"
groq = "^0.9.0"
```

**Note:** OpenRouter uses OpenAI-compatible API, so no additional package needed.

---

## Environment Variables Summary

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google AI API key |
| `MISTRAL_API_KEY` | Mistral API key |
| `COHERE_API_KEY` | Cohere API key |
| `GROQ_API_KEY` | Groq API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

---

## Usage

```bash
# Edit hunknote/config.py to set provider and model:
# ACTIVE_PROVIDER = LLMProvider.OPENAI
# ACTIVE_MODEL = "gpt-4o"

# Then run as usual
hunknote
hunknote -e -c
```

---

## Prompt Compatibility

All providers will use the same system/user prompts. The JSON output format is standard and works across all models:

```json
{
  "title": "string",
  "body_bullets": ["string", "..."]
}
```

Some providers may need slight prompt adjustments for optimal JSON output, which will be handled in each provider implementation.

---

## Error Handling

Each provider implementation will:
1. Validate API key presence
2. Handle rate limits gracefully
3. Parse and validate JSON response
4. Provide clear error messages for common failures

---

## Testing Checklist

- [ ] Anthropic direct API works
- [ ] OpenAI direct API works
- [ ] Google Gemini direct API works
- [ ] Mistral direct API works
- [ ] Cohere direct API works
- [ ] Groq direct API works
- [ ] OpenRouter works
- [ ] Caching works with all providers
- [ ] Token usage tracking works for all providers

---

## Decisions Made

1. **Local models support:** Not in MVP. Add Ollama/LM Studio support in future phase.

2. **Configuration method:** Edit `config.py` directly for MVP. Add `~/.config/hunknote/config` file support later.

3. **API key storage:** Environment variables only for MVP. Add `~/.hunknote/credentials` file support later.

4. **CLI flags:** No `--provider` or `--list-models` flags. Configuration is done via `config.py` only.

---

## Summary

This plan adds support for 6 direct LLM providers plus OpenRouter (200+ models) while maintaining backward compatibility with the existing Anthropic-only implementation. Configuration is done by editing `config.py`.
