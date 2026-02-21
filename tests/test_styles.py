"""Tests for hunknote.styles module."""


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestExtendedCommitJSONEdgeCases:
        """Additional edge case tests for ExtendedCommitJSON."""

        def test_get_subject_raises_when_neither_provided(self):
            """Test get_subject raises ValueError when neither subject nor title provided."""
            data = ExtendedCommitJSON(body_bullets=["Change"])
            try:
                data.get_subject()
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "subject" in str(e).lower() or "title" in str(e).lower()

        def test_get_subject_with_whitespace_only_title(self):
            """Test get_subject raises when title is whitespace only."""
            data = ExtendedCommitJSON(title="   ", body_bullets=["Change"])
            try:
                data.get_subject()
                assert False, "Should have raised ValueError"
            except ValueError:
                pass

        def test_get_subject_with_whitespace_only_subject(self):
            """Test get_subject falls back to title when subject is whitespace only."""
            data = ExtendedCommitJSON(title="Valid title", subject="   ")
            assert data.get_subject() == "Valid title"

        def test_get_scope_returns_none_for_whitespace(self):
            """Test get_scope returns None when scope is whitespace only."""
            data = ExtendedCommitJSON(title="Test", scope="   ")
            assert data.get_scope() is None

        def test_get_scope_strips_whitespace(self):
            """Test get_scope strips whitespace from scope."""
            data = ExtendedCommitJSON(title="Test", scope="  api  ")
            assert data.get_scope() == "api"

        def test_get_type_strips_whitespace(self):
            """Test get_type strips whitespace from type."""
            data = ExtendedCommitJSON(title="Test", type="  feat  ")
            assert data.get_type() == "feat"

        def test_ensure_footers_list_with_none(self):
            """Test footers validator converts None to empty list."""
            data = ExtendedCommitJSON(title="Test", footers=None)
            assert data.footers == []

        def test_ensure_sections_list_with_blueprint_section_objects(self):
            """Test sections validator handles BlueprintSection objects."""
            section = BlueprintSection(title="Changes", bullets=["Change 1"])
            data = ExtendedCommitJSON(
                title="Test",
                sections=[section],
            )
            assert len(data.sections) == 1
            assert data.sections[0].title == "Changes"

        def test_get_bullets_strips_whitespace(self):
            """Test get_bullets strips whitespace from bullets."""
            data = ExtendedCommitJSON(
                title="Test",
                body_bullets=["  First  ", "Second", "  "],
            )
            bullets = data.get_bullets()
            assert bullets == ["First", "Second"]

        def test_get_bullets_filters_empty_strings(self):
            """Test get_bullets filters out empty strings."""
            data = ExtendedCommitJSON(
                title="Test",
                body_bullets=["First", "", "Second", "   "],
            )
            bullets = data.get_bullets()
            assert bullets == ["First", "Second"]

        def test_get_summary_strips_whitespace(self):
            """Test get_summary strips whitespace."""
            data = ExtendedCommitJSON(
                title="Test",
                summary="  Summary text  ",
            )
            assert data.get_summary() == "Summary text"

        def test_get_summary_returns_none_for_whitespace(self):
            """Test get_summary returns None for whitespace only."""
            data = ExtendedCommitJSON(title="Test", summary="   ")
            assert data.get_summary() is None


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestSanitizeSubjectEdgeCases:
        """Additional edge case tests for sanitize_subject."""

        def test_multiline_subject(self):
            """Test multiline subject takes only first line."""
            result = sanitize_subject("First line\nSecond line\nThird line")
            assert result == "First line"

        def test_exact_max_length(self):
            """Test subject at exact max length is unchanged."""
            subject = "A" * 72
            result = sanitize_subject(subject, max_length=72)
            assert result == subject
            assert len(result) == 72

        def test_one_over_max_length(self):
            """Test subject one char over max gets truncated."""
            subject = "A" * 73
            result = sanitize_subject(subject, max_length=72)
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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestRenderDefaultEdgeCases:
        """Additional edge case tests for render_default."""

        def test_empty_bullets_list(self):
            """Test render_default with empty bullets list."""
            data = ExtendedCommitJSON(
                title="Add feature",
                body_bullets=[],
            )
            config = StyleConfig()
            result = render_default(data, config)
            assert result == "Add feature"

        def test_max_bullets_limits_output(self):
            """Test max_bullets config limits bullet output."""
            data = ExtendedCommitJSON(
                title="Add feature",
                body_bullets=["One", "Two", "Three", "Four", "Five"],
            )
            config = StyleConfig(max_bullets=3)
            result = render_default(data, config)
            assert "- One" in result
            assert "- Two" in result
            assert "- Three" in result
            assert "- Four" not in result
            assert "- Five" not in result

        def test_long_bullet_wrapping(self):
            """Test long bullets are wrapped correctly."""
            long_bullet = "This is a very long bullet point that should be wrapped to fit within the configured wrap width limit"
            data = ExtendedCommitJSON(
                title="Add feature",
                body_bullets=[long_bullet],
            )
            config = StyleConfig(wrap_width=50)
            result = render_default(data, config)
            lines = result.split("\n")
            for line in lines:
                assert len(line) <= 50


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestRenderConventionalEdgeCases:
        """Additional edge case tests for render_conventional."""

        def test_invalid_type_fallback_to_chore(self):
            """Test invalid type falls back to chore."""
            data = ExtendedCommitJSON(
                type="invalid_type",
                subject="Add feature",
                body_bullets=["Change"],
            )
            config = StyleConfig()
            result = render_conventional(data, config)
            assert result.startswith("chore:")

        def test_existing_footers_preserved(self):
            """Test existing footers are preserved."""
            data = ExtendedCommitJSON(
                type="feat",
                subject="Add feature",
                body_bullets=["Change"],
                footers=["Co-authored-by: Someone <email@example.com>"],
            )
            config = StyleConfig()
            result = render_conventional(data, config)
            assert "Co-authored-by: Someone" in result

        def test_duplicate_ticket_footer_prevention(self):
            """Test duplicate Refs footer is not added."""
            data = ExtendedCommitJSON(
                type="fix",
                subject="Fix bug",
                body_bullets=["Fix it"],
                ticket="PROJ-123",
                footers=["Refs: PROJ-123"],  # Already has Refs footer
            )
            config = StyleConfig()
            result = render_conventional(data, config)
            # Should only appear once
            assert result.count("Refs: PROJ-123") == 1

        def test_strips_double_type_prefix(self):
            """Test conventional strips type prefix from subject to avoid double prefix."""
            data = ExtendedCommitJSON(
                type="feat",
                subject="feat: Add feature",  # Subject already has type prefix
                body_bullets=["Change"],
            )
            config = StyleConfig()
            result = render_conventional(data, config)
            assert result.startswith("feat: Add feature")
            assert "feat: feat:" not in result

        def test_strips_type_with_scope_prefix(self):
            """Test conventional strips type(scope): prefix from subject."""
            data = ExtendedCommitJSON(
                type="fix",
                scope="api",
                subject="fix(api): Fix the bug",
                body_bullets=["Fix it"],
            )
            config = StyleConfig()
            result = render_conventional(data, config)
            assert "fix(api): Fix the bug" in result
            assert "fix(api): fix(api):" not in result

        def test_breaking_footer_disabled(self):
            """Test breaking footer can be disabled."""
            data = ExtendedCommitJSON(
                type="feat",
                subject="Breaking feature",
                body_bullets=["Major change"],
                breaking_change=True,
            )
            config = StyleConfig(breaking_footer=False)
            result = render_conventional(data, config)
            assert "BREAKING CHANGE:" not in result


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestRenderTicketEdgeCases:
        """Additional edge case tests for render_ticket."""

        def test_no_ticket_fallback(self):
            """Test render_ticket without ticket falls back to default-like format."""
            data = ExtendedCommitJSON(
                subject="Fix bug",
                body_bullets=["Fix the issue"],
                ticket=None,
            )
            config = StyleConfig()
            result = render_ticket(data, config)
            # Should just be the subject without any ticket
            assert result.startswith("Fix bug")
            assert "None" not in result

        def test_body_disabled(self):
            """Test render_ticket with body disabled."""
            data = ExtendedCommitJSON(
                subject="Fix bug",
                body_bullets=["Fix the issue"],
                ticket="PROJ-123",
            )
            config = StyleConfig(include_body=False)
            result = render_ticket(data, config)
            assert "PROJ-123" in result
            assert "Fix the issue" not in result

        def test_override_scope(self):
            """Test render_ticket with scope override."""
            data = ExtendedCommitJSON(
                subject="Fix bug",
                scope="old",
                body_bullets=["Fix it"],
                ticket="PROJ-123",
            )
            config = StyleConfig(ticket_placement="prefix")
            result = render_ticket(data, config, override_scope="new")
            assert "PROJ-123 (new)" in result
            assert "(old)" not in result


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

    def test_strips_type_prefix_from_subject(self):
        """Test kernel style strips type prefix from subject."""
        # This tests the bug fix for "llm: feat: support commit styles"
        data = ExtendedCommitJSON(
            scope="llm",
            subject="feat: support commit styles",  # Subject has type prefix
            body_bullets=["Add style support"],
        )
        config = StyleConfig(subsystem_from_scope=True)
        result = render_kernel(data, config)

        # Should have "llm: support commit styles", not "llm: feat: support commit styles"
        assert result.startswith("llm: support commit styles")
        assert "llm: feat:" not in result

    def test_strips_type_with_scope_prefix_from_subject(self):
        """Test kernel style strips type(scope): prefix from subject."""
        data = ExtendedCommitJSON(
            scope="net",
            subject="fix(tcp): handle packet loss",  # Subject has type(scope): prefix
            body_bullets=["Fix handling"],
        )
        config = StyleConfig(subsystem_from_scope=True)
        result = render_kernel(data, config)

        # Should strip the type(scope): prefix
        assert result.startswith("net: handle packet loss")
        assert "fix(tcp):" not in result

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestRenderKernelEdgeCases:
        """Additional edge case tests for render_kernel."""

        def test_subsystem_from_scope_disabled(self):
            """Test kernel style with subsystem_from_scope disabled."""
            data = ExtendedCommitJSON(
                scope="auth",
                subject="Add login support",
                body_bullets=["Implement login"],
            )
            config = StyleConfig(subsystem_from_scope=False)
            result = render_kernel(data, config)
            # Should not have scope prefix
            assert not result.startswith("auth:")
            assert result.startswith("Add login support")

        def test_body_disabled(self):
            """Test kernel style with body disabled."""
            data = ExtendedCommitJSON(
                scope="auth",
                subject="Add login support",
                body_bullets=["Implement login"],
            )
            config = StyleConfig(include_body=False)
            result = render_kernel(data, config)
            assert "auth: Add login support" in result
            assert "Implement login" not in result


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestRenderCommitMessageStyledAllProfiles:
        """Tests for render_commit_message_styled with all profiles."""

        def test_ticket_profile(self):
            """Test rendering with ticket profile."""
            data = ExtendedCommitJSON(
                subject="Fix bug",
                body_bullets=["Fix it"],
                ticket="PROJ-123",
            )
            config = StyleConfig(profile=StyleProfile.TICKET)
            result = render_commit_message_styled(data, config)
            assert "PROJ-123" in result

        def test_kernel_profile(self):
            """Test rendering with kernel profile."""
            data = ExtendedCommitJSON(
                scope="net",
                subject="Add TCP support",
                body_bullets=["Add support"],
            )
            config = StyleConfig(profile=StyleProfile.KERNEL)
            result = render_commit_message_styled(data, config)
            assert result.startswith("net:")

        def test_all_overrides_together(self):
            """Test all overrides work together."""
            data = ExtendedCommitJSON(
                type="feat",
                scope="old",
                subject="Add feature",
                body_bullets=["Change"],
                ticket="OLD-111",
            )
            config = StyleConfig(profile=StyleProfile.DEFAULT)
            result = render_commit_message_styled(
                data,
                config,
                override_style=StyleProfile.TICKET,
                override_scope="new",
                override_ticket="NEW-222",
            )
            assert "NEW-222" in result
            assert "(new)" in result


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestExtractTicketFromBranchEdgeCases:
        """Additional edge case tests for extract_ticket_from_branch."""

        def test_multiple_tickets_returns_first(self):
            """Test extraction returns first ticket when multiple present."""
            branch = "feature/PROJ-123-and-PROJ-456"
            ticket = extract_ticket_from_branch(branch)
            assert ticket == "PROJ-123"

        def test_lowercase_branch_with_uppercase_ticket(self):
            """Test extraction from lowercase branch with uppercase ticket."""
            branch = "feature/proj-123-add-login"
            ticket = extract_ticket_from_branch(branch)
            # Default pattern requires uppercase
            assert ticket is None

        def test_numeric_only_project(self):
            """Test ticket with numeric project key."""
            branch = "feature/A2-123-add-login"
            ticket = extract_ticket_from_branch(branch)
            # Pattern allows letters and numbers after first letter
            assert ticket == "A2-123"

        def test_long_project_key(self):
            """Test ticket with long project key."""
            branch = "feature/LONGPROJECT-9999-add-feature"
            ticket = extract_ticket_from_branch(branch)
            assert ticket == "LONGPROJECT-9999"


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestInferCommitTypeEdgeCases:
        """Additional edge case tests for infer_commit_type."""

        def test_gitlab_ci_files(self):
            """Test inference for GitLab CI files."""
            files = [".gitlab-ci.yml"]
            assert infer_commit_type(files) == "ci"

        def test_jenkinsfile(self):
            """Test inference for Jenkinsfile."""
            files = ["Jenkinsfile"]
            assert infer_commit_type(files) == "ci"

        def test_circleci_files(self):
            """Test inference for CircleCI files."""
            files = [".circleci/config.yml"]
            assert infer_commit_type(files) == "ci"

        def test_travis_files(self):
            """Test inference for Travis CI files."""
            files = [".travis.yml"]
            assert infer_commit_type(files) == "ci"

        def test_multiple_ci_files(self):
            """Test inference for multiple CI files."""
            files = [".github/workflows/ci.yml", ".github/workflows/release.yml"]
            assert infer_commit_type(files) == "ci"

        def test_doc_dir_files(self):
            """Test inference for files in doc directory."""
            files = ["doc/guide.txt", "doc/api.txt"]
            assert infer_commit_type(files) == "docs"

        def test_documentation_dir_files(self):
            """Test inference for files in documentation directory."""
            files = ["documentation/setup.md"]
            assert infer_commit_type(files) == "docs"

        def test_adoc_files(self):
            """Test inference for asciidoc files."""
            files = ["README.adoc", "docs/guide.adoc"]
            assert infer_commit_type(files) == "docs"

        def test_rst_files(self):
            """Test inference for RST files."""
            files = ["docs/index.rst", "docs/api.rst"]
            assert infer_commit_type(files) == "docs"

        def test_spec_directory(self):
            """Test inference for spec directory (test files)."""
            files = ["spec/feature_spec.rb", "spec/helper_spec.rb"]
            assert infer_commit_type(files) == "test"

        def test_jest_test_files(self):
            """Test inference for Jest test files."""
            files = ["__tests__/component.test.js", "__tests__/utils.test.js"]
            assert infer_commit_type(files) == "test"


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestLoadStyleConfigEdgeCases:
        """Additional edge case tests for load_style_config_from_dict."""

        def test_invalid_profile_fallback_to_default(self):
            """Test invalid profile falls back to DEFAULT."""
            config = load_style_config_from_dict({
                "style": {"profile": "nonexistent_profile"}
            })
            assert config.profile == StyleProfile.DEFAULT

        def test_loads_kernel_config(self):
            """Test loading kernel configuration."""
            config = load_style_config_from_dict({
                "style": {
                    "profile": "kernel",
                    "kernel": {
                        "subsystem_from_scope": False,
                    }
                }
            })
            assert config.profile == StyleProfile.KERNEL
            assert config.subsystem_from_scope is False

        def test_loads_conventional_breaking_footer(self):
            """Test loading conventional breaking_footer config."""
            config = load_style_config_from_dict({
                "style": {
                    "conventional": {
                        "breaking_footer": False,
                    }
                }
            })
            assert config.breaking_footer is False

        def test_loads_ticket_key_regex(self):
            """Test loading ticket key_regex config."""
            config = load_style_config_from_dict({
                "style": {
                    "ticket": {
                        "key_regex": r"(CUSTOM-\d+)",
                    }
                }
            })
            assert config.ticket_key_regex == r"(CUSTOM-\d+)"

        def test_loads_conventional_types(self):
            """Test loading custom conventional types."""
            config = load_style_config_from_dict({
                "style": {
                    "conventional": {
                        "types": ["feat", "fix", "custom"],
                    }
                }
            })
            assert config.conventional_types == ["feat", "fix", "custom"]


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

    # ============================================================================
    # Additional Test Cases for Complete Coverage
    # ============================================================================

    class TestStyleConfigToDictComplete:
        """Complete tests for style_config_to_dict."""

        def test_includes_all_config_sections(self):
            """Test all config sections are included."""
            config = StyleConfig(
                profile=StyleProfile.TICKET,
                include_body=False,
                max_bullets=4,
                wrap_width=80,
                conventional_types=["feat", "fix"],
                breaking_footer=False,
                ticket_key_regex=r"(TEST-\d+)",
                ticket_placement="suffix",
                subsystem_from_scope=False,
                blueprint_section_titles=["Changes"],
            )
            result = style_config_to_dict(config)

            assert result["style"]["profile"] == "ticket"
            assert result["style"]["include_body"] is False
            assert result["style"]["max_bullets"] == 4
            assert result["style"]["wrap_width"] == 80
            assert result["style"]["conventional"]["types"] == ["feat", "fix"]
            assert result["style"]["conventional"]["breaking_footer"] is False
            assert result["style"]["ticket"]["key_regex"] == r"(TEST-\d+)"
            assert result["style"]["ticket"]["placement"] == "suffix"
            assert result["style"]["kernel"]["subsystem_from_scope"] is False
            assert result["style"]["blueprint"]["section_titles"] == ["Changes"]


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


