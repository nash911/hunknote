"""Shared test fixtures and configuration."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_repo_root(temp_dir):
    """Create a mock git repository root directory."""
    # Create .git directory to simulate a git repo
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    return temp_dir


@pytest.fixture
def sample_context_bundle():
    """Sample git context bundle for testing."""
    return """[BRANCH]
main

[STAGED_STATUS]
## main...origin/main
A  new_file.py
M  existing_file.py

[LAST_5_COMMITS]
- Fix bug in user authentication
- Add new feature for data export
- Update dependencies
- Refactor database module
- Initial commit

[STAGED_DIFF]
diff --git a/new_file.py b/new_file.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,10 @@
+def hello():
+    print("Hello, world!")
+
+def goodbye():
+    print("Goodbye!")

diff --git a/existing_file.py b/existing_file.py
index 1234567..abcdefg 100644
--- a/existing_file.py
+++ b/existing_file.py
@@ -1,5 +1,8 @@
 def main():
-    print("old")
+    print("new")
+
+def helper():
+    return True
"""


@pytest.fixture
def sample_commit_json_dict():
    """Sample commit message JSON as dictionary."""
    return {
        "title": "Add hello and goodbye functions",
        "body_bullets": [
            "Add new_file.py with hello and goodbye functions",
            "Update existing_file.py to print new message",
            "Add helper function to existing_file.py",
        ],
    }


@pytest.fixture
def sample_llm_response():
    """Sample raw LLM response (valid JSON)."""
    return """{
    "title": "Add hello and goodbye functions",
    "body_bullets": [
        "Add new_file.py with hello and goodbye functions",
        "Update existing_file.py to print new message",
        "Add helper function to existing_file.py"
    ]
}"""


@pytest.fixture
def sample_llm_response_with_markdown():
    """Sample raw LLM response with markdown code fences."""
    return """```json
{
    "title": "Add hello and goodbye functions",
    "body_bullets": [
        "Add new_file.py with hello and goodbye functions",
        "Update existing_file.py to print new message"
    ]
}
```"""


@pytest.fixture
def mock_git_commands(mocker):
    """Mock subprocess.run for git commands."""
    mock_run = mocker.patch("subprocess.run")
    return mock_run
