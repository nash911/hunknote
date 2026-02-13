You are a senior maintainer. The name "hunknote" is already taken. So, perform a complete branding + namespace migration of this project from “hunknote” to “hunknote”.

CONTEXT (current project state)
- Current README says the tool name/commands are hunknote + git hunknote; config is ... and per-repo under .hunknote/; cache files live under <repo>/.hunknote/; install name currently uses “hunknote”; and there are multiple commands like init/config/ignore plus multi-LLM support and caching. Update ALL of this to “hunknote”.

HIGH-LEVEL GOAL
- New product name: Hunknote
- Primary CLI command: `hunknote`
- Git subcommand: `git hunknote`
- New global config directory: `~/.hunknote/`
- New per-repo directory: `.hunknote/`
- New cache files directory: `<repo>/.hunknote/`
- Keep identical unless explicitly noted below.

CRITICAL REQUIREMENT: Backward compatibility (for OSS adoption)
Implement a migration layer so existing users are not broken:
1) Do not directly rename/remove files or directories that are git tracked. Instead, use git mv and git rm where applicable to preserve history.
2) Completely remove the old entrypoints `hunknote` and `git hunknote`.
3) Config + cache fallback:
   - If `~/.hunknote/` doesn’t exist but `~/.hunknote/` does, load the old config/credentials and warn.
   - If `.hunknote/` doesn’t exist but `.hunknote/` does, load old repo config/cache and warn.

PACKAGING + NAMING (Python)
- Rename the import package from `hunknote` to `hunknote` (directory, imports, internal references, tests).
- Update pyproject/Poetry metadata:
  - Distribution/package name: `hunknote` is availability on PyPI, so use that.
- Update console scripts:
  - `hunknote = hunknote.cli:app`
  - `git-hunknote = hunknote.cli:app`

CODEBASE CHANGES (systematic)
Do a global search/replace, but be careful with semantics:
- Replace user-facing strings:
  - help text, banners, error messages, debug output, README examples
- Replace filesystem paths:
  - ~/.hunknote → ~/.hunknote
  - .hunknote → .hunknote
  - filenames like hunknote_message.txt, hunknote_metadata.json, etc. → hunknote_message.txt, hunknote_metadata.json, etc.
- Replace internal identifiers where appropriate:
  - classes, variables, constants, cache keys, directory names
- Keep provider API key environment variable names as-is (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.). Only tool-specific paths/names change.

README + DOCS UPDATE (must be complete)
Update README to reflect “Hunknote” everywhere:
- Title, description, badges (if any)
- Installation:
  - pipx / pip commands updated to the new distribution name
- Verify installation examples:
  - `hunknote --help`
  - `git hunknote --help`
- Quickstart:
  - `hunknote init`
  - `hunknote -e -c`
- Configuration paths:
  - global config under `~/.hunknote/`
  - per-repo config under `.hunknote/config.yaml`
- Cache paths + gitignore recommendations:
  - update `.hunknote/...` → `.hunknote/...`
- Update every section that mentions “hunknote” (usage tables, commands list, how-it-works, development/test sections).

TESTS + QA (must pass)
- Update all tests to the new package/module name and new default paths.
- Add tests for backward compatibility:
  - If only old dirs exist, tool still works and warns.
  - `hunknote migrate` copies/renames as expected.
- Run full suite; ensure it remains green.

DELIVERABLES (commit as a sequence)
Do this in milestones; each milestone should produce a clean commit:
Milestone 1: Package + import rename (`hunknote` → `hunknote`), update entrypoints, keep aliases.
Milestone 2: Path migration: new default dirs + fallback logic + warnings.
Milestone 3: Add `hunknote migrate` command + tests.
Milestone 4: README/docs overhaul to “hunknote” + examples + gitignore updates.
Milestone 5: Final QA: run lint/tests, sanity run in a sample repo.

ACCEPTANCE CHECKLIST (final)
- `poetry install` works.
- `poetry run hunknote --help` works.
- `poetry run hunknote --help` works and prints a deprecation warning.
- In a git repo with staged changes:
  - `hunknote` generates message
  - `hunknote -e` opens editor
  - `hunknote -c` commits using the generated message
  - `git hunknote` works
- Old config/cache directories still work (with warning), and `hunknote migrate` moves them.

Proceed now; do not ask questions unless blocked by missing info.
