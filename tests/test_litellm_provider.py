"""Tests for the unified LiteLLM provider."""

import os
from unittest.mock import MagicMock, patch

import pytest

from hunknote.config import LLMProvider
from hunknote.llm.base import MissingAPIKeyError, LLMResult, RawLLMResult
from hunknote.llm.litellm_provider import (
    LiteLLMProvider,
    _build_litellm_model_name,
    _is_thinking_model,
    _LITELLM_PREFIX,
    _LITELLM_API_KEY_ENV,
)


# ============================================================
# Model name building
# ============================================================

class TestBuildLitellmModelName:
    """Tests for _build_litellm_model_name helper."""

    def test_anthropic_prefix(self):
        result = _build_litellm_model_name(LLMProvider.ANTHROPIC, "claude-sonnet-4-20250514")
        assert result == "anthropic/claude-sonnet-4-20250514"

    def test_openai_prefix(self):
        result = _build_litellm_model_name(LLMProvider.OPENAI, "gpt-4o")
        assert result == "openai/gpt-4o"

    def test_google_prefix(self):
        result = _build_litellm_model_name(LLMProvider.GOOGLE, "gemini-2.0-flash")
        assert result == "gemini/gemini-2.0-flash"

    def test_mistral_prefix(self):
        result = _build_litellm_model_name(LLMProvider.MISTRAL, "mistral-large-latest")
        assert result == "mistral/mistral-large-latest"

    def test_cohere_prefix(self):
        result = _build_litellm_model_name(LLMProvider.COHERE, "command-r-plus")
        assert result == "cohere_chat/command-r-plus"

    def test_groq_prefix(self):
        result = _build_litellm_model_name(LLMProvider.GROQ, "llama-3.3-70b-versatile")
        assert result == "groq/llama-3.3-70b-versatile"

    def test_openrouter_prefix(self):
        result = _build_litellm_model_name(LLMProvider.OPENROUTER, "anthropic/claude-sonnet-4")
        assert result == "openrouter/anthropic/claude-sonnet-4"

    def test_skips_duplicate_prefix(self):
        """Model names that already include the prefix are not double-prefixed."""
        result = _build_litellm_model_name(LLMProvider.ANTHROPIC, "anthropic/claude-3-opus")
        assert result == "anthropic/claude-3-opus"

    def test_all_providers_have_prefix(self):
        """Every LLMProvider enum value has a litellm prefix mapping."""
        for provider in LLMProvider:
            assert provider in _LITELLM_PREFIX, f"Missing prefix for {provider}"

    def test_all_providers_have_api_key_env(self):
        """Every LLMProvider enum value has a litellm API key env mapping."""
        for provider in LLMProvider:
            assert provider in _LITELLM_API_KEY_ENV, f"Missing API key env for {provider}"


# ============================================================
# Thinking model detection
# ============================================================

class TestIsThinkingModel:
    """Tests for _is_thinking_model helper."""

    def test_gemini_25_flash_is_thinking(self):
        assert _is_thinking_model("gemini/gemini-2.5-flash") is True

    def test_gemini_25_pro_is_thinking(self):
        assert _is_thinking_model("gemini/gemini-2.5-pro") is True

    def test_gemini_20_flash_is_not_thinking(self):
        assert _is_thinking_model("gemini/gemini-2.0-flash") is False

    def test_openai_o1_is_thinking(self):
        assert _is_thinking_model("openai/o1") is True

    def test_openai_o3_is_thinking(self):
        assert _is_thinking_model("openai/o3") is True

    def test_regular_gpt_not_thinking(self):
        assert _is_thinking_model("openai/gpt-4o") is False

    def test_claude_regular_not_thinking(self):
        assert _is_thinking_model("anthropic/claude-sonnet-4-20250514") is False

    def test_case_insensitive(self):
        assert _is_thinking_model("GEMINI/GEMINI-2.5-FLASH") is True


# ============================================================
# LiteLLMProvider instantiation
# ============================================================

