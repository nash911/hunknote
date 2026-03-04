"""Checkpoint Validator sub-agent.

Validates that every intermediate checkpoint in the proposed commit
sequence leaves the codebase in a valid state.  Uses BOTH programmatic
validation (as a hint) and LLM-based semantic reasoning to catch issues
that heuristics miss (whole-file hunks, re-export chains, cross-language
coupling, build system dependencies).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from hunknote.compose.agents.base import BaseSubAgent
from hunknote.compose.agents.prompts import CHECKPOINT_VALIDATOR_PROMPT
from hunknote.compose.agents.tools import (
    check_file_in_repo,
    get_checkpoint_state,
    get_definitions_at_checkpoint,
    get_imports_at_checkpoint,
    run_programmatic_validation,
)
from hunknote.compose.models import (
    CommitGroup,
    DependencyGraph,
    FileDiff,
    HunkRef,
    HunkSymbols,
)

logger = logging.getLogger(__name__)


class CheckpointValidatorAgent(BaseSubAgent):
    """Sub-agent that validates commit checkpoint validity."""

    def __init__(
        self,
        model: str,
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        symbol_analyses: dict[str, HunkSymbols],
        repo_root: str | None = None,
        max_iterations: int = 8,
        temperature: float = 0.0,
        max_tokens: int = 16384,
    ):
        super().__init__(
            name="CheckpointValidator",
            system_prompt=CHECKPOINT_VALIDATOR_PROMPT,
            model=model,
            max_iterations=max_iterations,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.inventory = inventory
        self.file_diffs = file_diffs
        self.symbol_analyses = symbol_analyses
        self.repo_root = repo_root

        # Programmatic graph for tool use
        self._prog_graph: dict[str, set[str]] = {}
        self._all_hunk_ids: set[str] = set(inventory.keys())

        # Register tools
        self._register_validator_tools()

    def _register_validator_tools(self) -> None:
        """Register tools for checkpoint validation."""
        self.register_tool(
            name="get_checkpoint_state",
            func=self._tool_checkpoint_state,
            description="Get committed/remaining hunks at a specific checkpoint.",
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint": {
                        "type": "integer",
                        "description": "1-based checkpoint index.",
                    },
                },
                "required": ["checkpoint"],
            },
        )

        self.register_tool(
            name="get_imports_at_checkpoint",
            func=self._tool_imports_at_checkpoint,
            description="List all imports added by committed hunks at a checkpoint.",
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint": {
                        "type": "integer",
                        "description": "1-based checkpoint index.",
                    },
                },
                "required": ["checkpoint"],
            },
        )

        self.register_tool(
            name="get_definitions_at_checkpoint",
            func=self._tool_definitions_at_checkpoint,
            description="List all symbols defined by committed hunks at a checkpoint.",
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint": {
                        "type": "integer",
                        "description": "1-based checkpoint index.",
                    },
                },
                "required": ["checkpoint"],
            },
        )

        self.register_tool(
            name="run_programmatic_check",
            func=self._tool_programmatic_check,
            description="Run heuristic-based checkpoint validation as a hint.",
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint": {
                        "type": "integer",
                        "description": "1-based checkpoint index.",
                    },
                },
                "required": ["checkpoint"],
            },
        )

        self.register_tool(
            name="check_file_exists",
            func=self._tool_check_file_exists,
            description=(
                "Check if a file already exists in the repository (not part of "
                "any hunk). Returns whether the file exists, is git-tracked, and "
                "what symbols it exports. Use this to verify that imports from "
                "unchanged existing files are valid."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path relative to repo root.",
                    },
                },
                "required": ["file_path"],
            },
        )

    def run(
        self,
        ordered_groups: list[CommitGroup],
        dependency_graph: DependencyGraph,
        prog_graph: dict[str, set[str]] | None = None,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """Validate all checkpoints in the commit sequence.

        Args:
            ordered_groups: Ordered commit groups.
            dependency_graph: Semantic dependency graph.
            prog_graph: Optional programmatic dependency graph.
            stream_callback: Optional streaming callback.

        Returns:
            Validation result dict with "valid", "checkpoints", etc.
        """
        self._ordered_groups = ordered_groups
        self._prog_graph = prog_graph or {}

        # Build checkpoint summary for context
        checkpoint_text = self._format_checkpoints(ordered_groups)
        dep_summary = self._format_dependency_summary(dependency_graph)
        file_context = self._format_file_context()

        # Pre-compute programmatic validation for ALL checkpoints
        prog_results, all_prog_pass = self._precompute_programmatic_checks(
            ordered_groups,
        )

        # Build explicit safe-imports whitelist: imports that reference
        # existing (non-new) files and are ALWAYS valid regardless of
        # commit order.
        safe_imports_text = self._build_safe_imports_list()

        # Build the map of imports that actually point to NEW files —
        # these are the ONLY ones that can cause checkpoint violations.
        new_file_imports_text = self._build_new_file_import_map(ordered_groups)

        user_prompt = f"""\
