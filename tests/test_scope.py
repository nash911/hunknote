"""Tests for hunknote.scope module."""


from hunknote.scope import (
    ScopeStrategy,
    ScopeConfig,
    ScopeResult,
    DEFAULT_STOP_WORDS,
    DEFAULT_MONOREPO_ROOTS,
    normalize_path,
    get_path_segments,
    is_docs_file,
    is_test_file,
    infer_scope_from_mapping,
    infer_scope_from_monorepo,
    infer_scope_from_path_prefix,
    infer_scope,
    load_scope_config_from_dict,
    scope_config_to_dict,
)


class TestScopeStrategy:
    """Tests for ScopeStrategy enum."""

    def test_has_auto(self):
        """Test that AUTO strategy exists."""
        assert ScopeStrategy.AUTO.value == "auto"

    def test_has_monorepo(self):
        """Test that MONOREPO strategy exists."""
        assert ScopeStrategy.MONOREPO.value == "monorepo"

    def test_has_path_prefix(self):
        """Test that PATH_PREFIX strategy exists."""
        assert ScopeStrategy.PATH_PREFIX.value == "path-prefix"

    def test_has_mapping(self):
        """Test that MAPPING strategy exists."""
        assert ScopeStrategy.MAPPING.value == "mapping"

    def test_has_none(self):
        """Test that NONE strategy exists."""
        assert ScopeStrategy.NONE.value == "none"


class TestScopeConfig:
    """Tests for ScopeConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ScopeConfig()
        assert config.enabled is True
        assert config.strategy == ScopeStrategy.AUTO
        assert config.min_files == 1
        assert config.max_depth == 2
        assert config.dominant_threshold == 0.6

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ScopeConfig(
            enabled=False,
            strategy=ScopeStrategy.MONOREPO,
            max_depth=3,
        )
        assert config.enabled is False
        assert config.strategy == ScopeStrategy.MONOREPO
        assert config.max_depth == 3


class TestNormalizePath:
    """Tests for normalize_path function."""

    def test_forward_slashes(self):
        """Test that forward slashes are preserved."""
        assert normalize_path("src/api/routes.py") == "src/api/routes.py"

    def test_backslashes_converted(self):
        """Test that backslashes are converted."""
        assert normalize_path("src\\api\\routes.py") == "src/api/routes.py"

    def test_strips_leading_trailing_slashes(self):
        """Test that leading/trailing slashes are stripped."""
        assert normalize_path("/src/api/") == "src/api"


class TestGetPathSegments:
    """Tests for get_path_segments function."""

    def test_returns_directory_segments(self):
        """Test extraction of directory segments."""
        segments = get_path_segments("src/api/routes.py", max_depth=2)
        assert segments == ["src", "api"]

    def test_respects_max_depth(self):
        """Test that max_depth is respected."""
        segments = get_path_segments("a/b/c/d/file.py", max_depth=2)
        assert segments == ["a", "b"]

    def test_empty_for_root_file(self):
        """Test empty list for root-level file."""
        segments = get_path_segments("file.py", max_depth=2)
        assert segments == []


class TestIsDocsFile:
    """Tests for is_docs_file function."""

    def test_markdown_file(self):
        """Test markdown file detection."""
        assert is_docs_file("README.md") is True
        assert is_docs_file("docs/guide.md") is True

    def test_rst_file(self):
        """Test RST file detection."""
        assert is_docs_file("index.rst") is True

    def test_docs_directory(self):
        """Test docs directory detection."""
        assert is_docs_file("docs/api/reference.py") is True
        assert is_docs_file("documentation/guide.html") is True

    def test_non_docs_file(self):
        """Test non-docs file."""
        assert is_docs_file("src/main.py") is False


class TestIsTestFile:
    """Tests for is_test_file function."""

    def test_test_prefix(self):
        """Test test_ prefix detection."""
        assert is_test_file("test_main.py") is True

    def test_test_suffix(self):
        """Test _test suffix detection."""
        assert is_test_file("main_test.py") is True

    def test_tests_directory(self):
        """Test tests directory detection."""
        assert is_test_file("tests/test_api.py") is True
        assert is_test_file("test/unit/test_core.py") is True

    def test_spec_file(self):
        """Test spec file detection."""
        assert is_test_file("main.spec.js") is True

    def test_non_test_file(self):
        """Test non-test file."""
        assert is_test_file("src/main.py") is False


class TestInferScopeFromMapping:
    """Tests for infer_scope_from_mapping function."""

    def test_simple_mapping(self):
        """Test simple path-to-scope mapping."""
        files = ["src/api/routes.py", "src/api/models.py"]
        mapping = {"src/api/": "api"}
        result = infer_scope_from_mapping(files, mapping)

        assert result is not None
        assert result.scope == "api"
        assert result.confidence == 1.0

    def test_multiple_mappings(self):
        """Test multiple mappings with dominant scope."""
        files = ["src/api/routes.py", "src/api/models.py", "src/web/app.py"]
        mapping = {"src/api/": "api", "src/web/": "ui"}
        result = infer_scope_from_mapping(files, mapping)

        assert result is not None
        assert result.scope == "api"  # Dominant scope

    def test_no_matching_mapping(self):
        """Test when no mapping matches."""
        files = ["other/file.py"]
        mapping = {"src/api/": "api"}
        result = infer_scope_from_mapping(files, mapping)

        assert result is None

    def test_empty_mapping(self):
        """Test empty mapping."""
        files = ["src/api/routes.py"]
        result = infer_scope_from_mapping(files, {})

        assert result is None


class TestInferScopeFromMonorepo:
    """Tests for infer_scope_from_monorepo function."""

    def test_packages_directory(self):
        """Test monorepo with packages/ root."""
        files = ["packages/auth/src/login.py", "packages/auth/src/logout.py"]
        result = infer_scope_from_monorepo(files, ["packages/"])

        assert result is not None
        assert result.scope == "auth"
        assert result.confidence == 1.0

    def test_apps_directory(self):
        """Test monorepo with apps/ root."""
        files = ["apps/web/index.js", "apps/web/components/Button.js"]
        result = infer_scope_from_monorepo(files, ["apps/"])

        assert result is not None
        assert result.scope == "web"

    def test_multiple_packages(self):
        """Test changes across multiple packages."""
        files = [
            "packages/auth/login.py",
            "packages/auth/logout.py",
            "packages/api/routes.py",
        ]
        result = infer_scope_from_monorepo(files, ["packages/"])

        assert result is not None
        assert result.scope == "auth"  # Dominant
        assert len(result.candidates) == 2

    def test_no_monorepo_structure(self):
        """Test when files don't match monorepo structure."""
        files = ["src/main.py", "lib/utils.py"]
        result = infer_scope_from_monorepo(files, ["packages/", "apps/"])

        assert result is None


