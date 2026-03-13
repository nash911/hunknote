"""Compose plan generation — single-shot LLM flow.

Reusable function that encapsulates the compose plan generation logic
(build prompt → call LLM → parse → validate → retry). Used by both
the compose CLI and the eval harness.
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from hunknote.compose.models import ComposePlan, FileDiff, HunkRef
from hunknote.compose.prompt import (
    COMPOSE_SYSTEM_PROMPT,
    COMPOSE_RETRY_SYSTEM_PROMPT,
    build_compose_prompt,
    build_compose_retry_prompt,
)
from hunknote.compose.validation import try_correct_hunk_ids, validate_plan
from hunknote.llm.parsing import parse_json_response

logger = logging.getLogger(__name__)


@dataclass
class ComposeResult:
    """Result of a compose plan generation."""

    plan: Optional[ComposePlan] = None
    success: bool = False
    error: Optional[str] = None
    total_llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    model: str = ""
    retry_count: int = 0
    validation_errors: list[str] = field(default_factory=list)


def generate_compose_plan(
    file_diffs: list[FileDiff],
    inventory: dict[str, HunkRef],
    max_commits: int = 8,
    max_retries: int = 2,
    style: str = "conventional",
    branch: str = "main",
    recent_commits: Optional[list[str]] = None,
    llm_call_fn: Optional[Callable[[str, str], str]] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> ComposeResult:
    """Generate a compose plan using the single-shot LLM flow.

    This encapsulates the full compose pipeline: build prompt, call LLM,
    parse response, validate, auto-correct hunk IDs, and retry on errors.

    Can be called with either:
    - An explicit ``llm_call_fn(system_prompt, user_prompt) -> response``
    - Or ``provider_name`` / ``model_name`` to build one internally.

    Args:
        file_diffs: Parsed file diffs with hunks.
        inventory: Hunk ID → HunkRef mapping.
        max_commits: Maximum number of commits in the plan.
        max_retries: Maximum LLM retries on validation failure.
        style: Commit style profile name.
        branch: Current branch name (context for the prompt).
        recent_commits: Recent commit subjects (context for the prompt).
        llm_call_fn: Optional pre-built LLM call function.
        provider_name: Provider name string (used if llm_call_fn is None).
        model_name: Model name string (used if llm_call_fn is None).

    Returns:
        ComposeResult with the plan (or error details).
    """
    recent_commits = recent_commits or []
    result = ComposeResult()

    # ── Build LLM call function if not provided ──
    if llm_call_fn is None:
        from hunknote.config import LLMProvider
        from hunknote.llm import get_provider

        prov_enum = None
        if provider_name:
            prov_enum = LLMProvider(provider_name)

        provider = get_provider(provider=prov_enum, model=model_name)

        def llm_call_fn(system_prompt: str, user_prompt: str) -> str:
            llm_result = provider.generate_raw(system_prompt, user_prompt)
            result.input_tokens += llm_result.input_tokens
            result.output_tokens += llm_result.output_tokens
            result.thinking_tokens += llm_result.thinking_tokens
            result.model = llm_result.model
            return llm_result.raw_response

    # ── Build prompt and call LLM ──
    user_prompt = build_compose_prompt(
        file_diffs=file_diffs,
        branch=branch,
        recent_commits=recent_commits,
        style=style,
        max_commits=max_commits,
    )

    try:
        response = llm_call_fn(COMPOSE_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        result.error = f"LLM call failed: {e}"
        result.total_llm_calls = 1
        return result

    result.total_llm_calls = 1

    # ── Parse response ──
    plan = _try_parse_plan(response)
    if plan is None:
        result.error = "Failed to parse LLM response as ComposePlan"
        return result

    # ── Validate + auto-correct ──
    try_correct_hunk_ids(plan, inventory)
    errors = validate_plan(plan, inventory, max_commits)

    # ── Retry loop ──
    retry_count = 0
    while errors and retry_count < max_retries:
        retry_count += 1
        logger.info("Plan validation failed, retry %d/%d", retry_count, max_retries)

        retry_prompt = build_compose_retry_prompt(
            file_diffs=file_diffs,
            previous_plan=plan,
            validation_errors=errors,
            valid_hunk_ids=sorted(inventory.keys()),
            max_commits=max_commits,
        )

        try:
            response = llm_call_fn(COMPOSE_RETRY_SYSTEM_PROMPT, retry_prompt)
        except Exception as e:
            logger.warning("LLM retry call failed: %s", e)
            result.total_llm_calls += 1
            break

        result.total_llm_calls += 1

        new_plan = _try_parse_plan(response)
        if new_plan is None:
            continue

        plan = new_plan
        try_correct_hunk_ids(plan, inventory)
        errors = validate_plan(plan, inventory, max_commits)

    result.retry_count = retry_count
    result.validation_errors = errors

    if errors:
        result.error = f"Plan still invalid after {retry_count} retries: {errors}"
        # Still return the best plan we have
        result.plan = plan
        return result

    result.plan = plan
    result.success = True
    return result


def _try_parse_plan(response: str) -> Optional[ComposePlan]:
    """Parse an LLM response into a ComposePlan, returning None on failure."""
    try:
        data = parse_json_response(response)
        return ComposePlan(**data)
    except Exception as e:
        logger.warning("Failed to parse compose response: %s", e)
        return None


