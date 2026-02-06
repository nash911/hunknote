# AI Commit Message Generator (CLI) — Build Plan (90 minutes)

## Project description

**Objective:** Build a fast, reliable CLI tool that generates a high-quality **git commit message** from the *current repository state* using an LLM, without needing extra prompting inside your IDE.

**Core behavior (MVP):**
- Collect **git context**: current branch name, `git status`, last 5 commit subjects, and staged diff (`git diff --staged`).
- Send that context to an LLM that returns **structured JSON** (title + bullet points).
- Render the JSON into a normal commit message:
  - **Title** line
  - blank line
  - **bullet list** body
- Save the message inside the repo at: `<project_root>/.tmp/aicommit_<pid>.txt`
- Support UX flags:
  - `-e/--edit`: open the generated message file in **gedit** for manual edits
  - `-c/--commit`: perform the commit **via the tool** (internally runs `git commit -F <message_file>`)

**Constraints:**
- Timebox: **90 minutes**
- Python: **3.12**
- Install: `poetry install`

**Non-goals (for this hackathon MVP):**
- No Copilot transcript parsing
- No PR description generation
- No fancy style learning beyond basic prompt
- No unstaged diff support (only staged changes)

---

## Repo layout (target)

```
aicommit/
  pyproject.toml
  README.md
  aicommit/
    __init__.py
    cli.py
    git_ctx.py
    llm.py
    formatters.py
```

---

## Milestone 0 ✅ — Setup (5–10 min)

### Agent task
1. Initialize a new repo folder `aicommit/`.
2. Create a Poetry project (Python 3.12).
3. Add dependencies:
   - `typer`
   - `pydantic`
   - `anthropic`
4. Configure console scripts:
   - `aicommit`
   - `git-aicommit` (optional but nice; enables `git aicommit ...`)

### Acceptance criteria
- `poetry install` succeeds.
- Running `poetry run aicommit --help` shows the CLI.

### Notes
- Keep dependencies minimal. Avoid extras unless you need them.

---

## Milestone 1 ✅ — Git context collector (15–20 min)

### Agent task
Create `aicommit/git_ctx.py` with functions:

- `get_repo_root() -> Path`  
  - runs: `git rev-parse --show-toplevel`
  - errors nicely if not in git repo

- `get_branch() -> str`  
  - `git branch --show-current`

- `get_status() -> str`  
  - `git status --porcelain=v1 -b`

- `get_last_commits(n=5) -> list[str]`  
  - `git log -n 5 --pretty=%s`

- `get_staged_diff(max_chars=50000) -> str`  
  - `git diff --staged`
  - if empty: raise an error like “No staged changes. Run git add …”
  - if huge: truncate to `max_chars` and append `\n...[truncated]\n`

- `build_context_bundle(...) -> str`  
  produce a single string:
  ```
  [BRANCH]
  ...

  [STATUS]
  ...

  [LAST_5_COMMITS]
  - ...
  - ...

  [STAGED_DIFF]
  ...
  ```

### Acceptance criteria
- In a git repo with staged changes:
  - `build_context_bundle()` returns a string containing all sections.
- In a repo with **no staged changes**:
  - tool exits with a clear message and non-zero code.

---

## Milestone 2 ✅ — Commit JSON schema + rendering (10–15 min)

### Agent task
Create `aicommit/formatters.py`:

1. Pydantic model `CommitMessageJSON`:
   - `title: str`
   - `body_bullets: list[str]`

2. `render_commit_message(data: CommitMessageJSON) -> str`
   - Ensure title is single line, trimmed.
   - Render:
     ```
     <title>

     - bullet 1
     - bullet 2
     ```

3. (Optional) `sanitize_title(title: str) -> str`  
   enforce <= 72 chars by trimming (keep it simple).

### Acceptance criteria
- Given sample JSON, renderer outputs the exact message format.

---

## Milestone 3 ✅ — LLM call (JSON output) (20–25 min)

### Agent task
Create `aicommit/llm.py`:

1. Load configuration:
   - API key from env `ANTHROPIC_API_KEY` (required)
   - model from env `ANTHROPIC_MODEL` (default e.g. `"claude-3-5-sonnet-latest"` or `"claude-sonnet-4-5"` depending on availability)
   - Keep `max_tokens` modest (e.g. 600–900)

