"""Base class for ReAct sub-agents.

Provides the core ReAct loop: Think → Act (tool call) → Observe → repeat.
Each sub-agent subclasses this to register its own tools and system prompt.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from hunknote.compose.litellm_adapter import litellm_completion, parse_tool_arguments

logger = logging.getLogger(__name__)


def _repair_truncated_json(text: str) -> str | None:
    """Attempt to repair truncated JSON by closing open brackets/braces.

    When an LLM response is cut off by max_tokens, the JSON is often
    structurally valid up to the truncation point. This function tries
    to close any open arrays and objects to make it parseable.

    Strategy:
    1. Walk the string tracking bracket/brace depth and string state.
    2. Find the last position where a complete value ended.
    3. Trim everything after that, then close any remaining open
       brackets/braces.

    Args:
        text: Truncated JSON string.

    Returns:
        Repaired JSON string, or None if repair is not feasible.
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()

    # Track open brackets/braces (ignoring those inside strings)
    stack: list[str] = []
    in_string = False
    escape_next = False
    # Position just after the last complete value (after }, ], ", digit, true/false/null, or comma)
    last_safe_pos = 0

    for i, ch in enumerate(cleaned):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
                last_safe_pos = i + 1
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()
                last_safe_pos = i + 1
        elif ch == ',':
            # A comma between values in an array/object is a safe boundary
            last_safe_pos = i

    if not stack:
        return None  # Already balanced — nothing to repair

    # Trim to the last safe position (after a complete value)
    trimmed = cleaned[:last_safe_pos].rstrip().rstrip(',')

    # Recount the stack for the trimmed portion
    stack = []
    in_string = False
    escape_next = False
    for ch in trimmed:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()

    if not stack:
        # Trimmed portion is already balanced
        return None

    # Close open brackets/braces in reverse order
    closers = []
    for opener in reversed(stack):
        if opener == '{':
            closers.append('}')
        elif opener == '[':
            closers.append(']')

    repaired = trimmed + ''.join(closers)
    return repaired


@dataclass
class SubAgentResult:
    """Result from a sub-agent invocation."""

    output: dict              # Parsed JSON output from the agent
    raw_response: str = ""    # Raw text from the final LLM call
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    iterations: int = 0       # Number of ReAct iterations
    duration_seconds: float = 0.0
    trace: list[dict] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


