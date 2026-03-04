"""Dependency Analyzer sub-agent.

Analyses hunks to identify semantic dependencies between them. Uses the
LLM to reason about cross-hunk relationships that programmatic analysis
may miss (re-exports, transitive chains, semantic coupling).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from hunknote.compose.agents.base import BaseSubAgent, SubAgentResult
from hunknote.compose.agents.prompts import DEPENDENCY_ANALYZER_PROMPT
from hunknote.compose.agents.tools import (
    build_hunk_summary_text,
    get_file_hunks,
    get_hunk_diff,
    get_symbol_summary,
)
from hunknote.compose.models import (
    DependencyEdge,
    DependencyGraph,
    FileDiff,
    HunkRef,
    HunkSymbols,
)
from hunknote.compose.agents.xref import build_import_xref

logger = logging.getLogger(__name__)


class DependencyAnalyzerAgent(BaseSubAgent):
    """Sub-agent that identifies dependencies between hunks."""

    def __init__(
        self,
        model: str,
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        symbol_analyses: dict[str, HunkSymbols],
        max_iterations: int = 8,
        temperature: float = 0.0,
        max_tokens: int = 32768,
    ):
        super().__init__(
            name="DependencyAnalyzer",
            system_prompt=DEPENDENCY_ANALYZER_PROMPT,
            model=model,
            max_iterations=max_iterations,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.inventory = inventory
        self.file_diffs = file_diffs
        self.symbol_analyses = symbol_analyses

        # Register tools
        self.register_tool(
            name="get_hunk_diff",
            func=lambda hunk_ids: get_hunk_diff(hunk_ids, self.inventory),
            description="Get the raw diff lines for one or more hunks.",
            parameters={
                "type": "object",
                "properties": {
                    "hunk_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of hunk IDs to retrieve.",
                    },
                },
                "required": ["hunk_ids"],
            },
        )

        self.register_tool(
            name="get_file_hunks",
            func=lambda file_path: get_file_hunks(file_path, self.file_diffs),
            description="Get all hunk IDs belonging to a specific file.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path of the file.",
                    },
                },
                "required": ["file_path"],
            },
        )

        self.register_tool(
            name="get_symbol_summary",
            func=lambda hunk_ids: get_symbol_summary(hunk_ids, self.symbol_analyses),
            description="Get extracted symbol info (defines, references, imports) for given hunks.",
            parameters={
                "type": "object",
                "properties": {
                    "hunk_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of hunk IDs.",
                    },
                },
                "required": ["hunk_ids"],
            },
        )

    def run(
        self,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> DependencyGraph:
        """Run dependency analysis and return a DependencyGraph.

        Args:
            stream_callback: Optional callback for streaming status.

        Returns:
            DependencyGraph with edges and independent hunks.
        """
        # Build user prompt with hunk summaries
        summary_text = build_hunk_summary_text(
            self.inventory, self.file_diffs, self.symbol_analyses,
        )

        # Build a quick import→definition cross-reference
        import_xref = self._build_import_xref()

        user_prompt = f"""\
Analyse the following hunks and identify ALL dependencies between them.

[HUNKS]
{summary_text}

[IMPORT → DEFINITION CROSS-REFERENCE]
{import_xref}

The cross-reference above was pre-computed from static analysis of the
hunks. Each line shows a hunk importing a symbol or module from another
hunk. Convert the REAL dependencies into edges in your JSON output.

Filter out noise: some cross-reference lines may be false positives from
broad module-path matching (e.g., sibling files under the same package
that don't actually import from each other). Only include edges where
the source hunk genuinely depends on the target hunk.

IMPORTANT — keep your JSON output COMPACT:
- Use VERY short reasons (max 10 words per edge), e.g. "imports User model"
- Do NOT repeat file paths in reasons — the hunk IDs are sufficient
- Deduplicate: if H_A depends on H_B for multiple symbols from the same
  file, emit only ONE edge with the strongest strength

Output the JSON object now."""

        result = self._react_loop(user_prompt, stream_callback)

        if not result.success or not result.output:
            logger.warning("Dependency analysis failed: %s", result.error)
            return DependencyGraph(
                independent_hunks=list(self.inventory.keys()),
                reasoning_summary=f"Analysis failed: {result.error}",
            )

        return self._parse_output(result)

    def _build_import_xref(self) -> str:
        """Build a cross-reference of imports → definitions across hunks.

        Delegates to the language-aware ``build_import_xref`` in the
        xref module, which handles Python, TypeScript, Go, Rust, Java,
        C/C++, Ruby, and a generic fallback.
        """
        return build_import_xref(self.symbol_analyses, self.file_diffs)

    def _parse_output(self, result: SubAgentResult) -> DependencyGraph:
        """Parse the agent output into a DependencyGraph."""
        data = result.output
        edges: list[DependencyEdge] = []

        for edge_data in data.get("edges", []):
            source = edge_data.get("source", "")
            target = edge_data.get("target", "")
            if source and target:
                edges.append(DependencyEdge(
                    source=source,
                    target=target,
                    reason=edge_data.get("reason", ""),
                    strength=edge_data.get("strength", "must_be_ordered"),
                ))

        return DependencyGraph(
            edges=edges,
            independent_hunks=data.get("independent_hunks", []),
            reasoning_summary=data.get("reasoning_summary", ""),
        )

