"""LLM-as-judge scoring for commit quality.

Optional module that uses a different LLM model to evaluate
the quality of the agent's commit grouping. Scores cohesion,
separation, and ordering.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Callable, Optional

from hunknote.compose.models import ComposePlan, HunkRef
from eval.config import EVAL_CACHE_DIR

logger = logging.getLogger(__name__)

# Cache for judge results to avoid re-evaluating identical inputs
_judge_cache_dir = EVAL_CACHE_DIR / "judge_cache"


def judge_cohesion(
    commit_hunks: list[dict],
    commit_title: str,
    llm_call_fn: Callable[[str, str], str],
) -> tuple[float, str]:
    """Rate how cohesive a single commit's hunks are (0-1).

    Args:
        commit_hunks: List of dicts with keys: hunk_id, file_path, snippet.
        commit_title: The commit's title/message.
        llm_call_fn: Function(system_prompt, user_prompt) -> response string.

    Returns:
        Tuple of (score, reasoning).
    """
    cache_key = _cache_key("cohesion", commit_hunks, commit_title)
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    hunk_descriptions = "\n".join(
        f"  - {h['hunk_id']} ({h['file_path']}): {h.get('snippet', '')[:200]}"
        for h in commit_hunks
    )

    system_prompt = (
        "You are an expert code reviewer evaluating commit quality. "
        "Rate how cohesive the following commit is — do all the changes "
        "belong together as a single logical unit of work?\n\n"
        "Respond with JSON: {\"score\": <float 0-1>, \"reasoning\": \"<brief explanation>\"}\n"
        "1.0 = perfectly cohesive, all changes serve one purpose\n"
        "0.5 = somewhat related but could be split\n"
        "0.0 = completely unrelated changes lumped together"
    )

    user_prompt = (
        f"Commit title: {commit_title}\n\n"
        f"Hunks in this commit:\n{hunk_descriptions}\n\n"
        f"Rate the cohesion of this commit."
    )

    result = _call_and_parse(llm_call_fn, system_prompt, user_prompt)
    _save_cache(cache_key, result)
    return result


def judge_separation(
    commit_a: dict,
    commit_b: dict,
    llm_call_fn: Callable[[str, str], str],
) -> tuple[float, str]:
    """Rate whether two adjacent commits are properly separated (0-1).

    Args:
        commit_a: Dict with keys: title, files, hunk_count.
        commit_b: Dict with keys: title, files, hunk_count.
        llm_call_fn: Function(system_prompt, user_prompt) -> response string.

    Returns:
        Tuple of (score, reasoning).
    """
    cache_key = _cache_key("separation", commit_a, commit_b)
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    system_prompt = (
        "You are an expert code reviewer. Evaluate whether two adjacent commits "
        "in a sequence represent genuinely separate concerns, or if they should "
        "have been combined into one commit.\n\n"
        "Respond with JSON: {\"score\": <float 0-1>, \"reasoning\": \"<brief explanation>\"}\n"
        "1.0 = clearly separate concerns, correct to split\n"
        "0.5 = borderline, could go either way\n"
        "0.0 = should definitely be one commit"
    )

    user_prompt = (
        f"Commit A: {commit_a['title']}\n"
        f"  Files: {', '.join(commit_a.get('files', []))}\n"
        f"  Hunk count: {commit_a.get('hunk_count', 0)}\n\n"
        f"Commit B: {commit_b['title']}\n"
        f"  Files: {', '.join(commit_b.get('files', []))}\n"
        f"  Hunk count: {commit_b.get('hunk_count', 0)}\n\n"
        f"Are these two commits properly separated?"
    )

    result = _call_and_parse(llm_call_fn, system_prompt, user_prompt)
    _save_cache(cache_key, result)
    return result


def judge_ordering(
    commits: list[dict],
    llm_call_fn: Callable[[str, str], str],
) -> tuple[float, str]:
    """Rate the logical ordering of the commit sequence (0-1).

    Args:
        commits: List of dicts with keys: id, title, files.
        llm_call_fn: Function(system_prompt, user_prompt) -> response string.

    Returns:
        Tuple of (score, reasoning).
    """
    cache_key = _cache_key("ordering", commits)
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    system_prompt = (
        "You are an expert code reviewer. Evaluate whether the following "
        "sequence of commits is in a logical order. Good ordering means:\n"
        "- Foundational changes come before dependent ones\n"
        "- Refactors before new features that use them\n"
        "- Each commit builds on the previous in a sensible way\n\n"
        "Respond with JSON: {\"score\": <float 0-1>, \"reasoning\": \"<brief explanation>\"}\n"
        "1.0 = perfect logical order\n"
        "0.5 = acceptable but could be improved\n"
        "0.0 = completely wrong order"
    )

    commit_list = "\n".join(
        f"  {c.get('id', i+1)}. {c['title']} (files: {', '.join(c.get('files', []))})"
        for i, c in enumerate(commits)
    )

    user_prompt = f"Commit sequence:\n{commit_list}\n\nRate the ordering."

    result = _call_and_parse(llm_call_fn, system_prompt, user_prompt)
    _save_cache(cache_key, result)
    return result


def run_full_judge(
    agent_plan: ComposePlan,
    inventory: dict[str, HunkRef],
    llm_call_fn: Callable[[str, str], str],
) -> dict[str, Optional[float]]:
    """Run all LLM-as-judge evaluations.

    Args:
        agent_plan: The agent's ComposePlan.
        inventory: Hunk ID -> HunkRef mapping.
        llm_call_fn: Function(system_prompt, user_prompt) -> response string.

    Returns:
        Dict with keys: cohesion, separation, ordering (float or None).
    """
    results: dict[str, Optional[float]] = {
        "cohesion": None,
        "separation": None,
        "ordering": None,
    }

    if not agent_plan.commits:
        return results

    # Cohesion: average across all commits
    cohesion_scores: list[float] = []
    for commit in agent_plan.commits:
        commit_hunks = []
        for hunk_id in commit.hunks:
            hunk = inventory.get(hunk_id)
            if hunk:
                commit_hunks.append({
                    "hunk_id": hunk_id,
                    "file_path": hunk.file_path,
                    "snippet": hunk.snippet(max_lines=3),
                })
        if commit_hunks:
            score, _ = judge_cohesion(commit_hunks, commit.title, llm_call_fn)
            cohesion_scores.append(score)

    if cohesion_scores:
        results["cohesion"] = sum(cohesion_scores) / len(cohesion_scores)

    # Separation: average across adjacent pairs
    if len(agent_plan.commits) >= 2:
        separation_scores: list[float] = []
        for i in range(len(agent_plan.commits) - 1):
            ca = agent_plan.commits[i]
            cb = agent_plan.commits[i + 1]

            files_a = sorted({inventory[h].file_path for h in ca.hunks if h in inventory})
            files_b = sorted({inventory[h].file_path for h in cb.hunks if h in inventory})

            score, _ = judge_separation(
                {"title": ca.title, "files": files_a, "hunk_count": len(ca.hunks)},
                {"title": cb.title, "files": files_b, "hunk_count": len(cb.hunks)},
                llm_call_fn,
            )
            separation_scores.append(score)

        if separation_scores:
            results["separation"] = sum(separation_scores) / len(separation_scores)

    # Ordering
    commit_summaries = []
    for commit in agent_plan.commits:
        files = sorted({inventory[h].file_path for h in commit.hunks if h in inventory})
        commit_summaries.append({
            "id": commit.id,
            "title": commit.title,
            "files": files,
        })

    if len(commit_summaries) >= 2:
        score, _ = judge_ordering(commit_summaries, llm_call_fn)
        results["ordering"] = score

    return results


# ── Caching helpers ──


def _cache_key(*args) -> str:
    """Generate a cache key from arguments."""
    content = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _load_cache(key: str) -> Optional[tuple[float, str]]:
    """Load a cached judge result."""
    cache_file = _judge_cache_dir / f"{key}.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                data = json.load(f)
            return data["score"], data["reasoning"]
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def _save_cache(key: str, result: tuple[float, str]) -> None:
    """Save a judge result to cache."""
    _judge_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = _judge_cache_dir / f"{key}.json"
    with open(cache_file, "w") as f:
        json.dump({"score": result[0], "reasoning": result[1]}, f)


def _call_and_parse(
    llm_call_fn: Callable[[str, str], str],
    system_prompt: str,
    user_prompt: str,
) -> tuple[float, str]:
    """Call the LLM and parse the JSON response.

    Returns:
        Tuple of (score, reasoning). Defaults to (0.5, "parse error") on failure.
    """
    try:
        response = llm_call_fn(system_prompt, user_prompt)
        # Try to extract JSON from the response
        response = response.strip()

        # Handle markdown code blocks
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].split("```")[0].strip()

        data = json.loads(response)
        score = float(data.get("score", 0.5))
        score = max(0.0, min(1.0, score))  # Clamp
        reasoning = str(data.get("reasoning", ""))
        return score, reasoning
    except Exception as e:
        logger.warning("Failed to parse judge response: %s", e)
        return 0.5, f"Parse error: {e}"
