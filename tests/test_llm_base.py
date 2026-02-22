"""Tests for hunknote.llm.base module."""

import os

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


class TestSystemPromptContent:
    """Tests for SYSTEM_PROMPT content."""

    def test_system_prompt_contains_intent_handling(self):
        """Test that system prompt includes intent handling rules."""
        assert "INTENT HANDLING" in SYSTEM_PROMPT
        assert "[INTENT]" in SYSTEM_PROMPT

    def test_system_prompt_intent_guides_framing(self):
        """Test that intent handling mentions guiding framing."""
        assert "framing" in SYSTEM_PROMPT.lower()

    def test_system_prompt_intent_prefers_diff(self):
        """Test that intent handling says to prefer diff over contradicting intent."""
        assert "prefer the diff" in SYSTEM_PROMPT.lower()


class TestUserPromptIntentHandling:
    """Tests for intent handling in prompts."""

    def test_system_prompt_has_intent_section(self):
        """Test that SYSTEM_PROMPT has intent handling section."""
        assert "INTENT HANDLING" in SYSTEM_PROMPT
        assert "[INTENT]" in SYSTEM_PROMPT

    def test_system_prompt_intent_guides_why(self):
        """Test that intent handling describes guiding WHY/motivation."""
        assert "WHY" in SYSTEM_PROMPT or "motivation" in SYSTEM_PROMPT

    def test_system_prompt_intent_not_fabricate(self):
        """Test that intent handling says not to fabricate details."""
        assert "fabricate" in SYSTEM_PROMPT.lower() or "invent" in SYSTEM_PROMPT.lower()

    def test_system_prompt_intent_prefers_diff_on_conflict(self):
        """Test that if intent contradicts diff, prefer diff."""
        assert "prefer the diff" in SYSTEM_PROMPT.lower()


class TestMergeStateInPrompts:
    """Tests for merge state handling in prompts."""

    def test_conventional_prompt_includes_merge_type(self):
        """Test that conventional prompt includes merge as valid type."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL
        # merge should be in the type list
        assert "merge" in USER_PROMPT_TEMPLATE_CONVENTIONAL

    def test_conventional_prompt_merge_state_check(self):
        """Test that conventional prompt has merge state check section."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "MERGE_STATE" in USER_PROMPT_TEMPLATE_CONVENTIONAL

    def test_conventional_prompt_merge_in_progress(self):
        """Test that conventional prompt checks for merge in progress."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "merge in progress" in USER_PROMPT_TEMPLATE_CONVENTIONAL.lower()

    def test_blueprint_prompt_includes_merge_type(self):
        """Test that blueprint prompt includes merge as valid type."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "merge" in USER_PROMPT_TEMPLATE_BLUEPRINT.lower()

    def test_blueprint_prompt_merge_state_check(self):
        """Test that blueprint prompt has merge state check section."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_BLUEPRINT
        assert "MERGE_STATE" in USER_PROMPT_TEMPLATE_BLUEPRINT

    def test_prompts_mention_merging_branch(self):
        """Test that prompts mention extracting branch name from merge state."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "Merging branch" in USER_PROMPT_TEMPLATE_CONVENTIONAL


# ============================================================================
# Additional Test Cases for Complete Coverage
# ============================================================================


class TestRawLLMResult:
    """Tests for RawLLMResult dataclass."""

    def test_create_raw_result(self):
        """Test creating RawLLMResult."""
        from hunknote.llm.base import RawLLMResult

        result = RawLLMResult(
            raw_response='{"key": "value"}',
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
        )

        assert result.raw_response == '{"key": "value"}'
        assert result.model == "gpt-4"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    def test_raw_result_with_long_response(self):
        """Test RawLLMResult with long response."""
        from hunknote.llm.base import RawLLMResult

        long_response = "x" * 10000
        result = RawLLMResult(
            raw_response=long_response,
            model="claude-3",
            input_tokens=5000,
            output_tokens=2000,
        )

        assert len(result.raw_response) == 10000
        assert result.model == "claude-3"

    def test_raw_result_with_empty_response(self):
        """Test RawLLMResult with empty response."""
        from hunknote.llm.base import RawLLMResult

        result = RawLLMResult(
            raw_response="",
            model="gpt-4",
            input_tokens=100,
            output_tokens=0,
        )

        assert result.raw_response == ""
        assert result.output_tokens == 0


