"""Integration tests for compose coherence — re-export package gap.

These tests verify that the LLM (google gemini-2.5-flash) incorrectly splits
causally dependent changes across commits when the dependency is invisible
due to imports going through re-export packages (__init__.py / index.ts).

This is NOT a unit test — it makes real API calls to the LLM.

Run:
    python integration_tests/test_reexport_coherence.py

Each test case creates a synthetic diff where:
  - File A defines or modifies a function/class signature
  - File B calls that function/class through a re-export package
  - The re-export package (__init__.py / index.ts) is NOT in the changed set
  - Without re-export tracing, the relationship A ↔ B is invisible
  - The LLM splits them into separate commits, breaking the codebase at the split point
"""

import inspect
import sys
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hunknote.compose.models import ComposePlan, FileDiff, HunkRef
from hunknote.compose.prompt import COMPOSE_SYSTEM_PROMPT, build_compose_prompt
from hunknote.llm.base import parse_json_response


# ============================================================
# Test case data model
# ============================================================

@dataclass
class CoherenceTestCase:
    """A test case for re-export package coherence gap."""

    name: str
    description: str
    file_diffs: list[FileDiff]
    # Files that MUST be in the same commit for correctness
    must_be_together: list[set[str]]


# ============================================================
# Helper: build FileDiff with hunks from raw diff lines
# ============================================================

def make_file_diff(file_path: str, hunks_data: list[dict]) -> FileDiff:
    """Create a FileDiff with hunks from simplified data.

    Args:
        file_path: The file path.
        hunks_data: List of dicts with keys: id, header, lines.
    """
    hunks = []
    for i, hd in enumerate(hunks_data):
        hunks.append(HunkRef(
            id=hd["id"],
            file_path=file_path,
            header=hd.get("header", f"@@ -{i*10+1},5 +{i*10+1},8 @@"),
            old_start=i * 10 + 1,
            old_len=5,
            new_start=i * 10 + 1,
            new_len=8,
            lines=hd["lines"],
        ))
    return FileDiff(
        file_path=file_path,
        diff_header_lines=[f"diff --git a/{file_path} b/{file_path}"],
        hunks=hunks,
    )


# ============================================================
# Test Case 1: Python — add required parameter via __init__.py re-export
# (The exact real-world case that triggered this discovery)
# ============================================================

def case_python_add_required_param() -> CoherenceTestCase:
    """File A adds a required parameter. File B passes it. Import via __init__.py."""
    return CoherenceTestCase(
        name="Python: Add required parameter via __init__.py re-export",
        description=(
            "compose/prompt.py adds a required file_relationships parameter to "
            "build_compose_prompt(). cli/compose.py passes that argument. "
            "cli/compose.py imports build_compose_prompt from hunknote.compose "
            "(the __init__.py), not from hunknote.compose.prompt directly. "
            "Without re-export tracing, these appear unrelated."
        ),
        file_diffs=[
            make_file_diff("mypackage/core/prompt.py", [
                {
                    "id": "H1_a1b2c3",
                    "header": "@@ -8,6 +8,8 @@",
                    "lines": [
                        " from mypackage.core.models import FileDiff",
                        "+from mypackage.core.relationships import FileRelationship",
                        "+",
                    ],
                },
                {
                    "id": "H2_d4e5f6",
                    "header": "@@ -40,6 +42,7 @@",
                    "lines": [
                        " def build_prompt(",
                        "     file_diffs: list[FileDiff],",
                        "     style: str,",
                        "+    file_relationships: list[FileRelationship],",
                        " ) -> str:",
                        '+    """Build prompt with relationship hints."""',
                    ],
                },
            ]),
            make_file_diff("mypackage/cli/generate.py", [
                {
                    "id": "H3_g7h8i9",
                    "header": "@@ -24,6 +24,7 @@",
                    "lines": [
                        " from mypackage.cli.utils import get_style",
                        "+from mypackage.core.relationships import detect_file_relationships",
                        " ",
                    ],
                },
                {
                    "id": "H4_j0k1l2",
                    "header": "@@ -85,6 +86,9 @@",
                    "lines": [
                        "     # Generate prompt",
                        "+    relationships = detect_file_relationships(file_diffs, repo_root)",
                        "+",
                        "     prompt = build_prompt(",
                        "         file_diffs=file_diffs,",
                        "         style=style,",
                        "+        file_relationships=relationships,",
                        "     )",
                    ],
                },
            ]),
        ],
        must_be_together=[{"mypackage/core/prompt.py", "mypackage/cli/generate.py"}],
    )