class TestConventionalTypesMerge:
    """Tests for merge type in conventional commits."""

    def test_conventional_types_includes_merge(self):
        """Test that merge is in CONVENTIONAL_TYPES."""
        assert "merge" in CONVENTIONAL_TYPES

    def test_merge_type_renders_correctly(self):
        """Test that merge type renders correctly in conventional style."""
        data = ExtendedCommitJSON(
            type="merge",
            scope=None,
            title="Merge branch feature-auth",
            body_bullets=["Integrate authentication module"],
        )
        config = StyleConfig()
        result = render_conventional(data, config)
        assert result.startswith("merge:")
        assert "Merge branch feature-auth" in result

    def test_merge_type_with_scope(self):
        """Test merge type with scope in conventional style."""
        data = ExtendedCommitJSON(
            type="merge",
            scope="auth",
            title="Merge feature-auth into main",
            body_bullets=["Integrate authentication module"],
        )
        config = StyleConfig()
        result = render_conventional(data, config)
        assert result.startswith("merge(auth):")

    def test_merge_type_in_blueprint_style(self):
        """Test merge type renders correctly in blueprint style."""
        data = ExtendedCommitJSON(
            type="merge",
            scope="auth",
            title="Merge feature-auth branch",
            summary="Integrate the feature-auth branch with user authentication.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Add login endpoint"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)
        assert result.startswith("merge(auth):")
        assert "Merge feature-auth branch" in result