class BaseSubAgent:
    """Base class for ReAct sub-agents.

    Subclasses must:
    1. Set self.system_prompt in __init__
    2. Register tools via self.register_tool()
    3. Implement run() that calls self._react_loop()
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        model: str,
        max_iterations: int = 8,
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ):
        """Initialize the sub-agent.

        Args:
            name: Human-readable name for tracing.
            system_prompt: System prompt for this agent.
            model: LiteLLM model string.
            max_iterations: Max ReAct iterations.
            temperature: Sampling temperature.
            max_tokens: Max output tokens per call.
        """
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Tool registry: name → (function, schema)
        self._tools: dict[str, tuple[Callable, dict]] = {}

        # Last SubAgentResult (set after run/react_loop)
        self.last_result: Optional[SubAgentResult] = None

    def register_tool(
        self,
        name: str,
        func: Callable[..., str],
        description: str,
        parameters: dict,
    ) -> None:
        """Register a tool that the agent can call.

        Args:
            name: Tool name (must match function-calling convention).
            func: The function to call. Must return a string.
            description: Human-readable description.
            parameters: JSON Schema for the parameters.
        """
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
        self._tools[name] = (func, schema)

    def _get_tool_schemas(self) -> list[dict]:
        """Return LiteLLM-compatible tool schemas."""
        return [schema for _, schema in self._tools.values()]

    def _dispatch_tool(self, name: str, arguments: dict) -> str:
        """Dispatch a tool call and return the result string.

        Args:
            name: Tool name.
            arguments: Parsed arguments dict.

        Returns:
            Tool result as a string.
        """
        if name not in self._tools:
            return json.dumps({"error": f"Unknown tool: {name}"})
        func, _ = self._tools[name]
        try:
            return func(**arguments)
        except Exception as e:
            logger.warning("Tool %s failed: %s", name, e)
            return json.dumps({"error": f"Tool {name} failed: {str(e)}"})

    @staticmethod
    def _sanitize_message_dump(dumped: dict) -> dict:
        """Sanitize a message.model_dump() dict for context-window efficiency.

        Gemini 2.5 thinking models embed huge base64 ``thought_signature``
        blobs inside ``provider_specific_fields`` and inflate tool-call IDs
        with ``__thought__`` suffixes (500+ chars each). Over multiple
        ReAct iterations this bloats the message history and can exhaust
        the context window.

        This method strips those fields and truncates oversized IDs.

        Args:
            dumped: The dict returned by ``message.model_dump()``.

        Returns:
            A cleaned copy of the dict.
        """
        cleaned = dict(dumped)

        # Remove top-level provider fields
        cleaned.pop("provider_specific_fields", None)
        cleaned.pop("images", None)
        cleaned.pop("thinking_blocks", None)

        # Sanitize tool_calls entries
        if cleaned.get("tool_calls"):
            sanitized_calls = []
            for tc in cleaned["tool_calls"]:
                tc = dict(tc)
                tc.pop("provider_specific_fields", None)
                # Truncate bloated __thought__ IDs
                tc_id = tc.get("id", "")
                if len(tc_id) > 64:
                    tc["id"] = tc_id[:64]
                if isinstance(tc.get("function"), dict):
                    tc["function"] = dict(tc["function"])
                sanitized_calls.append(tc)
            cleaned["tool_calls"] = sanitized_calls

        return cleaned

    def _react_loop(
        self,
        user_prompt: str,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> SubAgentResult:
        """Run the ReAct loop: send message → handle tool calls → repeat.

        Args:
            user_prompt: The user message to start the conversation.
            stream_callback: Optional callback for streaming status updates.

        Returns:
            SubAgentResult with parsed output.
        """
        start_time = time.monotonic()
        trace: list[dict] = []
        total_input = 0
        total_output = 0
        total_thinking = 0

        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        tool_schemas = self._get_tool_schemas()
        json_retry_mode = False

        for iteration in range(1, self.max_iterations + 1):
            if stream_callback:
                stream_callback(f"  {self.name}: iteration {iteration}...")

            t0 = time.monotonic()
            try:
                # In JSON retry mode, don't provide tools so the LLM outputs text
                current_tools = None if json_retry_mode else (tool_schemas if tool_schemas else None)
                response = litellm_completion(
                    model=self.model,
                    messages=messages,
                    tools=current_tools,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
            except Exception as e:
                logger.error("%s LiteLLM call failed: %s", self.name, e)
                result = SubAgentResult(
                    output={},
                    iterations=iteration,
                    duration_seconds=time.monotonic() - start_time,
                    trace=trace,
                    success=False,
                    error=str(e),
                    input_tokens=total_input,
                    output_tokens=total_output,
                    thinking_tokens=total_thinking,
                )
                self.last_result = result
                return result
            t1 = time.monotonic()

            # Track tokens
            usage = getattr(response, "usage", None)
            if usage:
                total_input += getattr(usage, "prompt_tokens", 0) or 0
                total_output += getattr(usage, "completion_tokens", 0) or 0
                # Some providers report thinking tokens
                total_thinking += getattr(usage, "reasoning_tokens", 0) or 0

            choice = response.choices[0]
            message = choice.message

            # Add assistant message to history (sanitized to remove bloated fields)
            messages.append(self._sanitize_message_dump(message.model_dump()))

            # Check for tool calls
            if message.tool_calls:
                tool_results = []
                for tc in message.tool_calls:
                    tool_name = tc.function.name
                    tool_args = parse_tool_arguments(tc.function.arguments)

                    result_str = self._dispatch_tool(tool_name, tool_args)

                    trace.append({
                        "iteration": iteration,
                        "action": "tool_call",
                        "tool": tool_name,
                        "args_summary": {k: str(v)[:200] for k, v in tool_args.items()},
                        "result_snippet": result_str[:500] if result_str else "",
                        "result_length": len(result_str) if result_str else 0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc.id[:64] if len(tc.id) > 64 else tc.id,
                        "content": result_str,
                    })

                messages.extend(tool_results)

                trace.append({
                    "iteration": iteration,
                    "action": "tool_results_summary",
                    "num_tools": len(tool_results),
                    "duration_s": round(t1 - t0, 3),
                })
                continue  # Loop back for the next iteration

            # No tool calls — this is the final response
            raw_text = message.content or ""

            trace.append({
                "iteration": iteration,
                "action": "final_response",
                "length": len(raw_text),
                "duration_s": round(t1 - t0, 3),
                "raw_snippet": raw_text[:1000] if raw_text else "",
            })

            # Parse JSON from the response
            parsed = self._extract_json(raw_text)

            if not parsed and raw_text.strip() and iteration < self.max_iterations:
                # JSON extraction failed — ask the LLM to re-output as valid JSON
                logger.debug(
                    "%s: JSON extraction failed on iteration %d (len=%d), "
                    "requesting JSON re-output",
                    self.name, iteration, len(raw_text),
                )
                trace.append({
                    "iteration": iteration,
                    "action": "json_retry",
                    "reason": "extraction_failed",
                    "raw_length": len(raw_text),
                    "raw_snippet": raw_text[:1000] if raw_text else "",
                })
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous response could not be parsed as JSON. "
                        "Please re-output your analysis as a single valid JSON object, "
                        "with no additional text, commentary, or markdown fences. "
                        "Output ONLY the raw JSON object starting with { and ending with }."
                    ),
                })
                json_retry_mode = True  # Disable tools for the retry call
                continue  # Loop back for another iteration

            duration = time.monotonic() - start_time
            result = SubAgentResult(
                output=parsed,
                raw_response=raw_text,
                input_tokens=total_input,
                output_tokens=total_output,
                thinking_tokens=total_thinking,
                iterations=iteration,
                duration_seconds=round(duration, 3),
                trace=trace,
                success=bool(parsed),
                error=None if parsed else "Failed to extract JSON from response",
            )
            self.last_result = result
            return result

        # Max iterations reached without a final response
        duration = time.monotonic() - start_time
        result = SubAgentResult(
            output={},
            iterations=self.max_iterations,
            duration_seconds=round(duration, 3),
            trace=trace,
            success=False,
            error=f"Max iterations ({self.max_iterations}) reached without final response",
            input_tokens=total_input,
            output_tokens=total_output,
            thinking_tokens=total_thinking,
        )
        self.last_result = result
        return result

    def _single_call(
        self,
        user_prompt: str,
    ) -> SubAgentResult:
        """Make a single LLM call without tool-calling (for Messenger).

        Args:
            user_prompt: The user message.

        Returns:
            SubAgentResult with parsed output.
        """
        start_time = time.monotonic()

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = litellm_completion(
                model=self.model,
                messages=messages,
                tools=None,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception as e:
            result = SubAgentResult(
                output={},
                duration_seconds=time.monotonic() - start_time,
                success=False,
                error=str(e),
            )
            self.last_result = result
            return result

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0 if usage else 0

        raw_text = response.choices[0].message.content or ""
        parsed = self._extract_json(raw_text)

        # If JSON extraction failed, retry once asking for clean JSON
        if not parsed and raw_text.strip():
            logger.debug("%s: single-call JSON extraction failed, retrying", self.name)
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response could not be parsed as JSON. "
                    "Please re-output as a single valid JSON object, "
                    "with no additional text or markdown fences."
                ),
            })
            try:
                response2 = litellm_completion(
                    model=self.model,
                    messages=messages,
                    tools=None,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                usage2 = getattr(response2, "usage", None)
                input_tokens += getattr(usage2, "prompt_tokens", 0) or 0 if usage2 else 0
                output_tokens += getattr(usage2, "completion_tokens", 0) or 0 if usage2 else 0
                raw_text = response2.choices[0].message.content or ""
                parsed = self._extract_json(raw_text)
            except Exception:
                pass

        result = SubAgentResult(
            output=parsed,
            raw_response=raw_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            iterations=1,
            duration_seconds=round(time.monotonic() - start_time, 3),
            success=bool(parsed),
            error=None if parsed else "Failed to extract JSON from response",
        )
        self.last_result = result
        return result

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract a JSON object from LLM text response.

        Handles:
        - Responses wrapped in markdown code fences
        - Thinking/reasoning preamble before JSON
        - Multiple JSON blocks (takes the largest valid one)
        - Nested braces in strings

        Args:
            text: Raw text from the LLM.

        Returns:
            Parsed dict, or empty dict on failure.
        """
        if not text or not text.strip():
            return {}

        # Strip markdown fences
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # Try direct parse first
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # ── Truncated JSON recovery ──
        # If the text starts with { but direct parse failed, the response
        # may have been truncated by max_tokens. Try to repair before
        # falling back to inner-object extraction (which would return
        # a nested object instead of the top-level wrapper).
        if cleaned.lstrip().startswith("{"):
            repaired = _repair_truncated_json(cleaned)
            if repaired:
                try:
                    result = json.loads(repaired)
                    if isinstance(result, dict):
                        logger.info(
                            "Recovered truncated JSON (original %d chars, repaired %d chars)",
                            len(cleaned), len(repaired),
                        )
                        return result
                except json.JSONDecodeError:
                    pass

        # Find all potential JSON objects using brace balancing
        candidates: list[str] = []
        i = 0
        while i < len(cleaned):
            if cleaned[i] == '{':
                # Try brace-balanced extraction from this position
                depth = 0
                in_string = False
                escape_next = False
                j = i
                while j < len(cleaned):
                    ch = cleaned[j]
                    if escape_next:
                        escape_next = False
                    elif ch == '\\' and in_string:
                        escape_next = True
                    elif ch == '"' and not escape_next:
                        in_string = not in_string
                    elif not in_string:
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                candidate = cleaned[i:j + 1]
                                candidates.append(candidate)
                                break
                    j += 1
            i += 1

        # Try candidates from longest to shortest (longest is most likely the full output)
        candidates.sort(key=len, reverse=True)
        for candidate in candidates:
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue


        logger.warning("Could not extract JSON from response (length=%d)", len(text))
        return {}

