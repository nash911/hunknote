"""Generic ReAct (Reason + Act) loop engine.

Handles the Thought → Action → Observation cycle, tool dispatch,
and structured JSON output extraction. Used by Phase 2 and Phase 5b.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from hunknote.compose.agent.tools import (
    ToolResult,
    execute_tool,
    format_tool_definitions,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import HunkRef
from hunknote.llm.base import RawLLMResult

logger = logging.getLogger(__name__)


@dataclass
class ReActConfig:
    max_iterations: int = 15
    max_tool_calls: int = 15
    system_prompt: str = ""
    output_schema_description: str = ""
    available_tools: Optional[list[str]] = None


@dataclass
class ReActResult:
    """Result of a ReAct agent run."""

    output: dict = field(default_factory=dict)
    raw_output: str = ""
    iterations: int = 0
    tool_calls_made: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_thinking_tokens: int = 0


# ── ReAct prompt format ──

_REACT_INSTRUCTIONS = """
To use a tool, respond with EXACTLY this format:
Thought: <your reasoning>
Action: <tool_name>
Args: {"param1": "value1", "param2": "value2"}

After receiving the tool result, continue reasoning.

When you have enough information to produce your final answer, respond with:
Thought: <final reasoning>
Output:
```json
<your structured JSON output>
```"""


def run_react_loop(
    config: ReActConfig,
    initial_context: str,
    llm_call_fn: Callable[[str, str], RawLLMResult],
    repo_root: Path,
    inventory: dict[str, HunkRef],
    trace: AgentTrace,
    phase_name: str,
    hunk_summaries: Optional[dict] = None,
) -> ReActResult:
    """Run a ReAct agent loop.

    1. Send system prompt + accumulated conversation to the LLM.
    2. Parse for either:
       a. A tool call (Action + Args) → execute tool, append result, loop.
       b. A final output (Output: json) → parse JSON, return.
    3. If max iterations exceeded, ask LLM to emit final output immediately.

    Args:
        config: ReAct configuration.
        initial_context: The initial user message with all context.
        llm_call_fn: (system_prompt, user_prompt) -> RawLLMResult.
        repo_root: Path to the git repo root.
        inventory: Hunk inventory dict.
        trace: AgentTrace instance for logging.
        phase_name: Name of the current phase (for tracing).
        hunk_summaries: Optional dict of hunk_id -> HunkSummary.

    Returns:
        ReActResult with the parsed final output.
    """
    result = ReActResult()

    # Build system prompt
    tool_defs = format_tool_definitions(config.available_tools)
    system_prompt = (
        f"{config.system_prompt}\n\n"
        f"You have access to the following tools:\n{tool_defs}\n"
        f"{_REACT_INSTRUCTIONS}\n\n"
        f"{config.output_schema_description}"
    )

    # Conversation accumulator
    conversation_parts: list[str] = [initial_context]
    tool_calls_made = 0

    for iteration in range(config.max_iterations):
        result.iterations = iteration + 1

        # Add nudge if approaching limit
        if iteration >= config.max_iterations - 2:
            conversation_parts.append(
                "\n[SYSTEM: You are running low on iterations. "
                "Please produce your final Output now.]"
            )

        user_prompt = "\n\n".join(conversation_parts)

        # Trace and call LLM
        trace.llm_call(phase_name, system_prompt, user_prompt)
        start_time = time.time()

        try:
            llm_result = llm_call_fn(system_prompt, user_prompt)
        except Exception as e:
            logger.warning("ReAct LLM call failed at iteration %d: %s", iteration, e)
            trace.warning(phase_name, f"LLM call failed: {e}")
            break

        duration_ms = (time.time() - start_time) * 1000
        tokens = {
            "input": llm_result.input_tokens,
            "output": llm_result.output_tokens,
            "thinking": llm_result.thinking_tokens,
        }
        trace.llm_response(
            phase_name, llm_result.raw_response, llm_result.model,
            tokens, duration_ms,
        )

        result.total_input_tokens += llm_result.input_tokens
        result.total_output_tokens += llm_result.output_tokens
        result.total_thinking_tokens += llm_result.thinking_tokens

        response_text = llm_result.raw_response or ""

        # Try to parse as final output
        final_json = _extract_final_output(response_text)
        if final_json is not None:
            result.output = final_json
            result.raw_output = response_text
            result.tool_calls_made = tool_calls_made
            return result

        # Try to parse as tool call
        tool_name, tool_args = _extract_tool_call(response_text)
        if tool_name and tool_calls_made < config.max_tool_calls:
            # Execute tool
            trace.tool_call(phase_name, tool_name, tool_args)
            tool_start = time.time()

            tool_result = execute_tool(
                tool_name, tool_args, repo_root, inventory, hunk_summaries,
            )

            tool_duration = (time.time() - tool_start) * 1000
            trace.tool_result(
                phase_name, tool_name, tool_result.full_output,
                tool_result.success, tool_duration,
            )

            tool_calls_made += 1

            # Append to conversation
            conversation_parts.append(response_text)
            conversation_parts.append(f"Observation: {tool_result.output}")
            continue

        # Neither tool call nor final output — append response and nudge
        conversation_parts.append(response_text)
        conversation_parts.append(
            "\n[SYSTEM: Your response did not contain a valid tool call "
            "or final output. Please either use a tool with the "
            "Action/Args format, or produce your final Output in JSON.]"
        )

    # Max iterations reached — try to extract any JSON from last response
    result.tool_calls_made = tool_calls_made
    if not result.output:
        logger.warning(
            "ReAct loop exhausted %d iterations without final output",
            config.max_iterations,
        )
        result.output = {}
        result.raw_output = ""

    return result


def _extract_final_output(text: str) -> Optional[dict]:
    """Extract JSON final output from LLM response.

    Looks for 'Output:' followed by a JSON block (optionally in ```json fences).
    """
    # Pattern 1: Output: followed by ```json ... ```
    pattern1 = r"Output:\s*```(?:json)?\s*\n?(.*?)```"
    match = re.search(pattern1, text, re.DOTALL)
    if match:
        return _try_parse_json(match.group(1).strip())

    # Pattern 2: Output: followed by { ... } on next lines
    pattern2 = r"Output:\s*\n?\s*(\{.*\})"
    match = re.search(pattern2, text, re.DOTALL)
    if match:
        return _try_parse_json(match.group(1).strip())

    # Pattern 3: Just a raw JSON object at the end of the response
    # (some models skip the Output: prefix)
    stripped = text.strip()
    if stripped.endswith("}"):
        brace_start = stripped.rfind("\n{")
        if brace_start >= 0:
            candidate = stripped[brace_start + 1:]
            result = _try_parse_json(candidate)
            if result is not None:
                return result

    return None


def _extract_tool_call(text: str) -> tuple[Optional[str], dict]:
    """Extract a tool call from LLM response.

    Looks for 'Action: <tool_name>' and 'Args: {json}'.
    """
    action_match = re.search(r"Action:\s*(\w+)", text)
    if not action_match:
        return None, {}

    tool_name = action_match.group(1)

    # Find Args: { ... }
    args_match = re.search(r"Args:\s*(\{.*?\})", text, re.DOTALL)
    if args_match:
        args = _try_parse_json(args_match.group(1))
        if args is not None:
            return tool_name, args

    # No args or parse failure — call with empty args
    return tool_name, {}


def _try_parse_json(text: str) -> Optional[dict]:
    """Try to parse a string as JSON dict."""
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to fix common issues: trailing commas, single quotes
    cleaned = text.strip()
    # Remove trailing commas before } or ]
    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    return None
