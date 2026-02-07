# Caching Plan: Prevent Redundant LLM API Calls

## Problem Statement

Currently, every invocation of the `aicommit` command (e.g., `aicommit`, `aicommit -e`, `aicommit -c`) triggers the complete pipeline:

1. **Context gathering** - Git branch, status, last commits, staged diff
2. **LLM API call** - Send context to Anthropic, get JSON response
3. **JSON parsing** - Parse and validate the commit message

This results in:
- **Multiple API calls** for the exact same git context (same staged changes)
- **Different commit messages** each time, even when nothing has changed
- **Wasted API credits** and increased latency
- **Poor UX**: User generates message with `aicommit`, then runs `aicommit -e` to edit, and gets a completely different message

## Desired Behavior

The workflow should support:
1. `aicommit` — Generate and display the commit message (cache it)
2. `aicommit -e` — Reuse cached message OR generate if no cache; open editor
3. `aicommit -c` — Reuse cached message OR generate if no cache; commit
4. `aicommit -e -c` — Reuse cached message OR generate if no cache; edit, then commit

**Key principle**: If the staged changes havent changed since the last generation, reuse the cached message. If changes have occurred, regenerate.

---

## Proposed Solution: Context-Hash-Based Caching

### Overview

Use a **hash of the git context** (staged diff + branch + last commits) as a cache key. Store both the context hash and the generated message in the `.tmp/` directory.

### Cache Files

Location: `<repo_root>/.tmp/`

| File | Purpose |
|------|---------|
| `aicommit_message.txt` | The latest generated/edited commit message |
| `aicommit_context_hash.txt` | SHA256 hash of the context bundle used to generate the message |

**Note**: Removed PID-based naming. Use a single, stable file per repo.

### Cache Key Computation

```python
import hashlib

def compute_context_hash(context_bundle: str) -> str:
    """Compute SHA256 hash of the git context bundle."""
    return hashlib.sha256(context_bundle.encode()).hexdigest()
```

The context bundle already includes:
- Branch name
- Git status
- Last 5 commits
- Staged diff

This provides a comprehensive fingerprint of the current state.

---

## Implementation Plan

### Step 1: Add Caching Utility Functions

Create helper functions in `cli.py` (or a new `cache.py` module):

```python
def get_cache_dir(repo_root: Path) -> Path:
    """Return the .tmp directory, creating it if needed."""
    cache_dir = repo_root / ".tmp"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir

def get_message_file(repo_root: Path) -> Path:
    """Return path to the cached message file."""
    return get_cache_dir(repo_root) / "aicommit_message.txt"

def get_hash_file(repo_root: Path) -> Path:
    """Return path to the context hash file."""
    return get_cache_dir(repo_root) / "aicommit_context_hash.txt"

def compute_context_hash(context_bundle: str) -> str:
    """Compute SHA256 hash of the context bundle."""
    import hashlib
    return hashlib.sha256(context_bundle.encode()).hexdigest()

def is_cache_valid(repo_root: Path, current_hash: str) -> bool:
    """Check if cached message is still valid for the current context."""
    hash_file = get_hash_file(repo_root)
    message_file = get_message_file(repo_root)
    
    if not hash_file.exists() or not message_file.exists():
        return False
    
    stored_hash = hash_file.read_text().strip()
    return stored_hash == current_hash

def save_cache(repo_root: Path, context_hash: str, message: str) -> None:
    """Save the generated message and its context hash."""
    get_hash_file(repo_root).write_text(context_hash)
    get_message_file(repo_root).write_text(message)

def load_cached_message(repo_root: Path) -> str:
    """Load the cached message."""
    return get_message_file(repo_root).read_text()

def invalidate_cache(repo_root: Path) -> None:
    """Remove cache files (call after successful commit)."""
    hash_file = get_hash_file(repo_root)
    message_file = get_message_file(repo_root)
    if hash_file.exists():
        hash_file.unlink()
    if message_file.exists():
        message_file.unlink()
```

### Step 2: Modify CLI Flow