class TestExtendedCommitJSONMergeType:
    """Tests for ExtendedCommitJSON with merge type."""

    def test_extended_json_accepts_merge_type(self):
        """Test that ExtendedCommitJSON accepts merge type."""
        data = ExtendedCommitJSON(
            type="merge",
            title="Merge branch feature",
            body_bullets=["Merge changes"],
        )
        assert data.type == "merge"

    def test_extended_json_get_type_merge(self):
        """Test get_type returns merge when set."""
        data = ExtendedCommitJSON(
            type="merge",
            title="Merge branch",
            body_bullets=[],
        )
        assert data.get_type("feat") == "merge"


# ============================================================================
# Additional Top-Level Test Classes for Complete Coverage
# ============================================================================


class TestStyleConfigDefaults:
    """Tests for StyleConfig default values."""

    def test_ticket_key_regex_default(self):
        """Test ticket_key_regex has correct default."""
        config = StyleConfig()
        assert config.ticket_key_regex == r"([A-Z][A-Z0-9]+-\d+)"

    def test_ticket_placement_default(self):
        """Test ticket_placement has correct default."""
        config = StyleConfig()
        assert config.ticket_placement == "prefix"

    def test_blueprint_section_titles_default(self):
        """Test blueprint_section_titles has correct default."""
        config = StyleConfig()
        assert config.blueprint_section_titles == BLUEPRINT_SECTION_TITLES

    def test_breaking_footer_default(self):
        """Test breaking_footer has correct default."""
        config = StyleConfig()
        assert config.breaking_footer is True

    def test_subsystem_from_scope_default(self):
        """Test subsystem_from_scope has correct default."""
        config = StyleConfig()
        assert config.subsystem_from_scope is True

    def test_conventional_types_default(self):
        """Test conventional_types has correct default."""
        config = StyleConfig()
        assert config.conventional_types == CONVENTIONAL_TYPES


