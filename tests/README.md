# Hunknote Test Suite

Comprehensive test suite for the `hunknote` CLI tool.

## Overview

This test suite contains **820 unit tests** covering all modules of the hunknote project. The tests use `pytest` and `pytest-mock` for mocking external dependencies.

## Important Notes

### No API Calls

**The tests do NOT make any actual API calls to LLM providers.** All LLM interactions are mocked using `pytest-mock`. This means:

- Tests run quickly (typically < 5 seconds)
- No API keys are required to run tests
- No network connection is needed
- No costs are incurred from running tests

### Test Structure

```
tests/
├── __init__.py             # Test package init
├── conftest.py             # Shared fixtures
├── test_cache.py           # Cache module tests (90 tests)
├── test_cli.py             # CLI command tests (99 tests)
├── test_compose.py         # Compose feature tests (92 tests)
├── test_config.py          # Configuration tests (24 tests)
├── test_formatters.py      # Formatters module tests (21 tests)
├── test_git_ctx.py         # Git context tests (74 tests)
├── test_global_config.py   # Global config tests (26 tests)
├── test_llm_base.py        # LLM base module tests (116 tests)
├── test_llm_providers.py   # LLM provider tests (31 tests)
├── test_scope.py           # Scope inference tests (54 tests)
├── test_styles.py          # Style profiles tests (173 tests)
├── test_user_config.py     # User config tests (20 tests)
└── README.md               # This file
```

## Running Tests

### Run All Tests

```bash
# From project root
pytest tests/

# Or with verbose output
pytest tests/ -v

# Quick summary
pytest tests/ -q
```

### Run Specific Test File

```bash
pytest tests/test_formatters.py
pytest tests/test_cache.py -v
```

### Run Specific Test Class or Function

```bash
# Run a specific test class
pytest tests/test_formatters.py::TestCommitMessageJSON

# Run a specific test function
pytest tests/test_formatters.py::TestCommitMessageJSON::test_valid_commit_message
```

### Run Tests with Pattern Matching

```bash
# Run tests matching a pattern
pytest tests/ -k "cache"
pytest tests/ -k "provider"
pytest tests/ -k "blueprint"
```

## Test Coverage by Module

| Module | Test File | Tests | Description |
|--------|-----------|-------|-------------|
| `cache/` | `test_cache.py` | 90 | Cache models, paths, message caching, compose caching, utilities |
| `cli/` | `test_cli.py` | 99 | CLI commands (commit, compose, config, generate, init, scope, styles) |
| `compose/` | `test_compose.py` | 92 | Compose models, parser, inventory, validation, patch, executor |
| `config.py` | `test_config.py` | 24 | Configuration constants and enums |
| `formatters.py` | `test_formatters.py` | 21 | Commit message formatting and Pydantic validation |
| `git/` | `test_git_ctx.py` | 74 | Git operations (runner, branch, merge, status, diff, context) |
| `global_config.py` | `test_global_config.py` | 26 | Global user configuration (~/.hunknote/) |
| `llm/` | `test_llm_base.py` | 116 | LLM exceptions, results, parsing, prompts, providers |
| `llm/*.py` | `test_llm_providers.py` | 31 | All LLM provider classes and factory function |
| `scope.py` | `test_scope.py` | 54 | Scope inference from file paths |
| `styles/` | `test_styles.py` | 173 | Style models, renderers, inference, config, descriptions |
| `user_config.py` | `test_user_config.py` | 20 | Repository YAML config file management |

---

## Detailed Test Coverage

### Cache Module (`test_cache.py`) - 90 tests

Tests the `hunknote/cache/` package (refactored from cache.py):

