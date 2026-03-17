"""Phase 1: Hunk Summarization.

Batched LLM calls to summarize each hunk's intent, category,
symbols modified, and symbols referenced.
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Callable

from hunknote.compose.agent.batching import Batch, plan_batches
from hunknote.compose.agent.models import HunkSummary
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import FileDiff, HunkRef
from hunknote.llm.base import RawLLMResult

logger = logging.getLogger(__name__)

_SUMMARIZE_SYSTEM_PROMPT = """You are analyzing code changes (hunks) to produce structured summaries.
Output ONLY valid JSON. No markdown fences. No commentary."""


def run_phase1_summarize(
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    repo_root: Path,
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
) -> dict[str, HunkSummary]:
    """Summarize each hunk's intent and category.

    Hunks are batched by file. Dynamic batching splits large files
    and merges small files to optimize LLM call count.

    Returns:
        Dict mapping hunk_id -> HunkSummary.
    """
    batches = plan_batches(file_diffs, inventory, repo_root)
    trace.batch_plan("phase1", [
        {"batch_id": b.batch_id, "file_paths": b.file_paths,
         "hunk_count": len(b.hunk_ids), "estimated_tokens": b.estimated_tokens}
        for b in batches
    ])

    summaries: dict[str, HunkSummary] = {}

    # Pre-populate summaries for synthetic file-operation entries
    # (R_*, D_*) — they have no diff content to summarize.
    from hunknote.compose.inventory import is_file_op_id, RENAME_PREFIX, DELETE_PREFIX
    for hunk_id, hunk in inventory.items():
        if not is_file_op_id(hunk_id):
            continue
        if hunk_id.startswith(RENAME_PREFIX):
            summaries[hunk_id] = HunkSummary(
                hunk_id=hunk_id,
                file_path=hunk.file_path,
                intent=f"Rename file: {hunk.header}",
                category="refactor",
            )
        elif hunk_id.startswith(DELETE_PREFIX):
            summaries[hunk_id] = HunkSummary(
                hunk_id=hunk_id,
                file_path=hunk.file_path,
                intent=f"Delete file: {hunk.header}",
                category="chore",
            )

    # Build file_diff lookup for new file detection
    fd_by_path: dict[str, FileDiff] = {fd.file_path: fd for fd in file_diffs}

    for batch in batches:
        batch_summaries = _process_batch(
            batch, inventory, fd_by_path, repo_root, llm_call_fn, trace,
        )
        summaries.update(batch_summaries)

    # Ensure all hunks have summaries (fallback for missed ones)
    for hunk_id, hunk in inventory.items():
        if hunk_id not in summaries:
            fd = fd_by_path.get(hunk.file_path)
            summaries[hunk_id] = HunkSummary(
                hunk_id=hunk_id,
                file_path=hunk.file_path,
                intent="(summarization failed)",
                category="chore",
                is_new_file=fd.is_new_file if fd else False,
            )

    return summaries


def _process_batch(
    batch: Batch,
    inventory: dict[str, HunkRef],
    fd_by_path: dict[str, FileDiff],
    repo_root: Path,
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
) -> dict[str, HunkSummary]:
    """Process a single batch and return hunk summaries."""
    user_prompt = _build_batch_prompt(batch, inventory, fd_by_path, repo_root)

    trace.llm_call("phase1", _SUMMARIZE_SYSTEM_PROMPT, user_prompt)
    start_time = time.time()

    try:
        result = llm_call_fn(_SUMMARIZE_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        logger.warning("Phase 1 batch %d LLM call failed: %s", batch.batch_id, e)
        trace.warning("phase1", f"Batch {batch.batch_id} LLM call failed: {e}")
        return _fallback_summaries(batch, inventory, fd_by_path)

    duration_ms = (time.time() - start_time) * 1000
    trace.llm_response(
        "phase1", result.raw_response, result.model,
        {"input": result.input_tokens, "output": result.output_tokens,
         "thinking": result.thinking_tokens},
        duration_ms,
    )

    # Parse JSON array from response
    summaries = _parse_summaries(result.raw_response, batch, inventory, fd_by_path)
    if summaries is not None:
        return summaries

    # Retry once on parse failure
    logger.info("Phase 1 batch %d: parse failed, retrying", batch.batch_id)
    retry_prompt = user_prompt + "\n\n[Your previous response was not valid JSON. Please output ONLY a JSON array.]"

    trace.llm_call("phase1", _SUMMARIZE_SYSTEM_PROMPT, retry_prompt)
    start_time = time.time()
    try:
        result = llm_call_fn(_SUMMARIZE_SYSTEM_PROMPT, retry_prompt)
    except Exception:
        return _fallback_summaries(batch, inventory, fd_by_path)

    duration_ms = (time.time() - start_time) * 1000
    trace.llm_response(
        "phase1", result.raw_response, result.model,
        {"input": result.input_tokens, "output": result.output_tokens,
         "thinking": result.thinking_tokens},
        duration_ms,
    )

    summaries = _parse_summaries(result.raw_response, batch, inventory, fd_by_path)
    if summaries is not None:
        return summaries

    return _fallback_summaries(batch, inventory, fd_by_path)


def _build_batch_prompt(
    batch: Batch,
    inventory: dict[str, HunkRef],
    fd_by_path: dict[str, FileDiff],
    repo_root: Path,
) -> str:
    """Build the user prompt for a batch."""
    if batch.is_new_file and len(batch.file_paths) == 1:
        return _build_new_file_prompt(batch, inventory, repo_root)
    elif len(batch.file_paths) > 1:
        return _build_multi_file_prompt(batch, inventory, fd_by_path, repo_root)
    else:
        return _build_single_file_prompt(batch, inventory, repo_root)


def _build_single_file_prompt(
    batch: Batch,
    inventory: dict[str, HunkRef],
    repo_root: Path,
) -> str:
    """Build prompt for a single modified file batch."""
    file_path = batch.file_paths[0]

    # Get staged file context
    context = _get_staged_context(repo_root, file_path, inventory, batch.hunk_ids)

    hunks_text = []
    for hid in batch.hunk_ids:
        hunk = inventory[hid]
        diff_lines = "\n".join(hunk.lines)
        hunks_text.append(f"Hunk {hid}:\n{diff_lines}")

    return f"""Summarize these code changes from {file_path}.

