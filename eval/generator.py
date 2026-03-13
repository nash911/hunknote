"""Test case generator from real repo commit sequences.

Uses the squash-and-recover approach: takes a sequence of real atomic
commits, squashes them into a single diff, then records the original
commit boundaries as the reference decomposition.
"""

import hashlib
import json
import logging
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

from hunknote.compose.parser import parse_unified_diff
from hunknote.compose.inventory import build_hunk_inventory
from eval.config import EVAL_REPOS_CACHE_DIR
from eval.models import (
    BuildSystemConfig,
    DifficultyTier,
    KnownDependency,
    Language,
    ReferenceCommit,
    TestCase,
    TestCaseStats,
)

logger = logging.getLogger(__name__)


def generate_case(
    repo_url: str,
    commit_range: str,
    case_id: str,
    language: Language,
    tier: DifficultyTier,
    description: str,
    output_dir: Path,
    build_system: BuildSystemConfig,
    known_dependencies: Optional[list[KnownDependency]] = None,
    tags: Optional[list[str]] = None,
) -> TestCase:
    """Generate a test case from a real repo commit sequence.

    Steps:
    1. Clone the repo (or use cached bare clone).
    2. Identify before/after commits from the range.
    3. Extract individual commits with their diffs.
    4. Generate squashed diff and parse into hunks.
    5. Map each hunk to its original commit.
    6. Create repo.tar.gz snapshot at before state.
    7. Write case.json and reference.json.

    Args:
        repo_url: GitHub repo URL.
        commit_range: e.g. "abc123~4..abc123" or "abc123..def456".
        case_id: Unique test case ID.
        language: Programming language.
        tier: Difficulty tier.
        description: Human-readable description.
        output_dir: Where to write the test case.
        build_system: Build system configuration.
        known_dependencies: Known co-commit constraints.
        tags: Tags for filtering.

    Returns:
        The generated TestCase object.
    """
    known_dependencies = known_dependencies or []
    tags = tags or []

    # 1. Clone or use cached repo
    bare_repo = _clone_or_use_cached(repo_url)

    with tempfile.TemporaryDirectory(prefix="hunknote_gen_") as tmp_dir:
        work_dir = Path(tmp_dir) / "work"

        # Create a working clone from the bare repo
        subprocess.run(
            ["git", "clone", str(bare_repo), str(work_dir)],
            capture_output=True,
            check=True,
        )

        # 2. Parse commit range
        before_commit, after_commit = _parse_commit_range(work_dir, commit_range)
        logger.info("Range: %s..%s", before_commit[:8], after_commit[:8])

        # 3. Extract individual commits
        commit_sequence = _extract_commit_sequence(work_dir, commit_range)
        logger.info("Found %d commits in range", len(commit_sequence))

        # 4. Generate squashed diff
        squashed_diff = _get_squashed_diff(work_dir, before_commit, after_commit)

        # Parse into hunks
        file_diffs, warnings = parse_unified_diff(squashed_diff)
        inventory = build_hunk_inventory(file_diffs)

        # 5. Map hunks to original commits
        hunk_to_commit = _map_hunks_to_commits(
            inventory, file_diffs, commit_sequence
        )

        # Build reference commits
        reference_commits = _build_reference_commits(
            commit_sequence, hunk_to_commit
        )

        # Compute stats
        lines_added = sum(
            sum(1 for line in h.lines if line.startswith("+"))
            for h in inventory.values()
        )
        lines_removed = sum(
            sum(1 for line in h.lines if line.startswith("-"))
            for h in inventory.values()
        )

        stats = TestCaseStats(
            total_hunks=len(inventory),
            total_files=len(file_diffs),
            reference_commit_count=len(commit_sequence),
            lines_added=lines_added,
            lines_removed=lines_removed,
        )

        # 6. Create output directory and write files
        case_dir = output_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        # Write staged.patch
        (case_dir / "staged.patch").write_text(squashed_diff)

        # Create repo.tar.gz (snapshot at before state)
        _create_repo_snapshot(work_dir, before_commit, case_dir / "repo.tar.gz")

        # Build the TestCase
        source_commits = [c["sha"] for c in commit_sequence]

        test_case = TestCase(
            id=case_id,
            language=language,
            tier=tier,
            description=description,
            source_repo=repo_url,
            source_commits=source_commits,
            stats=stats,
            build_system=build_system,
            known_dependencies=known_dependencies,
            reference_commits=reference_commits,
            tags=tags,
        )

        # 7. Write case.json
        _write_case_json(test_case, case_dir)

        # Write reference.json
        _write_reference_json(reference_commits, case_dir)

        logger.info(
            "Generated case %s: %d hunks, %d files, %d reference commits",
            case_id,
            stats.total_hunks,
            stats.total_files,
            stats.reference_commit_count,
        )

        return test_case