| Test Class | Tests | Description |
|------------|-------|-------------|
| `TestCacheMetadata` | 3 | CacheMetadata Pydantic model validation |
| `TestGetCacheDir` | 2 | Cache directory creation and retrieval |
| `TestCacheFilePaths` | 4 | Path functions for all cache files |
| `TestComputeContextHash` | 3 | SHA256 hash computation |
| `TestIsCacheValid` | 4 | Cache validity checking |
| `TestSaveCache` | 8 | Save operations with all parameters |
| `TestLoadRawJsonResponse` | 3 | Load raw LLM JSON response |
| `TestUpdateMessageCache` | 1 | Update cached message |
| `TestLoadCacheMetadata` | 3 | Load and parse metadata |
| `TestInvalidateCache` | 2 | Remove cache files |
| `TestExtractStagedFiles` | 8 | Parse git status output |
| `TestGetDiffPreview` | 3 | Diff truncation |
| `TestLoadCachedMessage` | 3 | Load message from cache |
| `TestUpdateMetadataOverrides` | 5 | Update rendering overrides |
| `TestComposeCacheMetadata` | 2 | ComposeCacheMetadata model |
| `TestComposeFilePaths` | 4 | Compose cache file paths |
| `TestIsComposeCacheValid` | 4 | Compose cache validity |
| `TestSaveComposeCache` | 4 | Save compose plan and metadata |
| `TestLoadComposePlan` | 2 | Load cached compose plan |
| `TestLoadComposeMetadata` | 3 | Load compose metadata |
| `TestInvalidateComposeCache` | 2 | Remove compose cache files |
| `TestSaveComposeHunkIds` | 3 | Save hunk ID assignments |
| `TestLoadComposeHunkIds` | 3 | Load hunk ID data |
| `TestSaveCacheWithOverrides` | 5 | Cache with scope/ticket overrides |
| `TestCacheMetadataOverrideFields` | 4 | Override field validation |
| `TestComposeCacheIntegration` | 2 | Full compose cache workflow |

### Git Context Module (`test_git_ctx.py`) - 74 tests

Tests the `hunknote/git/` package (refactored from git_ctx.py):

| Test Class | Tests | Description |
|------------|-------|-------------|
| `TestRunGitCommand` | 3 | Git command execution and error handling |
| `TestGetRepoRoot` | 2 | Repository root detection |
| `TestGetBranch` | 2 | Current branch detection |
| `TestGetStatus` | 1 | Git status output |
| `TestGetStagedStatus` | 3 | Filter staged files from status |
| `TestGetLastCommits` | 3 | Recent commit history |
| `TestShouldExcludeFile` | 6 | File exclusion pattern matching |
| `TestDefaultDiffExcludePatterns` | 1 | Default ignore patterns |
| `TestGetStagedDiff` | 3 | Staged diff with filtering |
| `TestBuildContextBundle` | 8 | Context bundle construction |
| `TestMergeStateDetection` | 14 | Merge state functions |
| `TestBuildContextBundleMergeState` | 3 | Merge state in context bundle |
| `TestGetStagedFilesList` | 2 | List staged files |
| `TestParseFileChanges` | 6 | Parse file changes from status |
| `TestFormatMergeState` | 3 | Format merge state for display |
| `TestNewModuleImports` | 8 | New package import paths |
| `TestGitExceptions` | 3 | Exception class tests |
| `TestGetMergeSourceBranchEdgeCases` | 2 | Edge cases for merge source |
| `TestGetStagedDiffEdgeCases` | 2 | Edge cases for staged diff |
| `TestGetBranchEdgeCases` | 1 | Detached HEAD handling |

### Styles Module (`test_styles.py`) - 173 tests

Tests the `hunknote/styles/` package (refactored from styles.py):

| Test Class | Tests | Description |
|------------|-------|-------------|
| `TestStyleProfile` | 6 | StyleProfile enum values |
| `TestStyleConfig` | 6 | StyleConfig dataclass |
| `TestExtendedCommitJSON` | 6 | Commit JSON model validation |
| `TestSanitizeSubject` | 4 | Subject line sanitization |
| `TestStripTypePrefix` | 4 | Type prefix removal |
| `TestWrapText` | 4 | Text wrapping utilities |
| `TestRenderDefault` | 6 | Default style rendering |
| `TestRenderConventional` | 6 | Conventional Commits rendering |
| `TestRenderTicket` | 4 | Ticket-prefixed rendering |
| `TestRenderKernel` | 4 | Kernel-style rendering |
| `TestRenderCommitMessageStyled` | 5 | Style dispatcher |
| `TestExtractTicketFromBranch` | 4 | Ticket extraction from branches |
| `TestInferCommitType` | 6 | Commit type inference |
| `TestLoadStyleConfigFromDict` | 5 | Config loading |
| `TestStyleConfigToDict` | 5 | Config serialization |
| `TestProfileDescriptions` | 4 | Profile description constants |
| `TestConventionalTypes` | 4 | Conventional commit types |
| `TestBlueprintSectionTitles` | 4 | Blueprint section titles |
| `TestBlueprintSection` | 4 | Blueprint section model |
| `TestExtendedCommitJSONBlueprint` | 5 | Blueprint in commit JSON |
| `TestRenderBlueprint` | 10 | Blueprint style rendering |
| `TestRenderCommitMessageStyledBlueprint` | 4 | Blueprint style dispatcher |
| `TestLoadStyleConfigBlueprint` | 4 | Blueprint config loading |
| `TestStyleConfigToDictBlueprint` | 4 | Blueprint config serialization |
| `TestProfileDescriptionsBlueprint` | 2 | Blueprint description |
| `TestConventionalTypesMerge` | 2 | Merge type in conventional |
| `TestExtendedCommitJSONMergeType` | 2 | Merge type in commit JSON |
| `TestStyleConfigDefaults` | 4 | Default config values |
| `TestWrapTextEdgeCases` | 5 | Text wrapping edge cases |
| `TestProfileDescriptionsInvalidValues` | 2 | Invalid profile handling |
| `TestBlueprintSectionValidation` | 3 | Section validation |
| `TestRenderDefaultWithMaxBulletsZero` | 2 | Zero max bullets |
| `TestRenderConventionalNoBodyBullets` | 2 | No body bullets |
| `TestRenderBlueprintNoSummary` | 2 | Blueprint without summary |
| `TestRenderTicketSuffixWithBody` | 2 | Ticket with body |

