"""Git context collector functions."""

import subprocess
from pathlib import Path


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


# Files to exclude from the staged diff sent to LLM
# These are typically auto-generated and don't need commit message descriptions
DIFF_EXCLUDE_PATTERNS = [
    "poetry.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
]


def get_staged_diff(max_chars: int = 50000) -> str:
    """Get the staged diff, excluding lock files and truncating if necessary.

    Lock files (poetry.lock, package-lock.json, etc.) are excluded because
    they are auto-generated and inflate the diff without adding useful context
    for commit message generation.

    Args:
        max_chars: Maximum characters for the diff output.

    Returns:
        The staged diff string.

    Raises:
        NoStagedChangesError: If there are no staged changes.
    """
    # Build exclusion args for git diff
    exclude_args = []
    for pattern in DIFF_EXCLUDE_PATTERNS:
        exclude_args.extend([":(exclude)" + pattern])

    # Get diff excluding lock files
    diff = _run_git_command(["diff", "--staged", "--"] + exclude_args)

    if not diff:
        # Check if there are staged changes at all (might all be lock files)
        full_diff = _run_git_command(["diff", "--staged"])
        if full_diff:
            # There are changes but they're all in excluded files
            # Return a note about this
            diff = "(Only lock file changes staged - no code changes to describe)"
        else:
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

    # Build the context bundle
    bundle = f"""[BRANCH]
{branch}

[STAGED_STATUS]
{status}

[LAST_5_COMMITS]
{commits_formatted}

[STAGED_DIFF]
{staged_diff}"""

    return bundle
