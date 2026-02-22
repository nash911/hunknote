"""Cleanup utilities for hunknote compose module.

Contains:
- cleanup_temp_files: Clean up temporary files created during compose
"""

import glob
from pathlib import Path


def cleanup_temp_files(repo_root: Path, pid: int) -> None:
    """Clean up temporary files created during compose.

    Args:
        repo_root: Repository root path
        pid: Process ID used in filenames
    """
    tmp_dir = repo_root / ".tmp"
    if not tmp_dir.exists():
        return

    patterns = [
        f"hunknote_compose_*_{pid}.*",
    ]

    for pattern in patterns:
        for filepath in glob.glob(str(tmp_dir / pattern)):
            try:
                Path(filepath).unlink()
            except OSError:
                pass

