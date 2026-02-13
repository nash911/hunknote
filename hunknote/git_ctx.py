"""Git context collector functions."""

import fnmatch
import subprocess
from pathlib import Path

from hunknote.user_config import get_ignore_patterns


class GitError(Exception):
    """Custom exception for git-related errors."""
    pass


class NoStagedChangesError(GitError):
    """Raised when there are no staged changes."""
    pass


def _run_git_command(args: list[str]) -> str:
    """Run a git command and return its output.

    Args:
        args: List of arguments to pass to git.

    Returns:
        The stdout of the git command.

    Raises:
        GitError: If the command fails.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise GitError(f"Git command failed: git {' '.join(args)}\n{e.stderr.strip()}")
    except FileNotFoundError:
        raise GitError("Git is not installed or not in PATH.")


def get_repo_root() -> Path:
    """Get the root directory of the current git repository.

    Returns:
        Path to the repository root.

    Raises:
        GitError: If not in a git repository.
    """
    try:
        root = _run_git_command(["rev-parse", "--show-toplevel"])
        return Path(root)
    except GitError:
        raise GitError("Not in a git repository. Please run this command from within a git repo.")


def get_branch() -> str:
    """Get the current branch name.

    Returns:
        The current branch name, or 'HEAD' if in detached state.
    """
    branch = _run_git_command(["branch", "--show-current"])
    if not branch:
        # Detached HEAD state
        return "HEAD (detached)"
    return branch


def get_status() -> str:
    """Get git status output in porcelain format.

    Returns:
        The git status output.
    """
    return _run_git_command(["status", "--porcelain=v1", "-b"])


def get_staged_status() -> str:
    """Get git status filtered to only show staged files.

    The porcelain format uses two columns:
    - First column: staged status (index)
    - Second column: worktree status

    We only include lines where the first column indicates a staged change.

    Returns:
        Filtered status showing only staged files.
    """
    full_status = _run_git_command(["status", "--porcelain=v1", "-b"])
    lines = full_status.split("\n")
    filtered_lines = []

    for line in lines:
        if not line:
            continue
        # Keep the branch line (starts with ##)
        if line.startswith("##"):
            filtered_lines.append(line)
            continue
        # Skip lines that are too short
        if len(line) < 2:
            continue
        # Check first column (index/staged status)
        # If first char is not space and not '?', it's staged
        first_col = line[0]
        if first_col != " " and first_col != "?":
            filtered_lines.append(line)

    return "\n".join(filtered_lines)


def get_last_commits(n: int = 5) -> list[str]:
    """Get the last n commit subjects.

    Args:
        n: Number of commits to retrieve.

    Returns:
        List of commit subject lines.
    """
    try:
        output = _run_git_command(["log", f"-n{n}", "--pretty=%s"])
        if not output:
            return []
        return output.split("\n")
    except GitError:
        # No commits yet in the repo
        return []


# Default files to exclude from the staged diff sent to LLM
# These are typically auto-generated and don't need commit message descriptions
# Note: This list is used as fallback; actual patterns come from .hunknote/config.yaml
DEFAULT_DIFF_EXCLUDE_PATTERNS = [
    "poetry.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
]


def _get_staged_files_list() -> list[str]:
    """Get list of staged file paths.

    Returns:
        List of staged file paths.
    """
    output = _run_git_command(["diff", "--staged", "--name-only"])
    if not output:
        return []
    return output.split("\n")


def _should_exclude_file(filename: str, patterns: list[str]) -> bool:
    """Check if a file should be excluded based on patterns.

    Supports glob patterns like *.lock, build/*, etc.

    Args:
        filename: The file path to check.
        patterns: List of patterns to match against.

    Returns:
        True if the file should be excluded.
    """
    for pattern in patterns:
        # Handle exact matches
        if filename == pattern:
            return True
        # Handle glob patterns
        if fnmatch.fnmatch(filename, pattern):
            return True
        # Handle patterns that might match the basename
        if fnmatch.fnmatch(Path(filename).name, pattern):
            return True
    return False


def get_staged_diff(max_chars: int = 50000, repo_root: Path = None) -> str:
    """Get the staged diff, excluding ignored files and truncating if necessary.

    Files matching patterns in .hunknote/config.yaml ignore list are excluded
    because they are typically auto-generated and inflate the diff without
    adding useful context for commit message generation.

    Args:
        max_chars: Maximum characters for the diff output.
        repo_root: The root directory of the git repository (optional).

    Returns:
        The staged diff string.

    Raises:
        NoStagedChangesError: If there are no staged changes.
    """
    # Get ignore patterns from config (or use defaults if repo_root not provided)
    if repo_root:
        ignore_patterns = get_ignore_patterns(repo_root)
    else:
        # Try to get repo root, fall back to defaults if not in a repo
        try:
            repo_root = get_repo_root()
            ignore_patterns = get_ignore_patterns(repo_root)
        except GitError:
            ignore_patterns = DEFAULT_DIFF_EXCLUDE_PATTERNS

    # Get list of staged files
    staged_files = _get_staged_files_list()

    if not staged_files:
        raise NoStagedChangesError(
            "No staged changes found. Stage your changes first with: git add <files>"
        )

    # Filter out files matching ignore patterns
    files_to_include = [
        f for f in staged_files
        if not _should_exclude_file(f, ignore_patterns)
    ]

    if not files_to_include:
        # All staged files are in the ignore list
        return "(Only ignored files staged - no code changes to describe)"

    # Build git diff command with only included files
    diff = _run_git_command(["diff", "--staged", "--"] + files_to_include)

    if not diff:
        # This shouldn't happen if files_to_include is not empty, but handle it
        raise NoStagedChangesError(
            "No staged changes found. Stage your changes first with: git add <files>"
        )

    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n...[truncated]\n"

    return diff


def build_context_bundle(max_chars: int = 50000) -> str:
    """Build the complete context bundle for the LLM.

    Args:
        max_chars: Maximum characters for the staged diff.

    Returns:
        A formatted string containing all git context sections.

    Raises:
        NoStagedChangesError: If there are no staged changes.
        GitError: If not in a git repository.
    """
    # Get all context pieces
    branch = get_branch()
    # Use staged-only status to avoid confusing LLM with unstaged/untracked files
    status = get_staged_status()
    last_commits = get_last_commits(n=5)
    staged_diff = get_staged_diff(max_chars=max_chars)

    # Format commits as bullet list
    commits_formatted = "\n".join(f"- {commit}" for commit in last_commits) if last_commits else "- (no commits yet)"

    # Parse status to create a clear file change summary
    file_changes = _parse_file_changes(status)

    # Build the context bundle
    bundle = f"""[BRANCH]
{branch}

[FILE_CHANGES]
{file_changes}

[LAST_5_COMMITS]
{commits_formatted}

[STAGED_DIFF]
{staged_diff}"""

    return bundle


def _parse_file_changes(status: str) -> str:
    """Parse git status into a human-readable file change summary.

    This helps the LLM understand which files are NEW (didn't exist before)
    versus MODIFIED (already existed and are being changed).

    Args:
        status: Git status in porcelain format.

    Returns:
        Human-readable summary of file changes.
    """
    new_files = []
    modified_files = []
    deleted_files = []
    renamed_files = []

    for line in status.split("\n"):
        if not line or line.startswith("##"):
            continue
        if len(line) < 3:
            continue

        status_code = line[0]
        filename = line[3:]

        # Handle renames: "R  old -> new"
        if " -> " in filename:
            old_name, new_name = filename.split(" -> ")
            renamed_files.append(f"{old_name} -> {new_name}")
            continue

        if status_code == "A":
            new_files.append(filename)
        elif status_code == "M":
            modified_files.append(filename)
        elif status_code == "D":
            deleted_files.append(filename)

    # Build summary
    lines = []
    if new_files:
        lines.append("New files (did not exist before this commit):")
        for f in new_files:
            lines.append(f"  + {f}")
    if modified_files:
        lines.append("Modified files (already existed, now changed):")
        for f in modified_files:
            lines.append(f"  ~ {f}")
    if deleted_files:
        lines.append("Deleted files:")
        for f in deleted_files:
            lines.append(f"  - {f}")
    if renamed_files:
        lines.append("Renamed files:")
        for f in renamed_files:
            lines.append(f"  > {f}")

    return "\n".join(lines) if lines else "(no files)"