2. Implement `generate_commit_json(context_bundle: str) -> CommitMessageJSON`:
   - Call Anthropic Messages API via official `anthropic` SDK.
   - **Prompt** the model to output *only valid JSON* matching this exact schema:
     ```json
     {
       "title": "string",
       "body_bullets": ["string", "..."]
     }
     ```
   - Enforce instructions in prompt:
     - title imperative, <=72 chars
     - 2–7 bullets
     - bullets describe *what changed* and *why*, not implementation trivia
     - no markdown fences, no extra keys, no commentary
   - Parse with `json.loads`, then validate via `CommitMessageJSON`.

3. Robustness:
   - If parsing fails, show the raw model output in error and exit non-zero.

### Acceptance criteria
- With `ANTHROPIC_API_KEY` set, tool returns a validated `CommitMessageJSON`.

---

## Milestone 4 ✅ — CLI + file writing (15–20 min)

### Agent task
Create `aicommit/cli.py` with Typer:

Command: `aicommit`

Flags:
- `-e/--edit` (bool): open in gedit
- `-c/--commit` (bool): perform commit using the tool
- `--json` (bool, optional): print raw JSON for debugging
- `--max-diff-chars` (int, optional): default 50000

Main flow:
1. Determine repo root via `get_repo_root()`.
2. Ensure `<repo_root>/.tmp/` exists.
3. Build message file path:
   - `<repo_root>/.tmp/aicommit_<pid>.txt`
4. Collect context bundle.
5. Generate commit JSON via `generate_commit_json()`.
6. Render commit message text.
7. Write message text to the file.
8. Print the rendered message to stdout.

### Acceptance criteria
- Running `poetry run aicommit`:
  - prints a title + bullet body
  - creates `<repo_root>/.tmp/aicommit_<pid>.txt`

---

## Milestone 5 ✅ — `--edit` in gedit (10–12 min)

### Agent task
In `cli.py`:
- If `--edit`:
  - Launch editor on the message file.
  - Preferred:
    - `gedit --wait <file>` (if supported)
  - Fallback:
    - run `gedit <file>` then prompt user: “Save and close editor, then press Enter…”
  - After editor finishes, re-read the file as the final message content.
- If gedit not found:
  - fall back to `$EDITOR` if set, else `nano`.

### Acceptance criteria
- `poetry run aicommit -e` opens a file and resumes after edits.

---

## Milestone 6 ✅ — Tool-native commit flag `-c/--commit` (10–12 min)

### Agent task
Implement commit behavior in the tool itself:

- If `--commit` is set:
  1. Ensure message file exists (it should, from previous steps).
  2. Run:
     ```bash
     git commit -F <repo_root>/.tmp/aicommit_<pid>.txt
     ```
  3. Surface stderr if commit fails.

**Important UX requirement:** Users should run **the tool’s flag**:
```bash
aicommit -c
aicommit -e -c
```
The tool internally calls `git commit -F ...`.

### Acceptance criteria
- `poetry run aicommit -c` creates a git commit using generated message.
- `poetry run aicommit -e -c` commits using edited message.

---

## Milestone 7 ✅ — Polish (remaining time)

### Agent task (only if time remains)
- Add `git-aicommit` console script entrypoint so you can run:
  ```bash
  git aicommit -e -c
  ```
- Add friendly error messages:
  - missing API key
  - not in git repo
  - no staged diff
- Add `README.md` quickstart:
  - install (`poetry install`)
  - usage examples
  - env vars

### Acceptance criteria
- Smooth demo in any repo.

---

## Suggested prompts (copy into code)

### System prompt
You are an expert software engineer. Write concise, high-signal git commit messages.

### User prompt template
Given the following git context, produce a JSON object with exactly these keys:
- "title": string (imperative, <=72 chars)
- "body_bullets": array of 2–7 strings (each concise, describe what changed and why)

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys.
- Do not mention “diff”, “git”, or tool instructions.
- Prefer user-visible impact and rationale over implementation minutiae.

GIT CONTEXT:
<INSERT_CONTEXT_BUNDLE_HERE>

---

## Local demo script (2 minutes)
1. Make a small change
2. `git add -p`
3. `poetry run aicommit`
4. `poetry run aicommit -e -c`

---

## pyproject.toml checklist
- Requires Python 3.12
- Includes console scripts:
  - `aicommit = "aicommit.cli:app"`
  - `git-aicommit = "aicommit.cli:app"` (optional)

---

*End of build plan.*