def _clone_or_use_cached(repo_url: str) -> Path:
    """Clone repo as bare or return existing cached clone.

    Cached at ~/.hunknote/eval_cache/repos/{repo_name}.git
    """
    # Extract repo name from URL
    repo_name = repo_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    cache_dir = EVAL_REPOS_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    bare_path = cache_dir / f"{repo_name}.git"

    if bare_path.exists():
        # Update existing bare clone
        logger.info("Updating cached bare clone: %s", bare_path)
        subprocess.run(
            ["git", "fetch", "--all"],
            cwd=bare_path,
            capture_output=True,
        )
    else:
        # Clone as bare
        logger.info("Cloning %s as bare to %s", repo_url, bare_path)
        subprocess.run(
            ["git", "clone", "--bare", repo_url, str(bare_path)],
            capture_output=True,
            check=True,
        )

    return bare_path


def _parse_commit_range(repo_dir: Path, commit_range: str) -> tuple[str, str]:
    """Parse a commit range string into (before, after) commit SHAs.

    Args:
        repo_dir: Working repo directory.
        commit_range: e.g. "abc123~4..abc123"

    Returns:
        Tuple of (before_sha, after_sha).
    """
    parts = commit_range.split("..")
    if len(parts) != 2:
        raise ValueError(f"Invalid commit range: {commit_range}. Expected 'before..after'.")

    before_ref, after_ref = parts

    before_sha = subprocess.run(
        ["git", "rev-parse", before_ref],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    after_sha = subprocess.run(
        ["git", "rev-parse", after_ref],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    return before_sha, after_sha


def _extract_commit_sequence(repo_dir: Path, commit_range: str) -> list[dict]:
    """Extract individual commits with their file lists and diffs.

    Returns list of:
    {
        "sha": "abc123...",
        "message": "Refactor URL model",
        "files": ["httpx/_models.py", ...],
        "diff": "<unified diff>"
    }
    """
    # Get list of commits in range
    result = subprocess.run(
        ["git", "log", "--reverse", "--format=%H%n%s", commit_range],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().split("\n")
    commits: list[dict] = []

    for i in range(0, len(lines), 2):
        if i + 1 >= len(lines):
            break
        sha = lines[i].strip()
        message = lines[i + 1].strip()

        if not sha:
            continue

        # Get the diff for this commit
        diff_result = subprocess.run(
            ["git", "diff", f"{sha}~1..{sha}", "--patch", "--no-color"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        diff = diff_result.stdout

        # Get file list
        files_result = subprocess.run(
            ["git", "diff", "--name-only", f"{sha}~1..{sha}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        files = [f.strip() for f in files_result.stdout.strip().split("\n") if f.strip()]

        commits.append({
            "sha": sha,
            "message": message,
            "files": files,
            "diff": diff,
        })

    return commits


def _get_squashed_diff(repo_dir: Path, before: str, after: str) -> str:
    """Get the squashed diff between two commits."""
    result = subprocess.run(
        ["git", "diff", before, after, "--patch", "--no-color"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _map_hunks_to_commits(
    inventory: dict[str, "HunkRef"],
    file_diffs: list,
    commit_sequence: list[dict],
) -> dict[str, str]:
    """Map each hunk in the squashed diff to its original commit.

    Uses a fuzzy match strategy comparing changed line content
    (ignoring line numbers) between squashed hunks and per-commit hunks.

    Returns:
        Dict mapping squashed hunk_id -> original commit SHA.
    """
    hunk_to_commit: dict[str, str] = {}

    # Group squashed hunks by file
    hunks_by_file: dict[str, list] = {}
    for hunk_id, hunk in inventory.items():
        hunks_by_file.setdefault(hunk.file_path, []).append((hunk_id, hunk))

    for file_path, squashed_hunks in hunks_by_file.items():
        for hunk_id, squashed_hunk in squashed_hunks:
            # Extract the changed content (+ and - lines only)
            squashed_content = _extract_change_content(squashed_hunk.lines)

            best_match_sha: Optional[str] = None
            best_score = 0.0

            for commit_data in commit_sequence:
                if file_path not in commit_data["files"]:
                    continue

                # Parse this commit's diff for this file
                commit_file_diffs, _ = parse_unified_diff(commit_data["diff"])
                for cfd in commit_file_diffs:
                    if cfd.file_path != file_path:
                        continue
                    for commit_hunk in cfd.hunks:
                        commit_content = _extract_change_content(commit_hunk.lines)
                        score = _content_similarity(squashed_content, commit_content)
                        if score > best_score:
                            best_score = score
                            best_match_sha = commit_data["sha"]

            if best_match_sha:
                hunk_to_commit[hunk_id] = best_match_sha
            else:
                logger.warning(
                    "Could not map hunk %s (%s) to any commit",
                    hunk_id,
                    file_path,
                )
                # Assign to the first commit that touches this file
                for commit_data in commit_sequence:
                    if file_path in commit_data["files"]:
                        hunk_to_commit[hunk_id] = commit_data["sha"]
                        break

    return hunk_to_commit


def _extract_change_content(lines: list[str]) -> str:
    """Extract only the +/- lines from a hunk (the actual changes)."""
    return "\n".join(
        line for line in lines if line.startswith("+") or line.startswith("-")
    )


def _content_similarity(a: str, b: str) -> float:
    """Compute similarity between two change contents.

    Uses a simple set-based Jaccard similarity on lines.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    lines_a = set(a.split("\n"))
    lines_b = set(b.split("\n"))

    intersection = lines_a & lines_b
    union = lines_a | lines_b

    if not union:
        return 0.0

    return len(intersection) / len(union)


def _build_reference_commits(
    commit_sequence: list[dict],
    hunk_to_commit: dict[str, str],
) -> list[ReferenceCommit]:
    """Build ReferenceCommit list from the mapping."""
    # Group hunks by commit SHA
    commit_hunks: dict[str, list[str]] = {}
    for hunk_id, sha in hunk_to_commit.items():
        commit_hunks.setdefault(sha, []).append(hunk_id)

    references: list[ReferenceCommit] = []
    for i, commit_data in enumerate(commit_sequence):
        sha = commit_data["sha"]
        hunk_ids = sorted(commit_hunks.get(sha, []))
        if not hunk_ids:
            continue

        references.append(
            ReferenceCommit(
                index=i,
                message=commit_data["message"],
                files=commit_data["files"],
                hunk_ids=hunk_ids,
            )
        )

    return references


def _create_repo_snapshot(
    work_dir: Path, before_commit: str, output_path: Path
) -> None:
    """Create a tar.gz snapshot of the repo at the before state.

    The snapshot includes .git/ so git commands work.
    """
    # Checkout the before commit
    subprocess.run(
        ["git", "checkout", before_commit],
        cwd=work_dir,
        capture_output=True,
        check=True,
    )

    # Create tar.gz including .git
    with tarfile.open(output_path, "w:gz") as tar:
        tar.add(work_dir, arcname=".")


def _write_case_json(test_case: TestCase, case_dir: Path) -> None:
    """Write case.json to the test case directory."""
    data = {
        "id": test_case.id,
        "language": test_case.language.value,
        "tier": test_case.tier.value,
        "description": test_case.description,
        "source_repo": test_case.source_repo,
        "source_commits": test_case.source_commits,
        "stats": {
            "total_hunks": test_case.stats.total_hunks,
            "total_files": test_case.stats.total_files,
            "reference_commit_count": test_case.stats.reference_commit_count,
            "lines_added": test_case.stats.lines_added,
            "lines_removed": test_case.stats.lines_removed,
        },
        "build_system": {
            "type": test_case.build_system.type,
            "install_commands": test_case.build_system.install_commands,
            "check_command": test_case.build_system.check_command,
            "import_check": test_case.build_system.import_check,
            "import_command": test_case.build_system.import_command,
            "test_command": test_case.build_system.test_command,
            "test_enabled": test_case.build_system.test_enabled,
            "python_version_min": test_case.build_system.python_version_min,
        },
        "known_dependencies": [
            {
                "description": kd.description,
                "hunks_must_cocommit": kd.hunks_must_cocommit,
                "reason": kd.reason,
            }
            for kd in test_case.known_dependencies
        ],
        "tags": test_case.tags,
    }

    with open(case_dir / "case.json", "w") as f:
        json.dump(data, f, indent=2)


def _write_reference_json(
    reference_commits: list[ReferenceCommit], case_dir: Path
) -> None:
    """Write reference.json to the test case directory."""
    data = {
        "commits": [
            {
                "index": rc.index,
                "message": rc.message,
                "files": rc.files,
                "hunk_ids": rc.hunk_ids,
            }
            for rc in reference_commits
        ]
    }

    with open(case_dir / "reference.json", "w") as f:
        json.dump(data, f, indent=2)
