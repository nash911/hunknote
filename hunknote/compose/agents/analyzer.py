"""Dependency analyzer sub-agent."""

from __future__ import annotations

import json
import logging

from hunknote.compose.agents.base import BaseSubAgent
from hunknote.compose.agents.prompts import DEPENDENCY_ANALYZER_PROMPT
from hunknote.compose.agents.tools import (
    build_hunk_summaries,
    build_programmatic_dependencies,
    get_file_hunks,
    get_hunk_diff,
    repo_regex_search,
    get_symbol_summary,
)
from hunknote.compose.models import FileDiff, HunkRef

logger = logging.getLogger(__name__)


class DependencyAnalyzerAgent(BaseSubAgent):
    """LLM dependency analyzer with tool support."""

    def __init__(
        self,
        *,
        model: str,
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        symbol_info,
        repo_root: str = ".",
        max_tokens: int = 12000,
    ) -> None:
        super().__init__(
            name="DependencyAnalyzer",
            model=model,
            system_prompt=DEPENDENCY_ANALYZER_PROMPT,
            max_iterations=6,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        self.inventory = inventory
        self.file_diffs = file_diffs
        self.symbol_info = symbol_info
        self.repo_root = repo_root

        self.register_tool(
            name="get_hunk_diff",
            func=lambda hunk_ids: get_hunk_diff(hunk_ids, self.inventory),
            description="Return raw changed lines for selected hunks.",
            parameters={
                "type": "object",
                "properties": {
                    "hunk_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["hunk_ids"],
            },
        )
        self.register_tool(
            name="get_file_hunks",
            func=lambda file_path: get_file_hunks(file_path, self.file_diffs),
            description="Return hunk IDs for one file.",
            parameters={
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        )
        self.register_tool(
            name="get_symbol_summary",
            func=lambda hunk_ids: get_symbol_summary(hunk_ids, self.symbol_info),
            description="Return symbol/import summary for hunks.",
            parameters={
                "type": "object",
                "properties": {
                    "hunk_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["hunk_ids"],
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

    def run(self) -> dict:
        summary = build_hunk_summaries(self.inventory, self.file_diffs)
        prog_edges = build_programmatic_dependencies(
            self.inventory,
            self.file_diffs,
            self.symbol_info,
        )

        prompt = f"""Analyze dependencies for these hunks.

[HUNKS]
{summary}

[PROGRAMMATIC HINT EDGES]
{json.dumps(prog_edges, indent=2)}

Return JSON now."""

        result = self._react_loop(prompt)
        if result.success and result.output:
            return result.output

        logger.warning("Dependency analyzer failed, returning programmatic fallback: %s", result.error)
        return {
            "edges": prog_edges,
            "reasoning_summary": "Fallback to programmatic dependency hints.",
        }