# ============================================================
# Test Case 2: Python — rename function via __init__.py re-export
# ============================================================

def case_python_rename_function() -> CoherenceTestCase:
    """File A renames a function. File B updates the call. Import via __init__.py."""
    return CoherenceTestCase(
        name="Python: Rename function via __init__.py re-export",
        description=(
            "utils/parser.py renames parse_input() to parse_user_input(). "
            "api/handler.py updates its call to the new name. "
            "api/handler.py imports parse_input from utils (the __init__.py), "
            "not from utils.parser directly."
        ),
        file_diffs=[
            make_file_diff("utils/parser.py", [
                {
                    "id": "H1_m3n4o5",
                    "header": "@@ -15,7 +15,7 @@",
                    "lines": [
                        " ",
                        "-def parse_input(raw_data: str) -> dict:",
                        "+def parse_user_input(raw_data: str) -> dict:",
                        '     """Parse raw input data into structured format."""',
                        "     if not raw_data:",
                    ],
                },
            ]),
            make_file_diff("api/handler.py", [
                {
                    "id": "H2_p6q7r8",
                    "header": "@@ -3,7 +3,7 @@",
                    "lines": [
                        " from flask import request, jsonify",
                        "-from utils import parse_input",
                        "+from utils import parse_user_input",
                        " ",
                    ],
                },
                {
                    "id": "H3_s9t0u1",
                    "header": "@@ -22,7 +22,7 @@",
                    "lines": [
                        " def handle_request():",
                        "     raw = request.get_json()",
                        "-    data = parse_input(raw)",
                        "+    data = parse_user_input(raw)",
                        "     return jsonify(data)",
                    ],
                },
            ]),
        ],
        must_be_together=[{"utils/parser.py", "api/handler.py"}],
    )


# ============================================================
# Test Case 3: TypeScript — change interface via index.ts barrel
# ============================================================

def case_typescript_change_interface() -> CoherenceTestCase:
    """File A changes an interface. File B updates usage. Import via index.ts barrel."""
    return CoherenceTestCase(
        name="TypeScript: Change interface via index.ts barrel export",
        description=(
            "src/models/user.ts adds a required email field to UserConfig interface. "
            "src/services/auth.ts constructs UserConfig with the new field. "
            "auth.ts imports UserConfig from '../models' (index.ts barrel), "
            "not from '../models/user' directly."
        ),
        file_diffs=[
            make_file_diff("src/models/user.ts", [
                {
                    "id": "H1_v2w3x4",
                    "header": "@@ -5,6 +5,7 @@",
                    "lines": [
                        " export interface UserConfig {",
                        "   name: string;",
                        "   role: string;",
                        "+  email: string;",
                        " }",
                    ],
                },
            ]),
            make_file_diff("src/services/auth.ts", [
                {
                    "id": "H2_y5z6a7",
                    "header": "@@ -1,6 +1,6 @@",
                    "lines": [
                        "-import { UserConfig } from '../models';",
                        "+import { UserConfig } from '../models';",
                        " ",
                    ],
                },
                {
                    "id": "H3_b8c9d0",
                    "header": "@@ -18,6 +18,7 @@",
                    "lines": [
                        "   const config: UserConfig = {",
                        "     name: user.name,",
                        "     role: user.role,",
                        "+    email: user.email,",
                        "   };",
                    ],
                },
            ]),
        ],
        must_be_together=[{"src/models/user.ts", "src/services/auth.ts"}],
    )


# ============================================================
# Test Case 4: Python — change return type via __init__.py re-export
# ============================================================

def case_python_change_return_type() -> CoherenceTestCase:
    """File A changes return type. File B updates how it handles the return value."""
    return CoherenceTestCase(
        name="Python: Change return type via __init__.py re-export",
        description=(
            "database/queries.py changes get_user() to return Optional[User] instead "
            "of User (can now return None). "
            "routes/profile.py adds a None check. "
            "routes/profile.py imports get_user from database (the __init__.py)."
        ),
        file_diffs=[
            make_file_diff("database/queries.py", [
                {
                    "id": "H1_e1f2g3",
                    "header": "@@ -2,6 +2,7 @@",
                    "lines": [
                        "+from typing import Optional",
                        " from database.models import User",
                        " ",
                    ],
                },
                {
                    "id": "H2_h4i5j6",
                    "header": "@@ -30,8 +31,10 @@",
                    "lines": [
                        "-def get_user(user_id: int) -> User:",
                        "+def get_user(user_id: int) -> Optional[User]:",
                        '     """Fetch user by ID."""',
                        "-    return db.session.query(User).get(user_id)",
                        "+    user = db.session.query(User).get(user_id)",
                        "+    return user  # May be None if not found",
                    ],
                },
            ]),
            make_file_diff("routes/profile.py", [
                {
                    "id": "H3_k7l8m9",
                    "header": "@@ -15,7 +15,10 @@",
                    "lines": [
                        " def get_profile(user_id: int):",
                        "-    user = get_user(user_id)",
                        "-    return render_template('profile.html', user=user)",
                        "+    user = get_user(user_id)",
                        "+    if user is None:",
                        "+        abort(404)",
                        "+    return render_template('profile.html', user=user)",
                    ],
                },
            ]),
        ],
        must_be_together=[{"database/queries.py", "routes/profile.py"}],
    )


