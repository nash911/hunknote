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

    def test_create_result_with_raw_response(self):
        """Test creating LLMResult with raw_response."""
        commit_json = CommitMessageJSON(
            title="Test",
            body_bullets=["Change 1"],
        )
        raw = '{"title": "Test", "body_bullets": ["Change 1"]}'
        result = LLMResult(
            commit_json=commit_json,
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            raw_response=raw,
        )

        assert result.raw_response == raw

    def test_raw_response_default_empty(self):
        """Test that raw_response defaults to empty string."""
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

        assert result.raw_response == ""

    def test_create_result_with_char_counts(self):
        """Test creating LLMResult with character counts."""
        commit_json = CommitMessageJSON(
            title="Test",
            body_bullets=["Change 1"],
        )
        result = LLMResult(
            commit_json=commit_json,
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            input_chars=5000,
            prompt_chars=8000,
            output_chars=1500,
        )

        assert result.input_chars == 5000
        assert result.prompt_chars == 8000
        assert result.output_chars == 1500

    def test_char_counts_default_to_zero(self):
        """Test that character counts default to zero."""
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

        assert result.input_chars == 0
        assert result.prompt_chars == 0
        assert result.output_chars == 0


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
    """Tests for validate_commit_json function with ExtendedCommitJSON."""

    def test_validates_correct_schema(self):
        """Test validation of correct schema returns ExtendedCommitJSON."""
        from hunknote.styles import ExtendedCommitJSON
        parsed = {
            "title": "Add feature",
            "body_bullets": ["Change 1", "Change 2"],
        }

        result = validate_commit_json(parsed, "{}")

        assert isinstance(result, ExtendedCommitJSON)
        assert result.title == "Add feature"
        assert len(result.body_bullets) == 2

    def test_validates_extended_schema(self):
        """Test validation of extended schema with type, scope, etc."""
        parsed = {
            "type": "feat",
            "scope": "api",
            "title": "Add endpoint",
            "body_bullets": ["Add GET endpoint"],
        }

        result = validate_commit_json(parsed, "{}")

        assert result.type == "feat"
        assert result.scope == "api"
        assert result.title == "Add endpoint"

    def test_validates_blueprint_schema(self):
        """Test validation of blueprint schema with summary and sections."""
        parsed = {
            "type": "feat",
            "scope": "auth",
            "title": "Add authentication",
            "summary": "Implement user authentication with JWT.",
            "sections": [
                {"title": "Changes", "bullets": ["Add login endpoint"]},
                {"title": "Testing", "bullets": ["Add auth tests"]},
            ],
        }

        result = validate_commit_json(parsed, "{}")

        assert result.type == "feat"
        assert result.summary == "Implement user authentication with JWT."
        assert len(result.sections) == 2
        assert result.sections[0].title == "Changes"

    def test_normalizes_subsystem_to_scope(self):
        """Test that kernel-style subsystem is normalized to scope."""
        parsed = {
            "subsystem": "net",
            "subject": "fix packet handling",
            "body_bullets": ["Fix bug"],
        }

        result = validate_commit_json(parsed, "{}")

        assert result.scope == "net"
        assert result.subject == "fix packet handling"

    def test_normalizes_subject_to_title(self):
        """Test that subject is also set as title for compatibility."""
        parsed = {
            "subject": "Add feature",
            "body_bullets": ["Change 1"],
        }

        result = validate_commit_json(parsed, "{}")

        assert result.subject == "Add feature"
        assert result.title == "Add feature"

    def test_handles_missing_body_bullets(self):
        """Test that missing body_bullets is normalized to empty list."""
        parsed = {
            "title": "Add feature",
            "type": "feat",
            "summary": "A summary.",
            "sections": [{"title": "Changes", "bullets": ["Change 1"]}],
        }

        result = validate_commit_json(parsed, "{}")

        assert result.body_bullets == []

    def test_raises_on_wrong_type(self):
        """Test error on wrong field type."""
        parsed = {
            "title": "Test",
            "body_bullets": "not a list",
        }

        with pytest.raises(JSONParseError):
            validate_commit_json(parsed, "{}")


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