### Compose Module (`test_compose.py`) - 92 tests

Tests the `hunknote/compose/` package (refactored from compose.py):

| Test Class | Tests | Description |
|------------|-------|-------------|
| `TestParseUnifiedDiff` | 6 | Unified diff parsing |
| `TestHunkRef` | 4 | HunkRef model |
| `TestBuildHunkInventory` | 4 | Hunk inventory construction |
| `TestFormatInventoryForLlm` | 4 | Format inventory for LLM |
| `TestValidatePlan` | 6 | Plan validation |
| `TestBuildCommitPatch` | 4 | Patch generation |
| `TestBuildComposePrompt` | 4 | Compose prompt construction |
| `TestComposeSystemPrompt` | 2 | System prompt content |
| `TestCreateSnapshot` | 3 | Git state snapshots |
| `TestComposeCommand` | 5 | Compose CLI command |
| `TestPlannedCommit` | 3 | PlannedCommit model |
| `TestComposePlan` | 3 | ComposePlan model |
| `TestComposeCaching` | 5 | Compose caching |
| `TestComposeCLICaching` | 4 | CLI caching integration |
| `TestFileDiff` | 3 | FileDiff model |
| `TestPlannedCommitValidator` | 3 | Commit validation |
| `TestParseUnifiedDiffEdgeCases` | 4 | Parser edge cases |
| `TestFormatInventoryForLlmEdgeCases` | 3 | Inventory edge cases |
| `TestValidatePlanEdgeCases` | 4 | Validation edge cases |
| `TestBuildCommitPatchEdgeCases` | 3 | Patch edge cases |
| `TestBuildComposePromptEdgeCases` | 3 | Prompt edge cases |
| `TestHunkRefEdgeCases` | 2 | HunkRef edge cases |
| `TestBlueprintSectionCompose` | 2 | Blueprint in compose |
| `TestRestoreFromSnapshot` | 2 | Snapshot restoration |
| `TestCleanupTempFiles` | 2 | Temp file cleanup |
| `TestComposeExecutionError` | 2 | Execution error handling |
| `TestPlanValidationError` | 2 | Validation error handling |

### LLM Base Module (`test_llm_base.py`) - 116 tests

Tests the `hunknote/llm/` package:

| Test Class | Tests | Description |
|------------|-------|-------------|
| `TestExceptions` | 4 | LLMError, MissingAPIKeyError, JSONParseError |
| `TestLLMResult` | 4 | LLMResult dataclass |
| `TestParseJsonResponse` | 8 | JSON response parsing |
| `TestValidateCommitJson` | 6 | Commit JSON validation |
| `TestPromptTemplates` | 5 | Prompt template existence |
| `TestStyleSpecificPromptTemplates` | 5 | Style-specific prompts |
| `TestBaseLLMProviderPromptMethods` | 5 | Provider prompt methods |
| `TestSystemPromptContent` | 5 | System prompt content |
| `TestUserPromptIntentHandling` | 4 | Intent in prompts |
| `TestMergeStateInPrompts` | 5 | Merge state in prompts |
| `TestRawLLMResult` | 4 | RawLLMResult dataclass |
| `TestNormalizeCommitJson` | 6 | JSON normalization |
| `TestBaseLLMProviderMethods` | 5 | Provider abstract methods |
| `TestParseJsonResponseEdgeCases` | 8 | Parser edge cases |
| `TestGenerateCommitJson` | 5 | Commit JSON generation |
| `TestProviderStyleAttribute` | 4 | Provider style handling |
| `TestProviderCustomModel` | 4 | Custom model support |
| `TestApiKeyFromCredentials` | 5 | API key loading |
| `TestExceptionMessages` | 4 | Error message formatting |
| `TestTypeSelectionRulesInPrompts` | 5 | Type rules in prompts |
| `TestScopeRulesInPrompts` | 5 | Scope rules in prompts |

