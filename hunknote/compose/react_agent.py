"""ReAct Orchestrator Agent for compose commit planning.

Coordinates 5 sub-agents (Dependency Analyzer, Grouper, Orderer,
Checkpoint Validator, Messenger) in a Think → Act → Observe loop.
The orchestrator can re-plan if validation fails.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

from hunknote.compose.agents.analyzer import DependencyAnalyzerAgent
from hunknote.compose.agents.grouper import GrouperAgent
from hunknote.compose.agents.messenger import MessengerAgent
from hunknote.compose.agents.orderer import OrdererAgent
from hunknote.compose.agents.validator import CheckpointValidatorAgent
from hunknote.compose.litellm_adapter import (
    calculate_token_budget,
    setup_litellm_api_keys,
    to_litellm_model,
)
from hunknote.compose.models import (
    AgentState,
    CommitGroup,
    ComposePlan,
    DependencyGraph,
    FileDiff,
    HunkRef,
)
from hunknote.compose.symbols import annotate_large_hunks, extract_all_symbols

logger = logging.getLogger(__name__)

# Maximum orchestrator iterations (including validation retries)
MAX_ORCHESTRATOR_ITERATIONS = 16

# Maximum validation retry attempts before falling back to single commit
MAX_VALIDATION_RETRIES = 3


class OrchestratorAgent:
    """ReAct orchestrator that coordinates sub-agents for commit planning.

    The orchestrator maintains the full state from every sub-agent at all
    times.  When validation fails, it passes the *previous* output and
    the validator's reasoning to the sub-agent that needs to fix it,
    enabling targeted corrections without starting from scratch.

    Workflow:
    1. Extract symbols (programmatic, pre-step)
    2. Call Dependency Analyzer (LLM sub-agent) → store dep_graph
    3. Call Grouper (LLM sub-agent)              → store groups
    4. Call Orderer (LLM sub-agent)              → store ordered_groups
    5. Call Checkpoint Validator (LLM sub-agent)
       - If invalid (grouping): pass previous groups + dep_graph +
         reasoning → Grouper → Orderer → re-validate
       - If invalid (ordering): pass previous ordered list + reasoning
         → Orderer → re-validate
    6. Call Messenger (LLM sub-agent)
    """

    def __init__(
        self,
        provider_name: str,
        model_name: str,
        file_diffs: list[FileDiff],
        inventory: dict[str, HunkRef],
        style: str = "blueprint",
        max_commits: int = 16,
        branch: str = "",
        recent_commits: list[str] | None = None,
        stream: bool = False,
    ):
        """Initialize the orchestrator.

        Args:
            provider_name: Hunknote provider name (e.g., "google").
            model_name: Model name (e.g., "gemini-2.5-flash").
            file_diffs: Parsed file diffs.
            inventory: Hunk inventory.
            style: Commit style profile.
            max_commits: Maximum number of commits.
            branch: Current branch name.
            recent_commits: Recent commit subjects.
            stream: Whether to stream status updates.
        """
        self.provider_name = provider_name
        self.model_name = model_name
        self.litellm_model = to_litellm_model(provider_name, model_name)
        self.stream = stream

        # Set up API keys for LiteLLM
        setup_litellm_api_keys(provider_name)

        # Calculate token budget
        total_lines = sum(
            len(h.lines) for h in inventory.values()
        )
        self.token_budget = calculate_token_budget(
            len(inventory), total_lines,
        )

        # State
        self.state = AgentState(
            file_diffs=file_diffs,
            inventory=inventory,
            style=style,
            max_commits=max_commits,
            branch=branch,
            recent_commits=recent_commits or [],
        )
        self.state.llm_model = model_name

        # ── Sub-agent state history ──
        # Keeps track of every sub-agent output + validator feedback so
        # that retry calls can receive the full context of what went
        # wrong and what was previously attempted.
        self._dep_graph: DependencyGraph | None = None
        self._groups_history: list[list[CommitGroup]] = []
        self._ordered_history: list[list[CommitGroup]] = []
        self._validation_history: list[dict] = []

    def run(self) -> AgentState:
        """Run the orchestrator pipeline.

        Returns:
            AgentState with the final plan and all metadata.
        """
        start_time = time.monotonic()
        self._trace("orchestrator_start", "activated", {
            "provider": self.provider_name,
            "model": self.model_name,
            "hunks": len(self.state.inventory),
            "files": len(self.state.file_diffs),
            "token_budget": self.token_budget,
        })

        try:
            # ── Phase 0: Programmatic symbol extraction ──
            self._emit("Extracting symbols...")
            t0 = time.monotonic()
            symbol_analyses = extract_all_symbols(self.state.inventory)
            large_hunk_annotations = annotate_large_hunks(
                self.state.inventory, self.state.file_diffs, symbol_analyses,
            )
            self._trace("phase_0_symbols", "completed", {
                "hunks_analysed": len(symbol_analyses),
                "large_hunks": len(large_hunk_annotations),
            }, time.monotonic() - t0)

            # Also build programmatic graph as a hint for the validator
            from hunknote.compose.graph import build_hunk_dependency_graph, detect_renames
            renames = detect_renames(symbol_analyses)
            prog_graph = build_hunk_dependency_graph(symbol_analyses, renames)

            # ── Phase 1: Dependency Analysis ──
            self._emit("Analysing dependencies...")
            t0 = time.monotonic()
            analyzer = DependencyAnalyzerAgent(
                model=self.litellm_model,
                inventory=self.state.inventory,
                file_diffs=self.state.file_diffs,
                symbol_analyses=symbol_analyses,
                max_tokens=min(self.token_budget // 2, 32768),
            )
            dep_graph = analyzer.run(
                stream_callback=self._emit if self.stream else None,
            )
            self.state.dependency_graph = dep_graph
            self._dep_graph = dep_graph
            self._accumulate_tokens(analyzer)
            self._trace("phase_1_analyzer", "completed", {
                "edges": len(dep_graph.edges),
                "independent_hunks": len(dep_graph.independent_hunks),
                **self._get_sub_trace(analyzer),
            }, time.monotonic() - t0)

            # ── Phase 2: Grouping ──
            self._emit("Grouping hunks into commits...")
            t0 = time.monotonic()
            grouper = GrouperAgent(
                model=self.litellm_model,
                inventory=self.state.inventory,
                file_diffs=self.state.file_diffs,
                max_tokens=min(self.token_budget // 4, 8192),
            )
            groups = grouper.run(
                dependency_graph=dep_graph,
                max_commits=self.state.max_commits,
                symbol_analyses=symbol_analyses,
                stream_callback=self._emit if self.stream else None,
            )
            self.state.commit_groups = groups
            self._groups_history.append(list(groups))
            self._accumulate_tokens(grouper)
            self._trace("phase_2_grouper", "completed", {
                "groups": len(groups),
                **self._get_sub_trace(grouper),
            }, time.monotonic() - t0)

            # ── Phase 3: Ordering ──
            self._emit("Ordering commits...")
            t0 = time.monotonic()
            orderer = OrdererAgent(
                model=self.litellm_model,
                max_tokens=min(self.token_budget // 4, 8192),
            )
            ordered_groups = orderer.run(
                groups=groups,
                dependency_graph=dep_graph,
                inventory=self.state.inventory,
                file_diffs=self.state.file_diffs,
                symbol_analyses=symbol_analyses,
                stream_callback=self._emit if self.stream else None,
            )
            self.state.ordered_groups = ordered_groups
            self._ordered_history.append(list(ordered_groups))
            self._accumulate_tokens(orderer)
            self._trace("phase_3_orderer", "completed", {
                "order": [f"C{i+1}" for i in range(len(ordered_groups))],
                **self._get_sub_trace(orderer),
            }, time.monotonic() - t0)

            # ── Phase 4: Validation (with intelligent retry loop) ──
            validation_passed = False
            # Track issue types across retries to detect oscillation
            retry_issue_history: list[str] = []
            for retry in range(MAX_VALIDATION_RETRIES + 1):
                retry_label = f" (retry {retry})" if retry > 0 else ""
                self._emit(f"Validating checkpoints{retry_label}...")
                t0 = time.monotonic()

                validator = CheckpointValidatorAgent(
                    model=self.litellm_model,
                    inventory=self.state.inventory,
                    file_diffs=self.state.file_diffs,
                    symbol_analyses=symbol_analyses,
                    repo_root=self._get_repo_root(),
                    max_tokens=min(self.token_budget // 3, 16384),
                )
                validation_result = validator.run(
                    ordered_groups=ordered_groups,
                    dependency_graph=dep_graph,
                    prog_graph=prog_graph,
                    stream_callback=self._emit if self.stream else None,
                )
                self.state.validation_result = validation_result
                self._validation_history.append(dict(validation_result))
                self._accumulate_tokens(validator)
                phase_details = {**validation_result, **self._get_sub_trace(validator)}
                self._trace(f"phase_4_validator{'_retry' + str(retry) if retry else ''}",
                            "completed", phase_details, time.monotonic() - t0)

                if validation_result.get("valid", False):
                    validation_passed = True
                    break

                # ── Filter out false-positive violations ──
                # Remove violations that reference imports from existing
                # (non-new) files — these are always valid.
                validation_result = self._filter_false_positives(
                    validation_result,
                )
                # Re-check if all violations were false positives
                if validation_result.get("valid", False):
                    validation_passed = True
                    self._trace(
                        f"phase_4_false_positives_filtered_retry{retry}",
                        "completed",
                        {"action": "all_violations_were_false_positives"},
                    )
                    break

                # ── Intelligent re-planning based on issue classification ──
                if retry < MAX_VALIDATION_RETRIES:
                    issue_type = validation_result.get("issue_type", "")
                    fix_reasoning = validation_result.get(
                        "fix_reasoning",
                        validation_result.get("reasoning_summary", ""),
                    )

                    # Build detailed violation summary for hints
                    violation_details = self._format_violation_details(
                        validation_result,
                    )

                    # Detect oscillation: require TWO full cycles of the
                    # same issue type pattern (4 consecutive same-type)
                    # before triggering a programmatic merge.  This gives
                    # the LLM sub-agents enough retries to fix the issue.
                    retry_issue_history.append(issue_type or "unknown")
                    if len(retry_issue_history) >= 4:
                        last_four = retry_issue_history[-4:]
                        if len(set(last_four)) == 1:
                            # Same issue type four times in a row — stuck
                            logger.info(
                                "Oscillation detected (%s repeated %d×), "
                                "switching to programmatic merge",
                                last_four[0], len(last_four),
                            )
                            self._emit("Oscillation detected, applying targeted merge...")
                            ordered_groups = self._fix_validation_failures(
                                ordered_groups, validation_result, dep_graph,
                            )
                            self.state.ordered_groups = ordered_groups
                            self._ordered_history.append(list(ordered_groups))
                            self._trace(
                                f"phase_4_oscillation_merge_retry{retry}",
                                "completed",
                                {"issue_types": retry_issue_history},
                            )
                            continue

                    # Build previous-state context for sub-agent hints
                    prev_groups_text = self._format_previous_groups()
                    prev_order_text = self._format_previous_ordering()

                    if issue_type == "ordering":
                        # Only the order is wrong → re-call Orderer with
                        # the previous ordering attempt and validator feedback
                        self._emit("Reordering commits to fix ordering issue...")
                        t0 = time.monotonic()
                        orderer = OrdererAgent(
                            model=self.litellm_model,
                            max_tokens=min(self.token_budget // 4, 8192),
                        )
                        reorder_hint = (
                            f"Previous ordering was invalid.\n"
                            f"Validator feedback: {fix_reasoning}\n"
                            f"Specific violations:\n{violation_details}\n\n"
                            f"[PREVIOUS ORDERING ATTEMPT]\n{prev_order_text}\n"
                            f"Fix ONLY the ordering — do not change which "
                            f"hunks belong to which group."
                        )
                        ordered_groups = orderer.run(
                            groups=ordered_groups,
                            dependency_graph=dep_graph,
                            inventory=self.state.inventory,
                            file_diffs=self.state.file_diffs,
                            symbol_analyses=symbol_analyses,
                            stream_callback=self._emit if self.stream else None,
                            reorder_hint=reorder_hint,
                        )
                        self.state.ordered_groups = ordered_groups
                        self._ordered_history.append(list(ordered_groups))
                        self._accumulate_tokens(orderer)
                        self._trace(
                            f"phase_4_reorder_retry{retry}",
                            "completed",
                            {**self._get_sub_trace(orderer)},
                            time.monotonic() - t0,
                        )

                    elif issue_type == "grouping":
                        # Hunks are mis-grouped → re-call Grouper with
                        # previous grouping attempt + dep_graph + reasoning,
                        # then Orderer
                        self._emit("Regrouping hunks to fix grouping issue...")
                        t0 = time.monotonic()
                        grouper = GrouperAgent(
                            model=self.litellm_model,
                            inventory=self.state.inventory,
                            file_diffs=self.state.file_diffs,
                            max_tokens=min(self.token_budget // 4, 8192),
                        )
                        regroup_hint = (
                            f"Previous grouping was invalid.\n"
                            f"Validator feedback: {fix_reasoning}\n"
                            f"Specific violations:\n{violation_details}\n\n"
                            f"[PREVIOUS GROUPING ATTEMPT]\n{prev_groups_text}\n"
                            f"Fix the grouping by moving the problematic "
                            f"hunk(s) to the correct group, or merging the "
                            f"affected groups. Keep the fix minimal."
                        )
                        groups = grouper.run(
                            dependency_graph=dep_graph,
                            max_commits=self.state.max_commits,
                            symbol_analyses=symbol_analyses,
                            stream_callback=self._emit if self.stream else None,
                            regroup_hint=regroup_hint,
                        )
                        self.state.commit_groups = groups
                        self._groups_history.append(list(groups))
                        self._accumulate_tokens(grouper)
                        self._trace(
                            f"phase_4_regroup_retry{retry}",
                            "completed",
                            {"groups": len(groups), **self._get_sub_trace(grouper)},
                            time.monotonic() - t0,
                        )

                        self._emit("Reordering regrouped commits...")
                        t0 = time.monotonic()
                        orderer = OrdererAgent(
                            model=self.litellm_model,
                            max_tokens=min(self.token_budget // 4, 8192),
                        )
                        ordered_groups = orderer.run(
                            groups=groups,
                            dependency_graph=dep_graph,
                            inventory=self.state.inventory,
                            file_diffs=self.state.file_diffs,
                            symbol_analyses=symbol_analyses,
                            stream_callback=self._emit if self.stream else None,
                        )
                        self.state.ordered_groups = ordered_groups
                        self._ordered_history.append(list(ordered_groups))
                        self._accumulate_tokens(orderer)
                        self._trace(
                            f"phase_4_reorder_after_regroup_retry{retry}",
                            "completed",
                            {**self._get_sub_trace(orderer)},
                            time.monotonic() - t0,
                        )

                    else:
                        # Unknown or missing classification → fallback
                        # to programmatic merge as a last resort
                        self._emit("Applying programmatic merge fix...")
                        ordered_groups = self._fix_validation_failures(
                            ordered_groups, validation_result, dep_graph,
                        )
                        self.state.ordered_groups = ordered_groups
                        self._ordered_history.append(list(ordered_groups))

            if not validation_passed:
                # Last resort: merge all into a single commit
                self._emit("Validation failed after retries, merging to single commit...")
                ordered_groups = [CommitGroup(
                    hunk_ids=sorted(self.state.inventory.keys()),
                    files=sorted(set(
                        h.file_path for h in self.state.inventory.values()
                    )),
                    reason="Merged: validation could not be fixed",
                )]
                self.state.ordered_groups = ordered_groups
                self._ordered_history.append(list(ordered_groups))
                self._trace("phase_4_fallback", "completed", {
                    "action": "merged_all_to_single_commit",
                })

            # ── Phase 5: Message Generation ──
            self._emit("Generating commit messages...")
            t0 = time.monotonic()
            messenger = MessengerAgent(
                model=self.litellm_model,
                max_tokens=min(self.token_budget // 3, 8192),
            )
            plan = messenger.run(
                ordered_groups=ordered_groups,
                inventory=self.state.inventory,
                file_diffs=self.state.file_diffs,
                style=self.state.style,
                branch=self.state.branch,
                recent_commits=self.state.recent_commits,
            )
            self.state.plan = plan
            self._accumulate_tokens(messenger)
            self._trace("phase_5_messenger", "completed", {
                "commits": len(plan.commits),
                **self._get_sub_trace(messenger),
            }, time.monotonic() - t0)

        except Exception as e:
            logger.error("Orchestrator failed: %s", e, exc_info=True)
            self._trace("orchestrator_error", "failed", {"error": str(e)})
            # Fallback to single-commit plan
            self.state.plan = ComposePlan(commits=[])

        duration = time.monotonic() - start_time
        self._trace("orchestrator_complete", "completed", {
            "total_duration_s": round(duration, 3),
            "total_input_tokens": self.state.total_input_tokens,
            "total_output_tokens": self.state.total_output_tokens,
            "commits": len(self.state.plan.commits) if self.state.plan else 0,
        }, duration)

        return self.state

    # ── Previous-state formatting helpers ──

    def _format_previous_groups(self) -> str:
        """Format the most recent grouping attempt for retry context.

        Returns a compact text representation of the last grouping so the
        Grouper sub-agent can see exactly what it produced before and make
        targeted corrections instead of starting from scratch.
        """
        if not self._groups_history:
            return "  (no previous grouping)"
        prev = self._groups_history[-1]
        lines: list[str] = []
        for i, g in enumerate(prev, 1):
            files = ", ".join(g.files[:5])
            if len(g.files) > 5:
                files += f" ... (+{len(g.files) - 5} more)"
            lines.append(
                f"  C{i}: hunks=[{', '.join(g.hunk_ids)}], "
                f"files=[{files}]"
            )
            if g.reason:
                lines.append(f"       intent: {g.reason}")
        return "\n".join(lines)

    def _format_previous_ordering(self) -> str:
        """Format the most recent ordering attempt for retry context.

        Returns a compact text representation of the last ordering so the
        Orderer sub-agent can see the exact sequence that failed and make
        targeted corrections.
        """
        if not self._ordered_history:
            return "  (no previous ordering)"
        prev = self._ordered_history[-1]
        lines: list[str] = []
        for i, g in enumerate(prev, 1):
            files = ", ".join(g.files[:4])
            if len(g.files) > 4:
                files += f" ... (+{len(g.files) - 4} more)"
            lines.append(
                f"  Position {i} — C{i}: hunks=[{', '.join(g.hunk_ids[:6])}]"
                f"{' ...' if len(g.hunk_ids) > 6 else ''}, files=[{files}]"
            )
        # Also show validation history if available
        if self._validation_history:
            latest_val = self._validation_history[-1]
            reasoning = latest_val.get("reasoning_summary", "")
            if reasoning:
                lines.append(f"\n  Last validator summary: {reasoning}")
        return "\n".join(lines)

    def _fix_validation_failures(
        self,
        groups: list[CommitGroup],
        validation_result: dict,
        dep_graph: DependencyGraph,
    ) -> list[CommitGroup]:
        """Attempt to fix validation failures by merging groups.

        Strategy: For each invalid checkpoint, merge the failing group
        with ALL groups that contain missing dependencies.
        If no specific merge target is found, merge with the next group.
        """
        checkpoints = validation_result.get("checkpoints", [])
        # Map source commit → set of target commits to merge with
        merge_targets: dict[str, set[str]] = {}
        invalid_commits: list[str] = []

        for cp in checkpoints:
            if not cp.get("valid", True):
                commit_id = cp.get("commit_id", "")
                if not commit_id:
                    continue
                invalid_commits.append(commit_id)
                for violation in cp.get("violations", []):
                    missing_from = violation.get("missing_from", "")
                    if missing_from and missing_from != commit_id:
                        # Handle comma-separated targets like "C1, C2"
                        for target in missing_from.replace(" ", "").split(","):
                            target = target.strip()
                            if target:
                                merge_targets.setdefault(commit_id, set()).add(target)

        if not invalid_commits:
            return groups

        # If invalid commits exist but no merge targets were specified,
        # merge each invalid commit with its successor (or predecessor)
        id_to_idx = {f"C{i+1}": i for i in range(len(groups))}
        for commit_id in invalid_commits:
            if commit_id not in merge_targets:
                idx = id_to_idx.get(commit_id)
                if idx is not None:
                    # Merge with next group if possible, else previous
                    if idx + 1 < len(groups):
                        merge_targets.setdefault(commit_id, set()).add(f"C{idx+2}")
                    elif idx > 0:
                        merge_targets.setdefault(commit_id, set()).add(f"C{idx}")

        # Build clusters of groups that must be merged together
        clusters: list[set[int]] = []
        for src_id, tgt_ids in merge_targets.items():
            src_idx = id_to_idx.get(src_id)
            if src_idx is None:
                continue
            cluster = {src_idx}
            for tgt_id in tgt_ids:
                tgt_idx = id_to_idx.get(tgt_id)
                if tgt_idx is not None:
                    cluster.add(tgt_idx)

            # Merge with existing overlapping clusters
            merged = False
            for existing in clusters:
                if cluster & existing:
                    existing |= cluster
                    merged = True
                    break
            if not merged:
                clusters.append(cluster)

        # Apply merges
        merged_indices: set[int] = set()
        new_groups = list(groups)

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            sorted_indices = sorted(cluster)
            target_idx = sorted_indices[0]
            all_hunks: list[str] = []
            all_files: list[str] = []
            for idx in sorted_indices:
                all_hunks.extend(new_groups[idx].hunk_ids)
                all_files.extend(new_groups[idx].files)
            new_groups[target_idx] = CommitGroup(
                hunk_ids=sorted(set(all_hunks)),
                files=sorted(set(all_files)),
                reason=f"Merged {', '.join(f'C{i+1}' for i in sorted_indices)} to fix checkpoints",
            )
            for idx in sorted_indices[1:]:
                merged_indices.add(idx)

        # Remove merged groups
        result = [g for i, g in enumerate(new_groups) if i not in merged_indices]
        return result

    def _filter_false_positives(
        self,
        validation_result: dict,
    ) -> dict:
        """Filter out false-positive violations from the validator output.

        The LLM validator sometimes flags imports from existing (non-new)
        files as broken.  This method removes violations that explicitly
        mention an existing file path (not a new file).

        A violation is a false positive when:
        - Its issue text mentions a specific module/file path
        - That path resolves to an EXISTING file (not being created by
          any hunk in this diff)
        - The violation says "not yet committed" or "defined by
          uncommitted hunk", but the file actually exists already

        We do NOT filter violations that:
        - Reference new files (could be real)
        - Don't mention any file path (could be about symbol deps)
        """
        new_file_paths: set[str] = set()
        for fd in self.state.file_diffs:
            if fd.is_new_file:
                new_file_paths.add(fd.file_path)

        # Build set of all file paths that are in the diff (new or existing)
        all_diff_paths: set[str] = set()
        existing_diff_paths: set[str] = set()
        for fd in self.state.file_diffs:
            all_diff_paths.add(fd.file_path)
            if not fd.is_new_file:
                existing_diff_paths.add(fd.file_path)

        # Build module-form paths for new files and existing files
        new_file_modules: set[str] = set()
        for nfp in new_file_paths:
            stem = nfp.rsplit(".", 1)[0] if "." in nfp else nfp
            new_file_modules.add(nfp)
            new_file_modules.add(stem)
            new_file_modules.add(stem.replace("/", "."))

        existing_file_modules: set[str] = set()
        for efp in existing_diff_paths:
            stem = efp.rsplit(".", 1)[0] if "." in efp else efp
            existing_file_modules.add(efp)
            existing_file_modules.add(stem)
            existing_file_modules.add(stem.replace("/", "."))

        checkpoints = validation_result.get("checkpoints", [])
        if not checkpoints:
            # No checkpoints to filter → return as-is
            return validation_result

        any_real_violation = False

        for cp in checkpoints:
            if cp.get("valid", True):
                continue
            violations = cp.get("violations", [])
            real_violations = []
            for v in violations:
                issue = v.get("issue", "")

                # Check if the issue mentions a file path from an
                # EXISTING file — if so, it's a false positive
                mentions_existing = any(
                    mod in issue for mod in existing_file_modules
                )
                mentions_new = any(
                    mod in issue for mod in new_file_modules
                )

                if mentions_existing and not mentions_new:
                    # Issue mentions an existing file but no new file
                    # → false positive (existing file is always available)
                    logger.debug(
                        "Filtered false-positive violation: %s", issue,
                    )
                else:
                    # Either references a new file, or doesn't mention
                    # any specific file path → keep it as real
                    real_violations.append(v)

            if real_violations:
                cp["violations"] = real_violations
                any_real_violation = True
            else:
                # All violations were false positives → mark valid
                cp["valid"] = True
                cp.pop("violations", None)

        if not any_real_violation:
            validation_result["valid"] = True

        return validation_result

    @staticmethod
    def _format_violation_details(validation_result: dict) -> str:
        """Format violation details from a validation result for hints.

        Creates a concise, actionable summary that can be passed as a
        reorder_hint or regroup_hint to the Orderer/Grouper sub-agents.
        """
        lines: list[str] = []
        for cp in validation_result.get("checkpoints", []):
            if cp.get("valid", True):
                continue
            commit_id = cp.get("commit_id", "?")
            for v in cp.get("violations", []):
                hunk = v.get("hunk", "?")
                issue = v.get("issue", "?")
                missing = v.get("missing_from", "?")
                fix = v.get("fix", "?")
                lines.append(
                    f"  - {commit_id}/{hunk}: {issue} "
                    f"(needs {missing}, fix={fix})"
                )
        return "\n".join(lines) if lines else "  (no specific violations)"

    def _accumulate_tokens(self, agent: Any) -> None:
        """Accumulate token usage from a sub-agent's last result."""
        last = getattr(agent, "last_result", None)
        if last:
            self.state.total_input_tokens += last.input_tokens
            self.state.total_output_tokens += last.output_tokens
            self.state.total_thinking_tokens += last.thinking_tokens

    @staticmethod
    def _get_sub_trace(agent: Any) -> dict:
        """Extract sub-agent trace details for embedding in orchestrator trace.

        Returns a dict with the sub-agent's iteration-level trace, token
        usage, success/failure status, and error message if any.
        """
        last = getattr(agent, "last_result", None)
        if not last:
            return {}
        return {
            "sub_agent_name": getattr(agent, "name", "unknown"),
            "iterations": last.iterations,
            "success": last.success,
            "error": last.error,
            "input_tokens": last.input_tokens,
            "output_tokens": last.output_tokens,
            "thinking_tokens": last.thinking_tokens,
            "duration_s": last.duration_seconds,
            "trace": last.trace,
            "raw_response_snippet": (last.raw_response[:500] if last.raw_response else ""),
        }

    def _get_repo_root(self) -> str | None:
        """Get the git repo root for file-existence checks."""
        try:
            from hunknote.git_ctx import get_repo_root
            return get_repo_root()
        except Exception:
            pass
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _emit(self, message: str) -> None:
        """Emit a status message to stderr if streaming is enabled."""
        if self.stream:
            print(message, file=sys.stderr, flush=True)

    def _trace(
        self,
        phase: str,
        status: str,
        details: dict | None = None,
        duration: float = 0.0,
    ) -> None:
        """Add a trace entry to the state."""
        entry: dict[str, Any] = {
            "phase": phase,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(duration, 4),
        }
        if details:
            entry["details"] = details
        self.state.trace_log.append(entry)


def run_react_agent(
    provider_name: str,
    model_name: str,
    file_diffs: list[FileDiff],
    inventory: dict[str, HunkRef],
    style: str = "blueprint",
    max_commits: int = 16,
    branch: str = "",
    recent_commits: list[str] | None = None,
    stream: bool = False,
) -> AgentState:
    """Convenience function to run the ReAct orchestrator.

    Args:
        provider_name: LLM provider name.
        model_name: Model name.
        file_diffs: File diffs.
        inventory: Hunk inventory.
        style: Commit style.
        max_commits: Max commits.
        branch: Branch name.
        recent_commits: Recent commits.
        stream: Whether to stream status.

    Returns:
        AgentState with the final plan.
    """
    orchestrator = OrchestratorAgent(
        provider_name=provider_name,
        model_name=model_name,
        file_diffs=file_diffs,
        inventory=inventory,
        style=style,
        max_commits=max_commits,
        branch=branch,
        recent_commits=recent_commits,
        stream=stream,
    )
    return orchestrator.run()