# ============================================================
# Test Case 5: TypeScript — rename exported constant via index.ts barrel
# ============================================================

def case_typescript_rename_constant() -> CoherenceTestCase:
    """File A renames a constant. File B updates usage. Import via index.ts barrel."""
    return CoherenceTestCase(
        name="TypeScript: Rename constant via index.ts barrel",
        description=(
            "src/config/defaults.ts renames MAX_RETRIES to MAX_RETRY_COUNT. "
            "src/api/client.ts updates its usage. "
            "client.ts imports MAX_RETRIES from '../config' (index.ts barrel)."
        ),
        file_diffs=[
            make_file_diff("src/config/defaults.ts", [
                {
                    "id": "H1_n0o1p2",
                    "header": "@@ -8,7 +8,7 @@",
                    "lines": [
                        " export const API_TIMEOUT = 30000;",
                        "-export const MAX_RETRIES = 3;",
                        "+export const MAX_RETRY_COUNT = 3;",
                        " export const BASE_URL = 'https://api.example.com';",
                    ],
                },
            ]),
            make_file_diff("src/api/client.ts", [
                {
                    "id": "H2_q3r4s5",
                    "header": "@@ -1,7 +1,7 @@",
                    "lines": [
                        "-import { MAX_RETRIES, API_TIMEOUT } from '../config';",
                        "+import { MAX_RETRY_COUNT, API_TIMEOUT } from '../config';",
                        " ",
                    ],
                },
                {
                    "id": "H3_t6u7v8",
                    "header": "@@ -25,7 +25,7 @@",
                    "lines": [
                        " async function fetchWithRetry(url: string) {",
                        "-  for (let i = 0; i < MAX_RETRIES; i++) {",
                        "+  for (let i = 0; i < MAX_RETRY_COUNT; i++) {",
                        "     try {",
                    ],
                },
            ]),
        ],
        must_be_together=[{"src/config/defaults.ts", "src/api/client.ts"}],
    )


# ============================================================
# Test Case 6: Python — change class constructor via __init__.py re-export
# ============================================================

def case_python_change_constructor() -> CoherenceTestCase:
    """File A adds required __init__ param. File B updates instantiation."""
    return CoherenceTestCase(
        name="Python: Change class constructor via __init__.py re-export",
        description=(
            "models/config.py adds a required 'timeout' parameter to AppConfig.__init__. "
            "services/app.py passes the new argument. "
            "services/app.py imports AppConfig from models (the __init__.py)."
        ),
        file_diffs=[
            make_file_diff("models/config.py", [
                {
                    "id": "H1_w9x0y1",
                    "header": "@@ -10,8 +10,10 @@",
                    "lines": [
                        " class AppConfig:",
                        '-    def __init__(self, name: str, debug: bool = False):',
                        "+    def __init__(self, name: str, timeout: int, debug: bool = False):",
                        '         """Initialize application config."""',
                        "         self.name = name",
                        "+        self.timeout = timeout",
                        "         self.debug = debug",
                    ],
                },
            ]),
            make_file_diff("services/app.py", [
                {
                    "id": "H2_z2a3b4",
                    "header": "@@ -20,7 +20,8 @@",
                    "lines": [
                        " def create_app():",
                        "-    config = AppConfig(name='myapp')",
                        "+    config = AppConfig(name='myapp', timeout=30)",
                        "     return App(config)",
                    ],
                },
            ]),
        ],
        must_be_together=[{"models/config.py", "services/app.py"}],
    )


# ============================================================
# Test Case 7: Python — 3-file chain: schema → serializer → API endpoint
# Each file looks like a separate concern, but they form a causal chain.
# ============================================================