class TestWrapTextEdgeCases:
    """Additional edge case tests for wrap_text."""

    def test_empty_string(self):
        """Test wrapping empty string."""
        result = wrap_text("")
        assert result == ""

    def test_single_long_word(self):
        """Test wrapping single long word that cannot be broken."""
        long_word = "A" * 100
        result = wrap_text(long_word, width=50)
        # Since break_long_words=False, word should not be broken
        assert long_word in result

    def test_subsequent_indent(self):
        """Test subsequent indent is applied correctly."""
        text = "First part Second part Third part Fourth part"
        result = wrap_text(text, width=20, initial_indent="", subsequent_indent="    ")
        lines = result.split("\n")
        if len(lines) > 1:
            assert lines[1].startswith("    ")


class TestProfileDescriptionsInvalidValues:
    """Tests for StyleProfile error handling."""

    def test_invalid_profile_raises_value_error(self):
        """Test that invalid profile string raises ValueError."""
        try:
            StyleProfile("invalid")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestBlueprintSectionValidation:
    """Tests for BlueprintSection edge cases."""

    def test_empty_title(self):
        """Test section with empty title is allowed."""
        section = BlueprintSection(title="", bullets=["Change"])
        assert section.title == ""

    def test_whitespace_title(self):
        """Test section with whitespace title."""
        section = BlueprintSection(title="  Changes  ", bullets=["Change"])
        assert section.title == "  Changes  "  # Not stripped by model