Update the `main()` function in `cli.py`:

```python
def main(...):
    # 1. Get repo root
    repo_root = get_repo_root()
    
    # 2. Build context bundle
    context_bundle = build_context_bundle(max_chars=max_diff_chars)
    
    # 3. Compute context hash
    current_hash = compute_context_hash(context_bundle)
    
    # 4. Check cache validity
    if is_cache_valid(repo_root, current_hash):
        # Use cached message
        message = load_cached_message(repo_root)
        typer.echo("Using cached commit message...", err=True)
    else:
        # Generate new message via LLM
        typer.echo("Generating commit message...", err=True)
        commit_json = generate_commit_json(context_bundle)
        message = render_commit_message(commit_json)
        # Save to cache
        save_cache(repo_root, current_hash, message)
    
    # 5. Handle --json flag (still need to regenerate for fresh JSON)
    if json_output:
        # Force regeneration to get fresh JSON structure
        commit_json = generate_commit_json(context_bundle)
        typer.echo(commit_json.model_dump_json(indent=2))
        return
    
    # 6. Handle --edit flag
    message_file = get_message_file(repo_root)
    if edit:
        _open_editor(message_file)
        message = message_file.read_text()
        # Update cache with edited message (keep same hash since context unchanged)
        save_cache(repo_root, current_hash, message)
    
    # 7. Display message
    typer.echo("=" * 60)
    typer.echo(message)
    typer.echo("=" * 60)
    
    # 8. Handle --commit flag
    if commit:
        # ... perform commit ...
        # After successful commit, invalidate cache
        invalidate_cache(repo_root)
```

### Step 3: Add `--force` / `--regenerate` Flag

Add an option to bypass cache and force regeneration:

```python
@app.command()
def main(
    ...
    regenerate: bool = typer.Option(
        False,
        "--regenerate",
        "-r",
        is_flag=True,
        flag_value=True,
        help="Force regenerate the commit message, ignoring cache",
    ),
):
```

When `--regenerate` is set, skip the cache check and always call the LLM.

### Step 4: Add `--debug` Flag for Cache Metadata

Add a debug flag to show full metadata about the cached commit message:

```python
@app.command()
def main(
    ...
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        is_flag=True,
        flag_value=True,
        help="Show full metadata of the cached aicommit message",
    ),
):
```

#### Debug Metadata to Display

When `--debug` is set, show:

1. **Staged Files List** — Files currently staged for commit
2. **Diff Preview** — First few lines of each staged file diff
3. **Edit Diff** — If user edited the AI-generated message, show the diff between original AI message and edited version
4. **Cache Key** — The SHA256 hash of the context bundle
5. **Generation Timestamp** — When the cache was created
6. **LLM Model** — Which model was used for generation
7. **Token Usage** — Number of input and output tokens consumed

#### Additional Cache Metadata File

To support debug output, store additional metadata in JSON format:

Location: `<repo_root>/.tmp/aicommit_metadata.json`

```json
{
  "context_hash": "sha256...",
  "generated_at": "2024-01-15T10:30:00Z",
  "model": "claude-sonnet-4-20250514",
  "input_tokens": 1250,
  "output_tokens": 180,
  "staged_files": ["src/main.py", "README.md"],
  "original_message": "AI generated message...",
  "diff_preview": "First 500 chars of diff..."
}
```

#### Debug Output Format

```
============================================================
                    AICOMMIT DEBUG INFO
============================================================

Cache Status: VALID (using cached message)
Cache Key: a1b2c3d4e5f6...
Generated At: 2024-01-15 10:30:00 UTC
LLM Model: claude-sonnet-4-20250514
Tokens: 1250 input / 180 output

Staged Files:
  - src/main.py
  - README.md

Diff Preview:
  diff --git a/src/main.py b/src/main.py
  index 1234567..abcdef0 100644
  --- a/src/main.py
  +++ b/src/main.py
  @@ -10,6 +10,8 @@ def main():
  ...

Message Edit Status: MODIFIED
Original AI Message:
  Add new feature for user authentication
  - Implement login endpoint
  - Add session management

Current Message:
  Add secure user authentication system
  - Implement login endpoint with rate limiting
  - Add session management with JWT tokens

============================================================
```

