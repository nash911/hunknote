# Hunknote Architecture

This document describes the modular architecture of the hunknote codebase.

## Package Structure

```
hunknote/
├── __init__.py              # Package version and metadata
├── __main__.py              # CLI entry point
│
├── cli/                     # CLI Commands (refactored from cli.py)
│   ├── __init__.py          # Main Typer app, registers all commands
│   ├── commit.py            # hunknote commit - Execute commit with generated message
│   ├── compose.py           # hunknote compose - Split changes into commit stack
│   ├── config.py            # hunknote config - Configuration management
│   ├── generate.py          # hunknote (default) - Generate commit message
│   ├── init.py              # hunknote init - Interactive setup wizard
│   ├── scope.py             # hunknote scope - Scope inference tools
│   ├── styles.py            # hunknote styles - Style profile management
│   └── utils.py             # Shared CLI utilities
│
├── styles/                  # Style Profiles & Rendering (refactored from styles.py)
│   ├── __init__.py          # Re-exports public API
│   ├── models.py            # StyleProfile, StyleConfig, ExtendedCommitJSON
│   ├── descriptions.py      # Profile descriptions and constants
│   ├── inference.py         # Ticket/type inference from context
│   ├── config.py            # Style config loading/saving
│   └── renderers/           # Style-specific renderers
│       ├── __init__.py
│       ├── base.py          # Common rendering utilities
│       ├── default.py       # Default style renderer
│       ├── conventional.py  # Conventional Commits renderer
│       ├── blueprint.py     # Blueprint (structured) renderer
│       ├── ticket.py        # Ticket-prefixed renderer
│       └── kernel.py        # Linux kernel style renderer
│
├── compose/                 # Compose Feature (refactored from compose.py)
│   ├── __init__.py          # Re-exports public API
│   ├── models.py            # HunkRef, FileDiff, PlannedCommit, ComposePlan
│   ├── parser.py            # Unified diff parser
│   ├── inventory.py         # Hunk inventory builder
│   ├── validation.py        # Plan validation
│   ├── patch.py             # Patch builder for commits
│   ├── prompt.py            # LLM prompts for compose
│   ├── executor.py          # Git commit execution
│   └── cleanup.py           # Temporary file cleanup
│
├── git/                     # Git Operations (refactored from git_ctx.py)
│   ├── __init__.py          # Re-exports public API
│   ├── exceptions.py        # GitError, NoStagedChangesError
│   ├── runner.py            # Git command execution
│   ├── branch.py            # Branch and commit info
│   ├── merge.py             # Merge state detection
│   ├── status.py            # Git status utilities
│   ├── diff.py              # Diff handling and filtering
│   └── context.py           # Context bundle builder
│
├── cache/                   # Caching (refactored from cache.py)
│   ├── __init__.py          # Re-exports public API
│   ├── models.py            # CacheMetadata, ComposeCacheMetadata
│   ├── paths.py             # Cache file path utilities
│   ├── utils.py             # Hash computation, file extraction
│   ├── message.py           # Commit message cache operations
│   └── compose.py           # Compose plan cache operations
│
├── llm/                     # LLM Integration (unified via LiteLLM)
│   ├── __init__.py          # Provider factory, re-exports
│   ├── base.py              # LLMResult, BaseLLMProvider (slimmed)
│   ├── exceptions.py        # LLMError, MissingAPIKeyError, JSONParseError
│   ├── parsing.py           # JSON response parsing and validation
│   ├── litellm_provider.py  # Unified provider via litellm (all backends)
│   ├── prompts/             # Style-specific prompts (refactored from base.py)
│   │   ├── __init__.py      # Re-exports all prompts
│   │   ├── system.py        # System prompt
│   │   ├── default.py       # Default style prompt
│   │   ├── conventional.py  # Conventional style prompt
│   │   ├── blueprint.py     # Blueprint style prompt
│   │   ├── ticket.py        # Ticket style prompt
│   │   └── kernel.py        # Kernel style prompt
│
├── scope.py                 # Scope inference (not refactored - well-organized)
├── config.py                # Repository configuration
├── user_config.py           # User configuration loading
├── global_config.py         # Global configuration management
├── formatters.py            # Output formatters
│
├── styles.py                # Backward compatibility shim → styles/
├── compose.py               # Backward compatibility shim → compose/
├── git_ctx.py               # Backward compatibility shim → git/
└── cache.py                 # Backward compatibility shim → cache/
```

## Module Dependencies

```
┌────────────────────────────────────────────────────────┐
│                          CLI                           │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ compose │ │ commit  │ │ generate│ │  init   │  ...  │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘       │
└───────┼───────────┼───────────┼───────────┼────────────┘
        │           │           │           │
        ▼           ▼           ▼           ▼
┌────────────────────────────────────────────────────────┐
│                     Core Modules                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐    │
│  │ compose │  │ styles  │  │   git   │  │  cache  │    │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘    │
│       │            │            │            │         │
│       └────────────┴────────────┴────────────┘         │
│                          │                             │
│                          ▼                             │
│                     ┌─────────┐                        │
│                     │   llm   │                        │
│                     └─────────┘                        │
└────────────────────────────────────────────────────────┘
```

## Key Design Principles

### 1. Backward Compatibility Shims

Original module paths continue to work through shim files that re-export from new packages:

```python
# hunknote/styles.py (shim)
from hunknote.styles import *

# Works for both:
from hunknote.styles import StyleProfile           # Original path
from hunknote.styles.models import StyleProfile    # New path
```

### 2. Package-Level Exports

Each package's `__init__.py` re-exports the public API:

```python
# hunknote/git/__init__.py
from hunknote.git.exceptions import GitError, NoStagedChangesError
from hunknote.git.runner import get_repo_root
from hunknote.git.branch import get_branch
# ... etc
```

### 3. Separation of Concerns

- **Models** in dedicated `models.py` files
- **I/O operations** separate from business logic
- **Prompts** isolated from provider code
- **Utilities** grouped in `utils.py` or `base.py`

### 4. Single Responsibility

Each module has a focused purpose:
- `git/merge.py` - Only merge state detection
- `cache/message.py` - Only commit message caching
- `styles/renderers/blueprint.py` - Only blueprint rendering

## Testing Strategy

Tests patch at the module where functions are defined, not where they are imported:

```python
# Correct - patch at definition location
mocker.patch("hunknote.git.diff._get_staged_files_list", ...)

# Not - patch at import location
mocker.patch("hunknote.git_ctx._get_staged_files_list", ...)  # Won't work
```

## Adding New Features

### Adding a New Style Profile

1. Create `hunknote/styles/renderers/newstyle.py`
2. Add `NEWSTYLE` to `StyleProfile` enum in `models.py`
3. Add renderer function to `renderers/__init__.py`
4. Create `hunknote/llm/prompts/newstyle.py`
5. Add prompt to `prompts/__init__.py`
6. Add tests in `tests/test_styles.py`

### Adding a New CLI Command

1. Create `hunknote/cli/newcommand.py`
2. Register command in `cli/__init__.py`
3. Add tests in `tests/test_cli.py`

### Adding a New LLM Provider

1. Create `hunknote/llm/newprovider_provider.py`
2. Implement `BaseLLMProvider` interface
3. Register in `llm/__init__.py` factory
4. Add tests in `tests/test_llm_providers.py`

## File Size Guidelines

- Individual modules should be **< 300 lines** where possible
- If a module grows beyond 400 lines, consider splitting
- Exception: Test files may be larger due to comprehensive coverage

