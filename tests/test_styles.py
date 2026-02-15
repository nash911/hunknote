"""Tests for hunknote.styles module."""

import pytest

from hunknote.styles import (
    StyleProfile,
    StyleConfig,
    ExtendedCommitJSON,
    BlueprintSection,
    PROFILE_DESCRIPTIONS,
    CONVENTIONAL_TYPES,
    BLUEPRINT_SECTION_TITLES,
    load_style_config_from_dict,
    style_config_to_dict,
    render_default,
    render_conventional,
    render_ticket,
    render_kernel,
    render_blueprint,
    render_commit_message_styled,
    sanitize_subject,
    strip_type_prefix,
    wrap_text,
    extract_ticket_from_branch,
    infer_commit_type,
)


class TestStyleProfile:
    """Tests for StyleProfile enum."""

    def test_has_default(self):
        """Test that default profile exists."""
        assert StyleProfile.DEFAULT.value == "default"

    def test_has_blueprint(self):
        """Test that blueprint profile exists."""
        assert StyleProfile.BLUEPRINT.value == "blueprint"

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
        assert StyleProfile("blueprint") == StyleProfile.BLUEPRINT
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


class TestStripTypePrefix:
    """Tests for strip_type_prefix function."""

    def test_strips_feat_prefix(self):
        """Test stripping feat: prefix."""
        result = strip_type_prefix("feat: Add new feature")
        assert result == "Add new feature"

    def test_strips_fix_prefix(self):
        """Test stripping fix: prefix."""
        result = strip_type_prefix("fix: Fix the bug")
        assert result == "Fix the bug"

    def test_strips_prefix_with_scope(self):
        """Test stripping type(scope): prefix."""
        result = strip_type_prefix("feat(api): Add endpoint")
        assert result == "Add endpoint"

    def test_strips_prefix_case_insensitive(self):
        """Test stripping is case insensitive."""
        result = strip_type_prefix("FEAT: Add feature")
        assert result == "Add feature"

    def test_no_prefix_unchanged(self):
        """Test subject without prefix is unchanged."""
        result = strip_type_prefix("Add new feature")
        assert result == "Add new feature"

    def test_strips_all_conventional_types(self):
        """Test all conventional types are stripped."""
        types = ["feat", "fix", "docs", "refactor", "perf", "test", "build", "ci", "chore"]
        for t in types:
            result = strip_type_prefix(f"{t}: Some change")
            assert result == "Some change", f"Failed for type: {t}"

    def test_preserves_similar_words(self):
        """Test words starting with type names are preserved."""
        result = strip_type_prefix("Feature addition completed")
        assert result == "Feature addition completed"

    def test_handles_empty_string(self):
        """Test empty string handling."""
        result = strip_type_prefix("")
        assert result == ""

    def test_handles_whitespace(self):
        """Test whitespace handling."""
        result = strip_type_prefix("  feat: Add feature  ")
        assert result == "Add feature"

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


class TestBlueprintSectionTitles:
    """Tests for BLUEPRINT_SECTION_TITLES constant."""

    def test_contains_required_sections(self):
        """Test contains required section titles."""
        assert "Changes" in BLUEPRINT_SECTION_TITLES
        assert "Implementation" in BLUEPRINT_SECTION_TITLES
        assert "Testing" in BLUEPRINT_SECTION_TITLES
        assert "Documentation" in BLUEPRINT_SECTION_TITLES
        assert "Notes" in BLUEPRINT_SECTION_TITLES

    def test_contains_optional_sections(self):
        """Test contains optional section titles."""
        assert "Performance" in BLUEPRINT_SECTION_TITLES
        assert "Security" in BLUEPRINT_SECTION_TITLES
        assert "Config" in BLUEPRINT_SECTION_TITLES
        assert "API" in BLUEPRINT_SECTION_TITLES

    def test_section_order(self):
        """Test sections are in preferred order."""
        # Changes and Implementation should come before Testing
        assert BLUEPRINT_SECTION_TITLES.index("Changes") < BLUEPRINT_SECTION_TITLES.index("Testing")
        assert BLUEPRINT_SECTION_TITLES.index("Implementation") < BLUEPRINT_SECTION_TITLES.index("Testing")