def case_python_three_file_chain() -> CoherenceTestCase:
    """Schema adds required field → serializer adds field mapping → endpoint passes field."""
    return CoherenceTestCase(
        name="Python: 3-file causal chain (schema → serializer → endpoint)",
        description=(
            "models/schema.py adds a required 'priority' field to TaskSchema. "
            "serializers/task.py adds the field to the serialization mapping. "
            "api/tasks.py passes the new field when creating a task. "
            "Each file looks like a separate layer concern, but committing "
            "schema.py alone breaks serialization, and committing serializer "
            "alone breaks the API endpoint."
        ),
        file_diffs=[
            make_file_diff("models/schema.py", [
                {
                    "id": "H1_ch01a1",
                    "header": "@@ -12,6 +12,7 @@",
                    "lines": [
                        " class TaskSchema(BaseModel):",
                        "     title: str",
                        "     description: str",
                        "+    priority: int  # 1=low, 2=medium, 3=high",
                        "     assignee_id: Optional[int] = None",
                    ],
                },
            ]),
            make_file_diff("serializers/task.py", [
                {
                    "id": "H2_ch01b2",
                    "header": "@@ -18,6 +18,7 @@",
                    "lines": [
                        "     def to_dict(self, task: TaskSchema) -> dict:",
                        '         return {',
                        '             "title": task.title,',
                        '             "description": task.description,',
                        '+            "priority": task.priority,',
                        '             "assignee_id": task.assignee_id,',
                        "         }",
                    ],
                },
            ]),
            make_file_diff("api/tasks.py", [
                {
                    "id": "H3_ch01c3",
                    "header": "@@ -30,6 +30,7 @@",
                    "lines": [
                        " def create_task(request):",
                        "     data = request.get_json()",
                        "     task = TaskSchema(",
                        "         title=data['title'],",
                        "         description=data['description'],",
                        "+        priority=data.get('priority', 2),",
                        "     )",
                    ],
                },
            ]),
        ],
        must_be_together=[{"models/schema.py", "serializers/task.py", "api/tasks.py"}],
    )


# ============================================================
# Test Case 8: TypeScript — 4 files, 2 coupled pairs + noise
# Two independent features interleaved. The LLM must NOT merge everything
# into one commit, but MUST keep each pair together.
# ============================================================

def case_typescript_two_coupled_pairs() -> CoherenceTestCase:
    """Two independent features, each spanning 2 files, interleaved in the diff."""
    return CoherenceTestCase(
        name="TypeScript: 4 files — two coupled pairs interleaved",
        description=(
            "Feature A: src/models/order.ts adds 'discount' field to Order interface. "
            "src/services/billing.ts uses the new discount field in calculateTotal(). "
            "Feature B (independent): src/utils/logger.ts adds a new log level. "
            "src/middleware/errorHandler.ts uses the new log level. "
            "Features A and B are independent of each other, but within each feature "
            "the files are causally dependent. The LLM should create 2 commits, "
            "not 4 (one per file)."
        ),
        file_diffs=[
            make_file_diff("src/models/order.ts", [
                {
                    "id": "H1_cp02a1",
                    "header": "@@ -3,6 +3,7 @@",
                    "lines": [
                        " export interface Order {",
                        "   id: string;",
                        "   items: OrderItem[];",
                        "   total: number;",
                        "+  discount: number;",
                        " }",
                    ],
                },
            ]),
            make_file_diff("src/utils/logger.ts", [
                {
                    "id": "H2_cp02b2",
                    "header": "@@ -5,6 +5,7 @@",
                    "lines": [
                        " export enum LogLevel {",
                        "   DEBUG = 'debug',",
                        "   INFO = 'info',",
                        "   WARN = 'warn',",
                        "+  AUDIT = 'audit',",
                        "   ERROR = 'error',",
                        " }",
                    ],
                },
            ]),
            make_file_diff("src/services/billing.ts", [
                {
                    "id": "H3_cp02c3",
                    "header": "@@ -15,7 +15,8 @@",
                    "lines": [
                        " export function calculateTotal(order: Order): number {",
                        "   const subtotal = order.items.reduce((sum, item) => sum + item.price, 0);",
                        "-  return subtotal;",
                        "+  const discounted = subtotal * (1 - order.discount);",
                        "+  return Math.max(0, discounted);",
                        " }",
                    ],
                },
            ]),
            make_file_diff("src/middleware/errorHandler.ts", [
                {
                    "id": "H4_cp02d4",
                    "header": "@@ -8,6 +8,9 @@",
                    "lines": [
                        " export function handleError(err: Error, req: Request, res: Response) {",
                        "   logger.log(LogLevel.ERROR, err.message);",
                        "+  if (err instanceof AuthorizationError) {",
                        "+    logger.log(LogLevel.AUDIT, `Auth failure: ${req.path}`);",
                        "+  }",
                        "   res.status(500).json({ error: 'Internal server error' });",
                        " }",
                    ],
                },
            ]),
        ],
        must_be_together=[
            {"src/models/order.ts", "src/services/billing.ts"},
            {"src/utils/logger.ts", "src/middleware/errorHandler.ts"},
        ],
    )


