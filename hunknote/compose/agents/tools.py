"""Utility helpers and tool functions used by compose sub-agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from hunknote.compose.models import CommitGroup, FileDiff, HunkRef


@dataclass
class HunkSymbolInfo:
    """Lightweight symbol data extracted from a hunk."""

    hunk_id: str
    file_path: str
    defines: set[str]
    imports: set[str]


def get_changed_lines(hunk: HunkRef, limit: int | None = None) -> list[str]:
    """Return only +/- content lines (not file headers)."""
    changed = [
        ln for ln in hunk.lines
        if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
    ]
    if limit is None:
        return changed
    return changed[:limit]


def build_hunk_summaries(inventory: dict[str, HunkRef], file_diffs: list[FileDiff]) -> str:
    """Build compact multi-file hunk summary text for prompts."""
    lines: list[str] = []
    for fd in file_diffs:
        if fd.is_binary:
            continue
        tag = ""
        if fd.is_new_file:
            tag = " (new file)"
        elif fd.is_deleted_file:
            tag = " (deleted file)"
        elif fd.is_renamed:
            tag = f" (renamed from {fd.old_path})"
        lines.append(f"File: {fd.file_path}{tag}")
        for h in fd.hunks:
            changed = get_changed_lines(h)
            adds = sum(1 for ln in changed if ln.startswith("+"))
            dels = sum(1 for ln in changed if ln.startswith("-"))
            lines.append(f"  {h.id}: {h.header} (+{adds}/-{dels})")
            for ln in changed[:8]:
                lines.append(f"    {ln}")
            if len(changed) > 8:
                lines.append(f"    ... ({len(changed) - 8} more lines)")
    return "\n".join(lines)


def extract_symbol_info(inventory: dict[str, HunkRef]) -> dict[str, HunkSymbolInfo]:
    """Best-effort symbol/import extraction from added lines."""
    result: dict[str, HunkSymbolInfo] = {}

    define_patterns = [
        re.compile(r"^\+\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\+\s*export\s+(?:default\s+)?(?:function|class|const|let|var|type|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\+\s*(?:func|type|var|const)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\+\s*pub\s+(?:fn|struct|enum|trait|mod|type|const)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ]

    import_patterns = [
        re.compile(r"^\+\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+([A-Za-z0-9_\*,\s]+)"),
        re.compile(r"^\+\s*import\s+([A-Za-z0-9_\.]+)"),
        re.compile(r"^\+\s*import\s+.*?from\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"^\+\s*const\s+\w+\s*=\s*require\(['\"]([^'\"]+)['\"]\)"),
        re.compile(r"^\+\s*use\s+([A-Za-z0-9_:]+)"),
        re.compile(r"^\+\s*#include\s*[<\"]([^>\"]+)[>\"]"),
    ]

    for hid, hunk in inventory.items():
        defines: set[str] = set()
        imports: set[str] = set()

        for line in get_changed_lines(hunk):
            if not line.startswith("+"):
                continue

            for pat in define_patterns:
                match = pat.match(line)
                if match:
                    defines.add(match.group(1))

            # Python from-import captures both module and symbols
            py_from = import_patterns[0].match(line)
            if py_from:
                module = py_from.group(1)
                imports.add(module)
                symbols = [s.strip() for s in py_from.group(2).split(",") if s.strip() and s.strip() != "*"]
                imports.update(symbols)

            for pat in import_patterns[1:]:
                match = pat.match(line)
                if not match:
                    continue
                imported = match.group(1)
                imports.add(imported)
                last = imported.split("/")[-1].split(".")[-1].split("::")[-1]
                if last:
                    imports.add(last)

        result[hid] = HunkSymbolInfo(
            hunk_id=hid,
            file_path=hunk.file_path,
            defines=defines,
            imports=imports,
        )

    return result


def get_hunk_diff(hunk_ids: list[str], inventory: dict[str, HunkRef]) -> str:
    payload: list[dict] = []
    for hid in hunk_ids:
        h = inventory.get(hid)
        if not h:
            payload.append({"hunk_id": hid, "error": "not found"})
            continue
        payload.append({
            "hunk_id": hid,
            "file_path": h.file_path,
            "header": h.header,
            "changed_lines": get_changed_lines(h, limit=60),
        })
    return json.dumps(payload, indent=2)


def get_file_hunks(file_path: str, file_diffs: list[FileDiff]) -> str:
    for fd in file_diffs:
        if fd.file_path == file_path:
            return json.dumps({
                "file_path": file_path,
                "hunks": [
                    {"id": h.id, "header": h.header}
                    for h in fd.hunks
                ],
            })
    return json.dumps({"file_path": file_path, "error": "file not found"})


def get_symbol_summary(hunk_ids: list[str], symbol_info: dict[str, HunkSymbolInfo]) -> str:
    rows: list[dict] = []
    for hid in hunk_ids:
        sym = symbol_info.get(hid)
        if not sym:
            rows.append({"hunk_id": hid, "error": "no symbol data"})
            continue
        rows.append({
            "hunk_id": hid,
            "file_path": sym.file_path,
            "defines": sorted(sym.defines),
            "imports": sorted(sym.imports),
        })
    return json.dumps(rows, indent=2)


def build_programmatic_dependencies(
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    symbol_info: dict[str, HunkSymbolInfo],
) -> list[dict]:
    """Build conservative dependency edges used as hints for analyzer/orderer."""
    symbol_to_hunks: dict[str, list[str]] = {}
    for hid, sym in symbol_info.items():
        for name in sym.defines:
            symbol_to_hunks.setdefault(name, []).append(hid)

    new_file_hunks: dict[str, list[str]] = {}
    for fd in file_diffs:
        if fd.is_new_file:
            for h in fd.hunks:
                new_file_hunks.setdefault(fd.file_path, []).append(h.id)

    def file_modules(path: str) -> list[str]:
        stem = path.rsplit(".", 1)[0] if "." in path else path
        return [stem, stem.replace("/", "."), stem.split("/")[-1]]

    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for hid, sym in symbol_info.items():
        for imp in sym.imports:
            # Symbol-based dependency
            for provider_hid in symbol_to_hunks.get(imp, []):
                if provider_hid == hid:
                    continue
                key = (hid, provider_hid, "must_be_ordered")
                if key in seen:
                    continue
                seen.add(key)
                edges.append({
                    "source": hid,
                    "target": provider_hid,
                    "reason": f"imports {imp}",
                    "strength": "must_be_ordered",
                })

            # New-file module dependency
            for new_path, providers in new_file_hunks.items():
                mods = file_modules(new_path)
                if any(imp == m or imp.startswith(m + ".") or imp.endswith("/" + m) for m in mods):
                    for provider_hid in providers:
                        if provider_hid == hid:
                            continue
                        key = (hid, provider_hid, "must_be_ordered")
                        if key in seen:
                            continue
                        seen.add(key)
                        edges.append({
                            "source": hid,
                            "target": provider_hid,
                            "reason": "imports from new file",
                            "strength": "must_be_ordered",
                        })

        # same-file edits are often tightly coupled
        for other_hid, other_sym in symbol_info.items():
            if other_hid == hid:
                continue
            if other_sym.file_path == sym.file_path:
                key = (hid, other_hid, "must_be_together")
                if key in seen:
                    continue
                seen.add(key)
                edges.append({
                    "source": hid,
                    "target": other_hid,
                    "reason": "same file logical coupling",
                    "strength": "must_be_together",
                })

    return edges


def get_checkpoint_state(
    checkpoint: int,
    ordered_groups: list[CommitGroup],
    inventory: dict[str, HunkRef],
) -> str:
    committed: list[str] = []
    for group in ordered_groups[:checkpoint]:
        committed.extend(group.hunk_ids)

    committed_set = set(committed)
    remaining = [hid for hid in inventory if hid not in committed_set]
    return json.dumps({
        "checkpoint": checkpoint,
        "committed_hunks": committed,
        "remaining_hunks": remaining,
    })


def programmatic_checkpoint_validation(
    ordered_groups: list[CommitGroup],
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    symbol_info: dict[str, HunkSymbolInfo],
) -> dict:
    """Heuristic checkpoint validation focused on new-file dependency ordering."""
    # map new file -> creator hunks
    new_file_creators: dict[str, set[str]] = {}
    for fd in file_diffs:
        if fd.is_new_file:
            new_file_creators[fd.file_path] = {h.id for h in fd.hunks}

    def file_modules(path: str) -> list[str]:
        stem = path.rsplit(".", 1)[0] if "." in path else path
        return [stem, stem.replace("/", "."), stem.split("/")[-1]]

    new_file_modules: dict[str, list[str]] = {
        fp: file_modules(fp)
        for fp in new_file_creators
    }

    checkpoints: list[dict] = []
    committed: set[str] = set()

    for idx, group in enumerate(ordered_groups, start=1):
        committed.update(group.hunk_ids)
        violations: list[dict] = []

        for hid in group.hunk_ids:
            sym = symbol_info.get(hid)
            if not sym:
                continue
            for imp in sym.imports:
                for file_path, modules in new_file_modules.items():
                    if not any(imp == m or imp.startswith(m + ".") for m in modules):
                        continue
                    creator_hunks = new_file_creators[file_path]
                    if not creator_hunks.issubset(committed):
                        # locate creator commit id
                        missing_commit = ""
                        for j, g in enumerate(ordered_groups, start=1):
                            if any(h in g.hunk_ids for h in creator_hunks):
                                missing_commit = f"C{j}"
                                break
                        violations.append({
                            "commit": f"C{idx}",
                            "hunk": hid,
                            "issue": f"imports {imp} before new file exists",
                            "missing_from": missing_commit or f"C{idx}",
                            "fix": "ordering",
                        })

        checkpoints.append({
            "checkpoint": idx,
            "commit_id": f"C{idx}",
            "valid": not violations,
            **({"violations": violations} if violations else {}),
        })

    valid = all(cp["valid"] for cp in checkpoints)
    return {
        "valid": valid,
        "issue_type": None if valid else "ordering",
        "checkpoints": checkpoints,
        "fix_reasoning": "" if valid else "Move provider commits before importing commits.",
        "reasoning_summary": "Programmatic checkpoint validation.",
    }
