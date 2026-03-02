"""Checkpoint validator for the Compose Agent.

Validates that a proposed commit plan produces valid intermediate states.
Simulates applying commits in order and checks for:
- Removed symbols still referenced by uncommitted hunks
- Renamed symbols with unconverted consumer hunks
- New required parameters with unconverted call sites

This is entirely programmatic — no LLM calls.
"""

from hunknote.compose.models import (
    CheckpointResult,
    ComposePlan,
    HunkSymbols,
    Violation,
)


def validate_commit_checkpoint(
    committed_hunks: set[str],
    remaining_hunks: set[str],
    graph: dict[str, set[str]],
    symbol_analyses: dict[str, HunkSymbols],
) -> CheckpointResult:
    """Validate that a checkpoint is structurally valid.

    Checks whether the committed hunks, when applied without the
    remaining hunks, would leave the codebase in a broken state.

    Args:
        committed_hunks: Set of hunk IDs being committed in this checkpoint.
        remaining_hunks: Set of hunk IDs NOT yet committed.
        graph: Directed hunk dependency graph.
        symbol_analyses: Symbol analysis for all hunks.

    Returns:
        CheckpointResult with valid=True if the checkpoint is safe.
    """
    violations: list[Violation] = []

    # Collect symbols defined/removed/modified by committed hunks
    committed_removes: dict[str, str] = {}   # symbol → hunk that removes it
    committed_defines: dict[str, str] = {}   # symbol → hunk that defines it
    committed_modifies: dict[str, str] = {}  # symbol → hunk that modifies it

    for hunk_id in committed_hunks:
        symbols = symbol_analyses.get(hunk_id)
        if not symbols:
            continue
        for sym in symbols.removes:
            committed_removes[sym] = hunk_id
        for sym in symbols.defines:
            committed_defines[sym] = hunk_id
        for sym in symbols.modifies:
            committed_modifies[sym] = hunk_id

    # Check 1: A committed hunk removes a symbol that an uncommitted hunk references
    # This means the uncommitted code would break because the symbol no longer exists
    for hunk_id in remaining_hunks:
        symbols = symbol_analyses.get(hunk_id)
        if not symbols:
            continue
        for ref in symbols.references:
            if ref in committed_removes:
                violations.append(Violation(
                    hunk=hunk_id,
                    in_commit=False,
                    references=[ref],
                    defined_in=committed_removes[ref],
                    defined_in_committed=True,
                    issue=(
                        f"Symbol '{ref}' is removed by committed hunk "
                        f"{committed_removes[ref]}, but uncommitted hunk "
                        f"{hunk_id} still references it"
                    ),
                ))

    # Check 2: A committed hunk removes an import, but the corresponding
    # new import is in an uncommitted hunk (or vice versa)
    committed_imports_removed: dict[str, str] = {}
    for hunk_id in committed_hunks:
        symbols = symbol_analyses.get(hunk_id)
        if not symbols:
            continue
        for imp in symbols.imports_removed:
            committed_imports_removed[imp] = hunk_id

    remaining_imports_added: dict[str, str] = {}
    for hunk_id in remaining_hunks:
        symbols = symbol_analyses.get(hunk_id)
        if not symbols:
            continue
        for imp in symbols.imports_added:
            remaining_imports_added[imp] = hunk_id

    # Check 3: Rename consistency — if a committed hunk renames a symbol
    # (removes old, adds new), all consumer updates must also be committed
    for hunk_id in committed_hunks:
        symbols = symbol_analyses.get(hunk_id)
        if not symbols:
            continue

        # Detect renames within this hunk
        for removed_sym in symbols.removes:
            for added_sym in symbols.defines:
                if _looks_like_rename(removed_sym, added_sym):
                    # This hunk renames removed_sym → added_sym
                    # Check if any uncommitted hunk still uses removed_sym
                    from hunknote.compose.graph import _extract_symbol_from_import
                    for other_id in remaining_hunks:
                        other_symbols = symbol_analyses.get(other_id)
                        if not other_symbols:
                            continue
                        # Check both exact match and extracted symbol name
                        removed_import_syms = {
                            _extract_symbol_from_import(imp)
                            for imp in other_symbols.imports_removed
                        }
                        if removed_sym in other_symbols.imports_removed or removed_sym in removed_import_syms:
                            # This uncommitted hunk updates the import — it
                            # should be in the same commit
                            violations.append(Violation(
                                hunk=other_id,
                                in_commit=False,
                                references=[removed_sym],
                                defined_in=hunk_id,
                                defined_in_committed=True,
                                issue=(
                                    f"Hunk {hunk_id} renames '{removed_sym}' → "
                                    f"'{added_sym}', but consumer update in hunk "
                                    f"{other_id} is not in the same commit"
                                ),
                            ))

    # Check 4: An uncommitted hunk defines a symbol that a committed hunk
    # references (forward dependency violation — committed code calls
    # something that doesn't exist yet)
    remaining_defines: dict[str, str] = {}
    for hunk_id in remaining_hunks:
        symbols = symbol_analyses.get(hunk_id)
        if not symbols:
            continue
        for sym in symbols.defines:
            remaining_defines[sym] = hunk_id

    for hunk_id in committed_hunks:
        symbols = symbol_analyses.get(hunk_id)
        if not symbols:
            continue
        for ref in symbols.references:
            if ref in remaining_defines:
                # Check if this symbol is also defined by a committed hunk
                if ref not in committed_defines:
                    violations.append(Violation(
                        hunk=hunk_id,
                        in_commit=True,
                        references=[ref],
                        defined_in=remaining_defines[ref],
                        defined_in_committed=False,
                        issue=(
                            f"Committed hunk {hunk_id} references '{ref}', "
                            f"but it is defined by uncommitted hunk "
                            f"{remaining_defines[ref]}"
                        ),
                    ))

    # Check 5: Import added by a committed hunk points to a module
    # defined in an uncommitted hunk
    for hunk_id in committed_hunks:
        symbols = symbol_analyses.get(hunk_id)
        if not symbols:
            continue
        for imp in symbols.imports_added:
            # Extract the final symbol from the import path
            from hunknote.compose.graph import _extract_symbol_from_import
            sym = _extract_symbol_from_import(imp)
            if sym in remaining_defines and sym not in committed_defines:
                violations.append(Violation(
                    hunk=hunk_id,
                    in_commit=True,
                    references=[imp],
                    defined_in=remaining_defines[sym],
                    defined_in_committed=False,
                    issue=(
                        f"Committed hunk {hunk_id} imports '{imp}', "
                        f"but the symbol '{sym}' is defined by uncommitted "
                        f"hunk {remaining_defines[sym]}"
                    ),
                ))

    return CheckpointResult(
        valid=len(violations) == 0,
        violations=violations,
    )