# ============================================================
# Test Case 9: Python — behavioral coupling without shared identifiers
# File A changes a config constant. File B changes validation logic
# that depends on that constant. No shared function/class names.
# ============================================================

def case_python_behavioral_coupling() -> CoherenceTestCase:
    """Config changes a limit. Validation changes logic to match. No shared symbols."""
    return CoherenceTestCase(
        name="Python: Behavioral coupling — config limit + validation logic",
        description=(
            "settings/limits.py changes MAX_UPLOAD_SIZE from 10MB to 50MB. "
            "middleware/upload.py changes the chunked upload logic to handle the "
            "new larger size (increases buffer, adjusts progress calculation). "
            "There are no shared function names or class names between the files — "
            "the coupling is purely behavioral: the validation logic assumes a "
            "specific max size that the config defines."
        ),
        file_diffs=[
            make_file_diff("settings/limits.py", [
                {
                    "id": "H1_bh03a1",
                    "header": "@@ -5,7 +5,7 @@",
                    "lines": [
                        " # Upload configuration",
                        "-MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB",
                        "+MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB",
                        " ALLOWED_EXTENSIONS = {'.png', '.jpg', '.pdf'}",
                    ],
                },
            ]),
            make_file_diff("middleware/upload.py", [
                {
                    "id": "H2_bh03b2",
                    "header": "@@ -12,9 +12,11 @@",
                    "lines": [
                        " def process_upload(request):",
                        '     """Handle file upload with chunked reading."""',
                        "-    CHUNK_SIZE = 1024 * 1024  # 1MB chunks",
                        "+    CHUNK_SIZE = 5 * 1024 * 1024  # 5MB chunks for larger uploads",
                        "     bytes_read = 0",
                        "     chunks = []",
                    ],
                },
                {
                    "id": "H3_bh03b3",
                    "header": "@@ -28,7 +30,8 @@",
                    "lines": [
                        "     for chunk in request.stream:",
                        "         bytes_read += len(chunk)",
                        "         chunks.append(chunk)",
                        "-        progress = bytes_read / (10 * 1024 * 1024) * 100",
                        "+        # Progress based on configured max size",
                        "+        progress = bytes_read / (50 * 1024 * 1024) * 100",
                        "         emit_progress(progress)",
                    ],
                },
            ]),
        ],
        must_be_together=[{"settings/limits.py", "middleware/upload.py"}],
    )


# ============================================================
# Test Case 10: Python — move class between modules (3 files)
# Class moves from old module to new module. Consumer updates import.
# Each file looks self-contained.
# ============================================================