Validate the following commit sequence. For EACH checkpoint, determine
whether the codebase would be in a valid state.

[FILE CONTEXT]
{file_context}

[COMMIT SEQUENCE]
{checkpoint_text}

[DEPENDENCY SUMMARY]
{dep_summary}

[PROGRAMMATIC CHECK RESULTS]
{prog_results}

The programmatic check results above are pre-computed.
{"All programmatic checks passed — confirm with your own reasoning." if all_prog_pass else "Some checks flagged violations — investigate using tools if needed."}

[IMPORTS FROM EXISTING FILES — ALWAYS VALID]
{safe_imports_text}
↑ ALL of the above imports are from files that ALREADY EXIST in the
repository. Do NOT flag ANY of these as violations. They are always valid
at every checkpoint, regardless of commit order.

[IMPORTS FROM NEW FILES — POTENTIALLY INVALID]
{new_file_imports_text}
↑ ONLY these imports can be invalid. A checkpoint is broken ONLY if a
hunk that imports from a NEW file is committed BEFORE the hunk that
creates that new file.

IMPORTANT RULES:
- ONLY flag an import as broken if it references a NEW file whose
  creating hunk has NOT been committed at that checkpoint.
- NEVER flag imports from existing files as violations.
- If you are unsure whether a file is new or existing, check the
  [FILE CONTEXT] section above — it explicitly lists new vs existing.

