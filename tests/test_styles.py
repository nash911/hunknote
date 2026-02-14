"""Tests for hunknote.styles module."""

import pytest

from hunknote.styles import (
    StyleProfile,
    StyleConfig,
    ExtendedCommitJSON,
    PROFILE_DESCRIPTIONS,
    CONVENTIONAL_TYPES,
    load_style_config_from_dict,
    style_config_to_dict,
    render_default,
    render_conventional,
    render_ticket,
    render_kernel,
    render_commit_message_styled,
    sanitize_subject,
    wrap_text,
    extract_ticket_from_branch,
    infer_commit_type,
)


class TestStyleProfile:
    """Tests for StyleProfile enum."""

    def test_has_default(self):
        """Test that default profile exists."""
        assert StyleProfile.DEFAULT.value == "default"

    def test_has_conventional(self):
        """Test that conventional profile exists."""
        assert StyleProfile.CONVENTIONAL.value == "conventional"

    def test_has_ticket(self):
        """Test that ticket profile exists."""
        assert StyleProfile.TICKET.value == "ticket"

    def test_has_kernel(self):
        """Test that kernel profile exists."""
        assert StyleProfile.KERNEL.value == "kernel"

    def test_profile_from_string(self):
        """Test creating profile from string."""
        assert StyleProfile("default") == StyleProfile.DEFAULT
        assert StyleProfile("conventional") == StyleProfile.CONVENTIONAL