class TestLiteLLMProviderInit:
    """Tests for LiteLLMProvider constructor."""

    def test_stores_provider(self):
        p = LiteLLMProvider(LLMProvider.ANTHROPIC, "claude-sonnet-4-20250514")
        assert p.provider == LLMProvider.ANTHROPIC

    def test_stores_model(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        assert p.model == "gpt-4o"

    def test_stores_style(self):
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.0-flash", style="blueprint")
        assert p.style == "blueprint"

    def test_default_style_is_default(self):
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.0-flash")
        assert p.style == "default"

    def test_litellm_model_built(self):
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.0-flash")
        assert p._litellm_model == "gemini/gemini-2.0-flash"

    def test_api_key_env_var_set(self):
        p = LiteLLMProvider(LLMProvider.ANTHROPIC, "claude-sonnet-4-20250514")
        assert p.api_key_env_var == "ANTHROPIC_API_KEY"

    def test_all_styles(self):
        """All style profiles work with any provider."""
        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o", style=style)
            assert p.style == style


# ============================================================
# API key resolution
# ============================================================

class TestLiteLLMProviderApiKey:
    """Tests for API key resolution in LiteLLMProvider."""

    def test_gets_key_from_env(self):
        p = LiteLLMProvider(LLMProvider.ANTHROPIC, "claude-sonnet-4-20250514")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-123"}):
            assert p.get_api_key() == "test-key-123"

    def test_gets_key_from_keyring(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        with patch.dict(os.environ, {}, clear=True):
            with patch("hunknote.global_config.get_credential", return_value="keyring-key"):
                assert p.get_api_key() == "keyring-key"

    def test_missing_key_raises_error(self):
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.0-flash")
        with patch.dict(os.environ, {}, clear=True):
            with patch("hunknote.global_config.get_credential", return_value=None):
                with pytest.raises(MissingAPIKeyError) as exc_info:
                    p.get_api_key()
                assert "GOOGLE_API_KEY" in str(exc_info.value)

    def test_inject_api_key_sets_gemini_env(self):
        """For Google, inject sets GEMINI_API_KEY so litellm can find it."""
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.0-flash")
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "google-key"}, clear=True):
            p._inject_api_key_for_litellm()
            assert os.environ.get("GEMINI_API_KEY") == "google-key"

    def test_inject_api_key_all_providers(self):
        """API key injection works for every provider without errors."""
        for provider in LLMProvider:
            p = LiteLLMProvider(provider, "test-model")
            env_var = p.api_key_env_var
            with patch.dict(os.environ, {env_var: "test-key"}, clear=True):
                key = p._inject_api_key_for_litellm()
                assert key == "test-key"


# ============================================================
# Token budget
# ============================================================

class TestEffectiveMaxTokens:
    """Tests for _effective_max_tokens method."""

    def test_regular_model_uses_config(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        with patch("hunknote.config.MAX_TOKENS", 1500):
            assert p._effective_max_tokens() == 1500

    def test_thinking_model_multiplied(self):
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.5-flash")
        with patch("hunknote.config.MAX_TOKENS", 1500):
            assert p._effective_max_tokens() == 1500 * 3

    def test_raw_mode_floor(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        with patch("hunknote.config.MAX_TOKENS", 1500):
            assert p._effective_max_tokens(for_raw=True) == 8192

    def test_raw_mode_thinking_model(self):
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.5-pro")
        with patch("hunknote.config.MAX_TOKENS", 1500):
            assert p._effective_max_tokens(for_raw=True) == 8192 * 3

    def test_raw_mode_large_config(self):
        """If MAX_TOKENS > 8192, raw mode uses the larger value."""
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        with patch("hunknote.config.MAX_TOKENS", 10000):
            assert p._effective_max_tokens(for_raw=True) == 10000


# ============================================================
# generate() with mocked litellm.completion
# ============================================================

class TestLiteLLMProviderGenerate:
    """Tests for LiteLLMProvider.generate() with mocked litellm."""

    def _mock_response(self, text='{"title": "Test commit", "body_bullets": ["Change 1"]}',
                       prompt_tokens=100, completion_tokens=50):
        """Build a mock litellm completion response."""
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = text
        response.usage = MagicMock()
        response.usage.prompt_tokens = prompt_tokens
        response.usage.completion_tokens = completion_tokens
        response.usage.completion_tokens_details = None
        return response

    def test_generate_returns_llm_result(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        mock_resp = self._mock_response()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}):
            with patch("litellm.completion", return_value=mock_resp) as mock_comp:
                result = p.generate("test context bundle")

        assert isinstance(result, LLMResult)
        assert result.commit_json.title == "Test commit"
        assert result.model == "gpt-4o"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    def test_generate_passes_correct_model_to_litellm(self):
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.0-flash")
        mock_resp = self._mock_response()

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "key"}):
            with patch("litellm.completion", return_value=mock_resp) as mock_comp:
                p.generate("context")

        call_kwargs = mock_comp.call_args
        assert call_kwargs.kwargs["model"] == "gemini/gemini-2.0-flash"

    def test_generate_passes_api_key(self):
        p = LiteLLMProvider(LLMProvider.ANTHROPIC, "claude-sonnet-4-20250514")
        mock_resp = self._mock_response()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "my-key"}):
            with patch("litellm.completion", return_value=mock_resp) as mock_comp:
                p.generate("context")

        call_kwargs = mock_comp.call_args
        assert call_kwargs.kwargs["api_key"] == "my-key"

    def test_generate_uses_style_prompt(self):
        """Different styles produce different prompts."""
        for style in ["default", "conventional", "blueprint", "ticket", "kernel"]:
            p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o", style=style)
            mock_resp = self._mock_response()

            with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}):
                with patch("litellm.completion", return_value=mock_resp) as mock_comp:
                    p.generate("context")

            messages = mock_comp.call_args.kwargs["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert "context" in messages[1]["content"]

    def test_generate_raises_on_missing_key(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        with patch.dict(os.environ, {}, clear=True):
            with patch("hunknote.global_config.get_credential", return_value=None):
                with pytest.raises(MissingAPIKeyError):
                    p.generate("context")

    def test_generate_wraps_litellm_errors(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}):
            with patch("litellm.completion", side_effect=Exception("connection failed")):
                from hunknote.llm.base import LLMError
                with pytest.raises(LLMError) as exc_info:
                    p.generate("context")
                assert "connection failed" in str(exc_info.value)

    def test_generate_includes_char_counts(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        mock_resp = self._mock_response()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}):
            with patch("litellm.completion", return_value=mock_resp):
                result = p.generate("test context")

        assert result.input_chars == len("test context")
        assert result.prompt_chars > 0
        assert result.output_chars > 0


