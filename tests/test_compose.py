"""Tests for hunknote.compose module."""

import json
import subprocess

import pytest

from hunknote.compose import (
    HunkRef,
    PlannedCommit,
    ComposePlan,
    BlueprintSection,
    parse_unified_diff,
    build_hunk_inventory,
    format_inventory_for_llm,
    validate_plan,
    build_commit_patch,
    build_compose_prompt,
    create_snapshot,
    COMPOSE_SYSTEM_PROMPT,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_diff():
    """Sample unified diff output for testing."""
    return """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,8 @@ def main():
     print("Hello")
+    print("World")
+    print("!")
     return 0
@@ -20,3 +22,5 @@ def helper():
     pass
+    # New comment
+    return True
diff --git a/tests/test_main.py b/tests/test_main.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/tests/test_main.py
@@ -0,0 +1,10 @@
+import pytest
+
+def test_main():
+    assert True
+
+def test_helper():
+    assert True
"""


@pytest.fixture
def sample_diff_with_binary():
    """Sample diff with binary file."""
    return """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,7 @@ def main():
     print("Hello")
+    print("World")
     return 0
diff --git a/image.png b/image.png
index 1234567..abcdefg 100644
Binary files a/image.png and b/image.png differ
diff --git a/src/util.py b/src/util.py
index 1234567..abcdefg 100644
--- a/src/util.py
+++ b/src/util.py
@@ -1,3 +1,4 @@
 def util():
+    # utility function
     pass
"""


@pytest.fixture
def sample_plan():
    """Sample compose plan for testing."""
    return ComposePlan(
        version="1",
        warnings=[],
        commits=[
            PlannedCommit(
                id="C1",
                type="feat",
                scope="main",
                title="Add greeting messages",
                bullets=["Add World and ! messages"],
                hunks=["H1_abc123"],
            ),
            PlannedCommit(
                id="C2",
                type="test",
                scope=None,
                title="Add unit tests for main",
                bullets=["Add test_main and test_helper"],
                hunks=["H3_def456"],
            ),
        ],
    )


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary git repository for testing."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_dir,
        capture_output=True,
    )

    # Create initial commit
    (repo_dir / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir,
        capture_output=True,
    )

    return repo_dir


# ============================================================================
# Diff Parser Tests
# ============================================================================


class TestParseUnifiedDiff:
    """Tests for parse_unified_diff function."""

    def test_parses_multiple_files(self, sample_diff):
        """Test parsing diff with multiple files."""
        file_diffs, warnings = parse_unified_diff(sample_diff)

        assert len(file_diffs) == 2
        assert file_diffs[0].file_path == "src/main.py"
        assert file_diffs[1].file_path == "tests/test_main.py"

    def test_parses_multiple_hunks(self, sample_diff):
        """Test parsing file with multiple hunks."""
        file_diffs, warnings = parse_unified_diff(sample_diff)

        # First file has 2 hunks
        assert len(file_diffs[0].hunks) == 2

    def test_detects_new_file(self, sample_diff):
        """Test detecting new file."""
        file_diffs, warnings = parse_unified_diff(sample_diff)

        assert file_diffs[1].is_new_file is True

    def test_skips_binary_files(self, sample_diff_with_binary):
        """Test that binary files are skipped with warning."""
        file_diffs, warnings = parse_unified_diff(sample_diff_with_binary)

        # Should have 2 text files, 1 binary skipped
        non_binary = [f for f in file_diffs if not f.is_binary]
        assert len(non_binary) == 2
        assert any("Binary file skipped" in w for w in warnings)

    def test_empty_diff(self):
        """Test parsing empty diff."""
        file_diffs, warnings = parse_unified_diff("")

        assert len(file_diffs) == 0
        assert len(warnings) == 0

    def test_hunk_id_format(self, sample_diff):
        """Test that hunk IDs have correct format."""
        file_diffs, warnings = parse_unified_diff(sample_diff)

        for file_diff in file_diffs:
            for hunk in file_diff.hunks:
                # ID should start with H and contain underscore
                assert hunk.id.startswith("H")
                assert "_" in hunk.id

    def test_hunk_header_parsing(self, sample_diff):
        """Test that hunk headers are parsed correctly."""
        file_diffs, warnings = parse_unified_diff(sample_diff)

        hunk = file_diffs[0].hunks[0]
        assert hunk.old_start == 10
        assert hunk.new_start == 10


