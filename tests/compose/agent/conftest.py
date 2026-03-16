"""Shared fixtures for Compose Agent tests."""

import json
import tempfile
from pathlib import Path

import pytest

from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
    FrozenBaseline,
    FrozenCommit,
    HunkSummary,
    Remediation,
    RemediationAction,
    ValidationFailure,
    ValidationLayer,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import FileDiff, HunkRef, PlannedCommit
from hunknote.llm.base import RawLLMResult


# ── HunkRef fixtures ──


@pytest.fixture
def hunk_foo_1():
    """Hunk adding a function to foo.py."""
    return HunkRef(
        id="H1_abc123",
        file_path="foo.py",
        header="@@ -1,3 +1,7 @@",
        old_start=1, old_len=3, new_start=1, new_len=7,
        lines=[
            " import os",
            "+",
            "+def hello():",
            "+    return 'hello'",
        ],
    )


@pytest.fixture
def hunk_foo_2():
    """Hunk adding another function to foo.py."""
    return HunkRef(
        id="H2_def456",
        file_path="foo.py",
        header="@@ -10,3 +14,6 @@",
        old_start=10, old_len=3, new_start=14, new_len=6,
        lines=[
            " ",
            "+def goodbye():",
            "+    return 'bye'",
        ],
    )


@pytest.fixture
def hunk_bar():
    """Hunk modifying bar.py that imports from foo."""
    return HunkRef(
        id="H3_789ghi",
        file_path="bar.py",
        header="@@ -1,2 +1,4 @@",
        old_start=1, old_len=2, new_start=1, new_len=4,
        lines=[
            "+from foo import hello",
            " ",
            "+result = hello()",
        ],
    )


@pytest.fixture
def hunk_test():
    """Hunk adding tests."""
    return HunkRef(
        id="H4_jkl012",
        file_path="tests/test_foo.py",
        header="@@ -0,0 +1,8 @@",
        old_start=0, old_len=0, new_start=1, new_len=8,
        lines=[
            "+import pytest",
            "+from foo import hello",
            "+",
            "+def test_hello():",
            "+    assert hello() == 'hello'",
        ],
    )


@pytest.fixture
def hunk_new_file():
    """Hunk from a brand-new file."""
    return HunkRef(
        id="H5_mno345",
        file_path="new_module.py",
        header="@@ -0,0 +1,5 @@",
        old_start=0, old_len=0, new_start=1, new_len=5,
        lines=[
            "+# New module",
            "+def new_func():",
            "+    pass",
        ],
    )


# ── FileDiff fixtures ──


@pytest.fixture
def file_diff_foo(hunk_foo_1, hunk_foo_2):
    """FileDiff for foo.py with two hunks."""
    return FileDiff(
        file_path="foo.py",
        diff_header_lines=["diff --git a/foo.py b/foo.py"],
        hunks=[hunk_foo_1, hunk_foo_2],
    )


@pytest.fixture
def file_diff_bar(hunk_bar):
    """FileDiff for bar.py."""
    return FileDiff(
        file_path="bar.py",
        diff_header_lines=["diff --git a/bar.py b/bar.py"],
        hunks=[hunk_bar],
    )


@pytest.fixture
def file_diff_test(hunk_test):
    """FileDiff for test file."""
    return FileDiff(
        file_path="tests/test_foo.py",
        diff_header_lines=["diff --git a/tests/test_foo.py b/tests/test_foo.py"],
        hunks=[hunk_test],
    )


@pytest.fixture
def file_diff_new(hunk_new_file):
    """FileDiff for a new file."""
    return FileDiff(
        file_path="new_module.py",
        diff_header_lines=["diff --git a/new_module.py b/new_module.py"],
        hunks=[hunk_new_file],
        is_new_file=True,
    )


@pytest.fixture
def all_file_diffs(file_diff_foo, file_diff_bar, file_diff_test, file_diff_new):
    return [file_diff_foo, file_diff_bar, file_diff_test, file_diff_new]


@pytest.fixture
def inventory(hunk_foo_1, hunk_foo_2, hunk_bar, hunk_test, hunk_new_file):
    """Full inventory of all hunks."""
    return {
        "H1_abc123": hunk_foo_1,
        "H2_def456": hunk_foo_2,
        "H3_789ghi": hunk_bar,
        "H4_jkl012": hunk_test,
        "H5_mno345": hunk_new_file,
    }


# ── HunkSummary fixtures ──