class TestRenderDefaultWithMaxBulletsZero:
    """Test render_default edge case with max_bullets=0."""

    def test_max_bullets_zero_does_not_limit(self):
        """Test max_bullets=0 does not limit bullets (0 is falsy)."""
        data = ExtendedCommitJSON(
            title="Add feature",
            body_bullets=["One", "Two", "Three"],
        )
        config = StyleConfig(max_bullets=0)
        result = render_default(data, config)
        # With max_bullets=0 (falsy), get_bullets returns all bullets
        assert "- One" in result
        assert "- Two" in result
        assert "- Three" in result


class TestRenderConventionalNoBodyBullets:
    """Test render_conventional with no body bullets."""

    def test_no_body_bullets(self):
        """Test conventional with no body bullets."""
        data = ExtendedCommitJSON(
            type="feat",
            subject="Add feature",
            body_bullets=[],
        )
        config = StyleConfig()
        result = render_conventional(data, config)
        assert result == "feat: Add feature"

    def test_with_footers_but_no_body(self):
        """Test conventional with footers but no body bullets."""
        data = ExtendedCommitJSON(
            type="feat",
            subject="Add feature",
            body_bullets=[],
            ticket="PROJ-123",
        )
        config = StyleConfig()
        result = render_conventional(data, config)
        assert "feat: Add feature" in result
        assert "Refs: PROJ-123" in result


