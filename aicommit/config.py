"""Configuration for aicommit LLM providers.

Edit ACTIVE_PROVIDER and ACTIVE_MODEL below to change the LLM used for
generating commit messages.
"""

from enum import Enum


class LLMProvider(Enum):
    """Supported LLM providers."""

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

# Active provider - change this to switch providers
# Options: LLMProvider.ANTHROPIC, LLMProvider.OPENAI, LLMProvider.GOOGLE,
#          LLMProvider.MISTRAL, LLMProvider.COHERE, LLMProvider.GROQ,
#          LLMProvider.OPENROUTER
# ACTIVE_PROVIDER = LLMProvider.ANTHROPIC
ACTIVE_PROVIDER = LLMProvider.GOOGLE
# ACTIVE_PROVIDER = LLMProvider.OPENAI

# Active model - change this to use a different model
# See below for available models per provider
# ACTIVE_MODEL = "claude-sonnet-4-20250514"
ACTIVE_MODEL = "gemini-2.0-flash"
# ACTIVE_MODEL = "gpt-4.1-nano"

# ============================================================
# PROVIDER SETTINGS
# ============================================================

# Maximum tokens for LLM response
# Note: For Gemini thinking models, this is automatically multiplied
MAX_TOKENS = 1500

# Temperature for LLM response (lower = more deterministic)
TEMPERATURE = 0.3

# ============================================================
# AVAILABLE MODELS PER PROVIDER
# ============================================================

AVAILABLE_MODELS = {
    LLMProvider.ANTHROPIC: [
        "claude-sonnet-4-20250514",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
    ],
    LLMProvider.OPENAI: [
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
    ],
    LLMProvider.GOOGLE: [
        "gemini-3-pro-preview",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ],
    LLMProvider.MISTRAL: [
        "mistral-large-latest",
        "mistral-medium-latest",
        "mistral-small-latest",
        "codestral-latest",
    ],
    LLMProvider.COHERE: [
        "command-r-plus",
        "command-r",
        "command",
    ],
    LLMProvider.GROQ: [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
    LLMProvider.OPENROUTER: [
        # Anthropic via OpenRouter
        "anthropic/claude-sonnet-4",
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3-opus",
        # OpenAI via OpenRouter
        "openai/gpt-4o",
        "openai/gpt-4-turbo",
        "openai/gpt-3.5-turbo",
        # Google via OpenRouter
        "google/gemini-2.0-flash-exp",
        "google/gemini-pro-1.5",
        # Meta via OpenRouter
        "meta-llama/llama-3.3-70b-instruct",
        "meta-llama/llama-3.1-405b-instruct",
        # Mistral via OpenRouter
        "mistralai/mistral-large",
        "mistralai/mixtral-8x22b-instruct",
        # DeepSeek via OpenRouter
        "deepseek/deepseek-chat",
        "deepseek/deepseek-coder",
        # Qwen via OpenRouter
        "qwen/qwen-2.5-72b-instruct",
        "qwen/qwen-2.5-coder-32b-instruct",
    ],
}

# ============================================================
# API KEY ENVIRONMENT VARIABLES
# ============================================================

API_KEY_ENV_VARS = {
    LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
    LLMProvider.OPENAI: "OPENAI_API_KEY",
    LLMProvider.GOOGLE: "GOOGLE_API_KEY",
    LLMProvider.MISTRAL: "MISTRAL_API_KEY",
    LLMProvider.COHERE: "COHERE_API_KEY",
    LLMProvider.GROQ: "GROQ_API_KEY",
    LLMProvider.OPENROUTER: "OPENROUTER_API_KEY",
}


def get_api_key_env_var(provider: LLMProvider) -> str:
    """Get the environment variable name for the API key.

    Args:
        provider: The LLM provider.

    Returns:
        The environment variable name.
    """
    return API_KEY_ENV_VARS[provider]


# ============================================================
# FUTURE FEATURES (NOT YET IMPLEMENTED)
# ============================================================
# - Support for ~/.config/aicommit/config file
# - Support for local models (Ollama, LM Studio)
# - Support for ~/.aicommit/credentials file for API keys