@pytest.fixture
def summaries():
    """Pre-built Phase 1 summaries."""
    return {
        "H1_abc123": HunkSummary(
            hunk_id="H1_abc123", file_path="foo.py",
            intent="Add hello function", category="feature",
            symbols_modified=["hello"], symbols_referenced=["os"],
        ),
        "H2_def456": HunkSummary(
            hunk_id="H2_def456", file_path="foo.py",
            intent="Add goodbye function", category="feature",
            symbols_modified=["goodbye"], symbols_referenced=[],
        ),
        "H3_789ghi": HunkSummary(
            hunk_id="H3_789ghi", file_path="bar.py",
            intent="Call hello from bar", category="feature",
            symbols_modified=["result"], symbols_referenced=["hello"],
        ),
        "H4_jkl012": HunkSummary(
            hunk_id="H4_jkl012", file_path="tests/test_foo.py",
            intent="Add test for hello", category="test",
            symbols_modified=["test_hello"], symbols_referenced=["hello"],
        ),
        "H5_mno345": HunkSummary(
            hunk_id="H5_mno345", file_path="new_module.py",
            intent="Add new module", category="feature",
            symbols_modified=["new_func"], symbols_referenced=[],
            is_new_file=True,
        ),
    }


# ── DependencyGraph fixtures ──


@pytest.fixture
def dependency_graph():
    """Pre-built Phase 2 dependency graph."""
    graph = DependencyGraph()
    # bar.py imports hello from foo.py
    graph.add_edge(DependencyEdge(
        from_hunk="H3_789ghi", to_hunk="H1_abc123",
        edge_type=EdgeType.DIRECTIONAL, reason="bar imports hello from foo",
    ))
    # test depends on hello function — bidirectional
    graph.add_edge(DependencyEdge(
        from_hunk="H1_abc123", to_hunk="H4_jkl012",
        edge_type=EdgeType.BIDIRECTIONAL, reason="test validates hello behavior",
    ))
    return graph


# ── CommitGroup fixtures ──


@pytest.fixture
def commit_groups():
    """Pre-built Phase 3 groups (before ordering)."""
    return [
        CommitGroup(
            group_id="_G1", hunk_ids=["H1_abc123", "H4_jkl012"],
            theme="Add hello with tests", category="feature",
        ),
        CommitGroup(
            group_id="_G2", hunk_ids=["H2_def456"],
            theme="Add goodbye function", category="feature",
        ),
        CommitGroup(
            group_id="_G3", hunk_ids=["H3_789ghi"],
            theme="Integrate hello in bar", category="feature",
        ),
        CommitGroup(
            group_id="_G4", hunk_ids=["H5_mno345"],
            theme="Add new module", category="feature",
        ),
    ]


@pytest.fixture
def ordered_groups():
    """Groups after Phase 4 ordering."""
    return [
        CommitGroup(
            group_id="C1", hunk_ids=["H1_abc123", "H4_jkl012"],
            theme="Add hello with tests", category="feature",
        ),
        CommitGroup(
            group_id="C2", hunk_ids=["H3_789ghi"],
            theme="Integrate hello in bar", category="feature",
        ),
        CommitGroup(
            group_id="C3", hunk_ids=["H2_def456"],
            theme="Add goodbye function", category="feature",
        ),
        CommitGroup(
            group_id="C4", hunk_ids=["H5_mno345"],
            theme="Add new module", category="feature",
        ),
    ]


# ── Mock LLM ──


@pytest.fixture
def mock_llm_call_fn():
    """A configurable mock LLM call function.

    Returns a callable that routes based on system_prompt content.
    Configure responses by setting .responses dict before use.
    """
    class MockLLM:
        def __init__(self):
            self.calls = []
            self.responses = {}
            self.default_response = RawLLMResult(
                raw_response="{}", model="test-model",
                input_tokens=10, output_tokens=5,
            )

        def __call__(self, system_prompt: str, user_prompt: str) -> RawLLMResult:
            self.calls.append((system_prompt, user_prompt))
            sp = system_prompt.lower()
            for key, response in self.responses.items():
                if key in sp:
                    if callable(response):
                        return response(system_prompt, user_prompt)
                    return response
            return self.default_response

    return MockLLM()


@pytest.fixture
def trace():
    """Fresh AgentTrace instance."""
    return AgentTrace()


@pytest.fixture
def temp_repo(tmp_path):
    """Minimal temp directory simulating a repo root."""
    hunknote_dir = tmp_path / ".hunknote"
    hunknote_dir.mkdir()
    return tmp_path
