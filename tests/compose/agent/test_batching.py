"""Tests for hunknote.compose.agent.batching — Dynamic batch planning."""

import pytest

from hunknote.compose.agent.batching import (
    Batch,
    DEFAULT_BATCH_TOKEN_BUDGET,
    PROMPT_OVERHEAD_TOKENS,
    plan_batches,
)
from hunknote.compose.models import FileDiff, HunkRef


def _make_hunk(hid, file_path, num_lines=5):
    """Create a HunkRef with the given number of content lines."""
    lines = [f"+line {i}" for i in range(num_lines)]
    return HunkRef(
        id=hid, file_path=file_path, header="@@ -1,1 +1,5 @@",
        old_start=1, old_len=1, new_start=1, new_len=num_lines,
        lines=lines,
    )


def _make_fd(file_path, hunks, is_new=False, is_binary=False):
    """Create a FileDiff."""
    return FileDiff(
        file_path=file_path,
        diff_header_lines=[f"diff --git a/{file_path} b/{file_path}"],
        hunks=hunks, is_new_file=is_new, is_binary=is_binary,
    )


class TestPlanBatches:
    """Tests for plan_batches."""

    def test_single_small_file(self, tmp_path):
        """Single small file produces one batch."""
        h1 = _make_hunk("H1_a", "foo.py", 5)
        fd = _make_fd("foo.py", [h1])
        batches = plan_batches([fd], {"H1_a": h1}, tmp_path)
        assert len(batches) >= 1
        # All hunk IDs covered
        all_hids = []
        for b in batches:
            all_hids.extend(b.hunk_ids)
        assert "H1_a" in all_hids

    def test_binary_files_skipped(self, tmp_path):
        """Binary files produce no batches."""
        h1 = _make_hunk("H1_a", "foo.py", 5)
        fd_bin = _make_fd("image.png", [], is_binary=True)
        fd_py = _make_fd("foo.py", [h1])
        batches = plan_batches([fd_bin, fd_py], {"H1_a": h1}, tmp_path)
        file_paths = [p for b in batches for p in b.file_paths]
        assert "image.png" not in file_paths

    def test_empty_file_diffs_skipped(self, tmp_path):
        """Files with no hunks produce no batches."""
        fd = _make_fd("empty.py", [])
        batches = plan_batches([fd], {}, tmp_path)
        assert len(batches) == 0

    def test_small_files_merged(self, tmp_path):
        """Multiple small files are merged into multi-file batches."""
        hunks = {}
        fds = []
        for i in range(5):
            h = _make_hunk(f"H{i+1}_x{i}", f"small_{i}.py", 3)
            hunks[h.id] = h
            fds.append(_make_fd(f"small_{i}.py", [h]))

        batches = plan_batches(fds, hunks, tmp_path)
        # With 5 tiny files, they should be merged into fewer batches
        assert len(batches) < 5

    def test_new_file_flag_propagated(self, tmp_path):
        """New file flag is propagated when file exceeds small threshold."""
        # Use a custom budget so our file exceeds the small threshold (budget/4)
        h = _make_hunk("H1_a", "new.py", 200)
        fd = _make_fd("new.py", [h], is_new=True)
        # With budget=4000, threshold=1000, our file's ~2100 tokens exceeds it
        batches = plan_batches([fd], {"H1_a": h}, tmp_path, token_budget=4000)
        new_batches = [b for b in batches if b.is_new_file]
        assert len(new_batches) >= 1

    def test_multi_hunk_file(self, tmp_path):
        """File with multiple hunks keeps them together."""
        h1 = _make_hunk("H1_a", "foo.py", 5)
        h2 = _make_hunk("H2_b", "foo.py", 5)
        fd = _make_fd("foo.py", [h1, h2])
        batches = plan_batches([fd], {"H1_a": h1, "H2_b": h2}, tmp_path)
        # Both hunks should be in the same batch
        for b in batches:
            if "H1_a" in b.hunk_ids:
                assert "H2_b" in b.hunk_ids

    def test_large_file_split(self, tmp_path):
        """Very large file is split into sub-batches."""
        hunks = {}
        hunk_list = []
        # Create many hunks to exceed token budget
        for i in range(50):
            h = _make_hunk(f"H{i+1}_x{i:02d}", "big.py", 100)
            hunks[h.id] = h
            hunk_list.append(h)
        fd = _make_fd("big.py", hunk_list)
        batches = plan_batches([fd], hunks, tmp_path, token_budget=5000)
        # Should be split into multiple batches
        assert len(batches) > 1
        # All hunks covered
        all_hids = set()
        for b in batches:
            all_hids.update(b.hunk_ids)
        assert all_hids == set(hunks.keys())

    def test_batch_ids_unique(self, tmp_path):
        """All batches have unique IDs."""
        hunks = {}
        fds = []
        for i in range(4):
            h = _make_hunk(f"H{i+1}_x{i}", f"file_{i}.py", 20)
            hunks[h.id] = h
            fds.append(_make_fd(f"file_{i}.py", [h]))

        batches = plan_batches(fds, hunks, tmp_path)
        ids = [b.batch_id for b in batches]
        assert len(ids) == len(set(ids))