### CLI Module (`test_cli.py`) - 99 tests

Tests the `hunknote/cli/` package:

| Test Class | Tests | Description |
|------------|-------|-------------|
| `TestCommitCommand` | 8 | hunknote commit |
| `TestComposeCliCommand` | 10 | hunknote compose |
| `TestConfigCommand` | 12 | hunknote config (show/set/path) |
| `TestGenerateCommand` | 15 | hunknote (default) |
| `TestInitCommand` | 8 | hunknote init |
| `TestScopeCommand` | 12 | hunknote scope (check/tree/json) |
| `TestStylesCommand` | 10 | hunknote styles |
| `TestHelpMessages` | 6 | --help output |
| `TestErrorHandling` | 8 | Error scenarios |
| `TestFlagCombinations` | 10 | Flag interaction tests |

---

## Key Test Areas

### Refactored Modules

All major refactored modules have comprehensive test coverage:

1. **`hunknote/cache/`** - Tests cover models, paths, message caching, compose caching, and all utility functions
2. **`hunknote/git/`** - Tests cover exceptions, runner, branch, merge, status, diff, and context modules
3. **`hunknote/styles/`** - Tests cover models, all renderers, inference, config, and descriptions
4. **`hunknote/compose/`** - Tests cover models, parser, inventory, validation, patch, prompt, executor, and cleanup
5. **`hunknote/llm/`** - Tests cover exceptions, results, parsing, all prompts, and provider base class
6. **`hunknote/cli/`** - Tests cover all commands and subcommands

### Backward Compatibility

Tests verify both old and new import paths work:

```python
# Old paths (via shims)
from hunknote.cache import save_cache
from hunknote.git_ctx import get_repo_root

# New paths (direct)
from hunknote.cache.message import save_cache
from hunknote.git.runner import get_repo_root
```

### Mock Patching

Tests patch at the module where functions are **defined**, not imported:

```python
# Correct - patch at definition location
mocker.patch("hunknote.git.diff._get_staged_files_list", ...)

# Incorrect - shim path may not work for patches
mocker.patch("hunknote.git_ctx._get_staged_files_list", ...)
```

---

## Fixtures

Shared fixtures are defined in `conftest.py`:

- `temp_dir` - Creates a temporary directory for each test
- `temp_repo` - Creates a temporary git repository
- `mock_repo_root` - Simulates a git repository root
- `sample_context_bundle` - Sample git context for testing
- `sample_commit_json_dict` - Sample commit message as dict
- `sample_llm_response` - Sample raw LLM JSON response
- `sample_llm_response_with_markdown` - Sample response with markdown fences

## Mocking Strategy

The tests use mocking extensively to isolate units:

### Git Commands
```python
mocker.patch("subprocess.run", return_value=mock_result)
```

### LLM API Keys
```python
with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
    key = provider.get_api_key()
```

### File System
Tests use `temp_dir` fixture which provides a real temporary directory that is cleaned up after each test.

### CLI Testing
```python
from typer.testing import CliRunner
runner = CliRunner()
result = runner.invoke(app, ["commit", "-y"])
```

## Adding New Tests

1. Create test functions with descriptive names:
   ```python
   def test_function_does_expected_behavior(self):
       """Test that function does X when Y."""
       ...
   ```

2. Use fixtures for common setup:
   ```python
   def test_with_temp_dir(self, temp_dir):
       config_file = temp_dir / "config.yaml"
       ...
   ```

3. Mock external dependencies:
   ```python
   def test_with_mocked_git(self, mocker):
       mocker.patch("hunknote.git.runner.get_repo_root", return_value=Path("/mock"))
       ...
   ```

4. For refactored modules, patch at the **definition** location:
   ```python
   # For hunknote/git/diff.py functions:
   mocker.patch("hunknote.git.diff._get_staged_files_list", ...)
   
   # For hunknote/cache/message.py functions:
   mocker.patch("hunknote.cache.message.load_cache_metadata", ...)
   ```

## Dependencies

- `pytest >= 8.0.0` - Test framework
- `pytest-mock >= 3.12.0` - Mocking utilities

Install with:
```bash
poetry install --with dev
```
