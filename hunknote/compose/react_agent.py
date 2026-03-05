"""True ReAct orchestrator for compose planning."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from hunknote.compose.agents import (
    CheckpointValidatorAgent,
    DependencyAnalyzerAgent,
    GrouperAgent,
    MessengerAgent,
    OrdererAgent,
)
from hunknote.compose.agents.prompts import ORCHESTRATOR_PROMPT
from hunknote.compose.agents.tools import extract_symbol_info
from hunknote.compose.litellm_adapter import (
    extract_usage,
    litellm_completion,
    parse_tool_arguments,
    setup_litellm_api_keys,
    to_litellm_model,
)
from hunknote.compose.models import CommitGroup, ComposePlan, FileDiff, HunkRef

logger = logging.getLogger(__name__)


MAX_ORCHESTRATOR_ITERATIONS = 14
MAX_VALIDATION_RETRIES = 4


@dataclass
class ReactComposeResult:
    """Result returned by ReAct compose planner."""

    plan: ComposePlan
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    model: str = ""
    trace: list[dict] = field(default_factory=list)
    mode: str = "react"


class OrchestratorAgent:
    """Main orchestrator using LLM tool-calling to coordinate sub-agents."""

    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        style: str,
        max_commits: int,
        branch: str,
        recent_commits: list[str],
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.litellm_model = to_litellm_model(provider_name, model_name)
        self.inventory = inventory
        self.file_diffs = file_diffs
        self.style = style
        self.max_commits = max_commits
        self.branch = branch
        self.recent_commits = recent_commits

        setup_litellm_api_keys(provider_name)

        self.symbol_info = extract_symbol_info(inventory)

        self.dependency_graph: dict = {"edges": [], "reasoning_summary": ""}
        self.commit_groups: list[CommitGroup] = []
        self.ordered_groups: list[CommitGroup] = []
        self.validation_result: dict = {}
        self.plan: ComposePlan | None = None

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_thinking_tokens = 0
        self.trace: list[dict] = []
        self.validation_retries = 0

    def run(self) -> ReactComposeResult:
        tools = self._tool_definitions()
        messages = [
            {"role": "system", "content": ORCHESTRATOR_PROMPT},
            {"role": "user", "content": self._build_initial_context()},
        ]

        for iteration in range(1, MAX_ORCHESTRATOR_ITERATIONS + 1):
            response = litellm_completion(
                model=self.litellm_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=4096,
            )
            in_t, out_t, think_t = extract_usage(response)
            self.total_input_tokens += in_t
            self.total_output_tokens += out_t
            self.total_thinking_tokens += think_t

            message = response.choices[0].message
            messages.append(self._sanitize_message(message))

            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                for tc in tool_calls:
                    tool_name = tc.function.name
                    args = parse_tool_arguments(tc.function.arguments)
                    result_obj = self._dispatch_tool(tool_name, args)
                    self.trace.append({
                        "iteration": iteration,
                        "tool": tool_name,
                        "args": args,
                        "result": result_obj,
                    })
                    tc_id = tc.id[:64] if tc.id and len(tc.id) > 64 else tc.id
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(result_obj),
                    })
                if self.plan is not None and self.validation_result.get("valid", False):
                    break
                continue

            payload = self._extract_json(message.content or "")
            self.trace.append({
                "iteration": iteration,
                "assistant_final": payload or (message.content or "")[:300],
            })
            if payload.get("status") == "complete" and self.plan is not None:
                break

            # If no tool calls and no completion payload, push the model forward.
            messages.append({
                "role": "user",
                "content": (
                    "Continue using tools to finish planning. If plan is ready, "
                    "output {\"status\": \"complete\"}."
                ),
            })

        final_plan = self.plan or self._fallback_plan()
        return ReactComposeResult(
            plan=final_plan,
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
            thinking_tokens=self.total_thinking_tokens,
            model=self.model_name,
            trace=self.trace,
            mode="react",
        )

    def _build_initial_context(self) -> str:
        hunk_ids = sorted(self.inventory.keys())
        files = sorted({h.file_path for h in self.inventory.values()})
        return (
            "Plan commits for these staged hunks.\n"
            f"hunks={len(hunk_ids)} files={len(files)} max_commits={self.max_commits}\n"
            f"style={self.style} branch={self.branch}\n"
            f"hunk_ids={hunk_ids}\n"
            f"files={files}\n"
            "Use tool calls to complete all phases."
        )

    def _tool_definitions(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "call_dependency_analyzer",
                    "description": "Analyze hunk dependencies. Call first.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_grouper",
                    "description": "Group hunks into atomic commit groups.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "regroup_hint": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_orderer",
                    "description": "Order commit groups for valid checkpoints.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reorder_hint": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_checkpoint_validator",
                    "description": "Validate checkpoint sequence and classify issues.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "merge_groups",
                    "description": "Merge two commit groups by ID if needed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commit_a_id": {"type": "string"},
                            "commit_b_id": {"type": "string"},
                        },
                        "required": ["commit_a_id", "commit_b_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_messenger",
                    "description": "Generate final commit messages once validation is valid.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_state_snapshot",
                    "description": "Return current orchestrator planning state.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]

    def _dispatch_tool(self, tool_name: str, args: dict) -> dict:
        if tool_name == "call_dependency_analyzer":
            return self._call_dependency_analyzer()
        if tool_name == "call_grouper":
            return self._call_grouper(regroup_hint=args.get("regroup_hint", ""))
        if tool_name == "call_orderer":
            return self._call_orderer(reorder_hint=args.get("reorder_hint", ""))
        if tool_name == "call_checkpoint_validator":
            return self._call_checkpoint_validator()
        if tool_name == "merge_groups":
            return self._merge_groups(args.get("commit_a_id", ""), args.get("commit_b_id", ""))
        if tool_name == "call_messenger":
            return self._call_messenger()
        if tool_name == "get_state_snapshot":
            return self._get_state_snapshot()
        return {"error": f"unknown tool: {tool_name}"}

    def _call_dependency_analyzer(self) -> dict:
        agent = DependencyAnalyzerAgent(
            model=self.litellm_model,
            inventory=self.inventory,
            file_diffs=self.file_diffs,
            symbol_info=self.symbol_info,
        )
        graph = agent.run()
        self.dependency_graph = graph
        self._accumulate_agent_tokens(agent)
        self._record_subagent_trace("dependency_analyzer", agent)
        return {
            "ok": True,
            "edges": len(graph.get("edges", [])),
            "summary": graph.get("reasoning_summary", ""),
        }

    def _call_grouper(self, regroup_hint: str = "") -> dict:
        if not self.dependency_graph:
            return {"ok": False, "error": "dependency graph missing"}
        agent = GrouperAgent(
            model=self.litellm_model,
            inventory=self.inventory,
            file_diffs=self.file_diffs,
        )
        groups = agent.run(
            dependency_graph=self.dependency_graph,
            max_commits=self.max_commits,
            regroup_hint=regroup_hint,
        )
        self.commit_groups = groups
        self.ordered_groups = groups
        self._accumulate_agent_tokens(agent)
        self._record_subagent_trace("grouper", agent)
        return {"ok": True, "groups": len(groups)}

    def _call_orderer(self, reorder_hint: str = "") -> dict:
        groups = self.ordered_groups or self.commit_groups
        if not groups:
            return {"ok": False, "error": "groups missing"}
        agent = OrdererAgent(model=self.litellm_model)
        ordered = agent.run(
            groups=groups,
            dependency_graph=self.dependency_graph,
            reorder_hint=reorder_hint,
        )
        self.ordered_groups = ordered
        self._accumulate_agent_tokens(agent)
        self._record_subagent_trace("orderer", agent)
        return {"ok": True, "ordered_groups": len(ordered)}

    def _call_checkpoint_validator(self) -> dict:
        groups = self.ordered_groups or self.commit_groups
        if not groups:
            return {"ok": False, "error": "ordered groups missing"}
        agent = CheckpointValidatorAgent(
            model=self.litellm_model,
            inventory=self.inventory,
            file_diffs=self.file_diffs,
            symbol_info=self.symbol_info,
        )
        result = agent.run(groups, self.dependency_graph)
        self.validation_result = result
        self._accumulate_agent_tokens(agent)
        self._record_subagent_trace("checkpoint_validator", agent)

        if result.get("valid", False):
            return {"ok": True, "valid": True}

        self.validation_retries += 1
        if self.validation_retries <= MAX_VALIDATION_RETRIES:
            issue_type = result.get("issue_type") or "ordering"
            hint = result.get("fix_reasoning", "")
            if issue_type == "grouping":
                self._call_grouper(regroup_hint=hint)
                self._call_orderer()
            else:
                self._call_orderer(reorder_hint=hint)
        else:
            # Hard fallback
            self.commit_groups = [
                CommitGroup(
                    hunk_ids=sorted(self.inventory.keys()),
                    files=sorted({h.file_path for h in self.inventory.values()}),
                    reason="Merged after repeated validation failures",
                )
            ]
            self.ordered_groups = self.commit_groups
            self.validation_result = {"valid": True, "checkpoints": []}

        return {
            "ok": True,
            "valid": bool(self.validation_result.get("valid", False)),
            "issue_type": result.get("issue_type"),
            "validation_retries": self.validation_retries,
        }

    def _merge_groups(self, commit_a_id: str, commit_b_id: str) -> dict:
        groups = self.ordered_groups or self.commit_groups
        if not groups:
            return {"ok": False, "error": "groups missing"}

        id_to_index = {f"C{i+1}": i for i in range(len(groups))}
        if commit_a_id not in id_to_index or commit_b_id not in id_to_index:
            return {"ok": False, "error": "unknown commit id"}

        a = id_to_index[commit_a_id]
        b = id_to_index[commit_b_id]
        if a == b:
            return {"ok": True, "merged": False, "reason": "same commit id"}

        lo, hi = sorted((a, b))
        merged = CommitGroup(
            hunk_ids=sorted(set(groups[lo].hunk_ids + groups[hi].hunk_ids)),
            files=sorted(set(groups[lo].files + groups[hi].files)),
            reason=f"Merged {commit_a_id} and {commit_b_id}",
        )
        new_groups = list(groups)
        new_groups[lo] = merged
        new_groups.pop(hi)
        self.commit_groups = new_groups
        self.ordered_groups = new_groups

        return {"ok": True, "merged": True, "groups": len(new_groups)}

    def _call_messenger(self) -> dict:
        groups = self.ordered_groups or self.commit_groups
        if not groups:
            return {"ok": False, "error": "groups missing"}
        if not self.validation_result.get("valid", False):
            return {"ok": False, "error": "validation has not passed"}

        agent = MessengerAgent(model=self.litellm_model)
        self.plan = agent.run(
            ordered_groups=groups,
            inventory=self.inventory,
            style=self.style,
            branch=self.branch,
            recent_commits=self.recent_commits,
        )
        self._accumulate_agent_tokens(agent)
        self._record_subagent_trace("messenger", agent)

        return {"ok": True, "commits": len(self.plan.commits)}

    def _get_state_snapshot(self) -> dict:
        return {
            "has_dependency_graph": bool(self.dependency_graph),
            "groups": len(self.commit_groups),
            "ordered_groups": len(self.ordered_groups),
            "validation_valid": bool(self.validation_result.get("valid", False)),
            "has_plan": self.plan is not None,
        }

    def _fallback_plan(self) -> ComposePlan:
        groups = self.ordered_groups or self.commit_groups
        if not groups:
            groups = [
                CommitGroup(
                    hunk_ids=sorted(self.inventory.keys()),
                    files=sorted({h.file_path for h in self.inventory.values()}),
                    reason="Fallback single commit",
                )
            ]
        agent = MessengerAgent(model=self.litellm_model)
        plan = agent.run(
            ordered_groups=groups,
            inventory=self.inventory,
            style=self.style,
            branch=self.branch,
            recent_commits=self.recent_commits,
        )
        self._accumulate_agent_tokens(agent)
        self._record_subagent_trace("messenger_fallback", agent)
        return plan

    def _accumulate_agent_tokens(self, agent: Any) -> None:
        last = getattr(agent, "last_result", None)
        if not last:
            return
        self.total_input_tokens += last.input_tokens
        self.total_output_tokens += last.output_tokens
        self.total_thinking_tokens += last.thinking_tokens

    def _record_subagent_trace(self, phase: str, agent: Any) -> None:
        """Persist a compact but detailed sub-agent trace entry."""
        last = getattr(agent, "last_result", None)
        if not last:
            return
        self.trace.append({
            "phase": phase,
            "success": last.success,
            "error": last.error,
            "iterations": last.iterations,
            "duration_s": last.duration_seconds,
            "input_tokens": last.input_tokens,
            "output_tokens": last.output_tokens,
            "thinking_tokens": last.thinking_tokens,
            "trace": last.trace,
            "raw_response_snippet": (last.raw_response or "")[:800],
        })

    @staticmethod
    def _sanitize_message(message: Any) -> dict:
        dumped = message.model_dump() if hasattr(message, "model_dump") else {
            "role": "assistant",
            "content": getattr(message, "content", ""),
        }
        cleaned = dict(dumped)
        cleaned.pop("provider_specific_fields", None)
        cleaned.pop("thinking_blocks", None)
        calls = cleaned.get("tool_calls") or []
        if calls:
            for call in calls:
                cid = call.get("id")
                if isinstance(cid, str) and len(cid) > 64:
                    call["id"] = cid[:64]
                call.pop("provider_specific_fields", None)
        return cleaned

    @staticmethod
    def _extract_json(text: str) -> dict:
        if not text:
            return {}
        text = text.strip()
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
        if "{" in text and "}" in text:
            start = text.find("{")
            end = text.rfind("}")
            if end > start:
                try:
                    obj = json.loads(text[start:end + 1])
                    return obj if isinstance(obj, dict) else {}
                except Exception:
                    return {}
        return {}


def run_react_compose_planner(
    *,
    provider_name: str,
    model_name: str,
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    style: str,
    max_commits: int,
    branch: str,
    recent_commits: list[str],
) -> ReactComposeResult:
    """Convenience wrapper to execute the ReAct compose planner."""
    orchestrator = OrchestratorAgent(
        provider_name=provider_name,
        model_name=model_name,
        inventory=inventory,
        file_diffs=file_diffs,
        style=style,
        max_commits=max_commits,
        branch=branch,
        recent_commits=recent_commits,
    )
    return orchestrator.run()