class TestHunkRef:
    """Tests for HunkRef class."""

    def test_snippet_short(self):
        """Test snippet for short hunk."""
        hunk = HunkRef(
            id="H1_abc",
            file_path="test.py",
            header="@@ -1,3 +1,4 @@",
            old_start=1,
            old_len=3,
            new_start=1,
            new_len=4,
            lines=["@@ -1,3 +1,4 @@", " context", "+added", "-removed"],
        )

        snippet = hunk.snippet(10)
        assert "+added" in snippet
        assert "-removed" in snippet

    def test_snippet_truncated(self):
        """Test snippet truncation for long hunk."""
        lines = ["@@ -1,20 +1,25 @@"] + [f"+line{i}" for i in range(20)]
        hunk = HunkRef(
            id="H1_abc",
            file_path="test.py",
            header="@@ -1,20 +1,25 @@",
            old_start=1,
            old_len=20,
            new_start=1,
            new_len=25,
            lines=lines,
        )

        snippet = hunk.snippet(5)
        assert "more lines" in snippet


# ============================================================================
# Hunk Inventory Tests
# ============================================================================


class TestBuildHunkInventory:
    """Tests for build_hunk_inventory function."""

    def test_builds_inventory(self, sample_diff):
        """Test building hunk inventory from file diffs."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)

        # Should have 3 hunks total (2 from main.py, 1 from test_main.py)
        assert len(inventory) == 3

    def test_inventory_keys_are_hunk_ids(self, sample_diff):
        """Test that inventory keys match hunk IDs."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)

        for file_diff in file_diffs:
            for hunk in file_diff.hunks:
                assert hunk.id in inventory
                assert inventory[hunk.id] is hunk


class TestFormatInventoryForLlm:
    """Tests for format_inventory_for_llm function."""

    def test_formats_inventory(self, sample_diff):
        """Test formatting inventory for LLM prompt."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        formatted = format_inventory_for_llm(file_diffs)

        assert "[HUNK INVENTORY]" in formatted
        assert "src/main.py" in formatted
        assert "tests/test_main.py" in formatted

    def test_includes_hunk_ids(self, sample_diff):
        """Test that formatted inventory includes hunk IDs."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        formatted = format_inventory_for_llm(file_diffs)

        for hunk_id in inventory.keys():
            assert hunk_id in formatted

    def test_marks_new_file(self, sample_diff):
        """Test that new files are marked."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        formatted = format_inventory_for_llm(file_diffs)

        assert "(new file)" in formatted


# ============================================================================
# Plan Validation Tests
# ============================================================================


class TestValidatePlan:
    """Tests for validate_plan function."""

    def test_valid_plan(self, sample_diff):
        """Test validation of valid plan."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="First commit",
                    hunks=[hunk_ids[0], hunk_ids[1]],
                ),
                PlannedCommit(
                    id="C2",
                    title="Second commit",
                    hunks=[hunk_ids[2]],
                ),
            ],
        )

        errors = validate_plan(plan, inventory, max_commits=6)
        assert len(errors) == 0

    def test_unknown_hunk_id(self, sample_diff):
        """Test validation fails for unknown hunk ID."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="First commit",
                    hunks=["UNKNOWN_HUNK"],
                ),
            ],
        )

        errors = validate_plan(plan, inventory, max_commits=6)
        assert any("unknown hunk" in e.lower() for e in errors)

    def test_duplicate_hunk(self, sample_diff):
        """Test validation fails for duplicate hunk across commits."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="First commit",
                    hunks=[hunk_ids[0]],
                ),
                PlannedCommit(
                    id="C2",
                    title="Second commit",
                    hunks=[hunk_ids[0]],  # Duplicate!
                ),
            ],
        )

        errors = validate_plan(plan, inventory, max_commits=6)
        assert any("multiple commits" in e.lower() for e in errors)

    def test_empty_commit(self, sample_diff):
        """Test validation fails for empty commit."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Empty commit",
                    hunks=[],
                ),
            ],
        )

        errors = validate_plan(plan, inventory, max_commits=6)
        assert any("no hunks" in e.lower() for e in errors)

    def test_too_many_commits(self, sample_diff):
        """Test validation fails when exceeding max commits."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(id=f"C{i}", title=f"Commit {i}", hunks=[hunk_ids[i % len(hunk_ids)]])
                for i in range(10)
            ],
        )

        errors = validate_plan(plan, inventory, max_commits=3)
        assert any("exceeds max" in e.lower() for e in errors)

    def test_missing_title(self, sample_diff):
        """Test validation fails for missing title."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="",
                    hunks=[hunk_ids[0]],
                ),
            ],
        )

        errors = validate_plan(plan, inventory, max_commits=6)
        assert any("no title" in e.lower() for e in errors)

    def test_unassigned_hunks_warning(self, sample_diff):
        """Test warning for unassigned hunks."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Partial commit",
                    hunks=[hunk_ids[0]],  # Only one hunk assigned
                ),
            ],
        )

        errors = validate_plan(plan, inventory, max_commits=6)
        # Should not be an error, but a warning in plan.warnings
        assert len(errors) == 0
        assert any("unassigned" in w.lower() for w in plan.warnings)


