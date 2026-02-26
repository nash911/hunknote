"""CLI entry point for hunknote.

This module provides the main CLI application that combines all commands
and subcommands into a single unified interface.
"""

import typer

from hunknote.cli.ignore import ignore_app
from hunknote.cli.config import config_app
from hunknote.cli.style import style_app
from hunknote.cli.init import init_config
from hunknote.cli.commit import commit_command
from hunknote.cli.compose import compose_command, _build_hunk_ids_data
from hunknote.cli.main import main_command

# Re-export utility functions for backward compatibility with tests
from hunknote.cli.utils import (
    generate_message_diff as _generate_message_diff,
    get_current_branch_safe as _get_current_branch_safe,
    find_editor as _find_editor,
    open_editor as _open_editor,
    process_intent_options as _process_intent_options,
    compute_intent_fingerprint as _compute_intent_fingerprint,
    inject_intent_into_context as _inject_intent_into_context,
    display_debug_info as _display_debug_info,
    get_effective_style_config as _get_effective_style_config,
    get_effective_scope_config as _get_effective_scope_config,
    colorize_diff as _colorize_diff,
    show_in_pager as _show_in_pager,
)

# Re-export external dependencies used in tests for patching compatibility
# These need to be imported here so tests can patch them at hunknote.cli.*
from hunknote.git_ctx import get_repo_root, GitError, NoStagedChangesError
from hunknote.cache import (
    compute_context_hash,
    extract_staged_files,
    get_diff_preview,
    get_message_file,
    is_cache_valid,
    load_cache_metadata,
    load_cached_message,
    load_raw_json_response,
    save_cache,
    update_message_cache,
    update_metadata_overrides,
)
from hunknote.llm import generate_commit_json, LLMError, MissingAPIKeyError
from hunknote.user_config import (
    add_ignore_pattern,
    get_ignore_patterns,
    remove_ignore_pattern,
    get_repo_style_config,
    set_repo_style_profile,
)
from hunknote import global_config
from hunknote.git_ctx import build_context_bundle, get_staged_diff, get_status

# Main application
app = typer.Typer(
    name="hunknote",
    help="hunknote: AI-powered Git commit manager",
    add_completion=False,
)

# Add subcommand groups
app.add_typer(ignore_app, name="ignore")
app.add_typer(config_app, name="config")
app.add_typer(style_app, name="style")

# Add individual commands
app.command("init")(init_config)
app.command("commit")(commit_command)
app.command("compose")(compose_command)

# Set the main callback for default behavior (includes --version flag)
app.callback(invoke_without_command=True)(main_command)


# Re-export for backward compatibility with imports
__all__ = [
    "app",
    "ignore_app",
    "config_app",
    "style_app",
    "init_config",
    "commit_command",
    "compose_command",
    "main_command",
    # Utility functions (prefixed with _ for internal use)
    "_generate_message_diff",
    "_get_current_branch_safe",
    "_find_editor",
    "_open_editor",
    "_process_intent_options",
    "_compute_intent_fingerprint",
    "_inject_intent_into_context",
    "_display_debug_info",
    "_get_effective_style_config",
    "_get_effective_scope_config",
    "_colorize_diff",
    "_show_in_pager",
    "_build_hunk_ids_data",
    # External dependencies for test patching compatibility
    "get_repo_root",
    "GitError",
    "NoStagedChangesError",
    "compute_context_hash",
    "extract_staged_files",
    "get_diff_preview",
    "get_message_file",
    "is_cache_valid",
    "load_cache_metadata",
    "load_cached_message",
    "load_raw_json_response",
    "save_cache",
    "update_message_cache",
    "update_metadata_overrides",
    "generate_commit_json",
    "LLMError",
    "MissingAPIKeyError",
    "add_ignore_pattern",
    "get_ignore_patterns",
    "remove_ignore_pattern",
    "get_repo_style_config",
    "set_repo_style_profile",
    "global_config",
    "build_context_bundle",
    "get_staged_diff",
    "get_status",
]