Output your validation as the specified JSON object.
Keep your response COMPACT — use short issue descriptions."""

        # When all programmatic checks pass, use a single LLM call
        # (no tools) to avoid the model making unnecessary tool calls
        # that exhaust context and produce empty responses.
        if all_prog_pass:
            result = self._single_call(user_prompt)
        else:
            result = self._react_loop(user_prompt, stream_callback)

        if not result.success or not result.output:
            logger.warning("Validation failed: %s", result.error)
            return {
                "valid": False,
                "checkpoints": [],
                "reasoning_summary": f"Validation failed: {result.error}",
            }

        return result.output

    def _format_file_context(self) -> str:
        """Format file context showing new vs existing files."""
        new_files = []
        existing_files = []
        for fd in self.file_diffs:
            if fd.is_new_file:
                new_files.append(fd.file_path)
            else:
                existing_files.append(fd.file_path)

        lines = []
        if new_files:
            lines.append("  NEW files (created by hunks in this diff):")
            for f in sorted(new_files):
                lines.append(f"    - {f}")
            lines.append("  → These files do NOT exist until their hunks are committed.")
        if existing_files:
            lines.append("  EXISTING files (already in repo, being modified):")
            for f in sorted(existing_files):
                lines.append(f"    - {f}")
            lines.append("  → These files already exist. Imports from them are always valid.")
        lines.append("  All other files in the repository are unchanged and always available.")
        return "\n".join(lines)

    def _format_checkpoints(self, groups: list[CommitGroup]) -> str:
        """Format the commit sequence for the prompt."""
        lines = []
        for i, g in enumerate(groups, 1):
            files_str = ", ".join(g.files[:5])
            if len(g.files) > 5:
                files_str += f" ... (+{len(g.files) - 5} more)"
            lines.append(
                f"  Checkpoint {i} (C{i}): {len(g.hunk_ids)} hunks, "
                f"files: {files_str}"
            )
            # Show key hunks
            for hid in g.hunk_ids[:4]:
                hunk = self.inventory.get(hid)
                if hunk:
                    sym = self.symbol_analyses.get(hid)
                    sym_info = ""
                    if sym:
                        parts = []
                        if sym.defines:
                            parts.append(f"def: {', '.join(sorted(sym.defines)[:3])}")
                        if sym.imports_added:
                            parts.append(f"imp: {', '.join(sorted(sym.imports_added)[:3])}")
                        if sym.exports_added:
                            parts.append(f"exp: {', '.join(sorted(sym.exports_added)[:3])}")
                        if parts:
                            sym_info = f" [{'; '.join(parts)}]"
                    lines.append(f"    {hid}: {hunk.file_path}{sym_info}")
            if len(g.hunk_ids) > 4:
                lines.append(f"    ... and {len(g.hunk_ids) - 4} more hunks")
        return "\n".join(lines)

    def _format_dependency_summary(self, graph: DependencyGraph) -> str:
        """Format dependency graph summary."""
        if not graph.edges:
            return "  No dependencies."
        lines = []
        for e in graph.edges[:30]:
            lines.append(f"  {e.source} → {e.target} [{e.strength}]: {e.reason[:80]}")
        if len(graph.edges) > 30:
            lines.append(f"  ... and {len(graph.edges) - 30} more edges")
        return "\n".join(lines)

    # ── Pre-computation ──

    def _build_safe_imports_list(self) -> str:
        """Build an explicit whitelist of imports from existing files.

        Any import that resolves to a file NOT being created by any hunk
        in this diff is unconditionally safe at every checkpoint.  We
        enumerate them so the LLM cannot hallucinate violations for them.
        """
        new_file_paths: set[str] = set()
        for fd in self.file_diffs:
            if fd.is_new_file:
                new_file_paths.add(fd.file_path)

        # Collect all imports from all hunks, and classify each one
        safe_lines: list[str] = []
        for hid, sym in self.symbol_analyses.items():
            if not sym.imports_added:
                continue
            for imp in sorted(sym.imports_added):
                # Check if this import path points to a new file
                points_to_new = False
                # Convert import to potential file paths
                import_as_path = imp.replace(".", "/")
                for nfp in new_file_paths:
                    # Strip extension for comparison
                    nfp_stem = nfp.rsplit(".", 1)[0] if "." in nfp else nfp
                    if (
                        import_as_path == nfp_stem
                        or import_as_path.startswith(nfp_stem + "/")
                        or nfp_stem.endswith("/" + import_as_path)
                        or nfp_stem.endswith(import_as_path)
                    ):
                        points_to_new = True
                        break
                if not points_to_new:
                    safe_lines.append(f"  {hid} ({sym.file_path}): {imp}")

        if not safe_lines:
            return "  (No imports from existing files detected)"
        # Deduplicate and limit size
        seen: set[str] = set()
        deduped: list[str] = []
        for line in safe_lines:
            if line not in seen:
                seen.add(line)
                deduped.append(line)
        if len(deduped) > 50:
            deduped = deduped[:50]
            deduped.append(f"  ... and {len(safe_lines) - 50} more safe imports")
        return "\n".join(deduped)

    def _build_new_file_import_map(
        self, ordered_groups: list[CommitGroup],
    ) -> str:
        """Build a map of imports that point to NEW files.

        For each hunk that imports from a new file, shows which
        checkpoint creates that file so the validator knows exactly
        when the import becomes valid.
        """
        new_file_paths: set[str] = set()
        for fd in self.file_diffs:
            if fd.is_new_file:
                new_file_paths.add(fd.file_path)

        if not new_file_paths:
            return "  No new files in this diff — all imports are always valid."

        # Map new file path → which checkpoint creates it
        file_to_checkpoint: dict[str, int] = {}
        for ck_idx, grp in enumerate(ordered_groups, 1):
            for hid in grp.hunk_ids:
                hunk = self.inventory.get(hid)
                if hunk and hunk.file_path in new_file_paths:
                    # First hunk creating this file sets the checkpoint
                    if hunk.file_path not in file_to_checkpoint:
                        file_to_checkpoint[hunk.file_path] = ck_idx

        lines: list[str] = []
        for hid, sym in self.symbol_analyses.items():
            if not sym.imports_added:
                continue
            for imp in sorted(sym.imports_added):
                import_as_path = imp.replace(".", "/")
                for nfp in new_file_paths:
                    nfp_stem = nfp.rsplit(".", 1)[0] if "." in nfp else nfp
                    if (
                        import_as_path == nfp_stem
                        or import_as_path.startswith(nfp_stem + "/")
                        or nfp_stem.endswith("/" + import_as_path)
                        or nfp_stem.endswith(import_as_path)
                    ):
                        created_at = file_to_checkpoint.get(nfp, "?")
                        lines.append(
                            f"  {hid} ({sym.file_path}) imports '{imp}' "
                            f"→ new file {nfp} (created at C{created_at})"
                        )
                        break

        if not lines:
            return "  No imports from new files detected."
        # Deduplicate
        return "\n".join(sorted(set(lines)))

    def _precompute_programmatic_checks(
        self, ordered_groups: list[CommitGroup],
    ) -> tuple[str, bool]:
        """Run programmatic checkpoint validation for all checkpoints.

        Returns a tuple of (text_summary, all_valid) where text_summary
        can be included in the prompt and all_valid indicates if every
        checkpoint passed.
        """
        lines = []
        all_valid = True
        for i in range(1, len(ordered_groups) + 1):
            result_json = run_programmatic_validation(
                i, ordered_groups, self._prog_graph,
                self.symbol_analyses, self._all_hunk_ids,
            )
            import json as _json
            result = _json.loads(result_json)
            valid = result.get("valid", True)
            violations = result.get("violations", [])
            if valid:
                lines.append(f"  Checkpoint {i} (C{i}): PASS")
            else:
                all_valid = False
                lines.append(f"  Checkpoint {i} (C{i}): FAIL")
                for v in violations[:3]:
                    lines.append(
                        f"    - {v.get('hunk', '?')}: {v.get('issue', '?')[:80]}"
                    )
                if len(violations) > 3:
                    lines.append(f"    ... and {len(violations) - 3} more")

        if all_valid:
            lines.append("  → All programmatic checks passed.")
        return "\n".join(lines), all_valid

    # ── Tool implementations ──

    def _tool_checkpoint_state(self, checkpoint: int) -> str:
        return get_checkpoint_state(
            checkpoint, self._ordered_groups, self.inventory, self.file_diffs,
        )

    def _tool_imports_at_checkpoint(self, checkpoint: int) -> str:
        return get_imports_at_checkpoint(
            checkpoint, self._ordered_groups, self.symbol_analyses,
        )

    def _tool_definitions_at_checkpoint(self, checkpoint: int) -> str:
        return get_definitions_at_checkpoint(
            checkpoint, self._ordered_groups, self.symbol_analyses,
        )

    def _tool_programmatic_check(self, checkpoint: int) -> str:
        return run_programmatic_validation(
            checkpoint, self._ordered_groups, self._prog_graph,
            self.symbol_analyses, self._all_hunk_ids,
        )

    def _tool_check_file_exists(self, file_path: str) -> str:
        return check_file_in_repo(file_path, self.repo_root)