class TestRenderBlueprintNoSummary:
    """Test render_blueprint without summary."""

    def test_no_summary_sections_only(self):
        """Test blueprint with sections but no summary."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            sections=[
                BlueprintSection(title="Changes", bullets=["Change 1"]),
            ],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)
        assert "feat: Add feature" in result
        assert "Changes:" in result

    def test_empty_sections(self):
        """Test blueprint with empty sections list."""
        data = ExtendedCommitJSON(
            title="Add feature",
            type="feat",
            summary="Just a summary.",
            sections=[],
        )
        config = StyleConfig(profile=StyleProfile.BLUEPRINT)
        result = render_blueprint(data, config)
        assert "feat: Add feature" in result
        assert "Just a summary." in result


class TestRenderTicketSuffixWithBody:
    """Test render_ticket suffix placement with body."""

    def test_suffix_with_body(self):
        """Test ticket suffix with body bullets."""
        data = ExtendedCommitJSON(
            subject="Fix bug",
            body_bullets=["Fix 1", "Fix 2"],
            ticket="PROJ-123",
        )
        config = StyleConfig(ticket_placement="suffix")
        result = render_ticket(data, config)
        # First line should end with ticket
        first_line = result.split("\n")[0]
        assert first_line.endswith("(PROJ-123)")
        assert "- Fix 1" in result