class TestStyleSpecificPromptTemplates:
    """Tests for style-specific prompt templates."""

    def test_default_template_exists(self):
        """Test that default template exists."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_DEFAULT
        assert "{context_bundle}" in USER_PROMPT_TEMPLATE_DEFAULT
        assert "title" in USER_PROMPT_TEMPLATE_DEFAULT
        assert "body_bullets" in USER_PROMPT_TEMPLATE_DEFAULT

    def test_conventional_template_exists(self):
        """Test that conventional template exists."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "{context_bundle}" in USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "type" in USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "scope" in USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "subject" in USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "feat" in USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "fix" in USER_PROMPT_TEMPLATE_CONVENTIONAL

    def test_ticket_template_exists(self):
        """Test that ticket template exists."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_TICKET
        assert "{context_bundle}" in USER_PROMPT_TEMPLATE_TICKET
        assert "ticket" in USER_PROMPT_TEMPLATE_TICKET
        assert "subject" in USER_PROMPT_TEMPLATE_TICKET
        assert "PROJ-123" in USER_PROMPT_TEMPLATE_TICKET or "ABC-123" in USER_PROMPT_TEMPLATE_TICKET

    def test_kernel_template_exists(self):
        """Test that kernel template exists."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_KERNEL
        assert "{context_bundle}" in USER_PROMPT_TEMPLATE_KERNEL
        assert "subsystem" in USER_PROMPT_TEMPLATE_KERNEL
        assert "subject" in USER_PROMPT_TEMPLATE_KERNEL

    def test_conventional_template_has_all_types(self):
        """Test that conventional template includes all commit types."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL
        types = ["feat", "fix", "docs", "refactor", "perf", "test", "build", "ci", "chore", "style", "revert"]
        for commit_type in types:
            assert commit_type in USER_PROMPT_TEMPLATE_CONVENTIONAL

    def test_conventional_template_mentions_breaking_change(self):
        """Test that conventional template mentions breaking changes."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "breaking_change" in USER_PROMPT_TEMPLATE_CONVENTIONAL

    def test_ticket_template_mentions_branch_extraction(self):
        """Test that ticket template mentions extracting from branch."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_TICKET
        assert "branch" in USER_PROMPT_TEMPLATE_TICKET.lower()

    def test_kernel_template_mentions_lowercase(self):
        """Test that kernel template mentions lowercase preference."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_KERNEL
        assert "lowercase" in USER_PROMPT_TEMPLATE_KERNEL.lower()

    def test_blueprint_template_exists(self):
        """Test that blueprint template exists."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "{context_bundle}" in USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "type" in USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "summary" in USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "sections" in USER_PROMPT_TEMPLATE_BLUEPRINT

    def test_blueprint_template_has_allowed_sections(self):
        """Test that blueprint template lists allowed section titles."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "Changes" in USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "Implementation" in USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "Testing" in USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "Documentation" in USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "Notes" in USER_PROMPT_TEMPLATE_BLUEPRINT

    def test_blueprint_template_mentions_optional_sections(self):
        """Test that blueprint template mentions quality guidelines."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_BLUEPRINT
        # The new prompt focuses on quality guidelines rather than optional sections
        assert "QUALITY GUIDELINES" in USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "specific and informative" in USER_PROMPT_TEMPLATE_BLUEPRINT

    def test_all_templates_mention_json(self):
        """Test that all templates mention JSON output."""
        from hunknote.llm.base import (
            USER_PROMPT_TEMPLATE_DEFAULT,
            USER_PROMPT_TEMPLATE_BLUEPRINT,
            USER_PROMPT_TEMPLATE_CONVENTIONAL,
            USER_PROMPT_TEMPLATE_TICKET,
            USER_PROMPT_TEMPLATE_KERNEL,
        )
        for template in [USER_PROMPT_TEMPLATE_DEFAULT, USER_PROMPT_TEMPLATE_BLUEPRINT,
                         USER_PROMPT_TEMPLATE_CONVENTIONAL, USER_PROMPT_TEMPLATE_TICKET,
                         USER_PROMPT_TEMPLATE_KERNEL]:
            assert "JSON" in template

    def test_all_templates_mention_file_changes(self):
        """Test that non-blueprint templates mention FILE_CHANGES section."""
        from hunknote.llm.base import (
            USER_PROMPT_TEMPLATE_DEFAULT,
            USER_PROMPT_TEMPLATE_CONVENTIONAL,
            USER_PROMPT_TEMPLATE_TICKET,
            USER_PROMPT_TEMPLATE_KERNEL,
        )
        # Blueprint uses a different format focused on quality guidelines
        for template in [USER_PROMPT_TEMPLATE_DEFAULT,
                         USER_PROMPT_TEMPLATE_CONVENTIONAL, USER_PROMPT_TEMPLATE_TICKET,
                         USER_PROMPT_TEMPLATE_KERNEL]:
            assert "FILE_CHANGES" in template

    def test_all_templates_can_be_formatted(self):
        """Test that all templates can be formatted with context_bundle."""
        from hunknote.llm.base import (
            USER_PROMPT_TEMPLATE_DEFAULT,
            USER_PROMPT_TEMPLATE_BLUEPRINT,
            USER_PROMPT_TEMPLATE_CONVENTIONAL,
            USER_PROMPT_TEMPLATE_TICKET,
            USER_PROMPT_TEMPLATE_KERNEL,
        )
        test_context = "test git context here"
        for template in [USER_PROMPT_TEMPLATE_DEFAULT, USER_PROMPT_TEMPLATE_BLUEPRINT,
                         USER_PROMPT_TEMPLATE_CONVENTIONAL, USER_PROMPT_TEMPLATE_TICKET,
                         USER_PROMPT_TEMPLATE_KERNEL]:
            formatted = template.format(context_bundle=test_context)
            assert test_context in formatted


class TestBaseLLMProviderPromptMethods:
    """Tests for BaseLLMProvider prompt building methods."""

    def test_build_user_prompt_for_style_default(self):
        """Test build_user_prompt_for_style with default style."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_DEFAULT

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt_for_style("test context", "default")
        expected = USER_PROMPT_TEMPLATE_DEFAULT.format(context_bundle="test context")
        assert result == expected

    def test_build_user_prompt_for_style_conventional(self):
        """Test build_user_prompt_for_style with conventional style."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_CONVENTIONAL

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt_for_style("test context", "conventional")
        expected = USER_PROMPT_TEMPLATE_CONVENTIONAL.format(context_bundle="test context")
        assert result == expected

    def test_build_user_prompt_for_style_ticket(self):
        """Test build_user_prompt_for_style with ticket style."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_TICKET

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt_for_style("test context", "ticket")
        expected = USER_PROMPT_TEMPLATE_TICKET.format(context_bundle="test context")
        assert result == expected

    def test_build_user_prompt_for_style_kernel(self):
        """Test build_user_prompt_for_style with kernel style."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_KERNEL

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt_for_style("test context", "kernel")
        expected = USER_PROMPT_TEMPLATE_KERNEL.format(context_bundle="test context")
        assert result == expected

    def test_build_user_prompt_for_style_blueprint(self):
        """Test build_user_prompt_for_style with blueprint style."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_BLUEPRINT

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt_for_style("test context", "blueprint")
        expected = USER_PROMPT_TEMPLATE_BLUEPRINT.format(context_bundle="test context")
        assert result == expected

    def test_build_user_prompt_for_style_case_insensitive(self):
        """Test that style name is case insensitive."""
        from hunknote.llm.base import BaseLLMProvider

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result1 = provider.build_user_prompt_for_style("ctx", "CONVENTIONAL")
        result2 = provider.build_user_prompt_for_style("ctx", "Conventional")
        result3 = provider.build_user_prompt_for_style("ctx", "conventional")
        assert result1 == result2 == result3

    def test_build_user_prompt_for_style_none_defaults_to_default(self):
        """Test that None style defaults to default template."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_DEFAULT

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt_for_style("test", None)
        expected = USER_PROMPT_TEMPLATE_DEFAULT.format(context_bundle="test")
        assert result == expected

    def test_build_user_prompt_for_style_unknown_defaults_to_default(self):
        """Test that unknown style defaults to default template."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_DEFAULT

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt_for_style("test", "unknown_style")
        expected = USER_PROMPT_TEMPLATE_DEFAULT.format(context_bundle="test")
        assert result == expected

