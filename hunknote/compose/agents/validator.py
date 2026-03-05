"""Checkpoint validator sub-agent."""

from __future__ import annotations

import json
import logging

from hunknote.compose.agents.base import BaseSubAgent
from hunknote.compose.agents.prompts import CHECKPOINT_VALIDATOR_PROMPT
from hunknote.compose.agents.tools import (
    get_checkpoint_state,
    programmatic_checkpoint_validation,
    repo_regex_search,
)
from hunknote.compose.models import CommitGroup, FileDiff, HunkRef

logger = logging.getLogger(__name__)


class CheckpointValidatorAgent(BaseSubAgent):
    """Validate checkpoint integrity across ordered commit groups."""

    def __init__(
        self,
        *,
        model: str,
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        symbol_info,
        repo_root: str = ".",
        max_tokens: int = 16000,
    ) -> None:
        super().__init__(
            name="CheckpointValidator",
            model=model,
            system_prompt=CHECKPOINT_VALIDATOR_PROMPT,
            max_iterations=6,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        self.inventory = inventory
        self.file_diffs = file_diffs
        self.symbol_info = symbol_info
        self.repo_root = repo_root
        self._ordered_groups: list[CommitGroup] = []

        self.register_tool(
            name="get_checkpoint_state",
            func=self._tool_checkpoint_state,
            description="Get committed and remaining hunks for checkpoint N.",
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint": {"type": "integer"},
                },
                "required": ["checkpoint"],
            },
        )
        self.register_tool(
            name="repo_regex_search",
            func=lambda pattern, path_glob="", max_results=40: repo_regex_search(
                pattern=pattern,
                repo_root=self.repo_root,
                path_glob=path_glob,
                max_results=max_results,
            ),
            description="Search repository text with regex via ripgrep.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path_glob": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["pattern"],
            },
        )

    def run(self, ordered_groups: list[CommitGroup], dependency_graph: dict) -> dict:
        self._ordered_groups = ordered_groups

        programmatic = programmatic_checkpoint_validation(
            ordered_groups,
            self.inventory,
            self.file_diffs,
            self.symbol_info,
        )

        compact_groups = [
            {
                "id": f"C{i}",
                "hunk_ids": group.hunk_ids,
                "files": group.files,
                "intent": group.reason,
            }
            for i, group in enumerate(ordered_groups, start=1)
        ]

        prompt = f"""Validate commit checkpoints.

[ORDERED_GROUPS]
{json.dumps(compact_groups, indent=2)}

[DEPENDENCY_GRAPH]
{json.dumps(dependency_graph, indent=2)}

[PROGRAMMATIC_HINT]
{json.dumps(programmatic, indent=2)}

Return JSON now."""

        # Keep it efficient: if programmatic says valid, use single call.
        if programmatic.get("valid", False):
            result = self._single_call(prompt)
        else:
            result = self._react_loop(prompt)

        if not result.success or not result.output:
            logger.warning("Validator failed, using programmatic fallback: %s", result.error)
            return programmatic

        normalized = self._normalize(result.output, ordered_groups)
        return self._merge_with_programmatic(normalized, programmatic)

    def _tool_checkpoint_state(self, checkpoint: int) -> str:
        return get_checkpoint_state(checkpoint, self._ordered_groups, self.inventory)

    @staticmethod
    def _normalize(payload: dict, ordered_groups: list[CommitGroup]) -> dict:
        checkpoints = payload.get("checkpoints")
        if not isinstance(checkpoints, list):
            payload["checkpoints"] = []
            payload["valid"] = False
            payload["issue_type"] = payload.get("issue_type") or "ordering"
            payload["fix_reasoning"] = payload.get("fix_reasoning") or "validator output missing checkpoints"
            return payload

        for cp in checkpoints:
            if cp.get("valid", True):
                continue
            for violation in cp.get("violations", []):
                missing = (violation.get("missing_from") or "").strip()
                if not missing or not missing.startswith("C"):
                    # Coerce to a concrete commit id so repair logic can act.
                    violation["missing_from"] = f"C{len(ordered_groups)}"

        payload["valid"] = all(bool(cp.get("valid", False)) for cp in checkpoints)
        if payload["valid"]:
            payload["issue_type"] = None
        else:
            payload["issue_type"] = payload.get("issue_type") or "ordering"
        return payload

    @staticmethod
    def _merge_with_programmatic(llm_payload: dict, programmatic: dict) -> dict:
        """Programmatic violations are authoritative for checkpoint validity."""
        if programmatic.get("valid", True):
            return llm_payload

        merged = dict(llm_payload)
        merged["valid"] = False
        merged["issue_type"] = programmatic.get("issue_type") or merged.get("issue_type") or "ordering"

        llm_reason = (llm_payload.get("fix_reasoning") or "").strip()
        prog_reason = (programmatic.get("fix_reasoning") or "").strip()
        if llm_reason and prog_reason:
            merged["fix_reasoning"] = f"{llm_reason} Programmatic check: {prog_reason}"
        else:
            merged["fix_reasoning"] = llm_reason or prog_reason or "Programmatic checkpoint violations detected."

        # Prefer deterministic checkpoint details.
        merged["checkpoints"] = programmatic.get("checkpoints", llm_payload.get("checkpoints", []))
        return merged
