"""Dynamic batch planning for Phase 1 hunk summarization.

Groups hunks into batches for LLM processing, respecting:
- File boundaries (never split a file's hunks unless file exceeds budget)
- Token budget per batch
- New file handling (entire file as one unit)
- Small file merging (combine small files into multi-file batches)
"""

from dataclasses import dataclass, field
from pathlib import Path

from hunknote.compose.models import FileDiff, HunkRef

CHARS_PER_TOKEN = 4
DEFAULT_BATCH_TOKEN_BUDGET = 12_000  # Conservative to leave room for output
PROMPT_OVERHEAD_TOKENS = 500


@dataclass
class Batch:
    batch_id: int
    file_path: str               # Primary file (or "multi" for merged small files)
    hunk_ids: list[str]          # e.g. ["H1_abc123", "H2_def456"]
    file_paths: list[str]        # All files in this batch (>1 if small files merged)
    estimated_tokens: int
    is_new_file: bool = False


def plan_batches(
    file_diffs: list[FileDiff],
    inventory: dict[str, HunkRef],
    repo_root: Path,
    token_budget: int = DEFAULT_BATCH_TOKEN_BUDGET,
) -> list[Batch]:
    """Plan batches for Phase 1 summarization.

    Strategy:
    1. Group hunks by file (never split unless file exceeds budget).
    2. Estimate token cost per file.
    3. Single file fits budget → one batch per file.
    4. Single file exceeds budget → split into sub-batches.
    5. Small files → merge into multi-file batches.

    Returns:
        Ordered list of Batch objects.
    """
    # Group hunks by file
    file_groups: list[_FileGroup] = []
    for fd in file_diffs:
        if fd.is_binary or not fd.hunks:
            continue

        hunk_ids = [h.id for h in fd.hunks]
        est_tokens = _estimate_file_tokens(fd, inventory)

        file_groups.append(_FileGroup(
            file_path=fd.file_path,
            hunk_ids=hunk_ids,
            estimated_tokens=est_tokens,
            is_new_file=fd.is_new_file,
        ))

    batches: list[Batch] = []
    small_files: list[_FileGroup] = []
    batch_id = 0

    small_threshold = token_budget // 4

    for fg in file_groups:
        if fg.estimated_tokens > token_budget:
            # Large file: split into sub-batches by contiguous hunk groups
            sub_batches = _split_large_file(fg, token_budget, batch_id)
            batches.extend(sub_batches)
            batch_id += len(sub_batches)
        elif fg.estimated_tokens < small_threshold:
            small_files.append(fg)
        else:
            # Normal file: one batch
            batch_id += 1
            batches.append(Batch(
                batch_id=batch_id,
                file_path=fg.file_path,
                hunk_ids=fg.hunk_ids,
                file_paths=[fg.file_path],
                estimated_tokens=fg.estimated_tokens,
                is_new_file=fg.is_new_file,
            ))

    # Merge small files into multi-file batches
    if small_files:
        merged = _merge_small_files(small_files, token_budget, batch_id)
        batches.extend(merged)

    return batches


@dataclass
class _FileGroup:
    file_path: str
    hunk_ids: list[str]
    estimated_tokens: int
    is_new_file: bool = False


def _estimate_file_tokens(fd: FileDiff, inventory: dict[str, HunkRef]) -> int:
    """Estimate token count for a file's hunks + context."""
    total_chars = 0
    for hunk in fd.hunks:
        total_chars += sum(len(line) for line in hunk.lines)

    # Add context overhead (surrounding lines)
    context_chars = 60 * 80  # ~60 lines × 80 chars average
    total_chars += context_chars

    return (total_chars // CHARS_PER_TOKEN) + PROMPT_OVERHEAD_TOKENS


def _split_large_file(
    fg: _FileGroup,
    token_budget: int,
    start_batch_id: int,
) -> list[Batch]:
    """Split a large file into sub-batches of hunks."""
    batches: list[Batch] = []
    current_ids: list[str] = []
    current_tokens = PROMPT_OVERHEAD_TOKENS
    batch_id = start_batch_id

    per_hunk_budget = max(
        (token_budget - PROMPT_OVERHEAD_TOKENS) // max(len(fg.hunk_ids), 1),
        500,
    )

    for hid in fg.hunk_ids:
        hunk_tokens = per_hunk_budget
        if current_tokens + hunk_tokens > token_budget and current_ids:
            batch_id += 1
            batches.append(Batch(
                batch_id=batch_id,
                file_path=fg.file_path,
                hunk_ids=list(current_ids),
                file_paths=[fg.file_path],
                estimated_tokens=current_tokens,
                is_new_file=fg.is_new_file,
            ))
            current_ids = []
            current_tokens = PROMPT_OVERHEAD_TOKENS

        current_ids.append(hid)
        current_tokens += hunk_tokens

    if current_ids:
        batch_id += 1
        batches.append(Batch(
            batch_id=batch_id,
            file_path=fg.file_path,
            hunk_ids=list(current_ids),
            file_paths=[fg.file_path],
            estimated_tokens=current_tokens,
            is_new_file=fg.is_new_file,
        ))

    return batches


def _merge_small_files(
    small_files: list[_FileGroup],
    token_budget: int,
    start_batch_id: int,
) -> list[Batch]:
    """Merge small files into multi-file batches.

    Prefers merging files in the same directory.
    """
    # Sort by directory for locality
    small_files.sort(key=lambda fg: str(Path(fg.file_path).parent))

    batches: list[Batch] = []
    current_files: list[_FileGroup] = []
    current_tokens = PROMPT_OVERHEAD_TOKENS
    batch_id = start_batch_id

    for fg in small_files:
        if current_tokens + fg.estimated_tokens > token_budget and current_files:
            batch_id += 1
            all_hunk_ids = []
            all_paths = []
            for cf in current_files:
                all_hunk_ids.extend(cf.hunk_ids)
                all_paths.append(cf.file_path)
            batches.append(Batch(
                batch_id=batch_id,
                file_path="multi",
                hunk_ids=all_hunk_ids,
                file_paths=all_paths,
                estimated_tokens=current_tokens,
            ))
            current_files = []
            current_tokens = PROMPT_OVERHEAD_TOKENS

        current_files.append(fg)
        current_tokens += fg.estimated_tokens

    if current_files:
        batch_id += 1
        all_hunk_ids = []
        all_paths = []
        for cf in current_files:
            all_hunk_ids.extend(cf.hunk_ids)
            all_paths.append(cf.file_path)
        batches.append(Batch(
            batch_id=batch_id,
            file_path=all_paths[0] if len(all_paths) == 1 else "multi",
            hunk_ids=all_hunk_ids,
            file_paths=all_paths,
            estimated_tokens=current_tokens,
        ))

    return batches