# ============================================================================
# Patch Builder Tests
# ============================================================================


class TestBuildCommitPatch:
    """Tests for build_commit_patch function."""

    def test_builds_patch(self, sample_diff):
        """Test building patch for a commit."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        commit = PlannedCommit(
            id="C1",
            title="Test commit",
            hunks=[hunk_ids[0]],
        )

        patch = build_commit_patch(commit, inventory, file_diffs)

        assert "diff --git" in patch
        assert "@@" in patch

    def test_patch_includes_only_selected_hunks(self, sample_diff):
        """Test that patch only includes selected hunks."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        # Select only the first hunk
        commit = PlannedCommit(
            id="C1",
            title="Test commit",
            hunks=[hunk_ids[0]],
        )

        patch = build_commit_patch(commit, inventory, file_diffs)

        # Patch should only contain content from selected hunk
        # Count @@ -X,Y +A,B @@ pattern (hunk headers)
        import re
        hunk_headers = re.findall(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", patch)
        assert len(hunk_headers) == 1

    def test_patch_preserves_file_order(self, sample_diff):
        """Test that patch preserves original file order."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        # Select hunks from both files
        commit = PlannedCommit(
            id="C1",
            title="Test commit",
            hunks=hunk_ids[:2] + hunk_ids[2:3],  # First two hunks + third
        )

        patch = build_commit_patch(commit, inventory, file_diffs)

        # main.py should appear before test_main.py
        main_pos = patch.find("src/main.py")
        test_pos = patch.find("tests/test_main.py")
        assert main_pos < test_pos


# ============================================================================
# Compose Prompt Tests
# ============================================================================


class TestBuildComposePrompt:
    """Tests for build_compose_prompt function."""

    def test_builds_prompt(self, sample_diff):
        """Test building compose prompt."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=["Previous commit 1", "Previous commit 2"],
            style="conventional",
            max_commits=6,
        )

        assert "[CONTEXT]" in prompt
        assert "main" in prompt  # branch
        assert "[HUNK INVENTORY]" in prompt
        assert "[OUTPUT SCHEMA]" in prompt

    def test_prompt_includes_max_commits(self, sample_diff):
        """Test that prompt includes max commits constraint."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=[],
            style="default",
            max_commits=3,
        )

        assert "3" in prompt  # max commits value


class TestComposeSystemPrompt:
    """Tests for COMPOSE_SYSTEM_PROMPT."""

    def test_system_prompt_exists(self):
        """Test that system prompt is defined."""
        assert len(COMPOSE_SYSTEM_PROMPT) > 0

    def test_system_prompt_mentions_commits(self):
        """Test that system prompt mentions commit splitting."""
        assert "commit" in COMPOSE_SYSTEM_PROMPT.lower()

    def test_system_prompt_mentions_json(self):
        """Test that system prompt mentions JSON output."""
        assert "JSON" in COMPOSE_SYSTEM_PROMPT


# ============================================================================
# Snapshot Tests
# ============================================================================


class TestCreateSnapshot:
    """Tests for create_snapshot function."""

    def test_creates_snapshot(self, temp_repo):
        """Test creating snapshot of git state."""
        snapshot = create_snapshot(temp_repo, pid=12345)

        assert snapshot.pre_head != ""
        assert snapshot.head_file is not None
        assert snapshot.head_file.exists()

    def test_saves_staged_changes(self, temp_repo):
        """Test that staged changes are saved."""
        # Create and stage a change
        (temp_repo / "new_file.txt").write_text("new content")
        subprocess.run(["git", "add", "new_file.txt"], cwd=temp_repo, capture_output=True)

        snapshot = create_snapshot(temp_repo, pid=12345)

        assert snapshot.pre_staged_patch != ""
        assert snapshot.patch_file is not None
        assert snapshot.patch_file.exists()


# ============================================================================
# CLI Integration Tests
# ============================================================================


class TestComposeCommand:
    """Tests for compose CLI command."""

    def test_compose_help(self):
        """Test compose command help."""
        from typer.testing import CliRunner
        from hunknote.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["compose", "--help"])

        assert result.exit_code == 0
        assert "commit stack" in result.output.lower()

    def test_compose_in_main_help(self):
        """Test compose appears in main help."""
        from typer.testing import CliRunner
        from hunknote.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "compose" in result.output.lower()

    def test_compose_no_changes(self, temp_repo, mocker):
        """Test compose with no changes."""
        from typer.testing import CliRunner
        from hunknote.cli import app

        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["compose"])

        # Should exit cleanly with message about no changes
        assert "No changes" in result.output or result.exit_code == 0


# ============================================================================
# Data Model Tests
# ============================================================================


class TestPlannedCommit:
    """Tests for PlannedCommit model."""

    def test_create_basic(self):
        """Test creating basic planned commit."""
        commit = PlannedCommit(
            id="C1",
            title="Test commit",
            hunks=["H1_abc"],
        )

        assert commit.id == "C1"
        assert commit.title == "Test commit"
        assert commit.type is None
        assert commit.scope is None

    def test_create_with_all_fields(self):
        """Test creating planned commit with all fields."""
        commit = PlannedCommit(
            id="C1",
            type="feat",
            scope="api",
            ticket="PROJ-123",
            title="Add endpoint",
            bullets=["Add GET /api/users", "Add authentication"],
            summary="Adds user endpoint with auth.",
            sections=[
                BlueprintSection(title="Changes", bullets=["Add endpoint"]),
            ],
            hunks=["H1_abc", "H2_def"],
        )

        assert commit.type == "feat"
        assert commit.scope == "api"
        assert commit.ticket == "PROJ-123"
        assert len(commit.bullets) == 2
        assert len(commit.sections) == 1


class TestComposePlan:
    """Tests for ComposePlan model."""

    def test_create_empty(self):
        """Test creating empty plan."""
        plan = ComposePlan()

        assert plan.version == "1"
        assert plan.warnings == []
        assert plan.commits == []

    def test_create_with_commits(self):
        """Test creating plan with commits."""
        plan = ComposePlan(
            version="1",
            warnings=["Some warning"],
            commits=[
                PlannedCommit(id="C1", title="First", hunks=["H1"]),
                PlannedCommit(id="C2", title="Second", hunks=["H2"]),
            ],
        )

        assert len(plan.commits) == 2
        assert len(plan.warnings) == 1

    def test_from_json(self):
        """Test creating plan from JSON."""
        json_data = {
            "version": "1",
            "warnings": [],
            "commits": [
                {
                    "id": "C1",
                    "type": "feat",
                    "scope": "api",
                    "title": "Add feature",
                    "bullets": ["Change 1"],
                    "hunks": ["H1_abc"],
                }
            ],
        }

        plan = ComposePlan(**json_data)

        assert plan.commits[0].type == "feat"
        assert plan.commits[0].scope == "api"


# ============================================================================
# Compose Caching Tests
# ============================================================================


class TestComposeCaching:
    """Tests for compose caching functions."""

    def test_save_and_load_compose_cache(self, tmp_path):
        """Test saving and loading compose cache."""
        from hunknote.cache import (
            save_compose_cache,
            load_compose_plan,
            load_compose_metadata,
            is_compose_cache_valid,
            compute_context_hash,
        )

        repo_root = tmp_path

        plan_json = json.dumps({
            "version": "1",
            "warnings": [],
            "commits": [
                {"id": "C1", "title": "Test commit", "hunks": ["H1"]}
            ]
        }, indent=2)

        context_hash = compute_context_hash("test_diff|style=default|max_commits=6")

        save_compose_cache(
            repo_root=repo_root,
            context_hash=context_hash,
            plan_json=plan_json,
            model="test-model",
            input_tokens=100,
            output_tokens=50,
            changed_files=["file1.py", "file2.py"],
            total_hunks=3,
            num_commits=1,
            style="default",
            max_commits=6,
        )

        # Check cache is valid
        assert is_compose_cache_valid(repo_root, context_hash)

        # Load plan
        loaded_plan = load_compose_plan(repo_root)
        assert loaded_plan is not None
        assert "C1" in loaded_plan

        # Load metadata
        metadata = load_compose_metadata(repo_root)
        assert metadata is not None
        assert metadata.model == "test-model"
        assert metadata.num_commits == 1
        assert metadata.total_hunks == 3

    def test_compose_cache_invalid_with_different_hash(self, tmp_path):
        """Test that cache is invalid when hash changes."""
        from hunknote.cache import (
            save_compose_cache,
            is_compose_cache_valid,
            compute_context_hash,
        )

        repo_root = tmp_path

        context_hash = compute_context_hash("test_diff|style=default|max_commits=6")

        save_compose_cache(
            repo_root=repo_root,
            context_hash=context_hash,
            plan_json="{}",
            model="test-model",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=0,
            num_commits=0,
            style="default",
            max_commits=6,
        )

        # Different hash should be invalid
        different_hash = compute_context_hash("different_diff|style=default|max_commits=6")
        assert not is_compose_cache_valid(repo_root, different_hash)

    def test_invalidate_compose_cache(self, tmp_path):
        """Test invalidating compose cache."""
        from hunknote.cache import (
            save_compose_cache,
            invalidate_compose_cache,
            is_compose_cache_valid,
            load_compose_plan,
            compute_context_hash,
        )

        repo_root = tmp_path
        context_hash = compute_context_hash("test")

        save_compose_cache(
            repo_root=repo_root,
            context_hash=context_hash,
            plan_json="{}",
            model="test-model",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=0,
            num_commits=0,
            style="default",
            max_commits=6,
        )

        # Cache should be valid
        assert is_compose_cache_valid(repo_root, context_hash)

        # Invalidate cache
        invalidate_compose_cache(repo_root)

        # Cache should be invalid
        assert not is_compose_cache_valid(repo_root, context_hash)
        assert load_compose_plan(repo_root) is None

    def test_compose_cache_files_created(self, tmp_path):
        """Test that compose cache creates the correct files."""
        from hunknote.cache import (
            save_compose_cache,
            get_compose_hash_file,
            get_compose_plan_file,
            get_compose_metadata_file,
            compute_context_hash,
        )

        repo_root = tmp_path
        context_hash = compute_context_hash("test")

        save_compose_cache(
            repo_root=repo_root,
            context_hash=context_hash,
            plan_json='{"version": "1"}',
            model="test-model",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=0,
            num_commits=0,
            style="default",
            max_commits=6,
        )

        # Check files exist
        assert get_compose_hash_file(repo_root).exists()
        assert get_compose_plan_file(repo_root).exists()
        assert get_compose_metadata_file(repo_root).exists()

    def test_load_compose_plan_returns_none_when_no_cache(self, tmp_path):
        """Test that load_compose_plan returns None when no cache."""
        from hunknote.cache import load_compose_plan

        assert load_compose_plan(tmp_path) is None

    def test_load_compose_metadata_returns_none_when_no_cache(self, tmp_path):
        """Test that load_compose_metadata returns None when no cache."""
        from hunknote.cache import load_compose_metadata

        assert load_compose_metadata(tmp_path) is None

    def test_save_and_load_hunk_ids(self, tmp_path):
        """Test saving and loading hunk IDs file."""
        from hunknote.cache import (
            save_compose_hunk_ids,
            load_compose_hunk_ids,
            get_compose_hunk_ids_file,
        )

        repo_root = tmp_path
        hunk_ids_data = [
            {
                "hunk_id": "H1_abc123",
                "file": "src/main.py",
                "commit_id": "C1",
                "header": "@@ -10,6 +10,8 @@",
                "diff": "@@ -10,6 +10,8 @@\n context\n+added line",
            },
            {
                "hunk_id": "H2_def456",
                "file": "src/util.py",
                "commit_id": "C2",
                "header": "@@ -1,3 +1,4 @@",
                "diff": "@@ -1,3 +1,4 @@\n context\n+another line",
            },
        ]

        save_compose_hunk_ids(repo_root, hunk_ids_data)

        # Check file exists
        assert get_compose_hunk_ids_file(repo_root).exists()

        # Load and verify
        loaded = load_compose_hunk_ids(repo_root)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0]["hunk_id"] == "H1_abc123"
        assert loaded[0]["commit_id"] == "C1"
        assert loaded[1]["file"] == "src/util.py"

    def test_invalidate_removes_hunk_ids_file(self, tmp_path):
        """Test that invalidate_compose_cache removes hunk IDs file."""
        from hunknote.cache import (
            save_compose_cache,
            save_compose_hunk_ids,
            invalidate_compose_cache,
            get_compose_hunk_ids_file,
            compute_context_hash,
        )

        repo_root = tmp_path
        context_hash = compute_context_hash("test")

        # Save cache and hunk IDs
        save_compose_cache(
            repo_root=repo_root,
            context_hash=context_hash,
            plan_json="{}",
            model="test-model",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=0,
            num_commits=0,
            style="default",
            max_commits=6,
        )
        save_compose_hunk_ids(repo_root, [{"hunk_id": "H1_abc"}])

        # Verify file exists
        assert get_compose_hunk_ids_file(repo_root).exists()

        # Invalidate
        invalidate_compose_cache(repo_root)

        # Verify file is removed
        assert not get_compose_hunk_ids_file(repo_root).exists()

    def test_load_hunk_ids_returns_none_when_no_file(self, tmp_path):
        """Test that load_compose_hunk_ids returns None when no file."""
        from hunknote.cache import load_compose_hunk_ids

        assert load_compose_hunk_ids(tmp_path) is None


class TestComposeCLICaching:
    """Tests for compose CLI caching integration."""

    def test_compose_json_flag_in_help(self):
        """Test that --json flag appears in compose help."""
        from typer.testing import CliRunner
        from hunknote.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["compose", "--help"])

        assert result.exit_code == 0
        assert "--json" in result.output
        assert "-j" in result.output

    def test_compose_regenerate_flag_in_help(self):
        """Test that --regenerate flag appears in compose help."""
        from typer.testing import CliRunner
        from hunknote.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["compose", "--help"])

        assert result.exit_code == 0
        assert "--regenerate" in result.output
        assert "-r" in result.output

    def test_compose_from_plan_flag_in_help(self):
        """Test that --from-plan flag appears in compose help."""
        from typer.testing import CliRunner
        from hunknote.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["compose", "--help"])

        assert result.exit_code == 0
        assert "--from-plan" in result.output
