"""Tracing infrastructure for the Compose Agent pipeline.

Every phase, tool call, and LLM call emits trace events. The trace is:
1. A nested JSON tree mirroring the pipeline call hierarchy.
2. Saved incrementally to .hunknote/agent_trace.json after each phase.
3. Cleared when the compose plan is committed.
4. Displayed on stderr when --trace flag is used.
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class TraceEventType(Enum):
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    VALIDATION_CHECK = "validation_check"
    VALIDATION_FAIL = "validation_fail"
    VALIDATION_PASS = "validation_pass"
    GATE_CHECK = "gate_check"
    GATE_VIOLATION = "gate_violation"
    GATE_PASS = "gate_pass"
    REMEDIATION = "remediation"
    STATE_CHANGE = "state_change"
    BATCH_PLAN = "batch_plan"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class TraceEvent:
    event_type: TraceEventType
    phase: str
    message: str
    timestamp: float = field(default_factory=time.time)
    duration_ms: Optional[float] = None
    tokens: Optional[dict[str, int]] = None
    data: Optional[dict[str, Any]] = None
    children: list["TraceEvent"] = field(default_factory=list)


class AgentTrace:
    """Collects trace events from all phases of the agent pipeline.

    Produces a nested tree:
      orchestrator_run
        ├── phase1
        │     ├── batch_plan
        │     ├── llm_call (batch 1)
        │     └── llm_response (batch 1)
        ├── phase2
        │     ├── llm_call (ReAct iteration 1)
        │     ├── tool_call (ripgrep)
        │     └── tool_result
        └── ...
    """

    def __init__(self):
        self.root: TraceEvent = TraceEvent(
            event_type=TraceEventType.PHASE_START,
            phase="orchestrator",
            message="Agent pipeline started",
        )
        self._stack: list[TraceEvent] = [self.root]
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_thinking_tokens: int = 0
        self._total_llm_calls: int = 0
        self._saved_duration_ms: Optional[float] = None

    @property
    def _current_parent(self) -> TraceEvent:
        return self._stack[-1]

    def _append(self, event: TraceEvent) -> None:
        self._current_parent.children.append(event)

    def emit(self, event: TraceEvent) -> None:
        """Append an arbitrary event to the current scope."""
        self._append(event)

    def phase_start(self, phase: str, message: str = "") -> None:
        """Open a new phase scope. Subsequent events nest under it."""
        event = TraceEvent(
            event_type=TraceEventType.PHASE_START,
            phase=phase,
            message=message or f"Starting {phase}",
        )
        self._append(event)
        self._stack.append(event)

    def phase_end(self, phase: str, message: str = "") -> None:
        """Close the current phase scope and record duration."""
        if len(self._stack) > 1 and self._stack[-1].phase == phase:
            started = self._stack[-1]
            started.duration_ms = (time.time() - started.timestamp) * 1000
            started.event_type = TraceEventType.PHASE_END
            if message:
                started.message = message
            self._stack.pop()

    def llm_call(self, phase: str, system_prompt: str, user_prompt: str,
                 model: str = "") -> None:
        """Record a complete LLM call with FULL prompts."""
        self._total_llm_calls += 1
        self._append(TraceEvent(
            event_type=TraceEventType.LLM_CALL,
            phase=phase,
            message=f"LLM call #{self._total_llm_calls}",
            data={
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model,
            },
        ))

    def llm_response(self, phase: str, raw_response: str, model: str,
                     tokens: dict[str, int], duration_ms: float) -> None:
        """Record a complete LLM response with FULL output."""
        self._total_input_tokens += tokens.get("input", 0)
        self._total_output_tokens += tokens.get("output", 0)
        self._total_thinking_tokens += tokens.get("thinking", 0)
        self._append(TraceEvent(
            event_type=TraceEventType.LLM_RESPONSE,
            phase=phase,
            message=f"LLM response from {model}",
            duration_ms=duration_ms,
            tokens=tokens,
            data={"raw_response": raw_response, "model": model},
        ))

    def tool_call(self, phase: str, tool_name: str, args: dict) -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.TOOL_CALL,
            phase=phase,
            message=f"Tool call: {tool_name}",
            data={"tool_name": tool_name, "args": args},
        ))

    def tool_result(self, phase: str, tool_name: str, output: str,
                    success: bool, duration_ms: float) -> None:
        """Record tool result with FULL output."""
        self._append(TraceEvent(
            event_type=TraceEventType.TOOL_RESULT,
            phase=phase,
            message=f"Tool result: {tool_name} ({'ok' if success else 'fail'})",
            duration_ms=duration_ms,
            data={"tool_name": tool_name, "output": output, "success": success},
        ))

    def validation_check(self, phase: str, commit_id: str, layer: str) -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.VALIDATION_CHECK,
            phase=phase,
            message=f"Validation check: {commit_id} @ {layer}",
            data={"commit_id": commit_id, "layer": layer},
        ))

    def validation_pass(self, phase: str, commit_id: str) -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.VALIDATION_PASS,
            phase=phase,
            message=f"Validation passed: {commit_id}",
            data={"commit_id": commit_id},
        ))

    def validation_fail(self, phase: str, commit_id: str, layer: str,
                        error: str) -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.VALIDATION_FAIL,
            phase=phase,
            message=f"Validation failed: {commit_id} @ {layer}",
            data={"commit_id": commit_id, "layer": layer, "error": error},
        ))

    def gate_violation(self, phase: str, violations: list[dict]) -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.GATE_VIOLATION, phase=phase,
            message=f"Gate check failed: {len(violations)} violation(s)",
            data={"violations": violations},
        ))

    def gate_pass(self, phase: str, message: str = "") -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.GATE_PASS, phase=phase,
            message=message or "Gate check passed",
        ))

    def state_change(self, phase: str, message: str,
                     data: Optional[dict] = None) -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.STATE_CHANGE, phase=phase,
            message=message, data=data,
        ))

    def warning(self, phase: str, message: str,
                data: Optional[dict] = None) -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.WARNING, phase=phase,
            message=message, data=data,
        ))

    def batch_plan(self, phase: str, batches: list[dict]) -> None:
        self._append(TraceEvent(
            event_type=TraceEventType.BATCH_PLAN, phase=phase,
            message=f"Planned {len(batches)} batch(es)",
            data={"batches": batches},
        ))

    # ── Persistence ──

    def save_to_file(self, repo_root: Path) -> None:
        """Save the full trace tree to .hunknote/agent_trace.json."""
        trace_file = repo_root / ".hunknote" / "agent_trace.json"
        trace_file.parent.mkdir(parents=True, exist_ok=True)

        trace_data = {
            "version": "1",
            "summary": self.get_summary(),
            "trace": _event_to_dict(self.root),
        }
        trace_file.write_text(json.dumps(trace_data, indent=2, default=str))

    @staticmethod
    def load_from_file(repo_root: Path) -> Optional["AgentTrace"]:
        """Load a saved trace from .hunknote/agent_trace.json.

        Returns None if the file doesn't exist or is invalid.
        """
        trace_file = repo_root / ".hunknote" / "agent_trace.json"
        if not trace_file.exists():
            return None
        try:
            data = json.loads(trace_file.read_text())
            trace = AgentTrace()
            trace.root = _dict_to_event(data["trace"])
            # Restore counters from summary
            summary = data.get("summary", {})
            trace._total_llm_calls = summary.get("total_llm_calls", 0)
            trace._total_input_tokens = summary.get("total_input_tokens", 0)
            trace._total_output_tokens = summary.get("total_output_tokens", 0)
            trace._total_thinking_tokens = summary.get("total_thinking_tokens", 0)
            trace._saved_duration_ms = summary.get("total_duration_ms")
            return trace
        except Exception:
            return None

    @staticmethod
    def clear_trace_file(repo_root: Path) -> None:
        """Delete the trace file. Called when the compose plan is committed."""
        trace_file = repo_root / ".hunknote" / "agent_trace.json"
        if trace_file.exists():
            trace_file.unlink()

    # ── Reporting ──

    def get_summary(self) -> dict:
        return {
            "total_llm_calls": self._total_llm_calls,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_thinking_tokens": self._total_thinking_tokens,
            "total_duration_ms": (
                self._saved_duration_ms
                if self._saved_duration_ms is not None
                else round((time.time() - self.root.timestamp) * 1000, 2)
            ),
        }

    def format_for_stderr(self, verbose: bool = False) -> str:
        """Format the trace for stderr output.

        verbose=False: Compact progress summary.
        verbose=True: Detailed narrative trace with colors and structure.
        """
        if verbose:
            return _format_trace_verbose(self.root, self.get_summary())
        return _format_trace_compact(self.root, self.get_summary())


# ── ANSI color helpers ──

_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_WHITE = "\033[37m"

_PHASE_NAMES = {
    "phase1": "Summarize Hunks",
    "phase2": "Build Dependency Graph",
    "phase3": "Cluster into Commits",
    "phase4": "Order Commits",
    "phase5": "Validate Commit Sequence",
    "phase5b": "Diagnose Failure",
    "phase6": "Generate Commit Messages",
}


def _fmt_duration(ms: float | None) -> str:
    if ms is None:
        return ""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def _fmt_tokens(tok: dict | None) -> str:
    if not tok:
        return ""
    inp = tok.get("input", 0)
    out = tok.get("output", 0)
    return f"{inp + out:,} tokens"


# ── Compact format ──


def _format_trace_compact(root: TraceEvent, summary: dict) -> str:
    """Clean, color-coded phase summary."""
    lines: list[str] = []
    lines.append(f"{_BOLD}Agent Trace{_RESET}")
    lines.append(f"{_DIM}{'─' * 60}{_RESET}")

    # Collect top-level phases and retry-related events
    attempt = 0
    for child in root.children:
        et = child.event_type

        if et in (TraceEventType.PHASE_START, TraceEventType.PHASE_END):
            phase_label = _PHASE_NAMES.get(child.phase, child.phase)
            dur = _fmt_duration(child.duration_ms)

            # Check if this phase had a failure inside it
            had_failure = any(
                c.event_type == TraceEventType.VALIDATION_FAIL
                for c in child.children
            )

            if child.phase == "phase5" and had_failure:
                attempt += 1
                status = f"{_YELLOW}✗ failed{_RESET}"
                lines.append(
                    f"  {_CYAN}{phase_label}{_RESET} (attempt {attempt})"
                    f"  {_DIM}{dur}{_RESET}  {status}"
                )
            elif child.phase == "phase5" and not had_failure:
                attempt += 1
                status = f"{_GREEN}✓ all passed{_RESET}"
                lines.append(
                    f"  {_CYAN}{phase_label}{_RESET} (attempt {attempt})"
                    f"  {_DIM}{dur}{_RESET}  {status}"
                )
            else:
                # Count LLM calls within this phase
                llm_count = sum(
                    1 for c in child.children
                    if c.event_type == TraceEventType.LLM_CALL
                )
                llm_str = f"  {_DIM}{llm_count} LLM call{'s' if llm_count != 1 else ''}{_RESET}" if llm_count else ""
                lines.append(
                    f"  {_CYAN}{phase_label}{_RESET}"
                    f"  {_DIM}{dur}{_RESET}{llm_str}  {_GREEN}✓{_RESET}"
                )

        elif et == TraceEventType.REMEDIATION:
            action = child.data.get("action", "") if child.data else ""
            lines.append(f"  {_YELLOW}↻ Remediation: {action}{_RESET}")

    lines.append(f"{_DIM}{'─' * 60}{_RESET}")

    total_tokens = summary["total_input_tokens"] + summary["total_output_tokens"]
    dur = _fmt_duration(summary["total_duration_ms"])
    lines.append(
        f"  {_BOLD}{summary['total_llm_calls']}{_RESET} LLM calls"
        f"  {_DIM}│{_RESET}  {_BOLD}{total_tokens:,}{_RESET} tokens"
        f"  {_DIM}│{_RESET}  {_BOLD}{dur}{_RESET}"
    )

    return "\n".join(lines)


# ── Verbose format ──


def _format_trace_verbose(root: TraceEvent, summary: dict) -> str:
    """Detailed, color-coded narrative trace."""
    lines: list[str] = []
    lines.append(f"{_BOLD}Agent Trace (detailed){_RESET}")
    lines.append(f"{_DIM}{'━' * 70}{_RESET}")

    attempt = 0

    # Walk events, grouping remediation with the orphan events that follow
    # (recluster/reorder LLM calls, gates, state changes between remediation
    # and the next phase5 validation)
    events = root.children
    i = 0
    while i < len(events):
        child = events[i]
        et = child.event_type

        if et in (TraceEventType.PHASE_START, TraceEventType.PHASE_END):
            phase_label = _PHASE_NAMES.get(child.phase, child.phase)
            dur = _fmt_duration(child.duration_ms)

            had_failure = any(
                c.event_type == TraceEventType.VALIDATION_FAIL
                for c in child.children
            )
            if child.phase == "phase5":
                attempt += 1

            # Phase header
            if child.phase == "phase5" and had_failure:
                lines.append(
                    f"\n{_BOLD}{_YELLOW}▸ {phase_label}"
                    f" (attempt {attempt}){_RESET}"
                    f"  {_DIM}{dur}{_RESET}"
                )
            elif child.phase == "phase5":
                lines.append(
                    f"\n{_BOLD}{_GREEN}▸ {phase_label}"
                    f" (attempt {attempt}){_RESET}"
                    f"  {_DIM}{dur}{_RESET}"
                )
            else:
                lines.append(
                    f"\n{_BOLD}{_CYAN}▸ {phase_label}{_RESET}"
                    f"  {_DIM}{dur}{_RESET}"
                )
            lines.append(f"  {_DIM}{'─' * 66}{_RESET}")

            # Phase body
            _format_phase_body(child, lines)

        elif et == TraceEventType.REMEDIATION:
            action = child.data.get("action", "") if child.data else ""
            diag = child.message
            # Extract the diagnosis from the message (after "Applying <action>: ")
            if ": " in diag:
                diag = diag.split(": ", 1)[1]
            lines.append(f"\n{_BOLD}{_YELLOW}↻ Remediation: {action}{_RESET}")
            lines.append(f"  {_DIM}{'─' * 66}{_RESET}")
            # Wrap diagnosis text
            _append_wrapped(lines, diag, prefix="  ", width=68)

            mods = child.data.get("modifications", {}) if child.data else {}
            edges = mods.get("add_dependency_edges", [])
            merges = mods.get("merge_hunks_into_same_commit", [])
            if edges:
                lines.append(f"  {_DIM}New edges:{_RESET}")
                for e in edges:
                    arrow = "↔" if e.get("type") == "bidirectional" else "→"
                    lines.append(
                        f"    {e.get('from', '?')} {arrow} {e.get('to', '?')}"
                        f"  {_DIM}{e.get('reason', '')[:60]}{_RESET}"
                    )
            if merges:
                lines.append(f"  {_DIM}Force co-locate:{_RESET}")
                for group in merges:
                    lines.append(f"    {', '.join(group)}")

            # Collect orphan events that follow until next phase/remediation
            lines.append("")
            lines.append(f"  {_DIM}Re-running pipeline:{_RESET}")
            i += 1
            while i < len(events):
                nxt = events[i]
                nxt_et = nxt.event_type
                # Stop at next phase or remediation
                if nxt_et in (TraceEventType.PHASE_START, TraceEventType.PHASE_END,
                              TraceEventType.REMEDIATION):
                    break
                if nxt_et == TraceEventType.GATE_PASS:
                    lines.append(f"    {_GREEN}✓ {nxt.message}{_RESET}")
                elif nxt_et == TraceEventType.STATE_CHANGE:
                    lines.append(f"    {_BLUE}→ {nxt.message}{_RESET}")
                elif nxt_et == TraceEventType.LLM_RESPONSE:
                    rd = _fmt_duration(nxt.duration_ms)
                    rt = _fmt_tokens(nxt.tokens)
                    rm = nxt.data.get("model", "") if nxt.data else ""
                    lines.append(
                        f"    {_DIM}LLM call → {rm}  {rd}  {rt}{_RESET}"
                    )
                # Skip LLM_CALL (shown via response)
                i += 1
            continue  # Don't increment i again

        i += 1

    # Footer
    lines.append(f"\n{_DIM}{'━' * 70}{_RESET}")
    total_tokens = summary["total_input_tokens"] + summary["total_output_tokens"]
    dur = _fmt_duration(summary["total_duration_ms"])
    lines.append(
        f"  {_BOLD}{summary['total_llm_calls']}{_RESET} LLM calls"
        f"  {_DIM}│{_RESET}  {_BOLD}{total_tokens:,}{_RESET} tokens"
        f"  {_DIM}│{_RESET}  {_BOLD}{dur}{_RESET}"
    )

    return "\n".join(lines)


def _format_phase_body(phase: TraceEvent, lines: list[str]) -> None:
    """Format the inner events of a phase in plain English."""
    children = phase.children

    # Phase 1: Summarize — show batch plan + LLM call count
    if phase.phase == "phase1":
        batch_event = _find_event(children, TraceEventType.BATCH_PLAN)
        if batch_event and batch_event.data:
            batches = batch_event.data.get("batches", [])
            n_batches = len(batches)
            total_hunks = sum(b.get("hunk_count", 0) for b in batches)
            lines.append(
                f"  Planned {_BOLD}{n_batches}{_RESET} batches"
                f" covering {_BOLD}{total_hunks}{_RESET} hunks"
            )
        llm_calls = [c for c in children if c.event_type == TraceEventType.LLM_CALL]
        resps = [c for c in children if c.event_type == TraceEventType.LLM_RESPONSE]
        if resps:
            total_in = sum(c.tokens.get("input", 0) for c in resps if c.tokens)
            total_out = sum(c.tokens.get("output", 0) for c in resps if c.tokens)
            total_dur = sum(c.duration_ms or 0 for c in resps)
            model = resps[0].data.get("model", "") if resps[0].data else ""
            lines.append(
                f"  Sent {_BOLD}{len(llm_calls)}{_RESET} LLM calls"
                f" to {_DIM}{model}{_RESET}"
                f"  {_DIM}({total_in + total_out:,} tokens, "
                f"{_fmt_duration(total_dur)}){_RESET}"
            )
        return

    # Phase 2: Dependency — show ReAct iterations
    if phase.phase == "phase2":
        _format_react_phase(children, lines, "dependency edges")
        return

    # Phase 3: Cluster — show LLM call + gate result
    if phase.phase == "phase3":
        _format_llm_gate_phase(children, lines, "clustering")
        return

    # Phase 4: Order — show tie-break calls + final order
    if phase.phase == "phase4":
        llm_calls = [c for c in children if c.event_type == TraceEventType.LLM_CALL]
        state = _find_event(children, TraceEventType.STATE_CHANGE)
        if llm_calls:
            lines.append(
                f"  {_BOLD}{len(llm_calls)}{_RESET} LLM tie-break calls"
                f" to resolve ordering ambiguity"
            )
        if state:
            lines.append(f"  {_BLUE}→ {state.message}{_RESET}")
        return

    # Phase 5: Validate — show per-commit results
    if phase.phase == "phase5":
        _format_validation_phase(children, lines)
        return

    # Phase 5b: Diagnose — show ReAct iterations
    if phase.phase == "phase5b":
        _format_react_phase(children, lines, "remediation")
        return

    # Phase 6: Messages — show per-commit LLM calls
    if phase.phase == "phase6":
        resps = [c for c in children if c.event_type == TraceEventType.LLM_RESPONSE]
        if resps:
            model = resps[0].data.get("model", "") if resps[0].data else ""
            total_tok = sum(
                (c.tokens.get("input", 0) + c.tokens.get("output", 0))
                for c in resps if c.tokens
            )
            lines.append(
                f"  Generated {_BOLD}{len(resps)}{_RESET} commit messages"
                f" via {_DIM}{model}{_RESET}"
                f"  {_DIM}({total_tok:,} tokens){_RESET}"
            )
        return

    # Fallback: generic event listing
    for child in children:
        _format_generic_event(child, lines, indent=1)


def _format_react_phase(children: list[TraceEvent], lines: list[str],
                         output_noun: str) -> None:
    """Format a ReAct agent phase (Phase 2 or 5b)."""
    iterations = 0
    tool_calls: list[TraceEvent] = []
    gate = _find_event(children, TraceEventType.GATE_PASS)
    gate_fail = _find_event(children, TraceEventType.GATE_VIOLATION)
    resps = [c for c in children if c.event_type == TraceEventType.LLM_RESPONSE]
    tool_call_events = [c for c in children if c.event_type == TraceEventType.TOOL_CALL]
    tool_result_events = [c for c in children if c.event_type == TraceEventType.TOOL_RESULT]

    iterations = len(resps)
    if resps:
        model = resps[0].data.get("model", "") if resps[0].data else ""
        total_in = sum(c.tokens.get("input", 0) for c in resps if c.tokens)
        total_out = sum(c.tokens.get("output", 0) for c in resps if c.tokens)
        total_dur = sum(c.duration_ms or 0 for c in resps)
        lines.append(
            f"  {_BOLD}{iterations}{_RESET} ReAct iterations"
            f" via {_DIM}{model}{_RESET}"
            f"  {_DIM}({total_in + total_out:,} tokens, "
            f"{_fmt_duration(total_dur)}){_RESET}"
        )

    if tool_call_events:
        for tc, tr in zip(tool_call_events, tool_result_events):
            tool_name = tc.data.get("tool_name", "?") if tc.data else "?"
            args = tc.data.get("args", {}) if tc.data else {}
            success = tr.data.get("success", False) if tr.data else False
            status = f"{_GREEN}ok{_RESET}" if success else f"{_RED}fail{_RESET}"
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            lines.append(
                f"    {_MAGENTA}⚡ {tool_name}{_RESET}"
                f"({args_str})  {status}"
            )

    if gate:
        lines.append(f"  {_GREEN}✓ Gate passed: {gate.message}{_RESET}")
    elif gate_fail:
        n = len(gate_fail.data.get("violations", [])) if gate_fail.data else 0
        lines.append(f"  {_RED}✗ Gate failed: {n} violation(s){_RESET}")


def _format_llm_gate_phase(children: list[TraceEvent], lines: list[str],
                            phase_noun: str) -> None:
    """Format a single-LLM-call + gate phase (Phase 3)."""
    resps = [c for c in children if c.event_type == TraceEventType.LLM_RESPONSE]
    gate = _find_event(children, TraceEventType.GATE_PASS)
    gate_fail = _find_event(children, TraceEventType.GATE_VIOLATION)
    warnings = [c for c in children if c.event_type == TraceEventType.WARNING]

    if resps:
        model = resps[0].data.get("model", "") if resps[0].data else ""
        total_in = sum(c.tokens.get("input", 0) for c in resps if c.tokens)
        total_out = sum(c.tokens.get("output", 0) for c in resps if c.tokens)
        total_dur = sum(c.duration_ms or 0 for c in resps)
        attempt_str = f"  {_DIM}({len(resps)} attempt{'s' if len(resps) > 1 else ''}){_RESET}" if len(resps) > 1 else ""
        lines.append(
            f"  Called {_DIM}{model}{_RESET}"
            f" for {phase_noun}{attempt_str}"
            f"  {_DIM}({total_in + total_out:,} tokens, "
            f"{_fmt_duration(total_dur)}){_RESET}"
        )

    if gate:
        lines.append(f"  {_GREEN}✓ {gate.message}{_RESET}")
    elif gate_fail:
        n = len(gate_fail.data.get("violations", [])) if gate_fail.data else 0
        lines.append(f"  {_RED}✗ Gate failed: {n} violation(s){_RESET}")

    for w in warnings:
        lines.append(f"  {_YELLOW}⚠ {w.message}{_RESET}")


def _format_validation_phase(children: list[TraceEvent], lines: list[str]) -> None:
    """Format Phase 5 validation with per-commit results."""
    # Group events by commit_id
    commits_seen: list[str] = []
    commit_results: dict[str, dict] = {}

    for child in children:
        if child.event_type == TraceEventType.STATE_CHANGE:
            lines.append(f"  {_DIM}{child.message}{_RESET}")
            continue

        if child.event_type == TraceEventType.WARNING:
            lines.append(f"  {_YELLOW}⚠ {child.message}{_RESET}")
            continue

        cid = child.data.get("commit_id", "") if child.data else ""
        if not cid:
            continue

        if cid not in commit_results:
            commits_seen.append(cid)
            commit_results[cid] = {"layers": [], "failed": False, "error": ""}

        if child.event_type == TraceEventType.VALIDATION_CHECK:
            layer = child.data.get("layer", "") if child.data else ""
            commit_results[cid]["layers"].append(layer)

        elif child.event_type == TraceEventType.VALIDATION_FAIL:
            layer = child.data.get("layer", "") if child.data else ""
            error = child.data.get("error", "") if child.data else ""
            commit_results[cid]["failed"] = True
            commit_results[cid]["error"] = error
            commit_results[cid]["failed_layer"] = layer

    for cid in commits_seen:
        r = commit_results[cid]
        layers_checked = r["layers"]
        if r["failed"]:
            failed_at = r.get("failed_layer", "?")
            # Show which layers passed before the failure
            passed = [l for l in layers_checked if l != failed_at]
            passed_str = ", ".join(passed) if passed else "none"
            lines.append(
                f"  {_RED}✗ {cid}{_RESET}  "
                f"{_DIM}passed: {passed_str}{_RESET}  "
                f"{_RED}failed at: {failed_at}{_RESET}"
            )
            # Show first 2 lines of error
            error_lines = r["error"].strip().splitlines()
            for el in error_lines[-2:]:
                lines.append(f"    {_DIM}{el.strip()[:90]}{_RESET}")
        else:
            layers_str = ", ".join(sorted(set(layers_checked))) if layers_checked else "patch"
            lines.append(
                f"  {_GREEN}✓ {cid}{_RESET}  "
                f"{_DIM}checked: {layers_str}{_RESET}"
            )


def _format_generic_event(event: TraceEvent, lines: list[str],
                           indent: int) -> None:
    """Fallback formatter for events not covered by specific formatters."""
    prefix = "  " * indent
    dur = _fmt_duration(event.duration_ms)
    dur_str = f"  {_DIM}{dur}{_RESET}" if dur else ""
    lines.append(f"{prefix}{_DIM}[{event.event_type.value}]{_RESET} {event.message}{dur_str}")


def _find_event(children: list[TraceEvent],
                event_type: TraceEventType) -> TraceEvent | None:
    """Find the first child with the given event type."""
    for c in children:
        if c.event_type == event_type:
            return c
    return None


def _append_wrapped(lines: list[str], text: str, prefix: str = "",
                    width: int = 70) -> None:
    """Append word-wrapped text lines."""
    words = text.split()
    current = prefix
    for word in words:
        if len(current) + len(word) + 1 > width and current.strip():
            lines.append(current)
            current = prefix + word
        else:
            current = current + " " + word if current.strip() else prefix + word
    if current.strip():
        lines.append(current)


def _dict_to_event(d: dict) -> TraceEvent:
    """Deserialize a dictionary back into a TraceEvent."""
    event = TraceEvent(
        event_type=TraceEventType(d["event_type"]),
        phase=d.get("phase", ""),
        message=d.get("message", ""),
    )
    event.timestamp = d.get("timestamp", 0.0)
    event.duration_ms = d.get("duration_ms")
    event.tokens = d.get("tokens")
    event.data = d.get("data", {})
    event.children = [_dict_to_event(c) for c in d.get("children", [])]
    return event


def _event_to_dict(event: TraceEvent) -> dict:
    """Serialize a TraceEvent to a dictionary for JSON persistence."""
    d: dict[str, Any] = {
        "event_type": event.event_type.value,
        "phase": event.phase,
        "message": event.message,
        "timestamp": event.timestamp,
    }
    if event.duration_ms is not None:
        d["duration_ms"] = round(event.duration_ms, 2)
    if event.tokens:
        d["tokens"] = event.tokens
    if event.data:
        d["data"] = event.data
    if event.children:
        d["children"] = [_event_to_dict(c) for c in event.children]
    return d