class TestInferScopeFromPathPrefix:
    """Tests for infer_scope_from_path_prefix function."""

    def test_common_segment(self):
        """Test inference from common path segment."""
        files = ["api/routes.py", "api/models.py", "api/utils.py"]
        result = infer_scope_from_path_prefix(files, max_depth=2)

        assert result is not None
        assert result.scope == "api"
        assert result.confidence == 1.0

    def test_filters_stop_words(self):
        """Test that stop words are filtered."""
        files = ["src/api/routes.py", "src/api/models.py"]
        result = infer_scope_from_path_prefix(files, max_depth=2)

        assert result is not None
        assert result.scope == "api"  # 'src' is filtered as stop word

    def test_uses_deepest_segment(self):
        """Test that deepest valid segment is used."""
        files = ["services/auth/login.py", "services/auth/logout.py"]
        result = infer_scope_from_path_prefix(files, max_depth=2)

        assert result is not None
        assert result.scope == "auth"

    def test_no_valid_segments(self):
        """Test when all segments are stop words."""
        files = ["src/lib/main.py"]
        result = infer_scope_from_path_prefix(files, max_depth=2)

        assert result is None


class TestInferScope:
    """Tests for main infer_scope function."""

    def test_disabled_scope(self):
        """Test when scope inference is disabled."""
        config = ScopeConfig(enabled=False)
        result = infer_scope(["src/api/routes.py"], config)

        assert result.scope is None
        assert result.strategy_used == ScopeStrategy.NONE
        assert "disabled" in result.reason.lower()

    def test_empty_files(self):
        """Test with empty file list."""
        result = infer_scope([])

        assert result.scope is None
        assert "No files" in result.reason

    def test_all_docs_files(self):
        """Test docs-only changes."""
        config = ScopeConfig(docs_scope="docs")
        files = ["README.md", "docs/guide.md"]
        result = infer_scope(files, config)

        assert result.scope == "docs"
        assert "documentation" in result.reason.lower()

    def test_monorepo_inference(self):
        """Test monorepo strategy."""
        config = ScopeConfig(
            strategy=ScopeStrategy.MONOREPO,
            monorepo_roots=["packages/"],
        )
        files = ["packages/auth/login.py", "packages/auth/logout.py"]
        result = infer_scope(files, config)

        assert result.scope == "auth"
        assert result.strategy_used == ScopeStrategy.MONOREPO

    def test_mapping_strategy(self):
        """Test mapping strategy."""
        config = ScopeConfig(
            strategy=ScopeStrategy.MAPPING,
            mapping={"src/api/": "api"},
        )
        files = ["src/api/routes.py"]
        result = infer_scope(files, config)

        assert result.scope == "api"
        assert result.strategy_used == ScopeStrategy.MAPPING

    def test_auto_strategy_tries_all(self):
        """Test that AUTO strategy tries multiple methods."""
        config = ScopeConfig(
            strategy=ScopeStrategy.AUTO,
            mapping={"src/api/": "api"},
        )
        files = ["src/api/routes.py"]
        result = infer_scope(files, config)

        assert result.scope == "api"

    def test_mixed_changes_below_threshold(self):
        """Test mixed changes return no scope."""
        config = ScopeConfig(
            strategy=ScopeStrategy.PATH_PREFIX,
            dominant_threshold=0.7,
        )
        # 3 files in api, 2 files in web = 60% confidence, below 70% threshold
        files = [
            "api/routes.py",
            "api/models.py",
            "api/utils.py",
            "web/app.py",
            "web/index.py",
        ]
        result = infer_scope(files, config)

        assert result.scope is None
        assert "Mixed changes" in result.reason

    def test_none_strategy(self):
        """Test NONE strategy always returns no scope."""
        config = ScopeConfig(strategy=ScopeStrategy.NONE)
        files = ["src/api/routes.py"]
        result = infer_scope(files, config)

        assert result.scope is None
        assert result.strategy_used == ScopeStrategy.NONE