def case_python_move_class() -> CoherenceTestCase:
    """Move a class from one module to another, consumer updates import."""
    return CoherenceTestCase(
        name="Python: Move class between modules (3 files)",
        description=(
            "core/legacy.py removes the CacheBackend class. "
            "core/cache_backend.py adds the CacheBackend class (moved here). "
            "services/data.py updates its import from core.legacy to core.cache_backend. "
            "Each change looks self-contained: a deletion, an addition, and an import update. "
            "But committing any one alone breaks the codebase."
        ),
        file_diffs=[
            make_file_diff("core/legacy.py", [
                {
                    "id": "H1_mv04a1",
                    "header": "@@ -45,15 +45,3 @@",
                    "lines": [
                        "-class CacheBackend:",
                        '-    """Redis-based cache backend."""',
                        "-",
                        "-    def __init__(self, host: str, port: int = 6379):",
                        "-        self.host = host",
                        "-        self.port = port",
                        "-        self._client = None",
                        "-",
                        "-    def connect(self):",
                        "-        import redis",
                        "-        self._client = redis.Redis(host=self.host, port=self.port)",
                        "-",
                        "-    def get(self, key: str):",
                        "-        return self._client.get(key)",
                    ],
                },
            ]),
            make_file_diff("core/cache_backend.py", [
                {
                    "id": "H2_mv04b2",
                    "header": "@@ -0,0 +1,18 @@",
                    "lines": [
                        '+"""Extracted cache backend module."""',
                        "+",
                        "+",
                        "+class CacheBackend:",
                        '+    """Redis-based cache backend."""',
                        "+",
                        "+    def __init__(self, host: str, port: int = 6379):",
                        "+        self.host = host",
                        "+        self.port = port",
                        "+        self._client = None",
                        "+",
                        "+    def connect(self):",
                        "+        import redis",
                        "+        self._client = redis.Redis(host=self.host, port=self.port)",
                        "+",
                        "+    def get(self, key: str):",
                        "+        return self._client.get(key)",
                    ],
                },
            ]),
            make_file_diff("services/data.py", [
                {
                    "id": "H3_mv04c3",
                    "header": "@@ -1,7 +1,7 @@",
                    "lines": [
                        '-from core.legacy import CacheBackend',
                        '+from core.cache_backend import CacheBackend',
                        " ",
                        " ",
                        " class DataService:",
                    ],
                },
            ]),
        ],
        must_be_together=[{"core/legacy.py", "core/cache_backend.py", "services/data.py"}],
    )


# ============================================================
# Test Case 11: TypeScript — split enum + add new value simultaneously
# File A splits a large enum into two enums. File B and File C each
# update to use the correct sub-enum. Tricky because the split looks
# like a refactor and the usage updates look like independent fixes.
# ============================================================

def case_typescript_split_enum() -> CoherenceTestCase:
    """Split an enum into two, update two consumers to use the correct sub-enum."""
    return CoherenceTestCase(
        name="TypeScript: Split enum into two + update 2 consumers",
        description=(
            "src/types/status.ts splits StatusCode into HttpStatus and AppStatus. "
            "src/api/response.ts updates from StatusCode to HttpStatus. "
            "src/services/workflow.ts updates from StatusCode to AppStatus. "
            "The split looks like a refactor. Each consumer update looks like a "
            "standalone type fix. But committing the split without both consumer "
            "updates breaks compilation."
        ),
        file_diffs=[
            make_file_diff("src/types/status.ts", [
                {
                    "id": "H1_se05a1",
                    "header": "@@ -1,12 +1,16 @@",
                    "lines": [
                        "-export enum StatusCode {",
                        "-  OK = 200,",
                        "-  NOT_FOUND = 404,",
                        "-  ERROR = 500,",
                        "-  PENDING = 'pending',",
                        "-  APPROVED = 'approved',",
                        "-  REJECTED = 'rejected',",
                        "+export enum HttpStatus {",
                        "+  OK = 200,",
                        "+  NOT_FOUND = 404,",
                        "+  ERROR = 500,",
                        "+}",
                        "+",
                        "+export enum AppStatus {",
                        "+  PENDING = 'pending',",
                        "+  APPROVED = 'approved',",
                        "+  REJECTED = 'rejected',",
                        " }",
                    ],
                },
            ]),
            make_file_diff("src/api/response.ts", [
                {
                    "id": "H2_se05b2",
                    "header": "@@ -1,9 +1,9 @@",
                    "lines": [
                        "-import { StatusCode } from '../types/status';",
                        "+import { HttpStatus } from '../types/status';",
                        " ",
                        " export function sendResponse(res: Response, data: any) {",
                        "-  res.status(StatusCode.OK).json(data);",
                        "+  res.status(HttpStatus.OK).json(data);",
                        " }",
                    ],
                },
            ]),
            make_file_diff("src/services/workflow.ts", [
                {
                    "id": "H3_se05c3",
                    "header": "@@ -1,8 +1,8 @@",
                    "lines": [
                        "-import { StatusCode } from '../types/status';",
                        "+import { AppStatus } from '../types/status';",
                        " ",
                        " export function getNextStatus(current: string) {",
                        "-  if (current === StatusCode.PENDING) {",
                        "-    return StatusCode.APPROVED;",
                        "+  if (current === AppStatus.PENDING) {",
                        "+    return AppStatus.APPROVED;",
                        "   }",
                        " }",
                    ],
                },
            ]),
        ],
        must_be_together=[
            {"src/types/status.ts", "src/api/response.ts", "src/services/workflow.ts"},
        ],
    )


# ============================================================
# Test Case 12: Python — change exception type + update all handlers
# The exception class changes, and 3 different files must update
# their except clauses. Looks like 1 refactor + 3 independent fixes.
# ============================================================