[STAGED FILE CONTEXT]
{context}

[HUNKS TO SUMMARIZE]

{chr(10).join(hunks_text)}

Output a JSON array with one entry per hunk:
[
  {{
    "hunk_id": "{batch.hunk_ids[0]}",
    "intent": "<1-2 sentences: what this change does and why>",
    "category": "<feature|bugfix|refactor|test|docs|config|chore>",
    "symbols_modified": ["<symbols added/removed/changed>"],
    "symbols_referenced": ["<symbols used but not defined by this hunk>"]
  }}
]"""


def _build_new_file_prompt(
    batch: Batch,
    inventory: dict[str, HunkRef],
    repo_root: Path,
) -> str:
    """Build prompt for a new file."""
    file_path = batch.file_paths[0]
    staged_content = _read_staged_file(repo_root, file_path)

    hunk_ids_str = ", ".join(batch.hunk_ids)

    return f"""A new file is being added: {file_path}

[FULL FILE CONTENT]
{staged_content}

This file contains {len(batch.hunk_ids)} hunk(s): {hunk_ids_str}
Since this is a new file, all hunks are part of a single logical addition.

Summarize the file as a whole, producing one JSON entry per hunk.
All entries should share the same intent (the file's purpose) but
list different symbols_modified based on each hunk's diff lines.

Output a JSON array:
[
  {{
    "hunk_id": "<hunk_id>",
    "intent": "<file's purpose>",
    "category": "<feature|bugfix|refactor|test|docs|config|chore>",
    "symbols_modified": ["<symbols in this hunk>"],
    "symbols_referenced": ["<symbols referenced>"]
  }}
]"""


def _build_multi_file_prompt(
    batch: Batch,
    inventory: dict[str, HunkRef],
    fd_by_path: dict[str, FileDiff],
    repo_root: Path,
) -> str:
    """Build prompt for a multi-file batch (merged small files)."""
    sections = []
    for fp in batch.file_paths:
        file_hunks = [hid for hid in batch.hunk_ids if inventory[hid].file_path == fp]
        context = _get_staged_context(repo_root, fp, inventory, file_hunks)

        hunks_text = []
        for hid in file_hunks:
            hunk = inventory[hid]
            diff_lines = "\n".join(hunk.lines)
            hunks_text.append(f"Hunk {hid}:\n{diff_lines}")

        sections.append(
            f"[FILE: {fp}]\nContext: {context[:500]}\n{chr(10).join(hunks_text)}"
        )

    return f"""Summarize these code changes across multiple files.

{chr(10).join(sections)}

Output a JSON array with one entry per hunk:
[
  {{
    "hunk_id": "<hunk_id>",
    "intent": "<1-2 sentences>",
    "category": "<feature|bugfix|refactor|test|docs|config|chore>",
    "symbols_modified": ["<symbols>"],
    "symbols_referenced": ["<symbols>"]
  }}
]"""


def _parse_summaries(
    response: str,
    batch: Batch,
    inventory: dict[str, HunkRef],
    fd_by_path: dict[str, FileDiff],
) -> dict[str, HunkSummary] | None:
    """Parse LLM response into HunkSummary dict."""
    # Strip markdown fences if present
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array in the response
        import re
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                items = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        else:
            return None

    if not isinstance(items, list):
        return None

    summaries: dict[str, HunkSummary] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        hunk_id = item.get("hunk_id", "")
        if hunk_id not in inventory:
            continue
        fd = fd_by_path.get(inventory[hunk_id].file_path)
        summaries[hunk_id] = HunkSummary(
            hunk_id=hunk_id,
            file_path=inventory[hunk_id].file_path,
            intent=item.get("intent", ""),
            category=item.get("category", "chore"),
            symbols_modified=item.get("symbols_modified", []),
            symbols_referenced=item.get("symbols_referenced", []),
            is_new_file=fd.is_new_file if fd else False,
        )

    return summaries if summaries else None


def _fallback_summaries(
    batch: Batch,
    inventory: dict[str, HunkRef],
    fd_by_path: dict[str, FileDiff],
) -> dict[str, HunkSummary]:
    """Create fallback summaries when LLM call fails."""
    summaries: dict[str, HunkSummary] = {}
    for hid in batch.hunk_ids:
        hunk = inventory[hid]
        fd = fd_by_path.get(hunk.file_path)
        summaries[hid] = HunkSummary(
            hunk_id=hid,
            file_path=hunk.file_path,
            intent="(summarization failed)",
            category="chore",
            is_new_file=fd.is_new_file if fd else False,
        )
    return summaries


def _get_staged_context(
    repo_root: Path,
    file_path: str,
    inventory: dict[str, HunkRef],
    hunk_ids: list[str],
) -> str:
    """Get staged file context around the hunks."""
    content = _read_staged_file(repo_root, file_path)
    if not content:
        return "(file context unavailable)"

    lines = content.split("\n")

    # Find line range covering all hunks + 30 lines of context
    min_line = float("inf")
    max_line = 0
    for hid in hunk_ids:
        hunk = inventory.get(hid)
        if hunk:
            min_line = min(min_line, hunk.new_start)
            max_line = max(max_line, hunk.new_start + hunk.new_len)

    if min_line == float("inf"):
        return content[:2000]

    start = max(0, int(min_line) - 31)
    end = min(len(lines), int(max_line) + 30)
    context_lines = lines[start:end]

    return "\n".join(f"{start + i + 1}:{ln}" for i, ln in enumerate(context_lines))


def _read_staged_file(repo_root: Path, file_path: str) -> str:
    """Read the staged version of a file."""
    try:
        result = subprocess.run(
            ["git", "show", f":{file_path}"],
            capture_output=True, text=True,
            cwd=repo_root, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, Exception):
        pass
    return ""