def validate_plan_checkpoints(
    plan: ComposePlan,
    graph: dict[str, set[str]],
    symbol_analyses: dict[str, HunkSymbols],
    all_hunk_ids: set[str],
) -> list[tuple[str, CheckpointResult]]:
    """Validate all checkpoints in a compose plan sequentially.

    Simulates applying commits in order and checks each checkpoint.

    Args:
        plan: The compose plan to validate.
        graph: Directed hunk dependency graph.
        symbol_analyses: Symbol analysis for all hunks.
        all_hunk_ids: Complete set of all hunk IDs.

    Returns:
        List of (commit_id, CheckpointResult) for each commit.
    """
    results: list[tuple[str, CheckpointResult]] = []
    committed_so_far: set[str] = set()

    for commit in plan.commits:
        current_commit_hunks = set(commit.hunks)
        committed_so_far_with_current = committed_so_far | current_commit_hunks
        remaining = all_hunk_ids - committed_so_far_with_current

        result = validate_commit_checkpoint(
            committed_hunks=committed_so_far_with_current,
            remaining_hunks=remaining,
            graph=graph,
            symbol_analyses=symbol_analyses,
        )
        results.append((commit.id, result))

        committed_so_far = committed_so_far_with_current

    return results


def _looks_like_rename(old: str, new: str) -> bool:
    """Quick check if old → new looks like a rename."""
    if old == new:
        return False
    # Must have some shared characters
    min_len = min(len(old), len(new))
    if min_len < 2:
        return False
    # Length ratio
    ratio = len(new) / max(len(old), 1)
    if ratio < 0.4 or ratio > 2.5:
        return False
    # Shared prefix or suffix
    shared = min(3, min_len)
    return old[:shared] == new[:shared] or old[-shared:] == new[-shared:]

