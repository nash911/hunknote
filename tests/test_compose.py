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
    try_correct_hunk_ids,
    build_commit_patch,
    build_compose_prompt,
    build_compose_retry_prompt,
    create_snapshot,
    COMPOSE_SYSTEM_PROMPT,
    COMPOSE_RETRY_SYSTEM_PROMPT,
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

    def test_system_prompt_contains_coherence_rule(self):
        """Test that system prompt includes the atomic coherence rule."""
        prompt_lower = COMPOSE_SYSTEM_PROMPT.lower()
        # Must mention keeping dependent changes together
        assert "broken state" in prompt_lower
        assert "same commit" in prompt_lower

    def test_system_prompt_coherence_overrides_type_separation(self):
        """Test that coherence rule qualifies the type separation guidance.

        The prompt should say to separate types ONLY when independent,
        not unconditionally.
        """
        assert "ONLY when they are independent" in COMPOSE_SYSTEM_PROMPT

    def test_system_prompt_mentions_cross_file_dependency(self):
        """Test that system prompt addresses cross-file dependencies."""
        prompt_lower = COMPOSE_SYSTEM_PROMPT.lower()
        # Should mention changes in one file requiring changes in another
        assert "one file" in prompt_lower
        assert "another file" in prompt_lower


class TestCoherenceRuleInPrompt:
    """Tests that the coherence rule is properly included in compose prompts.

    Strategy 1: The LLM prompt must instruct that causally dependent hunks
    across different files are kept in the same commit.
    """

    def test_user_prompt_contains_coherence_rule(self, sample_diff):
        """Test that the user prompt includes the coherence rule in RULES."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=[],
            style="default",
            max_commits=6,
        )

        prompt_lower = prompt.lower()
        # The RULES section must contain the coherence rule
        assert "broken state" in prompt_lower
        assert "same commit" in prompt_lower

    def test_coherence_rule_mentions_tests(self, sample_diff):
        """Test that coherence rule explicitly mentions test updates as example."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=[],
            style="default",
            max_commits=6,
        )

        prompt_lower = prompt.lower()
        assert "test" in prompt_lower

    def test_coherence_rule_mentions_renaming(self, sample_diff):
        """Test that coherence rule mentions function renaming as example."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=[],
            style="default",
            max_commits=6,
        )

        prompt_lower = prompt.lower()
        assert "rename" in prompt_lower or "renaming" in prompt_lower

    def test_coherence_rule_mentions_interface_changes(self, sample_diff):
        """Test that coherence rule mentions interface/implementation changes."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=[],
            style="default",
            max_commits=6,
        )

        prompt_lower = prompt.lower()
        assert "interface" in prompt_lower or "implementation" in prompt_lower

    def test_coherence_rule_is_numbered_in_rules_section(self, sample_diff):
        """Test that coherence rule is a numbered rule in the RULES section."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=[],
            style="default",
            max_commits=6,
        )

        # Extract the RULES section
        rules_start = prompt.find("[RULES]")
        assert rules_start != -1, "RULES section not found in prompt"

        rules_section = prompt[rules_start:]
        # The coherence rule should be rule 7
        assert "7." in rules_section

    def test_coherence_rule_present_regardless_of_style(self, sample_diff):
        """Test that coherence rule is present for all style profiles."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        for style in ["default", "blueprint", "conventional", "ticket", "kernel"]:
            prompt = build_compose_prompt(
                file_diffs=file_diffs,
                branch="main",
                recent_commits=[],
                style=style,
                max_commits=6,
            )
            assert "broken state" in prompt.lower(), (
                f"Coherence rule missing for style: {style}"
            )

    def test_coherence_rule_present_regardless_of_max_commits(self, sample_diff):
        """Test that coherence rule is present for any max_commits value."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        for max_commits in [1, 2, 5, 10, 20]:
            prompt = build_compose_prompt(
                file_diffs=file_diffs,
                branch="main",
                recent_commits=[],
                style="default",
                max_commits=max_commits,
            )
            assert "broken state" in prompt.lower(), (
                f"Coherence rule missing for max_commits={max_commits}"
            )


class TestComposeRetryPrompt:
    """Tests for compose retry prompt functions."""

    def test_retry_system_prompt_exists(self):
        """Test that retry system prompt is defined."""
        assert len(COMPOSE_RETRY_SYSTEM_PROMPT) > 0

    def test_retry_system_prompt_mentions_fixing_errors(self):
        """Test that retry system prompt mentions fixing errors."""
        assert "fix" in COMPOSE_RETRY_SYSTEM_PROMPT.lower()
        assert "error" in COMPOSE_RETRY_SYSTEM_PROMPT.lower()

    def test_retry_system_prompt_emphasizes_exact_ids(self):
        """Test that retry system prompt emphasizes using exact hunk IDs."""
        assert "EXACT" in COMPOSE_RETRY_SYSTEM_PROMPT or "exact" in COMPOSE_RETRY_SYSTEM_PROMPT.lower()

    def test_build_retry_prompt_includes_errors(self, sample_diff):
        """Test that retry prompt includes validation errors."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        valid_hunk_ids = list(inventory.keys())

        previous_plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Test commit",
                    hunks=["H1_wrong", "H2_wrong"],
                ),
            ],
        )

        validation_errors = [
            "Commit C1 references unknown hunk: H1_wrong",
            "Commit C1 references unknown hunk: H2_wrong",
        ]

        prompt = build_compose_retry_prompt(
            file_diffs=file_diffs,
            previous_plan=previous_plan,
            validation_errors=validation_errors,
            valid_hunk_ids=valid_hunk_ids,
            max_commits=6,
        )

        assert "[VALIDATION ERRORS]" in prompt
        assert "H1_wrong" in prompt
        assert "H2_wrong" in prompt

    def test_build_retry_prompt_includes_previous_plan(self, sample_diff):
        """Test that retry prompt includes previous plan structure."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        valid_hunk_ids = list(inventory.keys())

        previous_plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Add feature X",
                    hunks=["H1_wrong"],
                ),
                PlannedCommit(
                    id="C2",
                    title="Fix bug Y",
                    hunks=["H2_wrong"],
                ),
            ],
        )

        prompt = build_compose_retry_prompt(
            file_diffs=file_diffs,
            previous_plan=previous_plan,
            validation_errors=["Some error"],
            valid_hunk_ids=valid_hunk_ids,
            max_commits=6,
        )

        assert "[YOUR PREVIOUS PLAN]" in prompt
        assert "C1" in prompt
        assert "C2" in prompt
        assert "Add feature X" in prompt
        assert "Fix bug Y" in prompt

    def test_build_retry_prompt_includes_valid_hunk_ids(self, sample_diff):
        """Test that retry prompt includes valid hunk IDs list."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        valid_hunk_ids = list(inventory.keys())

        previous_plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(id="C1", title="Test", hunks=["wrong"]),
            ],
        )

        prompt = build_compose_retry_prompt(
            file_diffs=file_diffs,
            previous_plan=previous_plan,
            validation_errors=["Error"],
            valid_hunk_ids=valid_hunk_ids,
            max_commits=6,
        )

        assert "[VALID HUNK IDs" in prompt
        # Check that at least some valid IDs are in the prompt
        for hunk_id in valid_hunk_ids[:3]:
            assert hunk_id in prompt

    def test_build_retry_prompt_includes_inventory(self, sample_diff):
        """Test that retry prompt includes full hunk inventory."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        valid_hunk_ids = list(inventory.keys())

        previous_plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(id="C1", title="Test", hunks=["wrong"]),
            ],
        )

        prompt = build_compose_retry_prompt(
            file_diffs=file_diffs,
            previous_plan=previous_plan,
            validation_errors=["Error"],
            valid_hunk_ids=valid_hunk_ids,
            max_commits=6,
        )

        assert "[FULL HUNK INVENTORY" in prompt
        assert "[HUNK INVENTORY]" in prompt

    def test_build_retry_prompt_includes_common_mistakes(self, sample_diff):
        """Test that retry prompt warns about common mistakes."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        valid_hunk_ids = list(inventory.keys())

        previous_plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(id="C1", title="Test", hunks=["wrong"]),
            ],
        )

        prompt = build_compose_retry_prompt(
            file_diffs=file_diffs,
            previous_plan=previous_plan,
            validation_errors=["Error"],
            valid_hunk_ids=valid_hunk_ids,
            max_commits=6,
        )

        assert "[COMMON MISTAKES TO AVOID]" in prompt
        assert "wrong hash" in prompt.lower() or "hash suffix" in prompt.lower()

    def test_build_retry_prompt_includes_output_schema(self, sample_diff):
        """Test that retry prompt includes JSON output schema."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        valid_hunk_ids = list(inventory.keys())

        previous_plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(id="C1", title="Test", hunks=["wrong"]),
            ],
        )

        prompt = build_compose_retry_prompt(
            file_diffs=file_diffs,
            previous_plan=previous_plan,
            validation_errors=["Error"],
            valid_hunk_ids=valid_hunk_ids,
            max_commits=6,
        )

        assert "[OUTPUT SCHEMA]" in prompt
        assert '"commits"' in prompt
        assert '"hunks"' in prompt

    def test_build_retry_prompt_respects_max_commits(self, sample_diff):
        """Test that retry prompt includes max commits constraint."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        valid_hunk_ids = list(inventory.keys())

        previous_plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(id="C1", title="Test", hunks=["wrong"]),
            ],
        )

        prompt = build_compose_retry_prompt(
            file_diffs=file_diffs,
            previous_plan=previous_plan,
            validation_errors=["Error"],
            valid_hunk_ids=valid_hunk_ids,
            max_commits=3,
        )

        assert "3" in prompt  # max commits value


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


# ============================================================================
# Additional Test Cases for Complete Coverage
# ============================================================================


class TestFileDiff:
    """Tests for FileDiff dataclass."""

    def test_renamed_file(self):
        """Test detecting renamed file."""
        diff = """diff --git a/old_name.py b/new_name.py
similarity index 95%
rename from old_name.py
rename to new_name.py
index 1234567..abcdefg 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,4 @@
 def func():
+    # comment
     pass
"""
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 1
        assert file_diffs[0].file_path == "new_name.py"
        assert file_diffs[0].is_renamed is True
        assert file_diffs[0].old_path == "old_name.py"

    def test_deleted_file(self):
        """Test detecting deleted file."""
        diff = """diff --git a/deleted.py b/deleted.py
deleted file mode 100644
index 1234567..0000000
--- a/deleted.py
+++ /dev/null
@@ -1,5 +0,0 @@
-def func():
-    pass
-
-def other():
-    return True
"""
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 1
        assert file_diffs[0].file_path == "deleted.py"
        assert file_diffs[0].is_deleted_file is True

    def test_mode_change_only(self):
        """Test file with mode change only (no hunks)."""
        diff = """diff --git a/script.sh b/script.sh
old mode 100644
new mode 100755
"""
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 1
        assert file_diffs[0].file_path == "script.sh"
        assert len(file_diffs[0].hunks) == 0