class TestNormalizeCommitJson:
    """Tests for _normalize_commit_json function edge cases."""

    def test_normalize_title_only(self):
        """Test normalization when only title is provided."""
        from hunknote.llm.base import _normalize_commit_json

        parsed = {
            "title": "Add feature",
            "body_bullets": ["Change 1"],
        }
        result = _normalize_commit_json(parsed)

        assert result["title"] == "Add feature"
        assert result["subject"] == "Add feature"

    def test_normalize_subject_only(self):
        """Test normalization when only subject is provided."""
        from hunknote.llm.base import _normalize_commit_json

        parsed = {
            "subject": "Fix bug",
            "body_bullets": ["Fix issue"],
        }
        result = _normalize_commit_json(parsed)

        assert result["subject"] == "Fix bug"
        assert result["title"] == "Fix bug"

    def test_normalize_both_title_and_subject(self):
        """Test normalization when both title and subject are provided."""
        from hunknote.llm.base import _normalize_commit_json

        parsed = {
            "title": "Title text",
            "subject": "Subject text",
            "body_bullets": ["Change"],
        }
        result = _normalize_commit_json(parsed)

        # Both should be preserved as-is
        assert result["title"] == "Title text"
        assert result["subject"] == "Subject text"

    def test_normalize_subsystem_to_scope(self):
        """Test that subsystem is converted to scope."""
        from hunknote.llm.base import _normalize_commit_json

        parsed = {
            "subsystem": "net",
            "subject": "fix packet handling",
            "body_bullets": ["Fix bug"],
        }
        result = _normalize_commit_json(parsed)

        assert "scope" in result
        assert result["scope"] == "net"
        assert "subsystem" not in result

    def test_normalize_subsystem_does_not_override_scope(self):
        """Test that subsystem does not override existing scope."""
        from hunknote.llm.base import _normalize_commit_json

        parsed = {
            "subsystem": "net",
            "scope": "api",
            "subject": "fix endpoint",
            "body_bullets": ["Fix"],
        }
        result = _normalize_commit_json(parsed)

        # scope should remain unchanged, subsystem should still be there
        assert result["scope"] == "api"
        # subsystem stays in parsed dict since scope already exists
        assert "subsystem" in result

    def test_normalize_empty_sections_list(self):
        """Test normalization with empty sections list."""
        from hunknote.llm.base import _normalize_commit_json

        parsed = {
            "type": "feat",
            "title": "Add feature",
            "sections": [],
        }
        result = _normalize_commit_json(parsed)

        assert result["sections"] == []
        assert result["body_bullets"] == []

    def test_normalize_preserves_extra_fields(self):
        """Test that extra fields are preserved."""
        from hunknote.llm.base import _normalize_commit_json

        parsed = {
            "title": "Test",
            "body_bullets": ["Change"],
            "extra_field": "extra_value",
            "custom": {"nested": True},
        }
        result = _normalize_commit_json(parsed)

        assert result["extra_field"] == "extra_value"
        assert result["custom"]["nested"] is True