def case_python_change_exception_type() -> CoherenceTestCase:
    """Rename exception class, update 3 separate handler files."""
    return CoherenceTestCase(
        name="Python: Rename exception + update 3 handlers across modules",
        description=(
            "core/exceptions.py renames ValidationError to InputValidationError. "
            "api/users.py, api/orders.py, and cli/import_cmd.py each update their "
            "except clause. The rename looks like a refactor. Each handler update "
            "looks like a standalone fix. But committing the rename without ALL "
            "handler updates breaks every except clause that still uses the old name."
        ),
        file_diffs=[
            make_file_diff("core/exceptions.py", [
                {
                    "id": "H1_ex06a1",
                    "header": "@@ -8,7 +8,7 @@",
                    "lines": [
                        " class AuthError(AppError):",
                        "     pass",
                        " ",
                        "-class ValidationError(AppError):",
                        "+class InputValidationError(AppError):",
                        '     """Raised when user input fails validation."""',
                        "     pass",
                    ],
                },
            ]),
            make_file_diff("api/users.py", [
                {
                    "id": "H2_ex06b2",
                    "header": "@@ -3,7 +3,7 @@",
                    "lines": [
                        "-from core import ValidationError",
                        "+from core import InputValidationError",
                        " ",
                    ],
                },
                {
                    "id": "H3_ex06b3",
                    "header": "@@ -22,7 +22,7 @@",
                    "lines": [
                        "     try:",
                        "         user = create_user(data)",
                        "-    except ValidationError as e:",
                        "+    except InputValidationError as e:",
                        '         return {"error": str(e)}, 400',
                    ],
                },
            ]),
            make_file_diff("api/orders.py", [
                {
                    "id": "H4_ex06c4",
                    "header": "@@ -5,7 +5,7 @@",
                    "lines": [
                        "-from core import ValidationError",
                        "+from core import InputValidationError",
                        " ",
                    ],
                },
                {
                    "id": "H5_ex06c5",
                    "header": "@@ -35,7 +35,7 @@",
                    "lines": [
                        "     try:",
                        "         order = process_order(items)",
                        "-    except ValidationError as e:",
                        "+    except InputValidationError as e:",
                        "         logger.warning(f'Order validation failed: {e}')",
                    ],
                },
            ]),
            make_file_diff("cli/import_cmd.py", [
                {
                    "id": "H6_ex06d6",
                    "header": "@@ -2,7 +2,7 @@",
                    "lines": [
                        "-from core import ValidationError",
                        "+from core import InputValidationError",
                        " ",
                    ],
                },
                {
                    "id": "H7_ex06d7",
                    "header": "@@ -48,7 +48,7 @@",
                    "lines": [
                        "     for row in csv_reader:",
                        "         try:",
                        "             validate_and_insert(row)",
                        "-        except ValidationError:",
                        "+        except InputValidationError:",
                        "             errors.append(row)",
                    ],
                },
            ]),
        ],
        must_be_together=[
            {"core/exceptions.py", "api/users.py", "api/orders.py", "cli/import_cmd.py"},
        ],
    )


# ============================================================
# Test runner
# ============================================================

ALL_CASES = [
    case_python_add_required_param,
    case_python_rename_function,
    case_typescript_change_interface,
    case_python_change_return_type,
    case_typescript_rename_constant,
    case_python_change_constructor,
    # Complex / multi-level cases
    case_python_three_file_chain,
    case_typescript_two_coupled_pairs,
    case_python_behavioral_coupling,
    case_python_move_class,
    case_typescript_split_enum,
    case_python_change_exception_type,
]