---

## Updated Workflow Examples

### Example 1: Normal Generation
```bash
$ aicommit
Generating commit message...   # LLM called, result cached
<message displayed>

$ aicommit                      # 2nd run
Using cached commit message... # Cache hit, no LLM call
<same message displayed>
```

### Example 2: Edit then Commit
```bash
$ aicommit                      # Generate and cache
<message displayed>

$ aicommit -e                   # Cache hit, open editor
Using cached commit message...
<editor opens, user edits, saves>

$ aicommit -c                   # Cache hit (with edits), commit
Using cached commit message...
<commit performed>
<cache invalidated>
```

### Example 3: Force Regeneration
```bash
$ aicommit -r                   # Bypass cache
Generating commit message...    # New LLM call
<new message displayed and cached>
```

### Example 4: Context Changed
```bash
$ aicommit                      # Generate for staged changes A
<message for changes A>

$ git add more_files.py         # Stage more changes

$ aicommit                      # Context hash changed
Generating commit message...    # New LLM call (cache invalidated)
<new message for changes A + B>
```

---

## Edge Cases

### 1. No Staged Changes
- Error early, before any caching logic
- Current behavior preserved

### 2. Commit Succeeds
- Invalidate cache after successful `git commit`
- Next `aicommit` will require new staged changes anyway

### 3. Commit Fails
- Keep cache intact
- User can retry with `aicommit -c`

### 4. Editor Cancelled Without Save
- Re-read file after editor closes
- If unchanged, keep original cached message

### 5. Multiple Repos
- Cache is per-repo (in each repos `.tmp/` directory)
- No cross-repo contamination

---

## Files to Modify

1. **`aicommit/cli.py`** — Add caching logic, `--regenerate` flag, and `--debug` flag
2. **`aicommit/cache.py`** — New module for caching utility functions and metadata handling
3. **`aicommit/llm.py`** — Modify to return token usage information
4. **`aicommit/__init__.py`** — (Optional) Export new utilities
5. **`README.md`** — Document new behavior, `--regenerate` flag, and `--debug` flag

---

## Testing Checklist

- [ ] `aicommit` generates and caches message
- [ ] `aicommit` (2nd run, same context) uses cache
- [ ] `aicommit -e` opens cached message in editor
- [ ] `aicommit -c` commits using cached message
- [ ] `aicommit -e -c` works end-to-end
- [ ] `aicommit -r` forces regeneration
- [ ] `aicommit -d` shows debug metadata
- [ ] `aicommit -d` shows edit diff when message was modified
- [ ] Staging additional files invalidates cache
- [ ] Unstaging files invalidates cache
- [ ] Modifying staged files invalidates cache
- [ ] Cache is invalidated after successful commit
- [ ] `--json` flag works (consider: should it use cache or always regenerate?)

---

## Open Questions for Review

1. **Should `--json` use cache?**
   - Option A: Always regenerate for `--json` (current plan)
   - Option B: Parse cached message back to JSON (more complex)
   - **Recommendation**: Keep it simple, `--json` is for debugging anyway

2. **Cache file permissions**
   - Should we set restrictive permissions on `.tmp/` files?
   - API keys arent stored, so low risk

3. **Cache TTL (Time-To-Live)**
   - Should cache expire after X hours even if context unchanged?
   - **Recommendation**: No TTL for MVP; hash-based invalidation is sufficient

---

## Summary

This caching plan introduces:
- **Hash-based cache validation** using SHA256 of the context bundle
- **Stable file naming** (no PID) for message persistence across invocations
- **Automatic cache invalidation** when context changes or commit succeeds
- **`--regenerate` flag** for manual cache bypass
- **Minimal code changes** concentrated in `cli.py`

The implementation preserves all existing functionality while eliminating redundant API calls.