class TestLoadScopeConfigFromDict:
    """Tests for load_scope_config_from_dict function."""

    def test_empty_dict_returns_defaults(self):
        """Test empty dict returns defaults."""
        config = load_scope_config_from_dict({})
        assert config.enabled is True
        assert config.strategy == ScopeStrategy.AUTO

    def test_loads_strategy(self):
        """Test loading strategy from dict."""
        config = load_scope_config_from_dict({
            "scope": {"strategy": "monorepo"}
        })
        assert config.strategy == ScopeStrategy.MONOREPO

    def test_loads_mapping(self):
        """Test loading mapping from dict."""
        config = load_scope_config_from_dict({
            "scope": {
                "mapping": {"src/api/": "api"}
            }
        })
        assert config.mapping == {"src/api/": "api"}

    def test_loads_all_options(self):
        """Test loading all options."""
        config = load_scope_config_from_dict({
            "scope": {
                "enabled": False,
                "strategy": "mapping",
                "min_files": 2,
                "max_depth": 3,
                "dominant_threshold": 0.8,
                "monorepo_roots": ["packages/"],
                "docs_scope": "documentation",
            }
        })
        assert config.enabled is False
        assert config.strategy == ScopeStrategy.MAPPING
        assert config.min_files == 2
        assert config.max_depth == 3
        assert config.dominant_threshold == 0.8
        assert config.monorepo_roots == ["packages/"]
        assert config.docs_scope == "documentation"


class TestScopeConfigToDict:
    """Tests for scope_config_to_dict function."""

    def test_converts_to_dict(self):
        """Test conversion to dict."""
        config = ScopeConfig(
            enabled=True,
            strategy=ScopeStrategy.MONOREPO,
            max_depth=3,
        )
        result = scope_config_to_dict(config)

        assert result["scope"]["enabled"] is True
        assert result["scope"]["strategy"] == "monorepo"
        assert result["scope"]["max_depth"] == 3


class TestDefaultConstants:
    """Tests for default constants."""

    def test_stop_words_contains_common(self):
        """Test stop words contains common directories."""
        assert "src" in DEFAULT_STOP_WORDS
        assert "lib" in DEFAULT_STOP_WORDS
        assert "tests" in DEFAULT_STOP_WORDS
        assert "node_modules" in DEFAULT_STOP_WORDS

    def test_monorepo_roots_contains_common(self):
        """Test monorepo roots contains common patterns."""
        assert "packages/" in DEFAULT_MONOREPO_ROOTS
        assert "apps/" in DEFAULT_MONOREPO_ROOTS


class TestScopeResult:
    """Tests for ScopeResult dataclass."""

    def test_creates_result(self):
        """Test ScopeResult creation."""
        result = ScopeResult(
            scope="api",
            confidence=0.9,
            strategy_used=ScopeStrategy.MAPPING,
            candidates=[("api", 3)],
            reason="Test reason",
        )
        assert result.scope == "api"
        assert result.confidence == 0.9
        assert result.strategy_used == ScopeStrategy.MAPPING


class TestRealWorldScenarios:
    """Tests for real-world repository scenarios."""

    def test_django_project(self):
        """Test scope inference for Django project structure."""
        files = [
            "myapp/api/views.py",
            "myapp/api/serializers.py",
            "myapp/api/urls.py",
        ]
        config = ScopeConfig(strategy=ScopeStrategy.PATH_PREFIX)
        result = infer_scope(files, config)

        assert result.scope == "api"

    def test_react_project(self):
        """Test scope inference for React project structure."""
        files = [
            "src/components/Button.jsx",
            "src/components/Input.jsx",
        ]
        config = ScopeConfig(strategy=ScopeStrategy.PATH_PREFIX)
        result = infer_scope(files, config)

        assert result.scope == "components"

    def test_nx_monorepo(self):
        """Test scope inference for Nx monorepo."""
        files = [
            "libs/shared-ui/src/Button.tsx",
            "libs/shared-ui/src/Input.tsx",
        ]
        config = ScopeConfig(
            strategy=ScopeStrategy.MONOREPO,
            monorepo_roots=["libs/", "apps/"],
        )
        result = infer_scope(files, config)

        assert result.scope == "shared-ui"

    def test_python_package(self):
        """Test scope inference for Python package."""
        files = [
            "hunknote/cli.py",
            "hunknote/config.py",
            "hunknote/cache.py",
        ]
        config = ScopeConfig(strategy=ScopeStrategy.PATH_PREFIX)
        result = infer_scope(files, config)

        assert result.scope == "hunknote"