def check_coherence(plan: ComposePlan, must_be_together: list[set[str]], file_diffs: list[FileDiff]) -> tuple[bool, str]:
    """Check if a plan keeps must-be-together files in the same commit.

    Args:
        plan: The compose plan from the LLM.
        must_be_together: List of sets of file paths that must share a commit.
        file_diffs: The file diffs to map hunk IDs to file paths.

    Returns:
        Tuple of (passed, details_string).
    """
    # Build hunk_id → file_path mapping
    hunk_to_file: dict[str, str] = {}
    for fd in file_diffs:
        for hunk in fd.hunks:
            hunk_to_file[hunk.id] = fd.file_path

    # For each commit, find which files it touches
    commit_files: dict[str, set[str]] = {}
    for commit in plan.commits:
        files_in_commit: set[str] = set()
        for hunk_id in commit.hunks:
            if hunk_id in hunk_to_file:
                files_in_commit.add(hunk_to_file[hunk_id])
        commit_files[commit.id] = files_in_commit

    # Check each must-be-together group
    all_passed = True
    details_lines = []

    for group in must_be_together:
        # Find which commits contain files from this group
        commits_per_file: dict[str, str] = {}
        for cid, cfiles in commit_files.items():
            for f in cfiles:
                if f in group:
                    commits_per_file[f] = cid

        unique_commits = set(commits_per_file.values())
        if len(unique_commits) > 1:
            all_passed = False
            details_lines.append(f"  SPLIT: {group} is split across {unique_commits}")
            for f, cid in sorted(commits_per_file.items()):
                details_lines.append(f"    {f} → {cid}")
        else:
            details_lines.append(f"  OK: {group} all in {unique_commits}")

    # Also show the full plan for context
    details_lines.append("")
    details_lines.append("  Plan summary:")
    for commit in plan.commits:
        files = commit_files.get(commit.id, set())
        details_lines.append(f"    {commit.id}: {commit.type}({commit.scope}): {commit.title}")
        details_lines.append(f"         files: {sorted(files)}")

    return all_passed, "\n".join(details_lines)


def run_test(case_fn, provider) -> tuple[str, bool, str]:
    """Run a single test case against the LLM.

    Returns:
        Tuple of (test_name, passed, details).
    """
    case = case_fn()

    # Build the prompt WITHOUT file relationships
    # (to simulate the gap — no re-export tracing available)
    prompt_kwargs = dict(
        file_diffs=case.file_diffs,
        branch="feature/update",
        recent_commits=["Previous commit 1", "Previous commit 2"],
        style="blueprint",
        max_commits=6,
    )

    # Only pass file_relationships if the function supports it
    # (backward-compatible with codebase before Strategy 2)
    sig = inspect.signature(build_compose_prompt)
    if "file_relationships" in sig.parameters:
        prompt_kwargs["file_relationships"] = None  # No relationships — simulates the gap

    prompt = build_compose_prompt(**prompt_kwargs)

    # Call the LLM
    try:
        result = provider.generate_raw(
            system_prompt=COMPOSE_SYSTEM_PROMPT,
            user_prompt=prompt,
        )

        plan_data = parse_json_response(result.raw_response)
        plan = ComposePlan(**plan_data)

        passed, details = check_coherence(plan, case.must_be_together, case.file_diffs)
        details = (
            f"  Model: {result.model} "
            f"({result.input_tokens} in / {result.output_tokens} out)\n"
            + details
        )

        return case.name, passed, details

    except Exception as e:
        return case.name, False, f"  ERROR: {e}"


def main():
    """Run all re-export coherence test cases."""
    # Load config and get the Google provider with gemini-2.5-flash
    from hunknote.config import LLMProvider, load_config
    from hunknote.llm import get_provider

    load_config()
    provider = get_provider(
        provider=LLMProvider.GOOGLE,
        model="gemini-2.5-flash",
    )

    print("=" * 70)
    print("  Re-Export Package Coherence Gap — Integration Tests")
    print("  LLM: Google Gemini 2.5 Flash")
    print("  Testing: Whether LLM splits causally dependent files across commits")
    print("           when the dependency is invisible (no FILE RELATIONSHIPS)")
    print("=" * 70)
    print()

    results = []
    for case_fn in ALL_CASES:
        case = case_fn()
        print(f"Running: {case.name}")
        print(f"  {case.description}")
        print()

        name, passed, details = run_test(case_fn, provider)
        results.append((name, passed, details))

        status = "✅ PASSED (files kept together)" if passed else "❌ FAILED (files split apart)"
        print(f"  Result: {status}")
        print(details)
        print()
        print("-" * 70)
        print()

    # Summary
    total = len(results)
    passed_count = sum(1 for _, p, _ in results if p)
    failed_count = total - passed_count

    print("=" * 70)
    print(f"  SUMMARY: {passed_count}/{total} passed, {failed_count}/{total} failed")
    print()
    for name, passed, _ in results:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")
    print()
    if failed_count > 0:
        print(f"  {failed_count} test(s) demonstrate the re-export coherence gap.")
        print("  These cases need Tier 1.5 (re-export tracing) to be fixed.")
    else:
        print("  All tests passed — LLM grouped correctly despite missing relationships.")
        print("  This may vary across runs due to LLM non-determinism.")
    print("=" * 70)


if __name__ == "__main__":
    main()