class TestStyleConfig:
    """Tests for StyleConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = StyleConfig()
        assert config.profile == StyleProfile.DEFAULT
        assert config.include_body is True
        assert config.max_bullets == 6
        assert config.wrap_width == 72

    def test_custom_values(self):
        """Test custom configuration values."""
        config = StyleConfig(
            profile=StyleProfile.CONVENTIONAL,
            max_bullets=5,
            wrap_width=80,
        )
        assert config.profile == StyleProfile.CONVENTIONAL
        assert config.max_bullets == 5
        assert config.wrap_width == 80


class TestExtendedCommitJSON:
    """Tests for ExtendedCommitJSON model."""

    def test_legacy_schema(self):
        """Test backward compatible legacy schema."""
        data = ExtendedCommitJSON(
            title="Add feature",
            body_bullets=["First change", "Second change"],
        )
        assert data.get_subject() == "Add feature"
        assert len(data.get_bullets()) == 2

    def test_extended_schema(self):
        """Test new extended schema."""
        data = ExtendedCommitJSON(
            type="feat",
            scope="api",
            subject="Add authentication endpoint",
            body_bullets=["Implement login", "Add session management"],
            breaking_change=False,
            ticket="PROJ-6767",
        )
        assert data.get_type() == "feat"
        assert data.get_scope() == "api"
        assert data.get_subject() == "Add authentication endpoint"
        assert data.ticket == "PROJ-6767"

    def test_subject_fallback_to_title(self):
        """Test that subject falls back to title."""
        data = ExtendedCommitJSON(
            title="Legacy title",
            body_bullets=["Change"],
        )
        assert data.get_subject() == "Legacy title"

    def test_subject_preferred_over_title(self):
        """Test that subject is preferred over title."""
        data = ExtendedCommitJSON(
            title="Legacy title",
            subject="New subject",
            body_bullets=["Change"],
        )
        assert data.get_subject() == "New subject"

    def test_type_default(self):
        """Test default type fallback."""
        data = ExtendedCommitJSON(title="Test", body_bullets=["Change"])
        assert data.get_type() == "feat"
        assert data.get_type("fix") == "fix"

    def test_bullets_max_limit(self):
        """Test bullet limiting."""
        data = ExtendedCommitJSON(
            title="Test",
            body_bullets=["One", "Two", "Three", "Four", "Five"],
        )
        assert len(data.get_bullets(3)) == 3
        assert len(data.get_bullets()) == 5


class TestSanitizeSubject:
    """Tests for sanitize_subject function."""

    def test_normal_subject(self):
        """Test normal subject unchanged."""
        result = sanitize_subject("Add feature")
        assert result == "Add feature"

    def test_strips_whitespace(self):
        """Test whitespace stripping."""
        result = sanitize_subject("  Add feature  ")
        assert result == "Add feature"

    def test_truncates_long_subject(self):
        """Test truncation of long subjects."""
        long_subject = "A" * 100
        result = sanitize_subject(long_subject, max_length=72)
        assert len(result) == 72
        assert result.endswith("...")

    def test_multiline_takes_first_line(self):
        """Test that only first line is used."""
        result = sanitize_subject("First line\nSecond line")
        assert result == "First line"


class TestWrapText:
    """Tests for wrap_text function."""

    def test_short_text_unchanged(self):
        """Test short text is unchanged."""
        result = wrap_text("Short text", width=72)
        assert result == "Short text"

    def test_wraps_long_text(self):
        """Test wrapping of long text."""
        long_text = "This is a very long line that should be wrapped to fit within the specified width"
        result = wrap_text(long_text, width=40)
        assert "\n" in result
        for line in result.split("\n"):
            assert len(line) <= 40

    def test_with_indent(self):
        """Test wrapping with indent."""
        result = wrap_text("Text", initial_indent="- ", subsequent_indent="  ")
        assert result.startswith("- ")


class TestRenderDefault:
    """Tests for render_default function."""

    def test_basic_render(self):
        """Test basic default rendering."""
        data = ExtendedCommitJSON(
            title="Add feature",
            body_bullets=["First change", "Second change"],
        )
        config = StyleConfig()
        result = render_default(data, config)

        assert "Add feature" in result
        assert "- First change" in result
        assert "- Second change" in result

    def test_no_body_when_disabled(self):
        """Test body omitted when include_body is false."""
        data = ExtendedCommitJSON(
            title="Add feature",
            body_bullets=["First change"],
        )
        config = StyleConfig(include_body=False)
        result = render_default(data, config)

        assert result == "Add feature"
        assert "First change" not in result


class TestRenderConventional:
    """Tests for render_conventional function."""

    def test_basic_conventional(self):
        """Test basic conventional commits rendering."""
        data = ExtendedCommitJSON(
            type="feat",
            subject="Add authentication",
            body_bullets=["Implement login"],
        )
        config = StyleConfig()
        result = render_conventional(data, config)

        assert result.startswith("feat: ")
        assert "Add authentication" in result

    def test_with_scope(self):
        """Test conventional with scope."""
        data = ExtendedCommitJSON(
            type="fix",
            scope="api",
            subject="Fix null pointer",
            body_bullets=["Add null check"],
        )
        config = StyleConfig()
        result = render_conventional(data, config)

        assert result.startswith("fix(api): ")

    def test_override_scope(self):
        """Test scope override."""
        data = ExtendedCommitJSON(
            type="feat",
            scope="api",
            subject="Add feature",
            body_bullets=["Change"],
        )
        config = StyleConfig()
        result = render_conventional(data, config, override_scope="ui")

        assert "feat(ui):" in result

    def test_no_scope_flag(self):
        """Test no_scope flag disables scope."""
        data = ExtendedCommitJSON(
            type="feat",
            scope="api",
            subject="Add feature",
            body_bullets=["Change"],
        )
        config = StyleConfig()
        result = render_conventional(data, config, no_scope=True)

        assert "feat: " in result
        assert "(api)" not in result

    def test_breaking_change_footer(self):
        """Test breaking change footer."""
        data = ExtendedCommitJSON(
            type="feat",
            subject="Breaking feature",
            body_bullets=["Major change"],
            breaking_change=True,
        )
        config = StyleConfig(breaking_footer=True)
        result = render_conventional(data, config)

        assert "BREAKING CHANGE:" in result

    def test_ticket_in_footer(self):
        """Test ticket added to footer."""
        data = ExtendedCommitJSON(
            type="fix",
            subject="Fix bug",
            body_bullets=["Fix it"],
            ticket="PROJ-6767",
        )
        config = StyleConfig()
        result = render_conventional(data, config)

        assert "Refs: PROJ-6767" in result


class TestRenderTicket:
    """Tests for render_ticket function."""

    def test_prefix_ticket(self):
        """Test ticket prefix placement."""
        data = ExtendedCommitJSON(
            subject="Fix bug",
            body_bullets=["Fix the issue"],
            ticket="PROJ-6767",
        )
        config = StyleConfig(ticket_placement="prefix")
        result = render_ticket(data, config)

        assert result.startswith("PROJ-6767 ")

    def test_prefix_ticket_with_scope(self):
        """Test ticket prefix with scope."""
        data = ExtendedCommitJSON(
            subject="Fix bug",
            scope="api",
            body_bullets=["Fix the issue"],
            ticket="PROJ-6767",
        )
        config = StyleConfig(ticket_placement="prefix")
        result = render_ticket(data, config)

        assert "PROJ-6767 (api)" in result

    def test_suffix_ticket(self):
        """Test ticket suffix placement."""
        data = ExtendedCommitJSON(
            subject="Fix bug",
            body_bullets=["Fix the issue"],
            ticket="PROJ-6767",
        )
        config = StyleConfig(ticket_placement="suffix")
        result = render_ticket(data, config)

        assert "(PROJ-6767)" in result
        assert result.endswith("(PROJ-6767)") or "(PROJ-6767)\n" in result

    def test_override_ticket(self):
        """Test ticket override."""
        data = ExtendedCommitJSON(
            subject="Fix bug",
            body_bullets=["Fix it"],
            ticket="OLD-111",
        )
        config = StyleConfig()
        result = render_ticket(data, config, override_ticket="NEW-222")

        assert "NEW-222" in result
        assert "OLD-111" not in result


class TestRenderKernel:
    """Tests for render_kernel function."""

    def test_with_scope_subsystem(self):
        """Test kernel style with scope as subsystem."""
        data = ExtendedCommitJSON(
            scope="auth",
            subject="Add login support",
            body_bullets=["Implement login"],
        )
        config = StyleConfig(subsystem_from_scope=True)
        result = render_kernel(data, config)

        assert result.startswith("auth: ")

    def test_without_scope(self):
        """Test kernel style without scope."""
        data = ExtendedCommitJSON(
            subject="Add feature",
            body_bullets=["Change"],
        )
        config = StyleConfig()
        result = render_kernel(data, config)

        assert ": " not in result.split("\n")[0] or result.startswith("Add feature")

    def test_override_scope(self):
        """Test scope override."""
        data = ExtendedCommitJSON(
            scope="old",
            subject="Add feature",
            body_bullets=["Change"],
        )
        config = StyleConfig()
        result = render_kernel(data, config, override_scope="new")

        assert result.startswith("new: ")


class TestRenderCommitMessageStyled:
    """Tests for render_commit_message_styled function."""

    def test_default_profile(self):
        """Test rendering with default profile."""
        data = ExtendedCommitJSON(
            title="Add feature",
            body_bullets=["Change one", "Change two"],
        )
        config = StyleConfig(profile=StyleProfile.DEFAULT)
        result = render_commit_message_styled(data, config)

        assert "Add feature" in result
        assert "- Change one" in result

    def test_conventional_profile(self):
        """Test rendering with conventional profile."""
        data = ExtendedCommitJSON(
            type="feat",
            subject="Add feature",
            body_bullets=["Change"],
        )
        config = StyleConfig(profile=StyleProfile.CONVENTIONAL)
        result = render_commit_message_styled(data, config)

        assert "feat:" in result

    def test_override_style(self):
        """Test style override."""
        data = ExtendedCommitJSON(
            type="fix",
            subject="Fix bug",
            body_bullets=["Fix it"],
        )
        config = StyleConfig(profile=StyleProfile.DEFAULT)
        result = render_commit_message_styled(
            data, config, override_style=StyleProfile.CONVENTIONAL
        )

        assert "fix:" in result


class TestExtractTicketFromBranch:
    """Tests for extract_ticket_from_branch function."""

    def test_extracts_jira_style_ticket(self):
        """Test extraction of JIRA-style ticket."""
        branch = "feature/PROJ-6767-add-login"
        ticket = extract_ticket_from_branch(branch)
        assert ticket == "PROJ-6767"

    def test_extracts_ticket_at_start(self):
        """Test extraction when ticket is at start."""
        branch = "PROJ-456/feature-name"
        ticket = extract_ticket_from_branch(branch)
        assert ticket == "PROJ-456"

    def test_no_ticket_returns_none(self):
        """Test returns None when no ticket found."""
        branch = "feature/add-login"
        ticket = extract_ticket_from_branch(branch)
        assert ticket is None

    def test_custom_pattern(self):
        """Test with custom pattern."""
        branch = "feature/CUSTOM123-add-login"
        ticket = extract_ticket_from_branch(branch, r"(CUSTOM\d+)")
        assert ticket == "CUSTOM123"


class TestInferCommitType:
    """Tests for infer_commit_type function."""

    def test_docs_only_changes(self):
        """Test inference for docs-only changes."""
        files = ["README.md", "docs/guide.md"]
        assert infer_commit_type(files) == "docs"

    def test_test_only_changes(self):
        """Test inference for test-only changes."""
        files = ["tests/test_feature.py", "tests/test_utils.py"]
        assert infer_commit_type(files) == "test"

    def test_build_changes(self):
        """Test inference for build changes."""
        files = ["pyproject.toml", "poetry.lock"]
        assert infer_commit_type(files) == "build"

    def test_ci_changes(self):
        """Test inference for CI changes."""
        files = [".github/workflows/ci.yml"]
        assert infer_commit_type(files) == "ci"

    def test_mixed_changes_returns_none(self):
        """Test returns None for mixed changes."""
        files = ["src/main.py", "README.md"]
        assert infer_commit_type(files) is None

    def test_empty_list_returns_none(self):
        """Test returns None for empty list."""
        assert infer_commit_type([]) is None


class TestLoadStyleConfigFromDict:
    """Tests for load_style_config_from_dict function."""

    def test_empty_dict_returns_defaults(self):
        """Test empty dict returns defaults."""
        config = load_style_config_from_dict({})
        assert config.profile == StyleProfile.DEFAULT
        assert config.include_body is True

    def test_loads_profile(self):
        """Test loading profile from dict."""
        config = load_style_config_from_dict({
            "style": {"profile": "conventional"}
        })
        assert config.profile == StyleProfile.CONVENTIONAL

    def test_loads_all_options(self):
        """Test loading all options."""
        config = load_style_config_from_dict({
            "style": {
                "profile": "ticket",
                "include_body": False,
                "max_bullets": 4,
                "wrap_width": 80,
                "ticket": {
                    "placement": "suffix",
                },
            }
        })
        assert config.profile == StyleProfile.TICKET
        assert config.include_body is False
        assert config.max_bullets == 4
        assert config.wrap_width == 80
        assert config.ticket_placement == "suffix"


class TestStyleConfigToDict:
    """Tests for style_config_to_dict function."""

    def test_converts_to_dict(self):
        """Test conversion to dict."""
        config = StyleConfig(
            profile=StyleProfile.CONVENTIONAL,
            max_bullets=5,
        )
        result = style_config_to_dict(config)

        assert result["style"]["profile"] == "conventional"
        assert result["style"]["max_bullets"] == 5


class TestProfileDescriptions:
    """Tests for PROFILE_DESCRIPTIONS constant."""

    def test_has_all_profiles(self):
        """Test descriptions exist for all profiles."""
        for profile in StyleProfile:
            assert profile in PROFILE_DESCRIPTIONS

    def test_descriptions_have_required_fields(self):
        """Test descriptions have required fields."""
        for profile, desc in PROFILE_DESCRIPTIONS.items():
            assert "name" in desc
            assert "description" in desc
            assert "format" in desc
            assert "example" in desc


class TestConventionalTypes:
    """Tests for CONVENTIONAL_TYPES constant."""

    def test_contains_common_types(self):
        """Test contains common conventional commit types."""
        assert "feat" in CONVENTIONAL_TYPES
        assert "fix" in CONVENTIONAL_TYPES
        assert "docs" in CONVENTIONAL_TYPES
        assert "refactor" in CONVENTIONAL_TYPES
        assert "test" in CONVENTIONAL_TYPES
        assert "chore" in CONVENTIONAL_TYPES

