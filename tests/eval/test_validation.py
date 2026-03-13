"""Tests for mechanical validation helpers."""

from pathlib import Path

import pytest

from eval.validation import _file_path_to_module, _get_touched_files


class TestFilePathToModule:
    def test_regular_module(self, temp_dir):
        # Create the __init__.py chain
        pkg = temp_dir / "httpx"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        (pkg / "_models.py").write_text("# models")

        result = _file_path_to_module("httpx/_models.py", temp_dir)
        assert result == "httpx._models"

    def test_init_file(self, temp_dir):
        pkg = temp_dir / "httpx"
        pkg.mkdir()
        (pkg / "__init__.py").touch()

        result = _file_path_to_module("httpx/__init__.py", temp_dir)
        assert result == "httpx"

    def test_nested_module(self, temp_dir):
        pkg = temp_dir / "httpx"
        sub = pkg / "transports"
        sub.mkdir(parents=True)
        (pkg / "__init__.py").touch()
        (sub / "__init__.py").touch()
        (sub / "_http11.py").write_text("# transport")

        result = _file_path_to_module("httpx/transports/_http11.py", temp_dir)
        assert result == "httpx.transports._http11"

    def test_top_level_script(self, temp_dir):
        (temp_dir / "setup.py").write_text("# setup")
        result = _file_path_to_module("setup.py", temp_dir)
        assert result is None

    def test_no_init_chain(self, temp_dir):
        # No __init__.py in docs/
        docs = temp_dir / "docs"
        docs.mkdir()
        (docs / "conf.py").write_text("# conf")

        result = _file_path_to_module("docs/conf.py", temp_dir)
        assert result is None

    def test_non_python_file(self, temp_dir):
        result = _file_path_to_module("README.md", temp_dir)
        assert result is None

    def test_test_module(self, temp_dir):
        tests = temp_dir / "tests"
        tests.mkdir()
        (tests / "__init__.py").touch()
        (tests / "test_models.py").write_text("# test")

        result = _file_path_to_module("tests/test_models.py", temp_dir)
        assert result == "tests.test_models"


class TestGetTouchedFiles:
    def test_extracts_files_from_hunks(self):
        from hunknote.compose.models import HunkRef, PlannedCommit

        inventory = {
            "H1": HunkRef(
                id="H1", file_path="src/a.py", header="@@",
                old_start=1, old_len=5, new_start=1, new_len=6, lines=[]
            ),
            "H2": HunkRef(
                id="H2", file_path="src/b.py", header="@@",
                old_start=1, old_len=3, new_start=1, new_len=4, lines=[]
            ),
            "H3": HunkRef(
                id="H3", file_path="src/a.py", header="@@",
                old_start=10, old_len=2, new_start=11, new_len=3, lines=[]
            ),
        }

        commit = PlannedCommit(id="C1", title="test", hunks=["H1", "H3"])
        files = _get_touched_files(commit, inventory)
        assert files == ["src/a.py"]  # Deduplicated and sorted

    def test_missing_hunk_id(self):
        from hunknote.compose.models import PlannedCommit

        commit = PlannedCommit(id="C1", title="test", hunks=["H99"])
        files = _get_touched_files(commit, {})
        assert files == []