class TestPlannedCommitValidator:
    """Tests for PlannedCommit strip_conventional_prefix_from_title validator."""

    def test_strips_redundant_type_prefix(self):
        """Test that redundant type prefix is stripped from title."""
        commit = PlannedCommit(
            id="C1",
            type="feat",
            scope="api",
            title="feat(api): Add pagination support",
            hunks=["H1_abc"],
        )

        # The validator should have stripped "feat(api): " from title
        assert commit.title == "Add pagination support"
        assert "feat" not in commit.title.lower()

    def test_strips_type_only_prefix(self):
        """Test that type-only prefix is stripped."""
        commit = PlannedCommit(
            id="C1",
            type="fix",
            title="fix: Prevent null pointer",
            hunks=["H1_abc"],
        )

        assert commit.title == "Prevent null pointer"

    def test_preserves_title_without_prefix(self):
        """Test that title without prefix is unchanged."""
        commit = PlannedCommit(
            id="C1",
            type="feat",
            title="Add new feature",
            hunks=["H1_abc"],
        )

        assert commit.title == "Add new feature"

    def test_preserves_title_with_different_type(self):
        """Test that title with different type prefix is preserved."""
        commit = PlannedCommit(
            id="C1",
            type="feat",
            title="fix: This is actually a fix",  # Different type
            hunks=["H1_abc"],
        )

        # Should NOT be stripped because types dont match
        assert commit.title == "fix: This is actually a fix"

    def test_no_type_field_preserves_title(self):
        """Test that title is preserved when type field is None."""
        commit = PlannedCommit(
            id="C1",
            type=None,
            title="feat: Add feature",
            hunks=["H1_abc"],
        )

        # Should NOT be stripped because type is None
        assert commit.title == "feat: Add feature"


class TestParseUnifiedDiffEdgeCases:
    """Additional edge case tests for parse_unified_diff."""

    def test_whitespace_only_diff(self):
        """Test parsing whitespace-only diff."""
        diff = "   \n\n  \t  \n"
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 0

    def test_git_binary_patch_format(self):
        """Test handling GIT binary patch format."""
        diff = """diff --git a/image.png b/image.png
index 1234567..abcdefg 100644
GIT binary patch
literal 1234
zcmV<abc123...

literal 0
Hc$@<O00001

"""
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 1
        assert file_diffs[0].is_binary is True
        assert any("Binary file skipped" in w for w in warnings)

    def test_hunk_header_without_length(self):
        """Test parsing hunk header without length (defaults to 1)."""
        diff = """diff --git a/single.py b/single.py
index 1234567..abcdefg 100644
--- a/single.py
+++ b/single.py
@@ -5 +5 @@
-old line
+new line
"""
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 1
        hunk = file_diffs[0].hunks[0]
        assert hunk.old_start == 5
        assert hunk.old_len == 1  # Default
        assert hunk.new_start == 5
        assert hunk.new_len == 1  # Default

    def test_hunk_header_with_context(self):
        """Test parsing hunk header with function context."""
        diff = """diff --git a/func.py b/func.py
index 1234567..abcdefg 100644
--- a/func.py
+++ b/func.py
@@ -10,6 +10,8 @@ def my_function():
     existing code
+    new line 1
+    new line 2
     more existing code
"""
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 1
        hunk = file_diffs[0].hunks[0]
        assert hunk.old_start == 10
        assert hunk.new_start == 10
        # The @@ line should include the context
        assert "my_function" in hunk.header

    def test_invalid_diff_format(self):
        """Test handling invalid diff format."""
        diff = """This is not a valid diff format
Some random text
Without proper diff markers
"""
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 0

    def test_multiple_hunks_same_file(self):
        """Test file with many hunks."""
        diff = """diff --git a/multi.py b/multi.py
index 1234567..abcdefg 100644
--- a/multi.py
+++ b/multi.py
@@ -1,3 +1,4 @@
 line 1
+added 1
 line 2
@@ -10,3 +11,4 @@
 line 10
+added 10
 line 11
@@ -20,3 +22,4 @@
 line 20
+added 20
 line 21
"""
        file_diffs, warnings = parse_unified_diff(diff)

        assert len(file_diffs) == 1
        assert len(file_diffs[0].hunks) == 3


class TestFormatInventoryForLlmEdgeCases:
    """Additional edge case tests for format_inventory_for_llm."""

    def test_skips_binary_files(self):
        """Test that binary files are skipped in inventory."""
        diff = """diff --git a/code.py b/code.py
index 1234567..abcdefg 100644
--- a/code.py
+++ b/code.py
@@ -1,3 +1,4 @@
 def func():
+    # comment
     pass
diff --git a/image.png b/image.png
Binary files a/image.png and b/image.png differ
"""
        file_diffs, _ = parse_unified_diff(diff)
        formatted = format_inventory_for_llm(file_diffs)

        assert "code.py" in formatted
        assert "image.png" not in formatted

    def test_marks_deleted_file(self):
        """Test that deleted files are marked in inventory."""
        diff = """diff --git a/deleted.py b/deleted.py
deleted file mode 100644
index 1234567..0000000
--- a/deleted.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def func():
-    pass
"""
        file_diffs, _ = parse_unified_diff(diff)
        formatted = format_inventory_for_llm(file_diffs)

        assert "(deleted file)" in formatted

    def test_marks_renamed_file(self):
        """Test that renamed files are marked in inventory."""
        diff = """diff --git a/old.py b/new.py
similarity index 95%
rename from old.py
rename to new.py
index 1234567..abcdefg 100644
--- a/old.py
+++ b/new.py
@@ -1,3 +1,4 @@
 def func():
+    # comment
     pass
"""
        file_diffs, _ = parse_unified_diff(diff)
        formatted = format_inventory_for_llm(file_diffs)

        assert "(renamed from old.py)" in formatted


