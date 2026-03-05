"""Base machinery for compose ReAct sub-agents."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from hunknote.compose.litellm_adapter import (
    extract_usage,
    litellm_completion,
    parse_tool_arguments,
)

logger = logging.getLogger(__name__)


def _repair_truncated_json(text: str) -> str | None:
    """Try to repair truncated JSON by closing open objects/arrays."""
    if not text or not text.strip():
        return None

    cleaned = text.strip()
    stack: list[str] = []
    in_string = False
    escaped = False
    last_safe = 0

    for i, ch in enumerate(cleaned):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == "\"":
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
            last_safe = i + 1
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
            last_safe = i + 1
        elif ch == ",":
            last_safe = i

    if not stack:
        return None

    trimmed = cleaned[:last_safe].rstrip().rstrip(",")
    if not trimmed:
        return None

    # recompute stack on trimmed text
    stack = []
    in_string = False
    escaped = False
    for ch in trimmed:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == "\"":
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()

    if not stack:
        return None

    closers = []
    for opener in reversed(stack):
        closers.append("}" if opener == "{" else "]")
    return trimmed + "".join(closers)


@dataclass
class SubAgentResult:
    """Result of one sub-agent execution."""

    output: dict
    raw_response: str = ""
    success: bool = True
    error: str | None = None
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    duration_seconds: float = 0.0
    trace: list[dict] = field(default_factory=list)


class BaseSubAgent:
    """Reusable ReAct loop with optional tool-calling."""

    def __init__(
        self,
        *,
        name: str,
        model: str,
        system_prompt: str,
        max_iterations: int = 6,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> None:
        self.name = name
        self.model = model
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._tools: dict[str, tuple[Callable[..., str], dict]] = {}
        self.last_result: SubAgentResult | None = None

    def register_tool(
        self,
        *,
        name: str,
        func: Callable[..., str],
        description: str,
        parameters: dict,
    ) -> None:
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
        self._tools[name] = (func, schema)

    def _dispatch_tool(self, tool_name: str, arguments: dict) -> str:
        if tool_name not in self._tools:
            return json.dumps({"error": f"unknown tool: {tool_name}"})
        fn, _ = self._tools[tool_name]
        try:
            return fn(**arguments)
        except Exception as exc:
            logger.warning("%s tool %s failed: %s", self.name, tool_name, exc)
            return json.dumps({"error": f"tool failed: {exc}"})

    def _tool_schemas(self) -> list[dict]:
        return [schema for _, schema in self._tools.values()]

    def _single_call(self, user_prompt: str) -> SubAgentResult:
        start = time.monotonic()
        trace: list[dict] = []
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        total_in = 0
        total_out = 0
        total_think = 0
        raw = ""
        parsed: dict = {}

        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                response = litellm_completion(
                    model=self.model,
                    messages=messages,
                    tools=None,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
            except Exception as exc:
                result = SubAgentResult(
                    output={},
                    success=False,
                    error=str(exc),
                    duration_seconds=time.monotonic() - start,
                    trace=trace,
                )
                self.last_result = result
                return result

            in_t, out_t, think_t = extract_usage(response)
            total_in += in_t
            total_out += out_t
            total_think += think_t
            raw = response.choices[0].message.content or ""
            parsed = self._extract_json(raw)
            trace.append({
                "attempt": attempt,
                "action": "single_call_response",
                "output_tokens": out_t,
                "parsed": bool(parsed),
                "raw_snippet": raw[:1000],
            })

            if parsed:
                break

            # Ask once for compact strict JSON and try again.
            if attempt < attempts:
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON. "
                        "Return ONE compact valid JSON object only. "
                        "No markdown fences and no prose."
                    ),
                })
                continue

        result = SubAgentResult(
            output=parsed,
            raw_response=raw,
            success=bool(parsed),
            error=None if parsed else "failed to parse JSON",
            iterations=1,
            input_tokens=total_in,
            output_tokens=total_out,
            thinking_tokens=total_think,
            duration_seconds=round(time.monotonic() - start, 3),
            trace=trace,
        )
        self.last_result = result
        return result

    def _react_loop(self, user_prompt: str) -> SubAgentResult:
        start = time.monotonic()
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        trace: list[dict] = []
        total_in = 0
        total_out = 0
        total_think = 0

        for i in range(1, self.max_iterations + 1):
            try:
                response = litellm_completion(
                    model=self.model,
                    messages=messages,
                    tools=self._tool_schemas() or None,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
            except Exception as exc:
                result = SubAgentResult(
                    output={},
                    success=False,
                    error=str(exc),
                    iterations=i,
                    input_tokens=total_in,
                    output_tokens=total_out,
                    thinking_tokens=total_think,
                    duration_seconds=round(time.monotonic() - start, 3),
                    trace=trace,
                )
                self.last_result = result
                return result

            in_t, out_t, think_t = extract_usage(response)
            total_in += in_t
            total_out += out_t
            total_think += think_t

            message = response.choices[0].message
            msg_dump = self._sanitize_message(message)
            messages.append(msg_dump)

            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                for tc in tool_calls:
                    tool_name = tc.function.name
                    args = parse_tool_arguments(tc.function.arguments)
                    result_text = self._dispatch_tool(tool_name, args)
                    trace.append({
                        "iteration": i,
                        "tool": tool_name,
                        "args": args,
                        "result_snippet": result_text[:300],
                    })
                    tc_id = tc.id[:64] if tc.id and len(tc.id) > 64 else tc.id
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_text,
                    })
                continue

            raw = message.content or ""
            parsed = self._extract_json(raw)
            trace.append({
                "iteration": i,
                "action": "llm_response",
                "parsed": bool(parsed),
                "raw_snippet": raw[:1000],
            })
            if not parsed and raw.strip() and i < self.max_iterations:
                messages.append({
                    "role": "user",
                    "content": (
                        "Re-output only one valid JSON object. "
                        "No markdown, no prose."
                    ),
                })
                continue

            result = SubAgentResult(
                output=parsed,
                raw_response=raw,
                success=bool(parsed),
                error=None if parsed else "failed to parse JSON",
                iterations=i,
                input_tokens=total_in,
                output_tokens=total_out,
                thinking_tokens=total_think,
                duration_seconds=round(time.monotonic() - start, 3),
                trace=trace,
            )
            self.last_result = result
            return result

        result = SubAgentResult(
            output={},
            success=False,
            error=f"max iterations ({self.max_iterations}) reached",
            iterations=self.max_iterations,
            input_tokens=total_in,
            output_tokens=total_out,
            thinking_tokens=total_think,
            duration_seconds=round(time.monotonic() - start, 3),
            trace=trace,
        )
        self.last_result = result
        return result

    @staticmethod
    def _sanitize_message(message: Any) -> dict:
        dumped = message.model_dump() if hasattr(message, "model_dump") else {
            "role": "assistant",
            "content": getattr(message, "content", ""),
        }
        cleaned = dict(dumped)
        cleaned.pop("provider_specific_fields", None)
        cleaned.pop("thinking_blocks", None)
        tool_calls = cleaned.get("tool_calls") or []
        if tool_calls:
            new_calls = []
            for tc in tool_calls:
                c = dict(tc)
                tc_id = c.get("id", "")
                if isinstance(tc_id, str) and len(tc_id) > 64:
                    c["id"] = tc_id[:64]
                c.pop("provider_specific_fields", None)
                new_calls.append(c)
            cleaned["tool_calls"] = new_calls
        return cleaned

    @staticmethod
    def _extract_json(raw: str | None) -> dict:
        if not raw:
            return {}

        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9_\-]*\n", "", text)
            text = re.sub(r"\n```$", "", text).strip()

        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass

        # Attempt truncated recovery for top-level object responses.
        if text.lstrip().startswith("{"):
            repaired = _repair_truncated_json(text)
            if repaired:
                try:
                    obj = json.loads(repaired)
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    pass

        # find all balanced objects and choose the largest valid dict
        candidates: list[str] = []
        i = 0
        while i < len(text):
            if text[i] != "{":
                i += 1
                continue
            start = i
            depth = 0
            in_string = False
            escaped = False
            j = i
            while j < len(text):
                ch = text[j]
                if escaped:
                    escaped = False
                elif ch == "\\" and in_string:
                    escaped = True
                elif ch == '"':
                    in_string = not in_string
                elif not in_string:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidates.append(text[start:j + 1])
                            i = j
                            break
                j += 1
            i += 1

        best: dict = {}
        best_len = -1
        for candidate in candidates:
            try:
                obj = json.loads(candidate)
            except Exception:
                continue
            if isinstance(obj, dict) and len(candidate) > best_len:
                best = obj
                best_len = len(candidate)

        return best if best_len >= 0 else {}