class TestBlueprintSection:
    """Tests for BlueprintSection model."""

    def test_create_section(self):
        """Test creating a section."""
        section = BlueprintSection(
            title="Changes",
            bullets=["First change", "Second change"],
        )
        assert section.title == "Changes"
        assert len(section.bullets) == 2

    def test_empty_bullets(self):
        """Test section with no bullets."""
        section = BlueprintSection(title="Notes", bullets=[])
        assert section.bullets == []

    def test_none_bullets_becomes_list(self):
        """Test that None bullets becomes empty list."""
        section = BlueprintSection(title="Notes", bullets=None)
        assert section.bullets == []


class TestExtendedCommitJSONBlueprint:
    """Tests for ExtendedCommitJSON blueprint fields."""

    def test_summary_field(self):
        """Test summary field."""
        data = ExtendedCommitJSON(
            title="Add feature",
            summary="This is a summary paragraph.",
        )
        assert data.get_summary() == "This is a summary paragraph."

    def test_summary_none(self):
        """Test summary returns None when not set."""
        data = ExtendedCommitJSON(title="Add feature")
        assert data.get_summary() is None

    def test_sections_field(self):
        """Test sections field."""
        data = ExtendedCommitJSON(
            title="Add feature",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
                BlueprintSection(title="Implementation", bullets=["Impl 1"]),
            ],
        )
        sections = data.get_sections()
        assert len(sections) == 2
        assert sections[0].title == "Changes"
        assert sections[1].title == "Implementation"

    def test_get_sections_filtered_by_allowed(self):
        """Test get_sections filters by allowed titles."""
        data = ExtendedCommitJSON(
            title="Add feature",
            sections=[
                BlueprintSection(title="Testing", bullets=["Test 1"]),
                BlueprintSection(title="Changes", bullets=["Change 1"]),
                BlueprintSection(title="Implementation", bullets=["Impl 1"]),
            ],
        )
        # Should be ordered by allowed_titles, not input order
        sections = data.get_sections(["Changes", "Implementation", "Testing"])
        assert len(sections) == 3
        assert sections[0].title == "Changes"
        assert sections[1].title == "Implementation"
        assert sections[2].title == "Testing"

    def test_sections_from_dict(self):
        """Test sections can be created from dict."""
        data = ExtendedCommitJSON(
            title="Add feature",
            sections=[
                {"title": "Changes", "bullets": ["Change 1"]},
                {"title": "Testing", "bullets": ["Test 1"]},
            ],
        )
        sections = data.get_sections()
        assert len(sections) == 2
        assert isinstance(sections[0], BlueprintSection)


