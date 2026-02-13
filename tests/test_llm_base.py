"""Tests for hunknote.llm.base module."""

import pytest

from hunknote.formatters import CommitMessageJSON
from hunknote.llm.base import (
    JSONParseError,
    LLMError,
    LLMResult,
    MissingAPIKeyError,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    parse_json_response,
    validate_commit_json,
)


class TestExceptions:
    """Tests for LLM exception classes."""

    def test_llm_error_is_exception(self):
        """Test that LLMError is an Exception."""
        error = LLMError("test error")
        assert isinstance(error, Exception)

    def test_missing_api_key_is_llm_error(self):
        """Test that MissingAPIKeyError is an LLMError."""
        error = MissingAPIKeyError("missing key")
        assert isinstance(error, LLMError)

    def test_json_parse_error_is_llm_error(self):
        """Test that JSONParseError is an LLMError."""
        error = JSONParseError("parse failed")
        assert isinstance(error, LLMError)


class TestLLMResult:
    """Tests for LLMResult dataclass."""

    def test_create_result(self):
        """Test creating LLMResult."""
        commit_json = CommitMessageJSON(
            title="Test",
            body_bullets=["Change 1"],
        )
        result = LLMResult(
            commit_json=commit_json,
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
        )

        assert result.model == "gpt-4"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.commit_json.title == "Test"


class TestParseJsonResponse:
    """Tests for parse_json_response function."""

    def test_parses_valid_json(self):
        """Test parsing valid JSON."""
        response = '{"title": "Test", "body_bullets": ["Change"]}'
        result = parse_json_response(response)

        assert result["title"] == "Test"
        assert result["body_bullets"] == ["Change"]

    def test_strips_whitespace(self):
        """Test that whitespace is stripped."""
        response = '  {"title": "Test", "body_bullets": ["Change"]}  \n'
        result = parse_json_response(response)

        assert result["title"] == "Test"

    def test_removes_markdown_fences(self):
        """Test removal of markdown code fences."""
        response = '''```json
{"title": "Test", "body_bullets": ["Change"]}
```'''
        result = parse_json_response(response)

        assert result["title"] == "Test"

    def test_removes_markdown_fences_no_language(self):
        """Test removal of code fences without language specifier."""
        response = '''```
{"title": "Test", "body_bullets": ["Change"]}
```'''
        result = parse_json_response(response)

        assert result["title"] == "Test"

    def test_extracts_json_from_surrounding_text(self):
        """Test extraction of JSON from surrounding text."""
        response = '''Here is the JSON:
{"title": "Test", "body_bullets": ["Change"]}
That's the response.'''
        result = parse_json_response(response)

        assert result["title"] == "Test"

    def test_handles_nested_json(self):
        """Test handling nested JSON structures."""
        response = '{"title": "Test", "body_bullets": ["Change"], "extra": {"nested": true}}'
        result = parse_json_response(response)

        assert result["title"] == "Test"
        assert result["extra"]["nested"] is True

    def test_raises_on_invalid_json(self):
        """Test that invalid JSON raises JSONParseError."""
        response = '{"title": "Test", "body_bullets": ['  # Incomplete

        with pytest.raises(JSONParseError) as exc_info:
            parse_json_response(response)

        assert "Failed to parse" in str(exc_info.value)

    def test_raises_on_empty_response(self):
        """Test that empty response raises JSONParseError."""
        with pytest.raises(JSONParseError):
            parse_json_response("")

    def test_error_includes_raw_response(self):
        """Test that error includes raw response."""
        response = "not json at all"

        with pytest.raises(JSONParseError) as exc_info:
            parse_json_response(response)

        assert "not json at all" in str(exc_info.value)

    def test_multiline_json(self):
        """Test parsing multiline JSON."""
        response = '''{
    "title": "Multi-line title",
    "body_bullets": [
        "First bullet",
        "Second bullet"
    ]
}'''
        result = parse_json_response(response)

        assert result["title"] == "Multi-line title"
        assert len(result["body_bullets"]) == 2


class TestValidateCommitJson:
    """Tests for validate_commit_json function."""

    def test_validates_correct_schema(self):
        """Test validation of correct schema."""
        parsed = {
            "title": "Add feature",
            "body_bullets": ["Change 1", "Change 2"],
        }

        result = validate_commit_json(parsed, "{}")

        assert isinstance(result, CommitMessageJSON)
        assert result.title == "Add feature"
        assert len(result.body_bullets) == 2

    def test_raises_on_missing_title(self):
        """Test error on missing title."""
        parsed = {"body_bullets": ["Change"]}

        with pytest.raises(JSONParseError) as exc_info:
            validate_commit_json(parsed, "{}")

        assert "does not match expected schema" in str(exc_info.value)

    def test_raises_on_missing_body_bullets(self):
        """Test error on missing body_bullets."""
        parsed = {"title": "Test"}

        with pytest.raises(JSONParseError):
            validate_commit_json(parsed, "{}")

    def test_raises_on_wrong_type(self):
        """Test error on wrong field type."""
        parsed = {
            "title": "Test",
            "body_bullets": "not a list",
        }

        with pytest.raises(JSONParseError):
            validate_commit_json(parsed, "{}")

    def test_raises_on_empty_title(self):
        """Test error on empty title."""
        parsed = {
            "title": "",
            "body_bullets": ["Change"],
        }

        with pytest.raises(JSONParseError):
            validate_commit_json(parsed, "{}")

    def test_raises_on_empty_bullets(self):
        """Test error on empty body_bullets."""
        parsed = {
            "title": "Test",
            "body_bullets": [],
        }

        with pytest.raises(JSONParseError):
            validate_commit_json(parsed, "{}")

    def test_error_includes_parsed_json(self):
        """Test that error includes parsed JSON."""
        parsed = {"invalid": "schema"}

        with pytest.raises(JSONParseError) as exc_info:
            validate_commit_json(parsed, "{}")

        assert "invalid" in str(exc_info.value)


class TestPromptTemplates:
    """Tests for prompt templates."""

    def test_system_prompt_not_empty(self):
        """Test that system prompt is not empty."""
        assert len(SYSTEM_PROMPT) > 0

    def test_system_prompt_mentions_commit_messages(self):
        """Test that system prompt mentions commit messages."""
        assert "commit" in SYSTEM_PROMPT.lower()

    def test_user_prompt_has_placeholder(self):
        """Test that user prompt has context_bundle placeholder."""
        assert "{context_bundle}" in USER_PROMPT_TEMPLATE

    def test_user_prompt_mentions_json(self):
        """Test that user prompt mentions JSON."""
        assert "JSON" in USER_PROMPT_TEMPLATE

    def test_user_prompt_specifies_structure(self):
        """Test that user prompt specifies title and body_bullets."""
        assert "title" in USER_PROMPT_TEMPLATE
        assert "body_bullets" in USER_PROMPT_TEMPLATE

    def test_user_prompt_format(self):
        """Test that user prompt can be formatted."""
        formatted = USER_PROMPT_TEMPLATE.format(context_bundle="test context")
        assert "test context" in formatted