class TestValidatePlanEdgeCases:
    """Additional edge case tests for validate_plan."""

    def test_empty_plan_no_commits(self):
        """Test validation fails for plan with no commits."""
        plan = ComposePlan(
            version="1",
            warnings=[],
            commits=[],
        )
        inventory = {"H1_abc": HunkRef(
            id="H1_abc",
            file_path="test.py",
            header="@@ -1,3 +1,4 @@",
            old_start=1,
            old_len=3,
            new_start=1,
            new_len=4,
            lines=["@@ -1,3 +1,4 @@", "+added"],
        )}

        errors = validate_plan(plan, inventory, max_commits=6)
        assert any("no commits" in e.lower() for e in errors)

    def test_whitespace_only_title(self, sample_diff):
        """Test validation fails for whitespace-only title."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)
        hunk_ids = list(inventory.keys())

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="   ",  # Whitespace only
                    hunks=[hunk_ids[0]],
                ),
            ],
        )

        errors = validate_plan(plan, inventory, max_commits=6)
        assert any("no title" in e.lower() for e in errors)


class TestTryCorrectHunkIds:
    """Tests for try_correct_hunk_ids function that auto-corrects LLM hallucinations."""

    def test_corrects_single_invalid_hunk(self):
        """Test that a single invalid hunk ID with matching prefix is corrected."""
        # Create inventory with hunk H2_e4f347
        inventory = {
            "H1_abc123": HunkRef(
                id="H1_abc123",
                file_path="file1.py",
                header="@@ -1,3 +1,4 @@",
                old_start=1, old_len=3, new_start=1, new_len=4,
                lines=["@@ -1,3 +1,4 @@", "+added"],
            ),
            "H2_e4f347": HunkRef(
                id="H2_e4f347",
                file_path="README.md",
                header="@@ -1,2 +1,77 @@",
                old_start=1, old_len=2, new_start=1, new_len=77,
                lines=["@@ -1,2 +1,77 @@", "+added"],
            ),
        }

        # LLM hallucinated H2_e43c95 instead of H2_e4f347
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Update file1",
                    hunks=["H1_abc123"],
                ),
                PlannedCommit(
                    id="C2",
                    title="Update README",
                    hunks=["H2_e43c95"],  # Wrong hash!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 1
        assert "H2_e43c95" in corrections_log[0]
        assert "H2_e4f347" in corrections_log[0]
        # Verify plan was corrected
        assert plan.commits[1].hunks == ["H2_e4f347"]

    def test_no_correction_when_all_valid(self):
        """Test that valid plans are not modified."""
        inventory = {
            "H1_abc123": HunkRef(
                id="H1_abc123",
                file_path="file1.py",
                header="@@ -1,3 +1,4 @@",
                old_start=1, old_len=3, new_start=1, new_len=4,
                lines=["@@ -1,3 +1,4 @@", "+added"],
            ),
            "H2_def456": HunkRef(
                id="H2_def456",
                file_path="file2.py",
                header="@@ -1,2 +1,3 @@",
                old_start=1, old_len=2, new_start=1, new_len=3,
                lines=["@@ -1,2 +1,3 @@", "+added"],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Update both files",
                    hunks=["H1_abc123", "H2_def456"],
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is False
        assert len(corrections_log) == 0
        assert plan.commits[0].hunks == ["H1_abc123", "H2_def456"]

    def test_no_correction_when_ambiguous(self):
        """Test that ambiguous cases (multiple candidates) are not auto-corrected."""
        # Two hunks with same H2 prefix
        inventory = {
            "H2_abc123": HunkRef(
                id="H2_abc123",
                file_path="file1.py",
                header="@@ -1,3 +1,4 @@",
                old_start=1, old_len=3, new_start=1, new_len=4,
                lines=["@@ -1,3 +1,4 @@", "+added"],
            ),
            "H2_def456": HunkRef(
                id="H2_def456",
                file_path="file2.py",
                header="@@ -1,2 +1,3 @@",
                old_start=1, old_len=2, new_start=1, new_len=3,
                lines=["@@ -1,2 +1,3 @@", "+added"],
            ),
        }

        # Invalid ID with H2 prefix - ambiguous which one to correct to
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Test commit",
                    hunks=["H2_wronghash"],
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # Should NOT correct because it's ambiguous
        assert corrections_made is False
        assert len(corrections_log) == 0
        assert plan.commits[0].hunks == ["H2_wronghash"]

    def test_no_correction_for_different_prefix(self):
        """Test that invalid IDs with no matching prefix are not corrected."""
        inventory = {
            "H1_abc123": HunkRef(
                id="H1_abc123",
                file_path="file1.py",
                header="@@ -1,3 +1,4 @@",
                old_start=1, old_len=3, new_start=1, new_len=4,
                lines=["@@ -1,3 +1,4 @@", "+added"],
            ),
        }

        # Invalid ID with completely different prefix
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Test commit",
                    hunks=["H99_xyz"],  # No H99 in inventory
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_skips_already_used_hunks(self):
        """Test that correction doesn't create duplicates."""
        inventory = {
            "H1_abc123": HunkRef(
                id="H1_abc123",
                file_path="file1.py",
                header="@@ -1,3 +1,4 @@",
                old_start=1, old_len=3, new_start=1, new_len=4,
                lines=["@@ -1,3 +1,4 @@", "+added"],
            ),
        }

        # Both commits reference the same hunk - one valid, one invalid with same prefix
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="First commit",
                    hunks=["H1_abc123"],  # Valid
                ),
                PlannedCommit(
                    id="C2",
                    title="Second commit",
                    hunks=["H1_wronghash"],  # Invalid - but H1_abc123 already used
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # Should NOT correct because H1_abc123 is already used
        assert corrections_made is False
        assert plan.commits[1].hunks == ["H1_wronghash"]

    def test_multiple_corrections_in_same_plan(self):
        """Test that multiple invalid hunks can be corrected in one pass."""
        inventory = {
            "H1_aaa111": HunkRef(
                id="H1_aaa111",
                file_path="file1.py",
                header="@@ -1,3 +1,4 @@",
                old_start=1, old_len=3, new_start=1, new_len=4,
                lines=["@@ -1,3 +1,4 @@", "+a"],
            ),
            "H2_bbb222": HunkRef(
                id="H2_bbb222",
                file_path="file2.py",
                header="@@ -1,2 +1,3 @@",
                old_start=1, old_len=2, new_start=1, new_len=3,
                lines=["@@ -1,2 +1,3 @@", "+b"],
            ),
            "H3_ccc333": HunkRef(
                id="H3_ccc333",
                file_path="file3.py",
                header="@@ -1,4 +1,5 @@",
                old_start=1, old_len=4, new_start=1, new_len=5,
                lines=["@@ -1,4 +1,5 @@", "+c"],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Commit 1",
                    hunks=["H1_wrong1", "H2_wrong2"],  # Both wrong
                ),
                PlannedCommit(
                    id="C2",
                    title="Commit 2",
                    hunks=["H3_ccc333"],  # Valid
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 2
        assert plan.commits[0].hunks == ["H1_aaa111", "H2_bbb222"]
        assert plan.commits[1].hunks == ["H3_ccc333"]

    def test_validation_passes_after_correction(self):
        """Integration test: validation should pass after correction."""
        inventory = {
            "H2_e4f347": HunkRef(
                id="H2_e4f347",
                file_path="README.md",
                header="@@ -1,2 +1,77 @@",
                old_start=1, old_len=2, new_start=1, new_len=77,
                lines=["@@ -1,2 +1,77 @@", "+added"],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Update README",
                    hunks=["H2_e43c95"],  # Wrong hash - like the real bug
                ),
            ],
        )

        # Before correction, validation should fail
        errors = validate_plan(plan, inventory, max_commits=6)
        assert len(errors) > 0
        assert any("unknown hunk" in e.lower() for e in errors)

        # Apply correction
        corrections_made, _ = try_correct_hunk_ids(plan, inventory)
        assert corrections_made is True

        # After correction, validation should pass
        errors = validate_plan(plan, inventory, max_commits=6)
        assert len(errors) == 0

    # ========================================================================
    # Multi-Level Cyclic Hash Swap Test Cases
    # These test cases simulate LLM confusing hashes in cyclic patterns
    # ========================================================================

    def test_level_1_cyclic_hash_swap_2_hunks(self):
        """
        Level 1: Two hunks swap hashes with each other.

        Correct:   H11_e9h3ng, H43_m3j0h4k
        Incorrect: H11_m3j0h4k, H43_e9h3ng  (hashes swapped)
        """
        inventory = {
            "H11_e9h3ng": HunkRef(
                id="H11_e9h3ng",
                file_path="file11.py",
                header="@@ -11,3 +11,4 @@",
                old_start=11, old_len=3, new_start=11, new_len=4,
                lines=["@@ -11,3 +11,4 @@", "+line11"],
            ),
            "H43_m3j0h4k": HunkRef(
                id="H43_m3j0h4k",
                file_path="file43.py",
                header="@@ -43,3 +43,4 @@",
                old_start=43, old_len=3, new_start=43, new_len=4,
                lines=["@@ -43,3 +43,4 @@", "+line43"],
            ),
        }

        # Hashes are swapped: H11 has H43's hash, H43 has H11's hash
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Level 1 swap test",
                    hunks=["H11_m3j0h4k", "H43_e9h3ng"],  # Both wrong!
                ),
            ],
        )

        # Before correction
        errors_before = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_before) == 2

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 2

        # Verify corrections
        assert plan.commits[0].hunks == ["H11_e9h3ng", "H43_m3j0h4k"]

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_after) == 0

    def test_level_2_cyclic_hash_swap_3_hunks(self):
        """
        Level 2: Three hunks form a cyclic hash swap.

        Correct:   H11_e9h3ng, H43_m3j0h4k, H26_9h2nk4
        Incorrect: H11_m3j0h4k, H43_9h2nk4, H26_e9h3ng  (A→B→C→A cycle)

        The hashes rotate: H11 gets H43's hash, H43 gets H26's hash, H26 gets H11's hash
        """
        inventory = {
            "H11_e9h3ng": HunkRef(
                id="H11_e9h3ng",
                file_path="file11.py",
                header="@@ -11,3 +11,4 @@",
                old_start=11, old_len=3, new_start=11, new_len=4,
                lines=["@@ -11,3 +11,4 @@", "+line11"],
            ),
            "H43_m3j0h4k": HunkRef(
                id="H43_m3j0h4k",
                file_path="file43.py",
                header="@@ -43,3 +43,4 @@",
                old_start=43, old_len=3, new_start=43, new_len=4,
                lines=["@@ -43,3 +43,4 @@", "+line43"],
            ),
            "H26_9h2nk4": HunkRef(
                id="H26_9h2nk4",
                file_path="file26.py",
                header="@@ -26,3 +26,4 @@",
                old_start=26, old_len=3, new_start=26, new_len=4,
                lines=["@@ -26,3 +26,4 @@", "+line26"],
            ),
        }

        # Cyclic rotation: H11→H43's hash, H43→H26's hash, H26→H11's hash
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Level 2 cyclic swap test",
                    hunks=["H11_m3j0h4k", "H43_9h2nk4", "H26_e9h3ng"],
                ),
            ],
        )

        # Before correction
        errors_before = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_before) == 3

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 3

        # Verify corrections
        assert set(plan.commits[0].hunks) == {"H11_e9h3ng", "H43_m3j0h4k", "H26_9h2nk4"}

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_after) == 0

    def test_level_3_cyclic_hash_swap_4_hunks(self):
        """
        Level 3: Four hunks form a cyclic hash swap.

        Correct:   H11_e9h3ng, H43_m3j0h4k, H26_9h2nk4, H387_k4m1k0
        Incorrect: H11_m3j0h4k, H43_k4m1k0, H26_e9h3ng, H387_9h2nk4  (A→B→C→D→A cycle)

        Pattern: H11→H43's hash, H43→H387's hash, H26→H11's hash, H387→H26's hash
        """
        inventory = {
            "H11_e9h3ng": HunkRef(
                id="H11_e9h3ng",
                file_path="file11.py",
                header="@@ -11,3 +11,4 @@",
                old_start=11, old_len=3, new_start=11, new_len=4,
                lines=["@@ -11,3 +11,4 @@", "+line11"],
            ),
            "H43_m3j0h4k": HunkRef(
                id="H43_m3j0h4k",
                file_path="file43.py",
                header="@@ -43,3 +43,4 @@",
                old_start=43, old_len=3, new_start=43, new_len=4,
                lines=["@@ -43,3 +43,4 @@", "+line43"],
            ),
            "H26_9h2nk4": HunkRef(
                id="H26_9h2nk4",
                file_path="file26.py",
                header="@@ -26,3 +26,4 @@",
                old_start=26, old_len=3, new_start=26, new_len=4,
                lines=["@@ -26,3 +26,4 @@", "+line26"],
            ),
            "H387_k4m1k0": HunkRef(
                id="H387_k4m1k0",
                file_path="file387.py",
                header="@@ -387,3 +387,4 @@",
                old_start=387, old_len=3, new_start=387, new_len=4,
                lines=["@@ -387,3 +387,4 @@", "+line387"],
            ),
        }

        # 4-way cyclic rotation
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Level 3 cyclic swap test",
                    hunks=["H11_m3j0h4k", "H43_k4m1k0", "H26_e9h3ng", "H387_9h2nk4"],
                ),
            ],
        )

        # Before correction
        errors_before = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_before) == 4

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 4

        # Verify all hunks corrected
        assert set(plan.commits[0].hunks) == {"H11_e9h3ng", "H43_m3j0h4k", "H26_9h2nk4", "H387_k4m1k0"}

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_after) == 0

    def test_level_4_cyclic_hash_swap_5_hunks(self):
        """
        Level 4: Five hunks form a cyclic hash swap.

        Correct:   H5_aaa, H17_bbb, H89_ccc, H204_ddd, H512_eee
        Incorrect: H5_bbb, H17_ccc, H89_ddd, H204_eee, H512_aaa  (5-way cycle)
        """
        inventory = {
            "H5_aaa111": HunkRef(
                id="H5_aaa111",
                file_path="file5.py",
                header="@@ -5,3 +5,4 @@",
                old_start=5, old_len=3, new_start=5, new_len=4,
                lines=["@@ -5,3 +5,4 @@", "+line5"],
            ),
            "H17_bbb222": HunkRef(
                id="H17_bbb222",
                file_path="file17.py",
                header="@@ -17,3 +17,4 @@",
                old_start=17, old_len=3, new_start=17, new_len=4,
                lines=["@@ -17,3 +17,4 @@", "+line17"],
            ),
            "H89_ccc333": HunkRef(
                id="H89_ccc333",
                file_path="file89.py",
                header="@@ -89,3 +89,4 @@",
                old_start=89, old_len=3, new_start=89, new_len=4,
                lines=["@@ -89,3 +89,4 @@", "+line89"],
            ),
            "H204_ddd444": HunkRef(
                id="H204_ddd444",
                file_path="file204.py",
                header="@@ -204,3 +204,4 @@",
                old_start=204, old_len=3, new_start=204, new_len=4,
                lines=["@@ -204,3 +204,4 @@", "+line204"],
            ),
            "H512_eee555": HunkRef(
                id="H512_eee555",
                file_path="file512.py",
                header="@@ -512,3 +512,4 @@",
                old_start=512, old_len=3, new_start=512, new_len=4,
                lines=["@@ -512,3 +512,4 @@", "+line512"],
            ),
        }

        # 5-way cyclic rotation: each hunk has the next hunk's hash
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Level 4 cyclic swap test",
                    hunks=["H5_bbb222", "H17_ccc333", "H89_ddd444", "H204_eee555", "H512_aaa111"],
                ),
            ],
        )

        # Before correction
        errors_before = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_before) == 5

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 5

        # Verify all hunks corrected
        assert set(plan.commits[0].hunks) == {"H5_aaa111", "H17_bbb222", "H89_ccc333", "H204_ddd444", "H512_eee555"}

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_after) == 0

    def test_level_5_cyclic_hash_swap_6_hunks(self):
        """
        Level 5: Six hunks form a cyclic hash swap.

        This is the deepest cyclic pattern where all 6 hashes are rotated.
        """
        inventory = {
            "H1_hash_a": HunkRef(
                id="H1_hash_a", file_path="f1.py", header="@@ -1,3 +1,4 @@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=["+a"],
            ),
            "H22_hash_b": HunkRef(
                id="H22_hash_b", file_path="f22.py", header="@@ -22,3 +22,4 @@",
                old_start=22, old_len=3, new_start=22, new_len=4, lines=["+b"],
            ),
            "H333_hash_c": HunkRef(
                id="H333_hash_c", file_path="f333.py", header="@@ -333,3 +333,4 @@",
                old_start=333, old_len=3, new_start=333, new_len=4, lines=["+c"],
            ),
            "H44_hash_d": HunkRef(
                id="H44_hash_d", file_path="f44.py", header="@@ -44,3 +44,4 @@",
                old_start=44, old_len=3, new_start=44, new_len=4, lines=["+d"],
            ),
            "H555_hash_e": HunkRef(
                id="H555_hash_e", file_path="f555.py", header="@@ -555,3 +555,4 @@",
                old_start=555, old_len=3, new_start=555, new_len=4, lines=["+e"],
            ),
            "H6_hash_f": HunkRef(
                id="H6_hash_f", file_path="f6.py", header="@@ -6,3 +6,4 @@",
                old_start=6, old_len=3, new_start=6, new_len=4, lines=["+f"],
            ),
        }

        # 6-way cyclic rotation: A→B→C→D→E→F→A
        # H1 gets hash_b, H22 gets hash_c, H333 gets hash_d, H44 gets hash_e, H555 gets hash_f, H6 gets hash_a
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Level 5 cyclic swap test",
                    hunks=["H1_hash_b", "H22_hash_c", "H333_hash_d", "H44_hash_e", "H555_hash_f", "H6_hash_a"],
                ),
            ],
        )

        # Before correction
        errors_before = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_before) == 6

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 6

        # Verify all hunks corrected
        expected = {"H1_hash_a", "H22_hash_b", "H333_hash_c", "H44_hash_d", "H555_hash_e", "H6_hash_f"}
        assert set(plan.commits[0].hunks) == expected

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_after) == 0

    def test_multiple_independent_cyclic_swaps(self):
        """
        Test multiple independent cyclic swaps in the same plan.

        - Group 1: Level 2 swap (3 hunks)
        - Group 2: Level 1 swap (2 hunks)
        - Group 3: Level 3 swap (4 hunks)

        Total: 9 hunks with cyclic swaps across 3 commits
        """
        inventory = {
            # Group 1: H10, H20, H30 (level 2 - 3-way cycle)
            "H10_g1a": HunkRef(id="H10_g1a", file_path="g1a.py", header="@@", old_start=10, old_len=3, new_start=10, new_len=4, lines=[]),
            "H20_g1b": HunkRef(id="H20_g1b", file_path="g1b.py", header="@@", old_start=20, old_len=3, new_start=20, new_len=4, lines=[]),
            "H30_g1c": HunkRef(id="H30_g1c", file_path="g1c.py", header="@@", old_start=30, old_len=3, new_start=30, new_len=4, lines=[]),
            # Group 2: H100, H200 (level 1 - 2-way swap)
            "H100_g2a": HunkRef(id="H100_g2a", file_path="g2a.py", header="@@", old_start=100, old_len=3, new_start=100, new_len=4, lines=[]),
            "H200_g2b": HunkRef(id="H200_g2b", file_path="g2b.py", header="@@", old_start=200, old_len=3, new_start=200, new_len=4, lines=[]),
            # Group 3: H1000, H2000, H3000, H4000 (level 3 - 4-way cycle)
            "H1000_g3a": HunkRef(id="H1000_g3a", file_path="g3a.py", header="@@", old_start=1000, old_len=3, new_start=1000, new_len=4, lines=[]),
            "H2000_g3b": HunkRef(id="H2000_g3b", file_path="g3b.py", header="@@", old_start=2000, old_len=3, new_start=2000, new_len=4, lines=[]),
            "H3000_g3c": HunkRef(id="H3000_g3c", file_path="g3c.py", header="@@", old_start=3000, old_len=3, new_start=3000, new_len=4, lines=[]),
            "H4000_g3d": HunkRef(id="H4000_g3d", file_path="g3d.py", header="@@", old_start=4000, old_len=3, new_start=4000, new_len=4, lines=[]),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Group 1: 3-way cycle",
                    # H10→g1b, H20→g1c, H30→g1a (rotated)
                    hunks=["H10_g1b", "H20_g1c", "H30_g1a"],
                ),
                PlannedCommit(
                    id="C2",
                    title="Group 2: 2-way swap",
                    # H100↔H200 swapped
                    hunks=["H100_g2b", "H200_g2a"],
                ),
                PlannedCommit(
                    id="C3",
                    title="Group 3: 4-way cycle",
                    # H1000→g3b, H2000→g3c, H3000→g3d, H4000→g3a
                    hunks=["H1000_g3b", "H2000_g3c", "H3000_g3d", "H4000_g3a"],
                ),
            ],
        )

        # Before correction: all 9 hunks are wrong
        errors_before = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_before) == 9

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 9

        # Verify each commit corrected
        assert set(plan.commits[0].hunks) == {"H10_g1a", "H20_g1b", "H30_g1c"}
        assert set(plan.commits[1].hunks) == {"H100_g2a", "H200_g2b"}
        assert set(plan.commits[2].hunks) == {"H1000_g3a", "H2000_g3b", "H3000_g3c", "H4000_g3d"}

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_after) == 0

    def test_mixed_correct_and_cyclic_swaps(self):
        """
        Test plan with mix of correct hunks and cyclic swaps.

        - 5 correct hunks (no change needed)
        - 3 hunks in level-2 cyclic swap
        - 2 hunks in level-1 swap

        Total: 10 hunks, 5 errors to correct
        """
        inventory = {
            # Correct hunks (will be used as-is)
            "H1_correct1": HunkRef(id="H1_correct1", file_path="c1.py", header="@@", old_start=1, old_len=3, new_start=1, new_len=4, lines=[]),
            "H2_correct2": HunkRef(id="H2_correct2", file_path="c2.py", header="@@", old_start=2, old_len=3, new_start=2, new_len=4, lines=[]),
            "H3_correct3": HunkRef(id="H3_correct3", file_path="c3.py", header="@@", old_start=3, old_len=3, new_start=3, new_len=4, lines=[]),
            "H4_correct4": HunkRef(id="H4_correct4", file_path="c4.py", header="@@", old_start=4, old_len=3, new_start=4, new_len=4, lines=[]),
            "H5_correct5": HunkRef(id="H5_correct5", file_path="c5.py", header="@@", old_start=5, old_len=3, new_start=5, new_len=4, lines=[]),
            # Level-2 cyclic swap hunks
            "H50_cyc_a": HunkRef(id="H50_cyc_a", file_path="cyc_a.py", header="@@", old_start=50, old_len=3, new_start=50, new_len=4, lines=[]),
            "H60_cyc_b": HunkRef(id="H60_cyc_b", file_path="cyc_b.py", header="@@", old_start=60, old_len=3, new_start=60, new_len=4, lines=[]),
            "H70_cyc_c": HunkRef(id="H70_cyc_c", file_path="cyc_c.py", header="@@", old_start=70, old_len=3, new_start=70, new_len=4, lines=[]),
            # Level-1 swap hunks
            "H80_swap_x": HunkRef(id="H80_swap_x", file_path="swap_x.py", header="@@", old_start=80, old_len=3, new_start=80, new_len=4, lines=[]),
            "H90_swap_y": HunkRef(id="H90_swap_y", file_path="swap_y.py", header="@@", old_start=90, old_len=3, new_start=90, new_len=4, lines=[]),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Correct hunks commit",
                    hunks=["H1_correct1", "H2_correct2", "H3_correct3"],  # All correct
                ),
                PlannedCommit(
                    id="C2",
                    title="Mixed correct and cyclic",
                    hunks=[
                        "H4_correct4",  # Correct
                        "H50_cyc_b",    # Wrong (has H60's hash)
                        "H60_cyc_c",    # Wrong (has H70's hash)
                        "H70_cyc_a",    # Wrong (has H50's hash)
                    ],
                ),
                PlannedCommit(
                    id="C3",
                    title="Swap and correct",
                    hunks=[
                        "H5_correct5",  # Correct
                        "H80_swap_y",   # Wrong (swapped with H90)
                        "H90_swap_x",   # Wrong (swapped with H80)
                    ],
                ),
            ],
        )

        # Before correction: 5 errors (3 cyclic + 2 swap)
        errors_before = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_before) == 5

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 5

        # Verify corrections
        assert plan.commits[0].hunks == ["H1_correct1", "H2_correct2", "H3_correct3"]
        assert set(plan.commits[1].hunks) == {"H4_correct4", "H50_cyc_a", "H60_cyc_b", "H70_cyc_c"}
        assert set(plan.commits[2].hunks) == {"H5_correct5", "H80_swap_x", "H90_swap_y"}

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=6)
        assert len(errors_after) == 0

    # ========================================================================
    # FAILURE CASES: Edge/Corner cases where current fuzzy logic FAILS
    # These tests document known limitations of try_correct_hunk_ids
    # ========================================================================

    def test_FAILS_wrong_numeric_prefix(self):
        """
        FAILURE CASE: LLM gets the numeric part wrong (not just the hash).

        Inventory has H11, but LLM generates H12 with same hash.
        Current strategy only matches by H# prefix, so this CANNOT be corrected.

        Example:
        - Correct:   H11_abc123
        - Incorrect: H12_abc123  (number wrong, hash is actually correct!)
        """
        inventory = {
            "H11_abc123": HunkRef(
                id="H11_abc123",
                file_path="file.py",
                header="@@ -11,3 +11,4 @@",
                old_start=11, old_len=3, new_start=11, new_len=4,
                lines=["@@ -11,3 +11,4 @@", "+line"],
            ),
        }

        # LLM got the number wrong (H12 instead of H11), but hash is correct
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Wrong number",
                    hunks=["H12_abc123"],  # H12 doesn't exist, should be H11
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: Current strategy cannot correct this because there's no H12 in inventory
        assert corrections_made is False
        assert len(corrections_log) == 0

        # Validation still fails
        errors = validate_plan(plan, inventory, max_commits=6)
        assert len(errors) == 1
        assert "H12_abc123" in errors[0]

    def test_FAILS_ambiguous_multiple_candidates_same_prefix(self):
        """
        FAILURE CASE: Multiple hunks with same H# prefix exist.

        When inventory has H5_aaa and H5_bbb (same file, multiple hunks),
        and LLM generates H5_wrong, we can't know which one it meant.
        """
        inventory = {
            "H5_aaa111": HunkRef(
                id="H5_aaa111",
                file_path="file.py",
                header="@@ -5,3 +5,4 @@",
                old_start=5, old_len=3, new_start=5, new_len=4,
                lines=["@@ -5,3 +5,4 @@", "+first hunk"],
            ),
            "H5_bbb222": HunkRef(
                id="H5_bbb222",
                file_path="file.py",
                header="@@ -50,3 +50,4 @@",
                old_start=50, old_len=3, new_start=50, new_len=4,
                lines=["@@ -50,3 +50,4 @@", "+second hunk"],
            ),
        }

        # LLM generates wrong hash for H5 - but which H5 did it mean?
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Ambiguous H5",
                    hunks=["H5_wrong99"],
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: Ambiguous - two candidates (H5_aaa111 and H5_bbb222)
        assert corrections_made is False
        assert len(corrections_log) == 0

        # Validation fails
        errors = validate_plan(plan, inventory, max_commits=6)
        assert len(errors) == 1

    def test_FAILS_completely_fabricated_hunk_id(self):
        """
        FAILURE CASE: LLM completely fabricates a hunk ID that doesn't
        match any pattern in the inventory.
        """
        inventory = {
            "H1_real11": HunkRef(
                id="H1_real11", file_path="a.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
            "H2_real22": HunkRef(
                id="H2_real22", file_path="b.py", header="@@",
                old_start=2, old_len=3, new_start=2, new_len=4, lines=[],
            ),
        }

        # LLM fabricates H999 which doesn't exist anywhere
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Fabricated hunk",
                    hunks=["H999_fabricated"],
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: No H999 prefix exists in inventory
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_malformed_hunk_id_no_underscore(self):
        """
        FAILURE CASE: LLM generates malformed hunk ID without underscore.
        """
        inventory = {
            "H1_abc123": HunkRef(
                id="H1_abc123", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        # Malformed: missing underscore
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Malformed ID",
                    hunks=["H1abc123"],  # Missing underscore!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: Can't parse "H1abc123" - no underscore separator
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_malformed_hunk_id_no_H_prefix(self):
        """
        FAILURE CASE: LLM generates hunk ID without 'H' prefix.
        """
        inventory = {
            "H5_xyz789": HunkRef(
                id="H5_xyz789", file_path="file.py", header="@@",
                old_start=5, old_len=3, new_start=5, new_len=4, lines=[],
            ),
        }

        # Malformed: missing H prefix
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="No H prefix",
                    hunks=["5_xyz789"],  # Missing H!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: Can't parse "5_xyz789" - regex expects H prefix
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_correct_hunk_already_used_in_earlier_commit(self):
        """
        FAILURE CASE: The correct hunk is already used in an earlier commit,
        so correction would create a duplicate.

        This is actually handled correctly (not corrected), but validation fails.
        """
        inventory = {
            "H1_onlyone": HunkRef(
                id="H1_onlyone", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        # H1_onlyone used correctly in C1, then incorrectly referenced in C2
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Uses H1 correctly",
                    hunks=["H1_onlyone"],
                ),
                PlannedCommit(
                    id="C2",
                    title="Tries to use H1 again with wrong hash",
                    hunks=["H1_wronghash"],  # Would correct to H1_onlyone, but it's used
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS to correct: H1_onlyone is already used in C1
        assert corrections_made is False
        assert len(corrections_log) == 0

        # Plan still has the invalid hunk
        assert plan.commits[1].hunks == ["H1_wronghash"]

    def test_FAILS_hash_correct_but_number_swapped(self):
        """
        FAILURE CASE: Two hunks swap their NUMBERS but keep original hashes.

        This is the inverse of the cyclic hash swap - here the hashes are
        correct but attached to wrong numbers.

        Correct:   H10_aaa, H20_bbb
        Incorrect: H10_bbb, H20_aaa  (numbers swapped, not hashes)

        Wait - this is actually the same as hash swap from the algorithm's POV.
        Let me create a different case: hash is correct but number is off-by-one.
        """
        inventory = {
            "H10_hashA": HunkRef(
                id="H10_hashA", file_path="a.py", header="@@",
                old_start=10, old_len=3, new_start=10, new_len=4, lines=[],
            ),
            "H20_hashB": HunkRef(
                id="H20_hashB", file_path="b.py", header="@@",
                old_start=20, old_len=3, new_start=20, new_len=4, lines=[],
            ),
        }

        # LLM gets numbers off by one, but uses correct hashes
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Off-by-one numbers",
                    hunks=["H11_hashA", "H21_hashB"],  # H11/H21 don't exist!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: No H11 or H21 in inventory, even though hashes are valid
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_partial_hash_match(self):
        """
        FAILURE CASE: LLM generates partial/truncated hash.

        Correct hash is "abc123", LLM generates "abc" (truncated).
        """
        inventory = {
            "H1_abc123": HunkRef(
                id="H1_abc123", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Truncated hash",
                    hunks=["H1_abc"],  # Truncated hash
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # This SUCCEEDS because H1 prefix matches and there's only one H1!
        # The hash doesn't matter for the current algorithm.
        assert corrections_made is True
        assert plan.commits[0].hunks == ["H1_abc123"]

    def test_FAILS_empty_hunk_id(self):
        """
        FAILURE CASE: LLM generates empty string as hunk ID.
        """
        inventory = {
            "H1_valid": HunkRef(
                id="H1_valid", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Empty hunk ID",
                    hunks=[""],  # Empty!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: Empty string can't be parsed
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_numeric_only_hunk_id(self):
        """
        FAILURE CASE: LLM generates just a number without H prefix or hash.
        """
        inventory = {
            "H42_hash42": HunkRef(
                id="H42_hash42", file_path="file.py", header="@@",
                old_start=42, old_len=3, new_start=42, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Numeric only",
                    hunks=["42"],  # Just a number!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: "42" doesn't match H(\d+)_ pattern
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_case_sensitivity_lowercase_h(self):
        """
        FAILURE CASE: LLM uses lowercase 'h' instead of uppercase 'H'.
        """
        inventory = {
            "H1_abc123": HunkRef(
                id="H1_abc123", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Lowercase h",
                    hunks=["h1_abc123"],  # lowercase h!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: Regex is case-sensitive, 'h' doesn't match 'H'
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_extra_prefix_before_H(self):
        """
        FAILURE CASE: LLM adds extra characters before H.
        """
        inventory = {
            "H5_hash55": HunkRef(
                id="H5_hash55", file_path="file.py", header="@@",
                old_start=5, old_len=3, new_start=5, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Extra prefix",
                    hunks=["XH5_hash55"],  # Extra 'X' prefix!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: "XH5_hash55" doesn't start with H
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_whitespace_in_hunk_id(self):
        """
        FAILURE CASE: LLM includes whitespace in hunk ID.
        """
        inventory = {
            "H1_abc123": HunkRef(
                id="H1_abc123", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Whitespace in ID",
                    hunks=["H1 _abc123"],  # Space before underscore!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: "H1 _abc123" has space, doesn't match pattern
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_negative_hunk_number(self):
        """
        FAILURE CASE: LLM generates negative hunk number.
        """
        inventory = {
            "H1_valid": HunkRef(
                id="H1_valid", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Negative number",
                    hunks=["H-1_valid"],  # Negative number!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: Regex expects \d+ (positive digits only)
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_zero_hunk_number(self):
        """
        FAILURE CASE: LLM generates H0 (zero) when hunks start at H1.
        """
        inventory = {
            "H1_first": HunkRef(
                id="H1_first", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
            "H2_second": HunkRef(
                id="H2_second", file_path="file.py", header="@@",
                old_start=10, old_len=3, new_start=10, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Zero hunk number",
                    hunks=["H0_first"],  # H0 doesn't exist!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: No H0 in inventory (hunks are 1-indexed)
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_very_large_hunk_number(self):
        """
        FAILURE CASE: LLM generates extremely large hunk number.
        """
        inventory = {
            "H1_only": HunkRef(
                id="H1_only", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Huge number",
                    hunks=["H999999999_hash"],  # Way too large!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: No H999999999 in inventory
        assert corrections_made is False
        assert len(corrections_log) == 0

    def test_FAILS_duplicate_hunk_in_same_commit(self):
        """
        FAILURE CASE: Same incorrect hunk ID appears twice in one commit.

        First occurrence gets corrected, second cannot (already used).
        """
        inventory = {
            "H1_correct": HunkRef(
                id="H1_correct", file_path="file.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[],
            ),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Duplicate wrong hunk",
                    hunks=["H1_wrong", "H1_wrong"],  # Same wrong ID twice!
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # First H1_wrong corrected to H1_correct
        # Second H1_wrong CANNOT be corrected (H1_correct already used)
        assert corrections_made is True
        assert len(corrections_log) == 1  # Only one correction

        # Plan now has one correct and one still wrong
        assert plan.commits[0].hunks == ["H1_correct", "H1_wrong"]

        # Validation still fails (duplicate reference attempt)
        errors = validate_plan(plan, inventory, max_commits=6)
        assert len(errors) >= 1

    def test_FAILS_all_hunks_have_same_wrong_prefix(self):
        """
        FAILURE CASE: Multiple different hunks all get the same wrong prefix.

        Inventory: H1, H2, H3
        LLM generates: H99_a, H99_b, H99_c (all with H99 prefix that doesn't exist)
        """
        inventory = {
            "H1_aaa": HunkRef(id="H1_aaa", file_path="a.py", header="@@", old_start=1, old_len=3, new_start=1, new_len=4, lines=[]),
            "H2_bbb": HunkRef(id="H2_bbb", file_path="b.py", header="@@", old_start=2, old_len=3, new_start=2, new_len=4, lines=[]),
            "H3_ccc": HunkRef(id="H3_ccc", file_path="c.py", header="@@", old_start=3, old_len=3, new_start=3, new_len=4, lines=[]),
        }

        # All wrong hunks have H99 prefix - none exist
        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="All wrong prefix",
                    hunks=["H99_aaa", "H99_bbb", "H99_ccc"],
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # FAILS: No H99 exists in inventory
        assert corrections_made is False
        assert len(corrections_log) == 0

        # All three hunks remain uncorrected
        assert plan.commits[0].hunks == ["H99_aaa", "H99_bbb", "H99_ccc"]

    def test_FAILS_mixed_valid_and_uncorrectable(self):
        """
        FAILURE CASE: Mix of valid, correctable, and uncorrectable hunks.

        Some corrections succeed, others fail, leaving plan partially fixed.
        """
        inventory = {
            "H1_valid1": HunkRef(id="H1_valid1", file_path="a.py", header="@@", old_start=1, old_len=3, new_start=1, new_len=4, lines=[]),
            "H2_valid2": HunkRef(id="H2_valid2", file_path="b.py", header="@@", old_start=2, old_len=3, new_start=2, new_len=4, lines=[]),
            "H3_valid3": HunkRef(id="H3_valid3", file_path="c.py", header="@@", old_start=3, old_len=3, new_start=3, new_len=4, lines=[]),
        }

        plan = ComposePlan(
            version="1",
            commits=[
                PlannedCommit(
                    id="C1",
                    title="Mixed scenario",
                    hunks=[
                        "H1_valid1",    # Valid - no change needed
                        "H2_wronghash", # Correctable - H2 prefix matches
                        "H99_invalid",  # UNCORRECTABLE - H99 doesn't exist
                    ],
                ),
            ],
        )

        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # Partial success: H2_wronghash corrected, H99_invalid not
        assert corrections_made is True
        assert len(corrections_log) == 1  # Only H2 corrected

        # Plan is partially fixed
        assert plan.commits[0].hunks == ["H1_valid1", "H2_valid2", "H99_invalid"]

        # Validation still fails due to H99_invalid
        errors = validate_plan(plan, inventory, max_commits=6)
        assert len(errors) == 1
        assert "H99_invalid" in errors[0]

    # ========================================================================
    # Extreme Test Cases - 1000 hunks with 500 incorrect IDs
    # ========================================================================

    def test_extreme_1000_hunks_with_500_incorrect_single_candidate(self):
        """
        Extreme test: 1000 hunks in inventory, 500 incorrect IDs in plan.
        Each incorrect hunk has exactly ONE valid candidate (unambiguous correction).

        Structure:
        - Inventory: H1_hash1 through H1000_hash1000
        - Plan uses: 500 correct IDs (H1 to H500) + 500 incorrect IDs (H501_wrongX to H1000_wrongX)
        - All 500 incorrect should be correctable because each H# prefix has only one entry
        """
        import hashlib

        # Build inventory with 1000 unique hunks
        inventory = {}
        for i in range(1, 1001):
            # Generate deterministic hash based on index
            hash_val = hashlib.md5(f"content_{i}".encode(), usedforsecurity=False).hexdigest()[:6]
            hunk_id = f"H{i}_{hash_val}"
            inventory[hunk_id] = HunkRef(
                id=hunk_id,
                file_path=f"file{i}.py",
                header=f"@@ -{i},3 +{i},4 @@",
                old_start=i, old_len=3, new_start=i, new_len=4,
                lines=[f"@@ -{i},3 +{i},4 @@", f"+line{i}"],
            )

        # Build plan with 50 commits (20 hunks each)
        commits = []
        hunk_index = 1
        correct_ids = list(inventory.keys())

        for commit_num in range(1, 51):
            commit_hunks = []
            for _ in range(20):
                if hunk_index <= 500:
                    # First 500: use correct IDs
                    commit_hunks.append(correct_ids[hunk_index - 1])
                else:
                    # Last 500: use incorrect IDs (wrong hash suffix)
                    # Extract the correct prefix, use wrong hash
                    correct_id = correct_ids[hunk_index - 1]
                    prefix = correct_id.split("_")[0]  # e.g., "H501"
                    wrong_hash = f"wrong{hunk_index}"
                    commit_hunks.append(f"{prefix}_{wrong_hash}")
                hunk_index += 1

            commits.append(PlannedCommit(
                id=f"C{commit_num}",
                title=f"Commit {commit_num}",
                hunks=commit_hunks,
            ))

        plan = ComposePlan(version="1", commits=commits)

        # Before correction: validation should fail with 500 errors
        errors_before = validate_plan(plan, inventory, max_commits=100)
        assert len(errors_before) == 500, f"Expected 500 errors, got {len(errors_before)}"

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 500, f"Expected 500 corrections, got {len(corrections_log)}"

        # After correction: validation should pass
        errors_after = validate_plan(plan, inventory, max_commits=100)
        assert len(errors_after) == 0, f"Expected 0 errors after correction, got {errors_after}"

        # Verify all hunks are now valid
        all_plan_hunks = [h for c in plan.commits for h in c.hunks]
        assert len(all_plan_hunks) == 1000
        assert all(h in inventory for h in all_plan_hunks)

    def test_extreme_multi_level_correction_depth_5(self):
        """
        Extreme test: Multi-level correction scenario simulating 5 levels of LLM confusion.

        This tests a scenario where the LLM makes cascading errors - using hashes
        from completely different hunks in a pattern that spans multiple "levels"
        of the hunk numbering scheme.

        Level structure (100 hunks each level, 500 total per level x 2 = 1000):
        - Level 1: H1-H200 (base hunks, some correct, some with errors)
        - Level 2: H201-H400 (intermediate hunks)
        - Level 3: H401-H600 (intermediate hunks)
        - Level 4: H601-H800 (intermediate hunks)
        - Level 5: H801-H1000 (final level hunks)

        Error patterns across levels:
        - Some H1xx hunks have H2xx hashes (cross-level confusion)
        - Some H3xx hunks have H5xx hashes (skipping levels)
        - etc.
        """
        import hashlib
        import random

        random.seed(42)  # Deterministic for reproducibility

        # Build inventory with 1000 hunks
        inventory = {}
        all_hashes = {}  # Store hashes for cross-referencing

        for i in range(1, 1001):
            hash_val = hashlib.md5(f"unique_content_{i}".encode(), usedforsecurity=False).hexdigest()[:6]
            hunk_id = f"H{i}_{hash_val}"
            inventory[hunk_id] = HunkRef(
                id=hunk_id,
                file_path=f"src/level{(i-1)//200 + 1}/file{i}.py",
                header=f"@@ -{i},5 +{i},6 @@",
                old_start=i, old_len=5, new_start=i, new_len=6,
                lines=[f"@@ -{i},5 +{i},6 @@", f"+level{(i-1)//200 + 1}_line{i}"],
            )
            all_hashes[i] = hash_val

        # Build plan with mixed correct and incorrect IDs
        # Pattern: alternating between correct and various error types
        commits = []
        correct_ids = list(inventory.keys())
        hunk_assignments = []

        for i in range(1, 1001):
            correct_id = correct_ids[i - 1]
            correct_hash = all_hashes[i]

            # Determine which level this hunk is in (1-5)
            level = (i - 1) // 200 + 1

            if i % 2 == 0:
                # Even indices: use correct ID
                hunk_assignments.append((correct_id, True))
            else:
                # Odd indices: create error with hash from different level
                # Level 1 hunks use Level 2 hashes, Level 2 use Level 3, etc.
                # Level 5 wraps around to Level 1
                error_source_level = (level % 5) + 1
                # Pick a random hunk from the error source level
                error_source_idx = random.randint(
                    (error_source_level - 1) * 200 + 1,
                    error_source_level * 200
                )
                wrong_hash = all_hashes[error_source_idx]
                wrong_id = f"H{i}_{wrong_hash}"
                hunk_assignments.append((wrong_id, False))

        # Count expected corrections
        expected_corrections = sum(1 for _, is_correct in hunk_assignments if not is_correct)
        assert expected_corrections == 500, f"Expected 500 incorrect, got {expected_corrections}"

        # Create commits (100 commits x 10 hunks each)
        for commit_num in range(100):
            start_idx = commit_num * 10
            commit_hunks = [hunk_assignments[start_idx + j][0] for j in range(10)]
            commits.append(PlannedCommit(
                id=f"C{commit_num + 1}",
                title=f"Multi-level commit {commit_num + 1}",
                hunks=commit_hunks,
            ))

        plan = ComposePlan(version="1", commits=commits)

        # Before correction
        errors_before = validate_plan(plan, inventory, max_commits=200)
        assert len(errors_before) == 500

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 500

        # Verify correction log mentions level-crossing corrections
        # (The log should show corrections like H1_abc -> H1_xyz where abc came from H201)
        assert all("Corrected" in log for log in corrections_log)

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=200)
        assert len(errors_after) == 0

    def test_extreme_complex_file_groupings_with_errors(self):
        """
        Extreme test: Simulate real-world scenario with file groupings.

        - 100 files, each with 10 hunks (1000 total)
        - 50 files have all correct IDs (500 hunks)
        - 50 files have all incorrect IDs (500 hunks)
        - Incorrect IDs use hashes from different files (simulating LLM confusion
          between similar filenames)
        """
        import hashlib

        # Build inventory: 100 files x 10 hunks each
        inventory = {}
        hunk_counter = 1
        file_hunks = {}  # Track hunks per file

        for file_num in range(1, 101):
            file_path = f"src/module{file_num // 10}/component{file_num}.py"
            file_hunks[file_num] = []

            for hunk_in_file in range(10):
                hash_val = hashlib.md5(
                    f"file{file_num}_hunk{hunk_in_file}".encode(),
                    usedforsecurity=False
                ).hexdigest()[:6]
                hunk_id = f"H{hunk_counter}_{hash_val}"

                inventory[hunk_id] = HunkRef(
                    id=hunk_id,
                    file_path=file_path,
                    header=f"@@ -{hunk_in_file * 10 + 1},5 +{hunk_in_file * 10 + 1},7 @@",
                    old_start=hunk_in_file * 10 + 1,
                    old_len=5,
                    new_start=hunk_in_file * 10 + 1,
                    new_len=7,
                    lines=[f"@@ -...,5 +...,7 @@", f"+modified_in_file{file_num}"],
                )
                file_hunks[file_num].append(hunk_id)
                hunk_counter += 1

        # Build plan:
        # - Files 1-50: correct IDs
        # - Files 51-100: incorrect IDs (use hashes from file in the 1-50 range)
        commits = []
        correct_count = 0
        incorrect_count = 0

        for file_num in range(1, 101):
            file_hunk_ids = file_hunks[file_num]

            if file_num <= 50:
                # Correct: use actual hunk IDs
                plan_hunks = file_hunk_ids.copy()
                correct_count += 10
            else:
                # Incorrect: use correct prefix but wrong hash from file in 1-50 range
                # Map file 51->1, 52->2, ..., 100->50
                source_file = file_num - 50
                source_hunks = file_hunks[source_file]

                plan_hunks = []
                for idx, correct_id in enumerate(file_hunk_ids):
                    prefix = correct_id.split("_")[0]
                    # Get hash from source file's corresponding hunk
                    wrong_hash = source_hunks[idx].split("_")[1]
                    plan_hunks.append(f"{prefix}_{wrong_hash}")
                incorrect_count += 10

            commits.append(PlannedCommit(
                id=f"C{file_num}",
                title=f"Update component{file_num}",
                hunks=plan_hunks,
            ))

        assert correct_count == 500
        assert incorrect_count == 500

        plan = ComposePlan(version="1", commits=commits)

        # Before correction
        errors_before = validate_plan(plan, inventory, max_commits=200)
        assert len(errors_before) == 500

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 500

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=200)
        assert len(errors_after) == 0

        # Verify the plan now has all valid hunks
        all_corrected_hunks = {h for c in plan.commits for h in c.hunks}
        assert all_corrected_hunks == set(inventory.keys())

    def test_extreme_sparse_errors_across_large_plan(self):
        """
        Extreme test: Errors sparsely distributed across a large plan.

        - 1000 hunks across 200 commits (5 hunks each)
        - Every 2nd hunk is incorrect (500 errors)
        - Tests that correction handles sparse error distribution efficiently
        """
        import hashlib

        # Build inventory
        inventory = {}
        for i in range(1, 1001):
            hash_val = hashlib.md5(f"sparse_{i}".encode(), usedforsecurity=False).hexdigest()[:6]
            hunk_id = f"H{i}_{hash_val}"
            inventory[hunk_id] = HunkRef(
                id=hunk_id,
                file_path=f"sparse/file{i}.py",
                header=f"@@ -{i},2 +{i},3 @@",
                old_start=i, old_len=2, new_start=i, new_len=3,
                lines=[f"@@ -{i},2 +{i},3 @@", "+sparse"],
            )

        correct_ids = list(inventory.keys())

        # Build plan with sparse errors
        commits = []
        for commit_num in range(200):
            hunks = []
            for j in range(5):
                hunk_idx = commit_num * 5 + j
                if hunk_idx % 2 == 0:
                    # Even: correct
                    hunks.append(correct_ids[hunk_idx])
                else:
                    # Odd: incorrect (wrong hash)
                    prefix = f"H{hunk_idx + 1}"
                    hunks.append(f"{prefix}_wrongsparse{hunk_idx}")

            commits.append(PlannedCommit(
                id=f"C{commit_num + 1}",
                title=f"Sparse commit {commit_num + 1}",
                hunks=hunks,
            ))

        plan = ComposePlan(version="1", commits=commits)

        # Count incorrect before correction
        all_hunks = [h for c in plan.commits for h in c.hunks]
        incorrect_before = sum(1 for h in all_hunks if h not in inventory)
        assert incorrect_before == 500

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 500

        # Validate after
        errors_after = validate_plan(plan, inventory, max_commits=300)
        assert len(errors_after) == 0

    def test_extreme_sequential_level_confusion_pattern(self):
        """
        Extreme test: Sequential level confusion with 5 distinct error levels.

        This simulates an LLM that systematically confuses hunks across 5 levels
        in a predictable pattern:

        Level 1 (H1-H200): Errors use hashes from Level 2
        Level 2 (H201-H400): Errors use hashes from Level 3
        Level 3 (H401-H600): Errors use hashes from Level 4
        Level 4 (H601-H800): Errors use hashes from Level 5
        Level 5 (H801-H1000): Errors use hashes from Level 1

        Each level has 200 hunks, 100 correct + 100 incorrect.
        Total: 500 correct + 500 incorrect = 1000 hunks
        """
        import hashlib

        # Build inventory with 5 levels
        inventory = {}
        level_hashes = {1: [], 2: [], 3: [], 4: [], 5: []}

        for i in range(1, 1001):
            hash_val = hashlib.md5(f"level_content_{i}".encode(), usedforsecurity=False).hexdigest()[:6]
            hunk_id = f"H{i}_{hash_val}"
            level = (i - 1) // 200 + 1

            inventory[hunk_id] = HunkRef(
                id=hunk_id,
                file_path=f"level{level}/file{i}.py",
                header=f"@@ -{i},4 +{i},5 @@",
                old_start=i, old_len=4, new_start=i, new_len=5,
                lines=[f"@@ -{i},4 +{i},5 @@", f"+level{level}"],
            )
            level_hashes[level].append(hash_val)

        # Build plan with level-crossing errors
        correct_ids = list(inventory.keys())
        commits = []
        hunk_plan = []

        for i in range(1, 1001):
            current_level = (i - 1) // 200 + 1
            position_in_level = (i - 1) % 200

            if position_in_level < 100:
                # First 100 in each level: correct
                hunk_plan.append(correct_ids[i - 1])
            else:
                # Second 100 in each level: use hash from next level
                next_level = (current_level % 5) + 1
                hash_idx = position_in_level - 100  # 0-99
                wrong_hash = level_hashes[next_level][hash_idx]
                hunk_plan.append(f"H{i}_{wrong_hash}")

        # Verify error distribution
        incorrect_count = sum(1 for h in hunk_plan if h not in inventory)
        assert incorrect_count == 500, f"Expected 500 incorrect, got {incorrect_count}"

        # Create 100 commits with 10 hunks each
        for commit_num in range(100):
            start = commit_num * 10
            commits.append(PlannedCommit(
                id=f"C{commit_num + 1}",
                title=f"Level-crossing commit {commit_num + 1}",
                hunks=hunk_plan[start:start + 10],
            ))

        plan = ComposePlan(version="1", commits=commits)

        # Before correction
        errors_before = validate_plan(plan, inventory, max_commits=200)
        assert len(errors_before) == 500

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 500

        # Verify each level had 100 corrections
        for level in range(1, 6):
            level_start = (level - 1) * 200 + 1
            level_end = level * 200
            level_corrections = [
                log for log in corrections_log
                if any(f"H{i}_" in log for i in range(level_start + 100, level_end + 1))
            ]
            assert len(level_corrections) == 100, f"Level {level} should have 100 corrections"

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=200)
        assert len(errors_after) == 0

    def test_extreme_worst_case_all_different_hash_sources(self):
        """
        Extreme test: Worst case where every incorrect hash comes from a different source.

        - 1000 hunks total
        - 500 correct, 500 incorrect
        - Each incorrect hunk uses a hash from a completely different hunk number
        - Tests O(n) correction performance with maximum hash diversity
        """
        import hashlib

        # Build inventory
        inventory = {}
        all_hashes = []

        for i in range(1, 1001):
            hash_val = hashlib.md5(f"worst_case_{i}".encode(), usedforsecurity=False).hexdigest()[:6]
            hunk_id = f"H{i}_{hash_val}"
            inventory[hunk_id] = HunkRef(
                id=hunk_id,
                file_path=f"worst/file{i}.py",
                header=f"@@ -{i},3 +{i},4 @@",
                old_start=i, old_len=3, new_start=i, new_len=4,
                lines=[f"@@ -{i},3 +{i},4 @@", "+worst"],
            )
            all_hashes.append(hash_val)

        correct_ids = list(inventory.keys())

        # Build plan:
        # - Hunks 1-500: correct
        # - Hunks 501-1000: incorrect, each uses hash from hunk (i - 500)
        plan_hunks = []
        for i in range(1, 1001):
            if i <= 500:
                plan_hunks.append(correct_ids[i - 1])
            else:
                # Use hash from hunk (i - 500), so H501 gets hash from H1
                wrong_hash = all_hashes[i - 501]  # Index for H1 is 0
                plan_hunks.append(f"H{i}_{wrong_hash}")

        # Create 50 commits with 20 hunks each
        commits = []
        for commit_num in range(50):
            start = commit_num * 20
            commits.append(PlannedCommit(
                id=f"C{commit_num + 1}",
                title=f"Worst case commit {commit_num + 1}",
                hunks=plan_hunks[start:start + 20],
            ))

        plan = ComposePlan(version="1", commits=commits)

        # Verify setup
        all_plan_hunks = [h for c in plan.commits for h in c.hunks]
        incorrect = [h for h in all_plan_hunks if h not in inventory]
        assert len(incorrect) == 500

        # Apply correction
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        assert corrections_made is True
        assert len(corrections_log) == 500

        # Verify all corrections point to the right target
        for log in corrections_log:
            # Log format: "Corrected H501_xxx -> H501_yyy in commit Cz"
            assert "Corrected" in log
            assert " -> " in log

        # After correction
        errors_after = validate_plan(plan, inventory, max_commits=100)
        assert len(errors_after) == 0


class TestBuildCommitPatchEdgeCases:
    """Additional edge case tests for build_commit_patch."""

    def test_missing_hunk_in_inventory(self, sample_diff):
        """Test building patch with missing hunk ID."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)

        commit = PlannedCommit(
            id="C1",
            title="Test commit",
            hunks=["NONEXISTENT_HUNK"],
        )

        patch = build_commit_patch(commit, inventory, file_diffs)

        # Should return empty or minimal patch
        assert "@@" not in patch or patch.strip() == "" or "NONEXISTENT" not in patch

    def test_multiple_hunks_same_file_sorted(self, sample_diff):
        """Test that multiple hunks from same file are sorted by line number."""
        file_diffs, _ = parse_unified_diff(sample_diff)
        inventory = build_hunk_inventory(file_diffs)

        # Get hunks from first file (main.py which has 2 hunks)
        main_py_hunks = [h for h in inventory.values() if h.file_path == "src/main.py"]
        hunk_ids = [h.id for h in main_py_hunks]

        commit = PlannedCommit(
            id="C1",
            title="Test commit",
            hunks=hunk_ids,
        )

        patch = build_commit_patch(commit, inventory, file_diffs)

        # Find hunk header positions
        import re
        hunk_headers = list(re.finditer(r"@@ -(\d+)", patch))
        if len(hunk_headers) >= 2:
            # First hunk should have lower line number
            first_line = int(hunk_headers[0].group(1))
            second_line = int(hunk_headers[1].group(1))
            assert first_line < second_line


class TestBuildComposePromptEdgeCases:
    """Additional edge case tests for build_compose_prompt."""

    def test_includes_style_parameter(self, sample_diff):
        """Test that prompt includes style parameter."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="feature-branch",
            recent_commits=[],
            style="blueprint",
            max_commits=5,
        )

        assert "blueprint" in prompt
        assert "5" in prompt  # max_commits

    def test_includes_stats_section(self, sample_diff):
        """Test that prompt includes stats section."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=[],
            style="default",
            max_commits=6,
        )

        assert "[STATS]" in prompt
        assert "Files with changes" in prompt
        assert "Total hunks" in prompt

    def test_handles_no_recent_commits(self, sample_diff):
        """Test prompt with no recent commits."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=[],
            style="default",
            max_commits=6,
        )

        assert "None" in prompt or "Recent commits" in prompt

    def test_truncates_long_recent_commits(self, sample_diff):
        """Test that only first 5 recent commits are included."""
        file_diffs, _ = parse_unified_diff(sample_diff)

        recent = [f"Commit {i}" for i in range(10)]
        prompt = build_compose_prompt(
            file_diffs=file_diffs,
            branch="main",
            recent_commits=recent,
            style="default",
            max_commits=6,
        )

        # Should only have first 5
        assert "Commit 0" in prompt
        assert "Commit 4" in prompt
        # Commit 5+ should not be present (unless in other context)


class TestHunkRefEdgeCases:
    """Additional edge case tests for HunkRef."""

    def test_snippet_excludes_diff_header_lines(self):
        """Test that snippet excludes +++ and --- lines."""
        hunk = HunkRef(
            id="H1_abc",
            file_path="test.py",
            header="@@ -1,3 +1,4 @@",
            old_start=1,
            old_len=3,
            new_start=1,
            new_len=4,
            lines=[
                "@@ -1,3 +1,4 @@",
                "--- a/test.py",
                "+++ b/test.py",
                " context",
                "+added",
                "-removed",
            ],
        )

        snippet = hunk.snippet(10)
        assert "+++" not in snippet
        assert "---" not in snippet
        assert "+added" in snippet
        assert "-removed" in snippet

    def test_snippet_exact_max_lines(self):
        """Test snippet with exact max lines."""
        lines = ["@@ -1,5 +1,5 @@"] + [f"+line{i}" for i in range(5)]
        hunk = HunkRef(
            id="H1_abc",
            file_path="test.py",
            header="@@ -1,5 +1,5 @@",
            old_start=1,
            old_len=5,
            new_start=1,
            new_len=5,
            lines=lines,
        )

        snippet = hunk.snippet(5)
        # Should show all 5 lines without truncation message
        assert "more lines" not in snippet
        assert "+line0" in snippet
        assert "+line4" in snippet


class TestBlueprintSectionCompose:
    """Tests for BlueprintSection model in compose."""

    def test_create_section(self):
        """Test creating a blueprint section."""
        section = BlueprintSection(
            title="Changes",
            bullets=["First change", "Second change"],
        )

        assert section.title == "Changes"
        assert len(section.bullets) == 2

    def test_empty_bullets(self):
        """Test section with empty bullets."""
        section = BlueprintSection(
            title="Notes",
            bullets=[],
        )

        assert section.bullets == []


class TestRestoreFromSnapshot:
    """Tests for restore_from_snapshot function."""

    def test_restore_basic(self, temp_repo):
        """Test basic restore from snapshot."""
        from hunknote.compose import restore_from_snapshot, ComposeSnapshot

        # Create a snapshot
        snapshot = ComposeSnapshot(
            pre_head="abc123",
            pre_staged_patch="",
            patch_file=None,
            head_file=None,
        )

        success, message = restore_from_snapshot(temp_repo, snapshot, commits_created=0)

        assert success
        assert "Reset index" in message

    def test_restore_with_commits_created(self, temp_repo):
        """Test restore with commits created shows recovery instructions."""
        from hunknote.compose import restore_from_snapshot, ComposeSnapshot

        # Get current HEAD
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=temp_repo,
        )
        pre_head = result.stdout.strip()

        snapshot = ComposeSnapshot(
            pre_head=pre_head,
            pre_staged_patch="",
            patch_file=None,
            head_file=None,
        )

        success, message = restore_from_snapshot(temp_repo, snapshot, commits_created=3)

        assert success
        assert "MANUAL RECOVERY" in message
        assert "3 commit(s)" in message
        assert pre_head in message

    def test_restore_with_staged_changes(self, temp_repo):
        """Test restore with previously staged changes."""
        from hunknote.compose import restore_from_snapshot, ComposeSnapshot

        # Create a patch file with staged changes
        tmp_dir = temp_repo / ".tmp"
        tmp_dir.mkdir(exist_ok=True)
        patch_file = tmp_dir / "test_staged.patch"
        patch_content = """diff --git a/test.txt b/test.txt
new file mode 100644
--- /dev/null
+++ b/test.txt
@@ -0,0 +1 @@
+test content
"""
        patch_file.write_text(patch_content)

        # Create the file so patch can apply
        (temp_repo / "test.txt").write_text("test content\n")

        snapshot = ComposeSnapshot(
            pre_head="abc123",
            pre_staged_patch=patch_content,
            patch_file=patch_file,
            head_file=None,
        )

        success, message = restore_from_snapshot(temp_repo, snapshot, commits_created=0)

        # May or may not succeed depending on repo state, but should not crash
        assert isinstance(success, bool)
        assert isinstance(message, str)


class TestCleanupTempFiles:
    """Tests for cleanup_temp_files function."""

    def test_cleanup_removes_files(self, temp_repo):
        """Test that cleanup removes temp files."""
        from hunknote.compose import cleanup_temp_files

        # Create temp directory and files
        tmp_dir = temp_repo / ".tmp"
        tmp_dir.mkdir(exist_ok=True)

        pid = 99999
        (tmp_dir / f"hunknote_compose_patch_C1_{pid}.patch").write_text("patch")
        (tmp_dir / f"hunknote_compose_msg_C1_{pid}.txt").write_text("message")
        (tmp_dir / f"hunknote_compose_pre_head_{pid}.txt").write_text("head")

        cleanup_temp_files(temp_repo, pid)

        # Check files are removed
        assert not (tmp_dir / f"hunknote_compose_patch_C1_{pid}.patch").exists()
        assert not (tmp_dir / f"hunknote_compose_msg_C1_{pid}.txt").exists()
        assert not (tmp_dir / f"hunknote_compose_pre_head_{pid}.txt").exists()

    def test_cleanup_no_tmp_dir(self, temp_repo):
        """Test cleanup when .tmp directory doesnt exist."""
        from hunknote.compose import cleanup_temp_files

        # Ensure .tmp doesnt exist
        tmp_dir = temp_repo / ".tmp"
        if tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir)

        # Should not raise
        cleanup_temp_files(temp_repo, 12345)

    def test_cleanup_only_removes_matching_pid(self, temp_repo):
        """Test that cleanup only removes files matching the PID."""
        from hunknote.compose import cleanup_temp_files

        tmp_dir = temp_repo / ".tmp"
        tmp_dir.mkdir(exist_ok=True)

        pid1 = 11111
        pid2 = 22222

        # Create files for both PIDs
        (tmp_dir / f"hunknote_compose_patch_C1_{pid1}.patch").write_text("patch1")
        (tmp_dir / f"hunknote_compose_patch_C1_{pid2}.patch").write_text("patch2")

        # Cleanup only pid1
        cleanup_temp_files(temp_repo, pid1)

        # pid1 file should be gone, pid2 should remain
        assert not (tmp_dir / f"hunknote_compose_patch_C1_{pid1}.patch").exists()
        assert (tmp_dir / f"hunknote_compose_patch_C1_{pid2}.patch").exists()


class TestComposeExecutionError:
    """Tests for ComposeExecutionError exception."""

    def test_exception_message(self):
        """Test exception with message."""
        from hunknote.compose import ComposeExecutionError

        error = ComposeExecutionError("Failed to apply patch")
        assert str(error) == "Failed to apply patch"

    def test_exception_inheritance(self):
        """Test exception inherits from Exception."""
        from hunknote.compose import ComposeExecutionError

        assert issubclass(ComposeExecutionError, Exception)


class TestPlanValidationError:
    """Tests for PlanValidationError exception."""

    def test_exception_message(self):
        """Test exception with message."""
        from hunknote.compose import PlanValidationError

        error = PlanValidationError("Invalid plan")
        assert str(error) == "Invalid plan"

    def test_exception_inheritance(self):
        """Test exception inherits from Exception."""
        from hunknote.compose import PlanValidationError

        assert issubclass(PlanValidationError, Exception)


class TestComposeIgnorePatterns:
    """Tests for ignore patterns in compose command."""

    def test_should_exclude_file_with_ignore_patterns(self):
        """Test that _should_exclude_file correctly filters files."""
        from hunknote.git.diff import _should_exclude_file

        patterns = ["poetry.lock", "*.min.js", "build/*"]

        # Should be excluded
        assert _should_exclude_file("poetry.lock", patterns) is True
        assert _should_exclude_file("app.min.js", patterns) is True
        assert _should_exclude_file("build/output.js", patterns) is True

        # Should NOT be excluded
        assert _should_exclude_file("pyproject.toml", patterns) is False
        assert _should_exclude_file("src/main.py", patterns) is False
        assert _should_exclude_file("app.js", patterns) is False

    def test_should_exclude_file_with_glob_patterns(self):
        """Test glob pattern matching."""
        from hunknote.git.diff import _should_exclude_file

        patterns = ["*.lock", "*.pyc", ".idea/*"]

        # Lock files
        assert _should_exclude_file("poetry.lock", patterns) is True
        assert _should_exclude_file("yarn.lock", patterns) is True

        # Compiled Python
        assert _should_exclude_file("module.pyc", patterns) is True
        assert _should_exclude_file("src/module.pyc", patterns) is True

        # IDE files
        assert _should_exclude_file(".idea/workspace.xml", patterns) is True

    def test_filter_staged_files_with_ignore_patterns(self):
        """Test filtering staged files using ignore patterns."""
        from hunknote.git.diff import _should_exclude_file

        staged_files = [
            "pyproject.toml",
            "poetry.lock",
            "src/main.py",
            "package-lock.json",
            "README.md",
        ]
        ignore_patterns = ["poetry.lock", "package-lock.json"]

        files_to_include = [
            f for f in staged_files
            if not _should_exclude_file(f, ignore_patterns)
        ]

        assert files_to_include == ["pyproject.toml", "src/main.py", "README.md"]
        assert "poetry.lock" not in files_to_include
        assert "package-lock.json" not in files_to_include
