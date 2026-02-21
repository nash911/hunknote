"""Inference utilities for hunknote styles.

Contains functions for:
- Extracting ticket keys from branch names
- Inferring commit types from staged files
"""

import re
from typing import Optional


def extract_ticket_from_branch(branch: str, pattern: str = r"([A-Z][A-Z0-9]+-\d+)") -> Optional[str]:
    """Extract ticket key from branch name.

    Args:
        branch: The branch name.
        pattern: Regex pattern for ticket extraction.

    Returns:
        The extracted ticket key or None.
    """
    match = re.search(pattern, branch)
    if match:
        return match.group(1)
    return None


def infer_commit_type(staged_files: list[str]) -> Optional[str]:
    """Infer conventional commit type from staged files.

    Args:
        staged_files: List of staged file paths.

    Returns:
        Inferred commit type or None if cannot determine.
    """
    if not staged_files:
        return None

    # Check for docs-only changes
    doc_extensions = {".md", ".rst", ".txt", ".adoc"}
    doc_dirs = {"docs", "doc", "documentation"}

    all_docs = all(
        any(f.endswith(ext) for ext in doc_extensions) or
        any(d in f.lower() for d in doc_dirs)
        for f in staged_files
    )
    if all_docs:
        return "docs"

    # Check for test-only changes
    test_patterns = {"test_", "_test.", ".test.", "tests/", "test/", "spec/", "__tests__/"}
    all_tests = all(
        any(p in f.lower() for p in test_patterns)
        for f in staged_files
    )
    if all_tests:
        return "test"

    # Check for CI changes (BEFORE build, since CI files often match build patterns)
    ci_patterns = {".github/workflows/", ".github/workflows", ".gitlab-ci", "Jenkinsfile", ".circleci/", ".travis", ".circleci"}
    all_ci = all(
        any(p in f for p in ci_patterns)
        for f in staged_files
    )
    if all_ci:
        return "ci"

    # Check for config/build changes (excluding CI files)
    build_files = {
        "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "pyproject.toml", "poetry.lock", "setup.py", "setup.cfg", "requirements.txt",
        "Makefile", "CMakeLists.txt", "Cargo.toml", "Cargo.lock",
        "go.mod", "go.sum", "Gemfile", "Gemfile.lock",
        "Dockerfile", "docker-compose",
    }
    all_build = all(
        any(bf in f for bf in build_files)
        for f in staged_files
    )
    if all_build:
        return "build"

    return None