# ============================================================
# generate_raw() with mocked litellm.completion
# ============================================================

class TestLiteLLMProviderGenerateRaw:
    """Tests for LiteLLMProvider.generate_raw() with mocked litellm."""

    def _mock_response(self, text="raw plan output", prompt_tokens=200, completion_tokens=150):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = text
        response.usage = MagicMock()
        response.usage.prompt_tokens = prompt_tokens
        response.usage.completion_tokens = completion_tokens
        response.usage.completion_tokens_details = None
        return response

    def test_generate_raw_returns_raw_result(self):
        p = LiteLLMProvider(LLMProvider.GOOGLE, "gemini-2.0-flash")
        mock_resp = self._mock_response()

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "key"}):
            with patch("litellm.completion", return_value=mock_resp):
                result = p.generate_raw("system prompt", "user prompt")

        assert isinstance(result, RawLLMResult)
        assert result.raw_response == "raw plan output"
        assert result.model == "gemini-2.0-flash"
        assert result.input_tokens == 200
        assert result.output_tokens == 150

    def test_generate_raw_uses_higher_token_budget(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        mock_resp = self._mock_response()

        with patch("hunknote.config.MAX_TOKENS", 1500):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}):
                with patch("litellm.completion", return_value=mock_resp) as mock_comp:
                    p.generate_raw("system", "user")

        call_kwargs = mock_comp.call_args
        assert call_kwargs.kwargs["max_tokens"] == 8192

    def test_generate_raw_raises_on_empty_response(self):
        p = LiteLLMProvider(LLMProvider.OPENAI, "gpt-4o")
        mock_resp = self._mock_response(text="")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}):
            with patch("litellm.completion", return_value=mock_resp):
                from hunknote.llm.base import LLMError
                with pytest.raises(LLMError) as exc_info:
                    p.generate_raw("system", "user")
                assert "empty response" in str(exc_info.value)

    def test_generate_raw_works_for_all_providers(self):
        """Unlike the old architecture, all providers support generate_raw."""
        for provider in LLMProvider:
            p = LiteLLMProvider(provider, "test-model")
            mock_resp = self._mock_response()
            env_var = p.api_key_env_var

            with patch.dict(os.environ, {env_var: "key"}):
                with patch("litellm.completion", return_value=mock_resp):
                    result = p.generate_raw("system", "user")
                    assert isinstance(result, RawLLMResult)


# ============================================================
# Integration with get_provider
# ============================================================

class TestGetProviderIntegration:
    """Test that get_provider returns LiteLLMProvider for all providers."""

    def test_all_providers_return_litellm_provider(self):
        from hunknote.llm import get_provider

        for provider in LLMProvider:
            result = get_provider(provider)
            assert isinstance(result, LiteLLMProvider)
            assert result.provider == provider

    def test_model_passthrough(self):
        from hunknote.llm import get_provider

        result = get_provider(LLMProvider.OPENAI, model="gpt-4-turbo")
        assert result.model == "gpt-4-turbo"

    def test_style_passthrough(self):
        from hunknote.llm import get_provider

        result = get_provider(LLMProvider.GOOGLE, style="kernel")
        assert result.style == "kernel"

    def test_generate_commit_json_uses_litellm(self, mocker):
        """generate_commit_json dispatches through LiteLLMProvider."""
        from hunknote.llm import generate_commit_json
        from hunknote.styles import ExtendedCommitJSON

        mock_result = LLMResult(
            commit_json=ExtendedCommitJSON(title="Test", body_bullets=["Change"]),
            model="test-model",
            input_tokens=100,
            output_tokens=50,
        )

        mock_provider = mocker.MagicMock(spec=LiteLLMProvider)
        mock_provider.generate.return_value = mock_result

        mocker.patch("hunknote.llm.get_provider", return_value=mock_provider)

        result = generate_commit_json("test context")
        assert result.commit_json.title == "Test"

