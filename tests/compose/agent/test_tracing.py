"""Tests for hunknote.compose.agent.tracing — Trace infrastructure."""

import json
import time

import pytest

from hunknote.compose.agent.tracing import AgentTrace, TraceEvent, TraceEventType


class TestTraceEventType:
    """Tests for TraceEventType enum."""

    def test_all_event_types_defined(self):
        """All expected event types exist."""
        expected = {
            "phase_start", "phase_end", "llm_call", "llm_response",
            "tool_call", "tool_result", "validation_check", "validation_fail",
            "validation_pass", "gate_check", "gate_violation", "gate_pass",
            "remediation", "state_change", "batch_plan", "warning", "error",
        }
        actual = {e.value for e in TraceEventType}
        assert expected.issubset(actual)


class TestAgentTrace:
    """Tests for AgentTrace collection and reporting."""

    def test_initial_state(self):
        """New trace has root event with zero counters."""
        t = AgentTrace()
        assert t.root.phase == "orchestrator"
        summary = t.get_summary()
        assert summary["total_llm_calls"] == 0
        assert summary["total_input_tokens"] == 0

    def test_phase_nesting(self):
        """Phase start/end creates nested structure."""
        t = AgentTrace()
        t.phase_start("phase1", "Summarizing")
        t.warning("phase1", "test warning")
        t.phase_end("phase1")

        assert len(t.root.children) == 1
        phase_event = t.root.children[0]
        assert phase_event.phase == "phase1"
        # Warning is nested under phase1
        assert len(phase_event.children) == 1
        assert phase_event.children[0].message == "test warning"

    def test_llm_call_counting(self):
        """LLM calls are counted correctly."""
        t = AgentTrace()
        t.llm_call("phase1", "system", "user")
        t.llm_response("phase1", "response", "model-1",
                        {"input": 100, "output": 50, "thinking": 10}, 500.0)
        t.llm_call("phase1", "system2", "user2")
        t.llm_response("phase1", "response2", "model-1",
                        {"input": 200, "output": 100, "thinking": 0}, 300.0)

        summary = t.get_summary()
        assert summary["total_llm_calls"] == 2
        assert summary["total_input_tokens"] == 300
        assert summary["total_output_tokens"] == 150
        assert summary["total_thinking_tokens"] == 10

    def test_llm_call_stores_full_prompts(self):
        """LLM call events store complete system and user prompts."""
        t = AgentTrace()
        t.llm_call("phase1", "full system prompt here", "full user prompt here")
        event = t.root.children[0]
        assert event.data["system_prompt"] == "full system prompt here"
        assert event.data["user_prompt"] == "full user prompt here"

    def test_tool_call_and_result(self):
        """Tool call and result events are recorded."""
        t = AgentTrace()
        t.tool_call("phase2", "ripgrep", {"pattern": "hello"})
        t.tool_result("phase2", "ripgrep", "found 3 matches", True, 50.0)
        assert len(t.root.children) == 2
        assert t.root.children[0].data["tool_name"] == "ripgrep"
        assert t.root.children[1].data["success"] is True

    def test_gate_violation(self):
        """Gate violations are recorded with details."""
        t = AgentTrace()
        t.gate_violation("phase3", [
            {"type": "frozen", "hunk_id": "H1_a", "detail": "frozen"},
        ])
        event = t.root.children[0]
        assert event.event_type == TraceEventType.GATE_VIOLATION
        assert len(event.data["violations"]) == 1

    def test_batch_plan(self):
        """Batch plan event records batch details."""
        t = AgentTrace()
        t.batch_plan("phase1", [
            {"batch_id": 1, "file_paths": ["foo.py"], "hunk_count": 2},
        ])
        event = t.root.children[0]
        assert event.event_type == TraceEventType.BATCH_PLAN
        assert len(event.data["batches"]) == 1

    def test_save_and_clear(self, tmp_path):
        """Trace saves to file and clear removes it."""
        repo = tmp_path
        (repo / ".hunknote").mkdir()
        t = AgentTrace()
        t.llm_call("phase1", "sys", "user")

        t.save_to_file(repo)
        trace_file = repo / ".hunknote" / "agent_trace.json"
        assert trace_file.exists()

        data = json.loads(trace_file.read_text())
        assert data["version"] == "1"
        assert "trace" in data
        assert "summary" in data

        AgentTrace.clear_trace_file(repo)
        assert not trace_file.exists()

    def test_load_from_file(self, tmp_path):
        """Trace can be loaded from a saved file."""
        repo = tmp_path
        (repo / ".hunknote").mkdir()
        t = AgentTrace()
        t.phase_start("phase1", "Summarizing")
        t.llm_call("phase1", "sys", "user")
        t.llm_response("phase1", "resp", "model-1",
                        {"input": 100, "output": 50, "thinking": 0}, 200.0)
        t.phase_end("phase1")
        t.save_to_file(repo)

        loaded = AgentTrace.load_from_file(repo)
        assert loaded is not None
        summary = loaded.get_summary()
        assert summary["total_llm_calls"] == 1
        assert summary["total_input_tokens"] == 100
        # Should format without errors
        compact = loaded.format_for_stderr(verbose=False)
        assert "Summarize" in compact or "phase1" in compact
        verbose = loaded.format_for_stderr(verbose=True)
        assert "Summarize" in verbose or "phase1" in verbose

    def test_load_from_nonexistent_file(self, tmp_path):
        """Loading from nonexistent file returns None."""
        assert AgentTrace.load_from_file(tmp_path) is None

    def test_clear_nonexistent_file(self, tmp_path):
        """Clearing a nonexistent trace file does not raise."""
        AgentTrace.clear_trace_file(tmp_path)  # Should not raise

    def test_format_compact(self):
        """Compact format shows phase summaries."""
        t = AgentTrace()
        t.phase_start("phase1", "Summarizing 5 hunks")
        t.llm_call("phase1", "sys", "user")
        t.llm_response("phase1", "resp", "m", {"input": 10, "output": 5, "thinking": 0}, 100)
        t.phase_end("phase1")

        output = t.format_for_stderr(verbose=False)
        assert "Summarize" in output or "phase1" in output
        assert "LLM calls" in output

    def test_format_verbose(self):
        """Verbose format shows nested details."""
        t = AgentTrace()
        t.phase_start("phase1", "Summarizing")
        t.llm_call("phase1", "system prompt", "user prompt")
        t.phase_end("phase1")

        output = t.format_for_stderr(verbose=True)
        # Verbose output should contain phase details (human-readable format)
        assert "Summarize" in output or "phase1" in output
        assert len(output) > 0

    def test_emit_arbitrary_event(self):
        """Emit adds an event to the current scope."""
        t = AgentTrace()
        t.emit(TraceEvent(
            event_type=TraceEventType.REMEDIATION,
            phase="orchestrator",
            message="Applying recluster",
        ))
        assert len(t.root.children) == 1
        assert t.root.children[0].event_type == TraceEventType.REMEDIATION

    def test_phase_duration_tracked(self):
        """Phase end records elapsed duration."""
        t = AgentTrace()
        t.phase_start("phase1", "test")
        time.sleep(0.01)
        t.phase_end("phase1")
        event = t.root.children[0]
        assert event.duration_ms is not None
        assert event.duration_ms > 0