class TestRenderBlueprint:
    """Tests for render_blueprint function."""

    def test_basic_blueprint(self):
        """Test basic blueprint rendering."""
        data = ExtendedCommitJSON(
            title="Add user authentication",
            type="feat",
            scope="auth",
            summary="Implement secure authentication.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Add login endpoint"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)

        assert "feat(auth): Add user authentication" in result
        assert "Implement secure authentication." in result
        assert "Changes:" in result
        assert "- Add login endpoint" in result

    def test_blueprint_strips_double_type_prefix(self):
        """Test blueprint strips type prefix from title to avoid double prefix."""
        # This tests the bug fix for "feat: feat: Add feature"
        data = ExtendedCommitJSON(
            title="feat: Add user authentication",  # Title already has type prefix
            type="feat",
            scope="auth",
            summary="Implement secure authentication.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Add login endpoint"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)

        # Should have exactly one "feat" prefix, not "feat: feat:"
        assert "feat(auth): Add user authentication" in result
        assert "feat: feat:" not in result
        assert "feat(auth): feat:" not in result

    def test_blueprint_strips_type_with_scope_in_title(self):
        """Test blueprint strips type(scope): prefix from title."""
        data = ExtendedCommitJSON(
            title="feat(api): Add endpoint",  # Title has type(scope): prefix
            type="feat",
            scope="api",
            summary="Add new API endpoint.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Add endpoint"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)

        # Should strip the prefix and build a clean header
        assert "feat(api): Add endpoint" in result
        assert "feat(api): feat(api):" not in result

    def test_blueprint_without_scope(self):
        """Test blueprint without scope."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            summary="A feature summary.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)

        assert "feat: Add feature" in result
        assert "feat():" not in result

    def test_blueprint_no_scope_flag(self):
        """Test blueprint with no_scope flag."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            scope="api",
            summary="A feature summary.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config, no_scope=True)

        assert "feat: Add feature" in result
        assert "api" not in result

    def test_blueprint_override_scope(self):
        """Test blueprint with scope override."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            scope="api",
            summary="A feature summary.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config, override_scope="core")

        assert "feat(core):" in result
        assert "feat(api):" not in result

    def test_blueprint_multiple_sections(self):
        """Test blueprint with multiple sections."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            summary="Summary here.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1", "Change 2"]),
                BlueprintSection(title="Implementation", bullets=["Impl 1"]),
                BlueprintSection(title="Testing", bullets=["Test 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)

        assert "Changes:" in result
        assert "Implementation:" in result
        assert "Testing:" in result

    def test_blueprint_section_ordering(self):
        """Test blueprint sections are ordered correctly."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            summary="Summary.",
            sections=[
                BlueprintSection(title="Testing", bullets=["Test 1"]),
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)

        # Changes should appear before Testing in output
        changes_pos = result.find("Changes:")
        testing_pos = result.find("Testing:")
        assert changes_pos < testing_pos

    def test_blueprint_wraps_summary(self):
        """Test blueprint wraps long summary."""
        long_summary = "This is a very long summary that should be wrapped to multiple lines when it exceeds the maximum width configured for the commit message output."
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            summary=long_summary,
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT, wrap_width=72)
        result = render_blueprint(data, config)

        # Should be wrapped
        lines = result.split("\n")
        for line in lines:
            assert len(line) <= 72

    def test_blueprint_fallback_to_body_bullets(self):
        """Test blueprint falls back to body_bullets if no sections."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            body_bullets=["First change", "Second change"],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)

        # Should use Changes section with body_bullets
        assert "Changes:" in result
        assert "- First change" in result
        assert "- Second change" in result

    def test_blueprint_invalid_type_fallback(self):
        """Test blueprint with invalid type falls back to chore."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="invalid_type",
            summary="Summary.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)

        assert "chore:" in result


class TestRenderCommitMessageStyledBlueprint:
    """Tests for render_commit_message_styled with blueprint profile."""

    def test_selects_blueprint_renderer(self):
        """Test blueprint profile selects blueprint renderer."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            summary="Summary.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_commit_message_styled(data, config)

        assert "feat: Add feature" in result
        assert "Summary." in result
        assert "Changes:" in result

    def test_override_to_blueprint(self):
        """Test overriding to blueprint style."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            summary="Summary.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.DEFAULT)
        result = render_commit_message_styled(
            data, config, override_style=StyleProfile.BLUEPRINT
        )

        assert "Changes:" in result


class TestLoadStyleConfigBlueprint:
    """Tests for load_style_config_from_dict with blueprint config."""

    def test_loads_blueprint_profile(self):
        """Test loading blueprint profile."""
        config = load_style_config_from_dict({
            "style": {"profile": "blueprint"}
        })
        assert config.profile == StyleProfile.BLUEPRINT

    def test_loads_blueprint_section_titles(self):
        """Test loading custom blueprint section titles."""
        config = load_style_config_from_dict({
            "style": {
                "profile": "blueprint",
                "blueprint": {
                    "section_titles": ["Changes", "Notes"],
                }
            }
        })
        assert config.blueprint_section_titles == ["Changes", "Notes"]


class TestStyleConfigToDictBlueprint:
    """Tests for style_config_to_dict with blueprint config."""

    def test_includes_blueprint_config(self):
        """Test blueprint config is included in dict."""
        config = StyleConfig(
            profile=StyleProfile.BLUEPRINT,
            blueprint_section_titles=["Changes", "Implementation"],
        )
        result = style_config_to_dict(config)

        assert result["style"]["profile"] == "blueprint"
        assert result["style"]["blueprint"]["section_titles"] == ["Changes", "Implementation"]


class TestProfileDescriptionsBlueprint:
    """Tests for PROFILE_DESCRIPTIONS with blueprint."""

    def test_has_blueprint_description(self):
        """Test blueprint has description."""
        assert StyleProfile.BLUEPRINT in PROFILE_DESCRIPTIONS

    def test_blueprint_description_fields(self):
        """Test blueprint description has required fields."""
        desc = PROFILE_DESCRIPTIONS[StyleProfile.BLUEPRINT]
        assert desc["name"] == "blueprint"
        assert "description" in desc
        assert "format" in desc
        assert "example" in desc
        assert "Changes" in desc["example"]
        assert "Implementation" in desc["example"]