class TestBaseLLMProviderMethods:
    """Tests for BaseLLMProvider methods."""

    def test_build_user_prompt(self):
        """Test build_user_prompt method."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_DEFAULT

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt("test context")
        expected = USER_PROMPT_TEMPLATE_DEFAULT.format(context_bundle="test context")

        assert result == expected

    def test_build_user_prompt_styled(self):
        """Test build_user_prompt_styled method (uses conventional)."""
        from hunknote.llm.base import BaseLLMProvider, USER_PROMPT_TEMPLATE_CONVENTIONAL

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()
        result = provider.build_user_prompt_styled("test context")
        expected = USER_PROMPT_TEMPLATE_CONVENTIONAL.format(context_bundle="test context")

        assert result == expected

    def test_generate_raw_raises_not_implemented(self):
        """Test that generate_raw raises NotImplementedError by default."""
        from hunknote.llm.base import BaseLLMProvider

        class TestProvider(BaseLLMProvider):
            def generate(self, context_bundle): pass
            def get_api_key(self): pass

        provider = TestProvider()

        with pytest.raises(NotImplementedError) as exc_info:
            provider.generate_raw("system", "user")

        assert "does not support generate_raw" in str(exc_info.value)
        assert "TestProvider" in str(exc_info.value)


class TestParseJsonResponseEdgeCases:
    """Additional edge case tests for parse_json_response."""

    def test_handles_json_with_trailing_newlines(self):
        """Test handling JSON with trailing newlines."""
        response = '{"title": "Test", "body_bullets": ["Change"]}\n\n\n'
        result = parse_json_response(response)

        assert result["title"] == "Test"

    def test_handles_json_with_leading_newlines(self):
        """Test handling JSON with leading newlines."""
        response = '\n\n\n{"title": "Test", "body_bullets": ["Change"]}'
        result = parse_json_response(response)

        assert result["title"] == "Test"

    def test_handles_json_with_unicode(self):
        """Test handling JSON with unicode characters."""
        response = '{"title": "Add émojis 🎉", "body_bullets": ["Support für Unicode"]}'
        result = parse_json_response(response)

        assert result["title"] == "Add émojis 🎉"
        assert "für" in result["body_bullets"][0]

    def test_extracts_first_json_object(self):
        """Test that JSON is extracted from surrounding text but multiple objects fail."""
        # With multiple JSON objects, the parser extracts from first { to last }
        # which creates invalid JSON (two objects concatenated)
        response = '''Some text before
{"title": "First", "body_bullets": ["One"]}
Some text between
{"title": "Second", "body_bullets": ["Two"]}
Some text after'''

        # This should fail because it extracts content between first { and last }
        # which results in two JSON objects concatenated
        with pytest.raises(JSONParseError):
            parse_json_response(response)

    def test_extracts_single_json_from_text(self):
        """Test that single JSON object is extracted from surrounding text."""
        response = '''Here is my response:
{"title": "Test", "body_bullets": ["Change"]}
Hope this helps!'''
        result = parse_json_response(response)

        assert result["title"] == "Test"

    def test_handles_json_with_special_characters_in_strings(self):
        """Test handling JSON with special characters in strings."""
        response = '{"title": "Fix \\"quoted\\" text", "body_bullets": ["Handle\\nNewlines"]}'
        result = parse_json_response(response)

        assert 'quoted' in result["title"]

    def test_handles_json_arrays_in_objects(self):
        """Test handling complex nested structures."""
        response = '''{"title": "Test", "body_bullets": ["Change"], "sections": [{"title": "Changes", "bullets": ["Item 1", "Item 2"]}]}'''
        result = parse_json_response(response)

        assert result["title"] == "Test"
        assert len(result["sections"]) == 1
        assert result["sections"][0]["title"] == "Changes"


class TestGenerateCommitJson:
    """Tests for generate_commit_json function."""

    def test_generate_commit_json_calls_provider(self, mocker):
        """Test that generate_commit_json uses the correct provider."""
        from hunknote.llm import generate_commit_json
        from hunknote.styles import ExtendedCommitJSON

        mock_result = LLMResult(
            commit_json=ExtendedCommitJSON(title="Test", body_bullets=["Change"]),
            model="test-model",
            input_tokens=100,
            output_tokens=50,
        )

        mock_provider = mocker.MagicMock()
        mock_provider.generate.return_value = mock_result

        mocker.patch("hunknote.llm.get_provider", return_value=mock_provider)

        result = generate_commit_json("test context")

        assert result.commit_json.title == "Test"
        mock_provider.generate.assert_called_once_with("test context")

    def test_generate_commit_json_with_style(self, mocker):
        """Test that generate_commit_json passes style to get_provider."""
        from hunknote.llm import generate_commit_json
        from hunknote.styles import ExtendedCommitJSON

        mock_result = LLMResult(
            commit_json=ExtendedCommitJSON(title="Test", body_bullets=["Change"]),
            model="test-model",
            input_tokens=100,
            output_tokens=50,
        )

        mock_provider = mocker.MagicMock()
        mock_provider.generate.return_value = mock_result

        mock_get_provider = mocker.patch("hunknote.llm.get_provider", return_value=mock_provider)

        generate_commit_json("test context", style="blueprint")

        mock_get_provider.assert_called_once_with(style="blueprint")


class TestProviderStyleAttribute:
    """Tests for style attribute on all providers."""

    def test_anthropic_provider_style(self):
        """Test Anthropic provider stores style."""
        from hunknote.llm.anthropic_provider import AnthropicProvider

        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            provider = AnthropicProvider(style=style)
            assert provider.style == style

    def test_openai_provider_style(self):
        """Test OpenAI provider stores style."""
        from hunknote.llm.openai_provider import OpenAIProvider

        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            provider = OpenAIProvider(style=style)
            assert provider.style == style

    def test_google_provider_style(self):
        """Test Google provider stores style."""
        from hunknote.llm.google_provider import GoogleProvider

        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            provider = GoogleProvider(style=style)
            assert provider.style == style

    def test_mistral_provider_style(self):
        """Test Mistral provider stores style."""
        from hunknote.llm.mistral_provider import MistralProvider

        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            provider = MistralProvider(style=style)
            assert provider.style == style

    def test_cohere_provider_style(self):
        """Test Cohere provider stores style."""
        from hunknote.llm.cohere_provider import CohereProvider

        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            provider = CohereProvider(style=style)
            assert provider.style == style

    def test_groq_provider_style(self):
        """Test Groq provider stores style."""
        from hunknote.llm.groq_provider import GroqProvider

        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            provider = GroqProvider(style=style)
            assert provider.style == style

    def test_openrouter_provider_style(self):
        """Test OpenRouter provider stores style."""
        from hunknote.llm.openrouter_provider import OpenRouterProvider

        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            provider = OpenRouterProvider(style=style)
            assert provider.style == style


class TestProviderCustomModel:
    """Tests for custom model on all providers."""

    def test_anthropic_provider_custom_model(self):
        """Test Anthropic provider with custom model."""
        from hunknote.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(model="claude-3-opus-20240229")
        assert provider.model == "claude-3-opus-20240229"

    def test_openai_provider_custom_model(self):
        """Test OpenAI provider with custom model."""
        from hunknote.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(model="gpt-4-turbo-preview")
        assert provider.model == "gpt-4-turbo-preview"

    def test_google_provider_custom_model(self):
        """Test Google provider with custom model."""
        from hunknote.llm.google_provider import GoogleProvider

        provider = GoogleProvider(model="gemini-1.5-pro")
        assert provider.model == "gemini-1.5-pro"

    def test_mistral_provider_custom_model(self):
        """Test Mistral provider with custom model."""
        from hunknote.llm.mistral_provider import MistralProvider

        provider = MistralProvider(model="mistral-large-latest")
        assert provider.model == "mistral-large-latest"

    def test_cohere_provider_custom_model(self):
        """Test Cohere provider with custom model."""
        from hunknote.llm.cohere_provider import CohereProvider

        provider = CohereProvider(model="command-r-plus")
        assert provider.model == "command-r-plus"

    def test_groq_provider_custom_model(self):
        """Test Groq provider with custom model."""
        from hunknote.llm.groq_provider import GroqProvider

        provider = GroqProvider(model="llama3-70b-8192")
        assert provider.model == "llama3-70b-8192"

    def test_openrouter_provider_custom_model(self):
        """Test OpenRouter provider with custom model."""
        from hunknote.llm.openrouter_provider import OpenRouterProvider

        provider = OpenRouterProvider(model="anthropic/claude-3-opus")
        assert provider.model == "anthropic/claude-3-opus"


class TestApiKeyFromCredentials:
    """Tests for API key retrieval from credentials file."""

    def test_anthropic_key_from_credentials(self):
        """Test Anthropic API key from credentials file."""
        from hunknote.llm.anthropic_provider import AnthropicProvider
        from unittest.mock import patch

        provider = AnthropicProvider()

        with patch.dict(os.environ, {}, clear=True):
            with patch("hunknote.global_config.get_credential", return_value="cred-key"):
                key = provider.get_api_key()
                assert key == "cred-key"

    def test_openai_key_from_credentials(self):
        """Test OpenAI API key from credentials file."""
        from hunknote.llm.openai_provider import OpenAIProvider
        from unittest.mock import patch

        provider = OpenAIProvider()

        with patch.dict(os.environ, {}, clear=True):
            with patch("hunknote.global_config.get_credential", return_value="openai-cred"):
                key = provider.get_api_key()
                assert key == "openai-cred"

    def test_google_key_from_credentials(self):
        """Test Google API key from credentials file."""
        from hunknote.llm.google_provider import GoogleProvider
        from unittest.mock import patch

        provider = GoogleProvider()

        with patch.dict(os.environ, {}, clear=True):
            with patch("hunknote.global_config.get_credential", return_value="google-cred"):
                key = provider.get_api_key()
                assert key == "google-cred"


class TestExceptionMessages:
    """Tests for exception message content."""

    def test_missing_api_key_error_includes_env_var(self):
        """Test that MissingAPIKeyError includes environment variable name."""
        error = MissingAPIKeyError("TEST_API_KEY not found. Set TEST_API_KEY.")
        assert "TEST_API_KEY" in str(error)

    def test_json_parse_error_includes_details(self):
        """Test that JSONParseError includes parsing details."""
        error = JSONParseError("Failed to parse: invalid syntax at line 5")
        assert "Failed to parse" in str(error)

    def test_llm_error_is_catchable(self):
        """Test that LLMError can be caught as base exception."""
        try:
            raise JSONParseError("test")
        except LLMError as e:
            assert "test" in str(e)


class TestTypeSelectionRulesInPrompts:
    """Tests for type selection rules in prompts."""

    def test_conventional_prompt_has_absolute_rules(self):
        """Test that conventional prompt has absolute type selection rules."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL

        assert "ABSOLUTE RULES" in USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert "FILE EXTENSION DETERMINES TYPE" in USER_PROMPT_TEMPLATE_CONVENTIONAL

    def test_blueprint_prompt_has_absolute_rules(self):
        """Test that blueprint prompt has absolute type selection rules."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_BLUEPRINT

        assert "ABSOLUTE RULES" in USER_PROMPT_TEMPLATE_BLUEPRINT

    def test_conventional_prompt_docs_rule(self):
        """Test conventional prompt has rule for docs type."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL

        assert ".md" in USER_PROMPT_TEMPLATE_CONVENTIONAL
        assert ".rst" in USER_PROMPT_TEMPLATE_CONVENTIONAL

    def test_conventional_prompt_test_rule(self):
        """Test conventional prompt has rule for test type."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL

        assert "test files" in USER_PROMPT_TEMPLATE_CONVENTIONAL.lower()

    def test_conventional_prompt_ci_rule(self):
        """Test conventional prompt has rule for CI type."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL

        assert "CI files" in USER_PROMPT_TEMPLATE_CONVENTIONAL or "ci" in USER_PROMPT_TEMPLATE_CONVENTIONAL.lower()


class TestScopeRulesInPrompts:
    """Tests for scope rules in prompts."""

    def test_conventional_prompt_avoid_redundant_scope(self):
        """Test conventional prompt mentions avoiding redundant scope."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_CONVENTIONAL

        assert "REDUNDANT SCOPE" in USER_PROMPT_TEMPLATE_CONVENTIONAL

    def test_blueprint_prompt_avoid_redundant_scope(self):
        """Test blueprint prompt mentions avoiding redundant scope."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_BLUEPRINT

        assert "REDUNDANT SCOPE" in USER_PROMPT_TEMPLATE_BLUEPRINT

    def test_ticket_prompt_avoid_redundant_scope(self):
        """Test ticket prompt mentions avoiding redundant scope."""
        from hunknote.llm.base import USER_PROMPT_TEMPLATE_TICKET

        assert "REDUNDANT SCOPE" in USER_PROMPT_TEMPLATE_TICKET

