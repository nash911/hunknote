#!/usr/bin/env python
"""Generate hyper_hard test case JSON files for compose coherence evaluation.

These cases are designed to be extremely difficult for LLMs to solve in one shot:
- 20+ files, 50+ hunks per case
- Multi-level circular dependency chains
- Overlapping must_be_together groups
- Mix of renames (must be atomic) + additive changes (ordering only)
- Decoy/noise files that tempt grouping by type
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "integration_tests" / "data"


def make_hunk(hunk_id: str, file_path: str, lines: list[str], header: str = "") -> dict:
    return {
        "id": hunk_id,
        "header": header or f"@@ -{len(lines)*2},5 +{len(lines)*2},8 @@",
        "lines": lines,
    }


def make_file_diff(file_path: str, hunks: list[dict]) -> dict:
    return {
        "file_path": file_path,
        "hunks": hunks,
    }


# ============================================================
# CASE 1: Python microservices — 5 coupled rename chains + noise
#
# Architecture: 5 microservice packages, each with:
#   - service.py (renames a function)
#   - client.py (calls the renamed function from another service)
#   - test_service.py (tests the renamed function)
#   - test_client.py (tests the client)
# Plus: 4 shared utility files, 2 config files, 2 doc files
#
# Dependency web (renames create circular chains):
#   auth.service renames login() -> authenticate()
#   user.client calls auth.login() -> must update to authenticate()
#   billing.service renames charge() -> process_payment()
#   order.client calls billing.charge() -> must update
#   notification.service renames send() -> dispatch()
#   user.service calls notification.send() -> must update
#   order.service renames create_order() -> place_order()
#   billing.client calls order.create_order() -> must update
#   auth.client calls user.get_profile() which is also renamed
#
# This creates 5 coupled groups where each rename propagates to
# a different service's client, forming a star topology.
# ============================================================

def generate_case1():
    """Generate microservices case with heterogeneous cascading renames.

    Key anti-LLM-lumping techniques:
    1. Each service rename CASCADES to a different name in the next layer
       (auth: login->authenticate, but user.client calls it as verify_credentials->validate)
    2. Shared types module renames a type used by all services differently
       per consumer (ServiceRequest->AuthPayload in auth, ->UserPayload in user)
    3. Cross-cutting middleware uses renamed functions from multiple services,
       creating ambiguity about which commit it belongs to
    4. Per-service config files with values specific to the renamed functions
    5. Gateway/router layer aggregates all services with different renamed
       function names, forming a separate natural grouping layer
    """
    file_diffs = []
    hunk_to_file = {}
    relationships = []
    hunk_counter = [0]

    def hid(file_path):
        hunk_counter[0] += 1
        n = hunk_counter[0]
        return f"H{n}_hh01{n:02x}"

    def add_file(path, hunks_data):
        hunks = []
        for lines in hunks_data:
            h = hid(path)
            hunks.append(make_hunk(h, path, lines))
            hunk_to_file[h] = path
        file_diffs.append(make_file_diff(path, hunks))

    # ── Layer 1: Shared types module ─────────────────────────────
    # Renames a base class that all services inherit from differently
    add_file("shared/types.py", [
        ["-class ServiceRequest:",
         "+class ServicePayload:",
         "     def __init__(self, data: dict):",
         "         self.data = data"],
        ["-class ServiceResponse:",
         "+class ServiceResult:",
         "     def __init__(self, status: str, body: dict):",
         "         self.status = status"],
        ["-def validate_request(req: ServiceRequest) -> bool:",
         "+def validate_payload(req: ServicePayload) -> bool:",
         "     return bool(req.data)"],
    ])

    add_file("shared/errors.py", [
        ["-class ServiceError(Exception):",
         "+class ServiceFailure(Exception):",
         "     def __init__(self, code: int, message: str):",
         "         self.code = code"],
        ["-class AuthError(ServiceError):",
         "+class AuthFailure(ServiceFailure):",
         "     pass"],
        ["-class ValidationError(ServiceError):",
         "+class PayloadError(ServiceFailure):",
         "     pass"],
    ])

    add_file("shared/test_types.py", [
        ["-from shared.types import ServiceRequest, ServiceResponse, validate_request",
         "+from shared.types import ServicePayload, ServiceResult, validate_payload"],
        [" def test_validate():",
         "-    req = ServiceRequest({'key': 'val'})",
         "-    assert validate_request(req) is True",
         "+    req = ServicePayload({'key': 'val'})",
         "+    assert validate_payload(req) is True"],
        [" def test_response():",
         "-    resp = ServiceResponse('ok', {})",
         "+    resp = ServiceResult('ok', {})",
         "     assert resp.status == 'ok'"],
    ])
    relationships.append({"source": "shared/test_types.py", "target": "shared/types.py", "kind": "direct"})

    add_file("shared/test_errors.py", [
        ["-from shared.errors import ServiceError, AuthError, ValidationError",
         "+from shared.errors import ServiceFailure, AuthFailure, PayloadError"],
        [" def test_auth_error_hierarchy():",
         "-    err = AuthError(401, 'Unauthorized')",
         "-    assert isinstance(err, ServiceError)",
         "+    err = AuthFailure(401, 'Unauthorized')",
         "+    assert isinstance(err, ServiceFailure)"],
        [" def test_validation_error():",
         "-    err = ValidationError(400, 'Invalid')",
         "-    assert isinstance(err, ServiceError)",
         "+    err = PayloadError(400, 'Invalid')",
         "+    assert isinstance(err, ServiceFailure)"],
    ])
    relationships.append({"source": "shared/test_errors.py", "target": "shared/errors.py", "kind": "direct"})

    # ── Layer 2: Service implementations ─────────────────────────
    # Each uses the renamed shared types AND renames its own function
    services = [
        {"pkg": "auth", "old_fn": "login", "new_fn": "authenticate",
         "old_req": "AuthRequest", "new_req": "AuthCredentials"},
        {"pkg": "user", "old_fn": "get_profile", "new_fn": "fetch_profile",
         "old_req": "ProfileQuery", "new_req": "ProfileLookup"},
        {"pkg": "billing", "old_fn": "charge", "new_fn": "process_payment",
         "old_req": "ChargeRequest", "new_req": "PaymentIntent"},
        {"pkg": "order", "old_fn": "create_order", "new_fn": "place_order",
         "old_req": "OrderRequest", "new_req": "OrderSubmission"},
        {"pkg": "notification", "old_fn": "send", "new_fn": "dispatch",
         "old_req": "NotifyRequest", "new_req": "AlertPayload"},
    ]

    for svc in services:
        pkg = svc["pkg"]
        # models.py — renames the service-specific request class
        model_file = f"services/{pkg}/models.py"
        add_file(model_file, [
            [f"-from shared.types import ServiceRequest",
             f"+from shared.types import ServicePayload"],
            [f"-class {svc['old_req']}(ServiceRequest):",
             f"+class {svc['new_req']}(ServicePayload):",
             f"     \"\"\"Request model for {pkg} service.\"\"\""],
        ])
        relationships.append({"source": model_file, "target": "shared/types.py", "kind": "direct"})

        # service.py — renames the function AND uses renamed model + errors
        svc_file = f"services/{pkg}/service.py"
        add_file(svc_file, [
            [f"-from services.{pkg}.models import {svc['old_req']}",
             f"+from services.{pkg}.models import {svc['new_req']}"],
            [f"-from shared.errors import ServiceError",
             f"+from shared.errors import ServiceFailure"],
            [f"-def {svc['old_fn']}(request: {svc['old_req']}):",
             f"+def {svc['new_fn']}(request: {svc['new_req']}):",
             f'    """Handle {pkg} request."""',
             f"-    if not request.data:",
             f"-        raise ServiceError(400, 'Empty')",
             f"+    if not request.data:",
             f"+        raise ServiceFailure(400, 'Empty')"],
            [f" def handle_{pkg}_request(data):",
             f"-    req = {svc['old_req']}(data)",
             f"-    return {svc['old_fn']}(req)",
             f"+    req = {svc['new_req']}(data)",
             f"+    return {svc['new_fn']}(req)"],
        ])
        relationships.append({"source": svc_file, "target": model_file, "kind": "direct"})
        relationships.append({"source": svc_file, "target": "shared/errors.py", "kind": "direct"})

        # test_service.py
        test_file = f"services/{pkg}/test_service.py"
        add_file(test_file, [
            [f"-from services.{pkg}.service import {svc['old_fn']}",
             f"+from services.{pkg}.service import {svc['new_fn']}"],
            [f"-from services.{pkg}.models import {svc['old_req']}",
             f"+from services.{pkg}.models import {svc['new_req']}"],
            [f"-from shared.errors import ServiceError",
             f"+from shared.errors import ServiceFailure"],
            [f" def test_{svc['old_fn']}_success():",
             f"-    req = {svc['old_req']}({{'key': 'val'}})",
             f"-    result = {svc['old_fn']}(req)",
             f"+    req = {svc['new_req']}({{'key': 'val'}})",
             f"+    result = {svc['new_fn']}(req)",
             f"     assert result.status == 'ok'"],
            [f" def test_{svc['old_fn']}_invalid():",
             f"-    req = {svc['old_req']}({{}})",
             f"-    with pytest.raises(ServiceError):",
             f"-        {svc['old_fn']}(req)",
             f"+    req = {svc['new_req']}({{}})",
             f"+    with pytest.raises(ServiceFailure):",
             f"+        {svc['new_fn']}(req)"],
        ])
        relationships.append({"source": test_file, "target": svc_file, "kind": "direct"})
        relationships.append({"source": test_file, "target": model_file, "kind": "direct"})
        relationships.append({"source": test_file, "target": "shared/errors.py", "kind": "transitive", "via": svc_file})

    # ── Layer 3: Cross-service clients ───────────────────────────
    # Each service calls another service using the cascaded renamed names
    cross_calls = [
        ("user", "auth", "login", "authenticate"),
        ("auth", "user", "get_profile", "fetch_profile"),
        ("order", "billing", "charge", "process_payment"),
        ("billing", "order", "create_order", "place_order"),
        ("user", "notification", "send", "dispatch"),
    ]
    for caller_pkg, target_pkg, old_fn, new_fn in cross_calls:
        client_file = f"services/{caller_pkg}/clients/{target_pkg}_client.py"
        target_svc = next(s for s in services if s["pkg"] == target_pkg)
        add_file(client_file, [
            [f"-from services.{target_pkg}.service import {old_fn}",
             f"+from services.{target_pkg}.service import {new_fn}"],
            [f"-from services.{target_pkg}.models import {target_svc['old_req']}",
             f"+from services.{target_pkg}.models import {target_svc['new_req']}"],
            [f" def call_{target_pkg}(data):",
             f"-    req = {target_svc['old_req']}(data)",
             f"-    return {old_fn}(req)",
             f"+    req = {target_svc['new_req']}(data)",
             f"+    return {new_fn}(req)"],
        ])
        relationships.append({"source": client_file, "target": f"services/{target_pkg}/service.py", "kind": "direct"})
        relationships.append({"source": client_file, "target": f"services/{target_pkg}/models.py", "kind": "direct"})

        test_client_file = f"services/{caller_pkg}/tests/test_{target_pkg}_client.py"
        add_file(test_client_file, [
            [f"-from services.{caller_pkg}.clients.{target_pkg}_client import call_{target_pkg}",
             f"+from services.{caller_pkg}.clients.{target_pkg}_client import call_{target_pkg}"],
            [f" def test_call_{target_pkg}():",
             f"-    mock_{old_fn}.return_value = ServiceResponse('ok', {{}})",
             f"+    mock_{new_fn}.return_value = ServiceResult('ok', {{}})",
             f"     result = call_{target_pkg}(test_data)"],
        ])
        relationships.append({"source": test_client_file, "target": client_file, "kind": "direct"})

    # ── Layer 4: Gateway/Router ──────────────────────────────────
    # Aggregates all services — uses ALL renamed functions + types
    add_file("gateway/router.py", [
        ["-from services.auth.service import login",
         "+from services.auth.service import authenticate"],
        ["-from services.user.service import get_profile",
         "+from services.user.service import fetch_profile"],
        ["-from services.billing.service import charge",
         "+from services.billing.service import process_payment"],
        ["-from services.order.service import create_order",
         "+from services.order.service import place_order"],
        ["-from services.notification.service import send",
         "+from services.notification.service import dispatch"],
        ["-from shared.errors import ServiceError",
         "+from shared.errors import ServiceFailure"],
        [" ROUTE_MAP = {",
         "-    '/auth': login,",
         "-    '/user': get_profile,",
         "-    '/billing': charge,",
         "-    '/order': create_order,",
         "-    '/notify': send,",
         "+    '/auth': authenticate,",
         "+    '/user': fetch_profile,",
         "+    '/billing': process_payment,",
         "+    '/order': place_order,",
         "+    '/notify': dispatch,",
         " }"],
        [" def dispatch_request(path, data):",
         "     handler = ROUTE_MAP.get(path)",
         "-    except ServiceError as e:",
         "+    except ServiceFailure as e:",
         "         return error_response(e.code, e.message)"],
    ])
    for svc in services:
        relationships.append({"source": "gateway/router.py", "target": f"services/{svc['pkg']}/service.py", "kind": "direct"})
    relationships.append({"source": "gateway/router.py", "target": "shared/errors.py", "kind": "direct"})

    add_file("gateway/test_router.py", [
        ["-from shared.errors import ServiceError",
         "+from shared.errors import ServiceFailure"],
        [" def test_auth_route():",
         "-    mock_login.return_value = ServiceResponse('ok', {})",
         "+    mock_authenticate.return_value = ServiceResult('ok', {})",
         "     result = dispatch_request('/auth', {})"],
        [" def test_error_handling():",
         "-    mock_login.side_effect = ServiceError(500, 'fail')",
         "+    mock_authenticate.side_effect = ServiceFailure(500, 'fail')",
         "     result = dispatch_request('/auth', {})"],
    ])
    relationships.append({"source": "gateway/test_router.py", "target": "gateway/router.py", "kind": "direct"})

    # ── Layer 5: Middleware ───────────────────────────────────────
    # Uses auth + user renamed functions together
    add_file("middleware/auth_middleware.py", [
        ["-from services.auth.service import login",
         "+from services.auth.service import authenticate"],
        ["-from services.user.service import get_profile",
         "+from services.user.service import fetch_profile"],
        ["-from shared.errors import AuthError",
         "+from shared.errors import AuthFailure"],
        [" def auth_required(handler):",
         "     def wrapper(request):",
         "-        token = login(request.credentials)",
         "-        request.user = get_profile(token.user_id)",
         "+        token = authenticate(request.credentials)",
         "+        request.user = fetch_profile(token.user_id)",
         "-    except AuthError:",
         "+    except AuthFailure:",
         "         return unauthorized()"],
    ])
    relationships.append({"source": "middleware/auth_middleware.py", "target": "services/auth/service.py", "kind": "direct"})
    relationships.append({"source": "middleware/auth_middleware.py", "target": "services/user/service.py", "kind": "direct"})
    relationships.append({"source": "middleware/auth_middleware.py", "target": "shared/errors.py", "kind": "direct"})

    add_file("middleware/rate_limiter.py", [
        ["-from shared.errors import ServiceError",
         "+from shared.errors import ServiceFailure"],
        [" def rate_limit(handler):",
         "     def wrapper(request):",
         "-        except ServiceError:",
         "+        except ServiceFailure:",
         "             return rate_limited()"],
    ])
    relationships.append({"source": "middleware/rate_limiter.py", "target": "shared/errors.py", "kind": "direct"})

    # ── Per-service config files ─────────────────────────────────
    # Each has config values referencing the renamed function names
    for svc in services:
        pkg = svc["pkg"]
        cfg_file = f"services/{pkg}/config.py"
        add_file(cfg_file, [
            [f"-HANDLER_NAME = '{svc['old_fn']}'",
             f"+HANDLER_NAME = '{svc['new_fn']}'",
             f"-REQUEST_CLASS = '{svc['old_req']}'",
             f"+REQUEST_CLASS = '{svc['new_req']}'"],
        ])

    # ── Noise: independent doc/config files ──────────────────────
    for doc_path in ["docs/API.md", "docs/CHANGELOG.md"]:
        h = hid(doc_path)
        file_diffs.append(make_file_diff(doc_path, [
            make_hunk(h, doc_path, [
                "+## Updated function names",
                "+- auth: login -> authenticate",
                "+- billing: charge -> process_payment",
            ]),
        ]))
        hunk_to_file[h] = doc_path

    # Merge file_diffs that share the same file_path
    merged = {}
    for fd in file_diffs:
        fp = fd["file_path"]
        if fp in merged:
            merged[fp]["hunks"].extend(fd["hunks"])
        else:
            merged[fp] = {"file_path": fp, "hunks": list(fd["hunks"])}
    file_diffs = list(merged.values())

    # Deduplicate relationships
    seen_rels = set()
    unique_rels = []
    for r in relationships:
        key = (r["source"], r["target"], r["kind"])
        if key not in seen_rels:
            seen_rels.add(key)
            unique_rels.append(r)

    # Must be together: ALL files with renames (everything except docs)
    # because the renames cascade: shared→service→client→gateway→middleware
    all_rename_files = set()
    for fd in file_diffs:
        fp = fd["file_path"]
        if fp.startswith("docs/"):
            continue
        for h_data in fd["hunks"]:
            if any(l.startswith("-") for l in h_data["lines"]) and any(l.startswith("+") for l in h_data["lines"]):
                all_rename_files.add(fp)
                break
    must_be_together = [sorted(all_rename_files)]

    num_files = len(file_diffs)
    num_hunks = sum(len(fd["hunks"]) for fd in file_diffs)

    return {
        "id": "py_microservices_5_rename_chains",
        "language": "python",
        "name": f"Python: 5 microservice cascading renames — {num_files} files, {num_hunks} hunks",
        "description": (
            "5 microservice packages with cascading heterogeneous renames across 5 layers: "
            "(1) shared/types.py renames ServiceRequest->ServicePayload and ServiceResponse->ServiceResult. "
            "(2) shared/errors.py renames ServiceError->ServiceFailure, AuthError->AuthFailure, "
            "ValidationError->PayloadError. "
            "(3) Each service renames its own function AND its request model class. "
            "(4) Cross-service clients use BOTH the service's renamed function AND its renamed model. "
            "(5) Gateway/router aggregates all renamed functions. "
            "(6) Middleware uses auth+user renamed functions + renamed errors. "
            f"ALL {len(all_rename_files)} files with renames must be in a single commit. "
            "The LLM is tempted to split by layer (shared, services, clients, gateway, middleware) "
            "or by service (auth, user, billing, order, notification) — both break cascading deps."
        ),
        "difficulty": "hyper_hard",
        "category": "multi_service_cascading_rename",
        "num_files": num_files,
        "num_hunks": num_hunks,
        "file_diffs": file_diffs,
        "file_relationships": unique_rels,
        "must_be_together": must_be_together,
        "must_be_ordered": [],
        "hunk_to_file": hunk_to_file,
    }


# ============================================================
# CASE 2: TypeScript monorepo — 4 packages with interface/type changes
#          cascading through barrel exports across package boundaries
#
# packages/core/types.ts renames UserRole -> Permission
# packages/core/index.ts re-exports Permission
# packages/auth/guards.ts uses Permission (from @core)
# packages/auth/middleware.ts uses Permission
# packages/auth/index.ts re-exports guards, middleware
# packages/api/routes/users.ts uses guards (from @auth)
# packages/api/routes/admin.ts uses guards
# packages/api/routes/billing.ts uses guards
# packages/api/handlers/user.handler.ts uses Permission
# packages/api/handlers/admin.handler.ts uses Permission
# packages/api/handlers/billing.handler.ts uses Permission
# packages/api/index.ts re-exports routes
# packages/ui/hooks/usePermissions.ts uses Permission (from @core)
# packages/ui/components/PermissionGate.tsx uses Permission
# packages/ui/components/AdminPanel.tsx uses PermissionGate
# packages/ui/components/UserSettings.tsx uses PermissionGate
# tests for each package
# Plus: config files, CI pipeline changes
# ============================================================

def generate_case2():
    file_diffs = []
    hunk_to_file = {}
    relationships = []
    hunk_counter = [0]

    def hid(file_path):
        hunk_counter[0] += 1
        n = hunk_counter[0]
        return f"H{n}_hh02{n:02x}"

    def add_file(path, hunks_data):
        hunks = []
        for lines in hunks_data:
            h = hid(path)
            hunks.append(make_hunk(h, path, lines))
            hunk_to_file[h] = path
        file_diffs.append(make_file_diff(path, hunks))

    # Core package — the root of the rename
    add_file("packages/core/src/types.ts", [
        ["-export type UserRole = 'admin' | 'editor' | 'viewer';",
         "+export type Permission = 'admin' | 'editor' | 'viewer';"],
        ["-export interface RoleConfig {", "-  role: UserRole;", "-  level: number;",
         "+export interface PermissionConfig {", "+  permission: Permission;", "+  level: number;",
         " }"],
        ["-export function hasRole(user: User, role: UserRole): boolean {",
         "-  return user.roles.includes(role);",
         "+export function hasPermission(user: User, perm: Permission): boolean {",
         "+  return user.permissions.includes(perm);",
         " }"],
    ])

    add_file("packages/core/src/constants.ts", [
        ["-export const DEFAULT_ROLE: UserRole = 'viewer';",
         "+export const DEFAULT_PERMISSION: Permission = 'viewer';"],
        ["-export const ROLE_HIERARCHY: Record<UserRole, number> = {",
         "+export const PERMISSION_HIERARCHY: Record<Permission, number> = {",
         "   admin: 3, editor: 2, viewer: 1,", " };"],
    ])

    add_file("packages/core/src/index.ts", [
        ["-export { UserRole, RoleConfig, hasRole } from './types';",
         "+export { Permission, PermissionConfig, hasPermission } from './types';"],
        ["-export { DEFAULT_ROLE, ROLE_HIERARCHY } from './constants';",
         "+export { DEFAULT_PERMISSION, PERMISSION_HIERARCHY } from './constants';"],
    ])

    add_file("packages/core/tests/types.test.ts", [
        ["-import { hasRole, UserRole } from '../src/types';",
         "+import { hasPermission, Permission } from '../src/types';"],
        [" it('checks admin role', () => {",
         "-  expect(hasRole(adminUser, 'admin')).toBe(true);",
         "+  expect(hasPermission(adminUser, 'admin')).toBe(true);",
         " });"],
        [" it('rejects unauthorized', () => {",
         "-  expect(hasRole(viewer, 'admin')).toBe(false);",
         "+  expect(hasPermission(viewer, 'admin')).toBe(false);",
         " });"],
    ])

    # Auth package — uses core types
    add_file("packages/auth/src/guards.ts", [
        ["-import { UserRole, hasRole } from '@core';",
         "+import { Permission, hasPermission } from '@core';"],
        ["-export function requireRole(role: UserRole) {",
         "+export function requirePermission(perm: Permission) {",
         "   return (req: Request, res: Response, next: NextFunction) => {",
         "-    if (!hasRole(req.user, role)) {",
         "+    if (!hasPermission(req.user, perm)) {",
         "       return res.status(403).json({ error: 'Forbidden' });", "     }"],
    ])

    add_file("packages/auth/src/middleware.ts", [
        ["-import { UserRole } from '@core';",
         "+import { Permission } from '@core';"],
        ["-export function extractRoles(token: string): UserRole[] {",
         "+export function extractPermissions(token: string): Permission[] {",
         "   const decoded = jwt.verify(token, SECRET);",
         "-  return decoded.roles as UserRole[];",
         "+  return decoded.permissions as Permission[];",
         " }"],
    ])

    add_file("packages/auth/src/index.ts", [
        ["-export { requireRole } from './guards';",
         "+export { requirePermission } from './guards';"],
        ["-export { extractRoles } from './middleware';",
         "+export { extractPermissions } from './middleware';"],
    ])

    add_file("packages/auth/tests/guards.test.ts", [
        ["-import { requireRole } from '../src/guards';",
         "+import { requirePermission } from '../src/guards';"],
        [" it('blocks unauthorized', () => {",
         "-  const guard = requireRole('admin');",
         "+  const guard = requirePermission('admin');",
         "   guard(req, res, next);",
         "   expect(res.status).toHaveBeenCalledWith(403);"],
        [" it('allows authorized', () => {",
         "-  const guard = requireRole('viewer');",
         "+  const guard = requirePermission('viewer');",
         "   guard(adminReq, res, next);",
         "   expect(next).toHaveBeenCalled();"],
    ])

    add_file("packages/auth/tests/middleware.test.ts", [
        ["-import { extractRoles } from '../src/middleware';",
         "+import { extractPermissions } from '../src/middleware';"],
        [" it('extracts roles from token', () => {",
         "-  const roles = extractRoles(validToken);",
         "-  expect(roles).toContain('admin');",
         "+  const perms = extractPermissions(validToken);",
         "+  expect(perms).toContain('admin');"],
    ])

    relationships.append({"source": "packages/auth/src/guards.ts", "target": "packages/core/src/types.ts", "kind": "direct"})
    relationships.append({"source": "packages/auth/src/middleware.ts", "target": "packages/core/src/types.ts", "kind": "direct"})
    relationships.append({"source": "packages/auth/tests/guards.test.ts", "target": "packages/auth/src/guards.ts", "kind": "direct"})
    relationships.append({"source": "packages/auth/tests/middleware.test.ts", "target": "packages/auth/src/middleware.ts", "kind": "direct"})

    # API package — uses auth guards
    for route_name in ["users", "admin", "billing"]:
        route_file = f"packages/api/src/routes/{route_name}.ts"
        add_file(route_file, [
            [f"-import {{ requireRole }} from '@auth';",
             f"+import {{ requirePermission }} from '@auth';"],
            [f" router.get('/{route_name}',",
             f"-  requireRole('{('admin' if route_name == 'admin' else 'viewer')}'),",
             f"+  requirePermission('{('admin' if route_name == 'admin' else 'viewer')}'),",
             f"   {route_name}Handler,", " );"],
        ])
        relationships.append({"source": route_file, "target": "packages/auth/src/guards.ts", "kind": "direct"})

        handler_file = f"packages/api/src/handlers/{route_name}.handler.ts"
        add_file(handler_file, [
            [f"-import {{ UserRole }} from '@core';",
             f"+import {{ Permission }} from '@core';"],
            [f"-  const requiredRole: UserRole = '{('admin' if route_name == 'admin' else 'viewer')}';",
             f"+  const requiredPerm: Permission = '{('admin' if route_name == 'admin' else 'viewer')}';"],
        ])
        relationships.append({"source": handler_file, "target": "packages/core/src/types.ts", "kind": "direct"})

        test_file = f"packages/api/tests/{route_name}.test.ts"
        add_file(test_file, [
            [f"-jest.mock('@auth', () => ({{ requireRole: jest.fn(() => (req, res, next) => next()) }}));",
             f"+jest.mock('@auth', () => ({{ requirePermission: jest.fn(() => (req, res, next) => next()) }}));"],
            [f" it('requires auth for {route_name}', () => {{",
             f"-  expect(requireRole).toHaveBeenCalledWith('{('admin' if route_name == 'admin' else 'viewer')}');",
             f"+  expect(requirePermission).toHaveBeenCalledWith('{('admin' if route_name == 'admin' else 'viewer')}');",
             " });"],
        ])
        relationships.append({"source": test_file, "target": route_file, "kind": "direct"})
        relationships.append({"source": test_file, "target": "packages/auth/src/guards.ts", "kind": "transitive", "via": route_file})

    # UI package — uses core types
    add_file("packages/ui/src/hooks/usePermissions.ts", [
        ["-import { UserRole, hasRole } from '@core';",
         "+import { Permission, hasPermission } from '@core';"],
        ["-export function usePermissions(user: User): Record<UserRole, boolean> {",
         "+export function usePermissions(user: User): Record<Permission, boolean> {",
         "   return {",
         "-    admin: hasRole(user, 'admin'),",
         "-    editor: hasRole(user, 'editor'),",
         "-    viewer: hasRole(user, 'viewer'),",
         "+    admin: hasPermission(user, 'admin'),",
         "+    editor: hasPermission(user, 'editor'),",
         "+    viewer: hasPermission(user, 'viewer'),",
         "   };"],
    ])
    relationships.append({"source": "packages/ui/src/hooks/usePermissions.ts", "target": "packages/core/src/types.ts", "kind": "direct"})

    add_file("packages/ui/src/components/PermissionGate.tsx", [
        ["-import { UserRole } from '@core';",
         "+import { Permission } from '@core';"],
        ["-interface Props { required: UserRole; children: React.ReactNode; }",
         "+interface Props { required: Permission; children: React.ReactNode; }"],
    ])
    relationships.append({"source": "packages/ui/src/components/PermissionGate.tsx", "target": "packages/core/src/types.ts", "kind": "direct"})

    add_file("packages/ui/src/components/AdminPanel.tsx", [
        [" export const AdminPanel = () => (",
         "-  <PermissionGate required='admin'>",
         "+  <PermissionGate required='admin'>",  # same value but context changed
         "     <AdminDashboard />",
         "   </PermissionGate>", " );"],
    ])

    add_file("packages/ui/src/components/UserSettings.tsx", [
        ["-import type { UserRole } from '@core';",
         "+import type { Permission } from '@core';"],
        ["-  const [selectedRole, setSelectedRole] = useState<UserRole>('viewer');",
         "+  const [selectedPerm, setSelectedPerm] = useState<Permission>('viewer');"],
    ])
    relationships.append({"source": "packages/ui/src/components/UserSettings.tsx", "target": "packages/core/src/types.ts", "kind": "direct"})

    add_file("packages/ui/tests/usePermissions.test.ts", [
        ["-import { hasRole } from '@core';",
         "+import { hasPermission } from '@core';"],
        ["-jest.mock('@core', () => ({ hasRole: jest.fn() }));",
         "+jest.mock('@core', () => ({ hasPermission: jest.fn() }));"],
        [" it('checks admin permission', () => {",
         "-  (hasRole as jest.Mock).mockReturnValue(true);",
         "+  (hasPermission as jest.Mock).mockReturnValue(true);"],
    ])
    relationships.append({"source": "packages/ui/tests/usePermissions.test.ts", "target": "packages/ui/src/hooks/usePermissions.ts", "kind": "direct"})

    add_file("packages/ui/tests/PermissionGate.test.tsx", [
        ["-import type { UserRole } from '@core';",
         "+import type { Permission } from '@core';"],
        ["-  const renderGate = (required: UserRole) =>",
         "+  const renderGate = (required: Permission) =>",
         "     render(<PermissionGate required={required}><Child /></PermissionGate>);"],
    ])
    relationships.append({"source": "packages/ui/tests/PermissionGate.test.tsx", "target": "packages/ui/src/components/PermissionGate.tsx", "kind": "direct"})

    # Noise: CI/config files
    add_file(".github/workflows/ci.yml", [
        ["+  # Updated test matrix for permission changes",
         "+  strategy:",
         "+    matrix:",
         "+      package: [core, auth, api, ui]"],
    ])

    add_file("tsconfig.base.json", [
        ['+    "@core/*": ["packages/core/src/*"],',
         '+    "@auth/*": ["packages/auth/src/*"],'],
    ])

    # Everything that uses the renamed type/function MUST be together
    all_rename_files = set()
    for fd in file_diffs:
        fp = fd["file_path"]
        if fp.endswith((".yml", ".json")):
            continue
        # Check if any hunk has a rename (- and + with different names)
        for h in fd["hunks"]:
            has_minus = any(l.startswith("-") for l in h["lines"])
            has_plus = any(l.startswith("+") for l in h["lines"])
            if has_minus and has_plus:
                all_rename_files.add(fp)
                break

    # Remove noise/additive-only files
    all_rename_files.discard("packages/ui/src/components/AdminPanel.tsx")

    must_be_together = [sorted(all_rename_files)]

    num_files = len(file_diffs)
    num_hunks = sum(len(fd["hunks"]) for fd in file_diffs)

    return {
        "id": "ts_monorepo_type_rename_cascade",
        "language": "typescript",
        "name": f"TypeScript: Monorepo type rename across 4 packages — {num_files} files, {num_hunks} hunks",
        "description": (
            "A TypeScript monorepo with 4 packages (core, auth, api, ui). "
            "core/types.ts renames UserRole->Permission and hasRole()->hasPermission(). "
            "This cascades through barrel exports to auth guards+middleware, "
            "3 API routes + 3 handlers, UI hooks + 2 components, and all their tests. "
            "The rename touches every package via transitive re-exports. "
            "ALL renamed files must be in the same commit. Plus CI and tsconfig noise. "
            "The LLM is strongly tempted to split by package (core, auth, api, ui commits) "
            "which breaks every downstream consumer at each checkpoint."
        ),
        "difficulty": "hyper_hard",
        "category": "monorepo_type_rename_cascade",
        "num_files": num_files,
        "num_hunks": num_hunks,
        "file_diffs": file_diffs,
        "file_relationships": relationships,
        "must_be_together": must_be_together,
        "must_be_ordered": [],
        "hunk_to_file": hunk_to_file,
    }


# ============================================================
# CASE 3: Python — Large refactor: extract module + rename class + update
#          20+ consumers + add new feature on top
#
# The old models.py is split into:
#   models/base.py (BaseModel renamed to Entity)
#   models/user.py (User model, uses Entity)
#   models/product.py (Product model, uses Entity)
#   models/order.py (Order model, uses Entity, User, Product)
#   models/__init__.py (re-exports)
#
# 12 consumer files update imports: from models import BaseModel -> from models import Entity
# 5 test files update imports and assertions
# 3 migration files
# Plus: 2 new feature files that depend on the refactored models
# Plus: config + docs noise
# ============================================================

def generate_case3():
    file_diffs = []
    hunk_to_file = {}
    relationships = []
    hunk_counter = [0]

    def hid(path):
        hunk_counter[0] += 1
        n = hunk_counter[0]
        return f"H{n}_hh03{n:02x}"

    def add_file(path, hunks_data):
        hunks = []
        for lines in hunks_data:
            h = hid(path)
            hunks.append(make_hunk(h, path, lines))
            hunk_to_file[h] = path
        file_diffs.append(make_file_diff(path, hunks))

    # Core model files — the rename happens here
    add_file("models/base.py", [
        ["-class BaseModel:", "+class Entity:",
         "     id = Column(Integer, primary_key=True)",
         "     created_at = Column(DateTime, default=datetime.utcnow)"],
        ["-    def to_dict(self):", "+    def serialize(self):",
         "         return {c.name: getattr(self, c.name) for c in self.__table__.columns}"],
    ])

    add_file("models/user.py", [
        ["-from models.base import BaseModel", "+from models.base import Entity"],
        ["-class User(BaseModel):", "+class User(Entity):",
         "     email = Column(String, unique=True)"],
    ])

    add_file("models/product.py", [
        ["-from models.base import BaseModel", "+from models.base import Entity"],
        ["-class Product(BaseModel):", "+class Product(Entity):",
         "     name = Column(String)", "     price = Column(Float)"],
    ])

    add_file("models/order.py", [
        ["-from models.base import BaseModel", "+from models.base import Entity"],
        ["-class Order(BaseModel):", "+class Order(Entity):",
         "     user_id = Column(Integer, ForeignKey('user.id'))"],
        ["-    def summary(self):", "-        return self.to_dict()",
         "+    def summary(self):", "+        return self.serialize()"],
    ])

    add_file("models/__init__.py", [
        ["-from models.base import BaseModel", "+from models.base import Entity"],
        ["-__all__ = ['BaseModel', 'User', 'Product', 'Order']",
         "+__all__ = ['Entity', 'User', 'Product', 'Order']"],
    ])

    # Consumer files — 12 files that import and use BaseModel
    consumer_modules = [
        "api/views/users", "api/views/products", "api/views/orders",
        "api/views/admin", "api/views/search", "api/views/reports",
        "services/auth", "services/billing", "services/shipping",
        "services/analytics", "services/notifications", "cli/import_cmd",
    ]
    for mod in consumer_modules:
        path = f"{mod}.py"
        add_file(path, [
            ["-from models import BaseModel", "+from models import Entity"],
            [f" def process(obj):",
             f"-    if isinstance(obj, BaseModel):",
             f"+    if isinstance(obj, Entity):",
             f"-        return obj.to_dict()",
             f"+        return obj.serialize()"],
        ])
        relationships.append({"source": path, "target": "models/base.py", "kind": "direct"})

    # Test files
    test_modules = [
        "tests/test_user", "tests/test_product", "tests/test_order",
        "tests/test_api_views", "tests/test_services",
    ]
    for mod in test_modules:
        path = f"{mod}.py"
        add_file(path, [
            ["-from models import BaseModel", "+from models import Entity"],
            [f" def test_model_creation():",
             f"-    assert isinstance(obj, BaseModel)",
             f"+    assert isinstance(obj, Entity)"],
            [f" def test_serialization():",
             f"-    data = obj.to_dict()",
             f"+    data = obj.serialize()",
             f"     assert 'id' in data"],
        ])
        relationships.append({"source": path, "target": "models/base.py", "kind": "direct"})

    # Migration files
    for i, mig_name in enumerate(["rename_basemodel_table", "update_constraints", "add_audit_columns"]):
        path = f"migrations/{mig_name}.py"
        add_file(path, [
            [f"+# Migration {i+1}: {mig_name}",
             f"+def upgrade():",
             f"+    op.rename_table('basemodel', 'entity')" if i == 0 else f"+    op.alter_column('entity', 'updated')",
             ],
        ])

    # New feature files that depend on refactored models
    add_file("features/export.py", [
        ["+from models import Entity",
         "+",
         "+def export_all(model_class: type[Entity]) -> list[dict]:",
         "+    return [obj.serialize() for obj in model_class.query.all()]"],
    ])
    relationships.append({"source": "features/export.py", "target": "models/base.py", "kind": "direct"})

    add_file("features/bulk_import.py", [
        ["+from models import Entity",
         "+",
         "+def bulk_import(model_class: type[Entity], data: list[dict]):",
         "+    for item in data:",
         "+        obj = model_class(**item)",
         "+        db.session.add(obj)"],
    ])
    relationships.append({"source": "features/bulk_import.py", "target": "models/base.py", "kind": "direct"})

    # Noise
    add_file("docs/models.md", [
        ["+## Entity Base Class",
         "+All models now inherit from `Entity` instead of `BaseModel`."],
    ])
    add_file("pyproject.toml", [
        ['+[tool.pytest.ini_options]',
         '+testpaths = ["tests"]'],
    ])

    # All files that reference the renamed class/method MUST be together
    rename_files = set()
    rename_files.add("models/base.py")
    rename_files.add("models/user.py")
    rename_files.add("models/product.py")
    rename_files.add("models/order.py")
    rename_files.add("models/__init__.py")
    for mod in consumer_modules:
        rename_files.add(f"{mod}.py")
    for mod in test_modules:
        rename_files.add(f"{mod}.py")

    must_be_together = [sorted(rename_files)]

    num_files = len(file_diffs)
    num_hunks = sum(len(fd["hunks"]) for fd in file_diffs)

    return {
        "id": "py_large_refactor_class_rename_20_consumers",
        "language": "python",
        "name": f"Python: Class rename BaseModel->Entity across {num_files} files, {num_hunks} hunks",
        "description": (
            "models/base.py renames BaseModel to Entity and to_dict() to serialize(). "
            "4 model files + __init__.py update inheritance. "
            "12 consumer files (6 API views, 4 services, 1 CLI) update imports and isinstance checks. "
            "5 test files update imports and assertions. "
            "3 migration files, 2 new feature files, docs, and config as noise. "
            f"ALL {len(rename_files)} renamed-reference files must be in the same commit. "
            "The LLM is strongly tempted to split into: models commit, consumers commit, tests commit, "
            "migrations commit — each of which breaks the codebase."
        ),
        "difficulty": "hyper_hard",
        "category": "class_rename_mass_consumer",
        "num_files": num_files,
        "num_hunks": num_hunks,
        "file_diffs": file_diffs,
        "file_relationships": relationships,
        "must_be_together": must_be_together,
        "must_be_ordered": [
            ["models/base.py", "features/export.py"],
            ["models/base.py", "features/bulk_import.py"],
        ],
        "hunk_to_file": hunk_to_file,
    }


# ============================================================
# CASE 4: Go — Protocol buffer + gRPC service refactor
#          Renames across proto, generated code, server, client,
#          middleware, 3 separate services, integration tests
#
# Circular deps: proto defines types used by all services,
# service A calls service B which calls service C which calls A.
# Each renames an RPC method that others depend on.
# ============================================================

def generate_case4():
    file_diffs = []
    hunk_to_file = {}
    relationships = []
    hunk_counter = [0]

    def hid(path):
        hunk_counter[0] += 1
        n = hunk_counter[0]
        return f"H{n}_hh04{n:02x}"

    def add_file(path, hunks_data):
        hunks = []
        for lines in hunks_data:
            h = hid(path)
            hunks.append(make_hunk(h, path, lines))
            hunk_to_file[h] = path
        file_diffs.append(make_file_diff(path, hunks))

    # Proto files — 3 service protos, each renaming an RPC
    protos = [
        ("proto/auth.proto", "VerifyToken", "ValidateToken", "AuthService"),
        ("proto/user.proto", "GetUser", "FetchUser", "UserService"),
        ("proto/payment.proto", "ProcessPayment", "ExecutePayment", "PaymentService"),
    ]

    for proto_path, old_rpc, new_rpc, svc_name in protos:
        add_file(proto_path, [
            [f"   // {svc_name} API",
             f"-  rpc {old_rpc}({old_rpc}Request) returns ({old_rpc}Response);",
             f"+  rpc {new_rpc}({new_rpc}Request) returns ({new_rpc}Response);"],
            [f"-message {old_rpc}Request {{", f"+message {new_rpc}Request {{",
             "   string id = 1;", " }"],
            [f"-message {old_rpc}Response {{", f"+message {new_rpc}Response {{",
             "   bool success = 1;", "   string message = 2;", " }"],
        ])

    # Generated Go code (pb.go files)
    for proto_path, old_rpc, new_rpc, svc_name in protos:
        pkg = proto_path.split("/")[1].replace(".proto", "")
        gen_path = f"gen/{pkg}/{pkg}.pb.go"
        add_file(gen_path, [
            [f"-type {old_rpc}Request struct {{", f"+type {new_rpc}Request struct {{",
             "\tId string `protobuf:\"bytes,1,opt,name=id\"`", "}"],
            [f"-type {old_rpc}Response struct {{", f"+type {new_rpc}Response struct {{",
             "\tSuccess bool", "\tMessage string", "}"],
            [f"-func (c *{svc_name}Client) {old_rpc}(ctx context.Context, req *{old_rpc}Request) (*{old_rpc}Response, error) {{",
             f"+func (c *{svc_name}Client) {new_rpc}(ctx context.Context, req *{new_rpc}Request) (*{new_rpc}Response, error) {{"],
        ])
        relationships.append({"source": gen_path, "target": proto_path, "kind": "direct"})

    # Server implementations
    servers = [
        ("internal/auth/server.go", "VerifyToken", "ValidateToken", "auth",
         [("internal/user/client.go", "GetUser", "FetchUser")]),  # auth calls user
        ("internal/user/server.go", "GetUser", "FetchUser", "user",
         [("internal/payment/client.go", "ProcessPayment", "ExecutePayment")]),  # user calls payment
        ("internal/payment/server.go", "ProcessPayment", "ExecutePayment", "payment",
         [("internal/auth/client.go", "VerifyToken", "ValidateToken")]),  # payment calls auth (circular!)
    ]

    for srv_path, old_rpc, new_rpc, pkg, client_deps in servers:
        add_file(srv_path, [
            [f"-func (s *Server) {old_rpc}(ctx context.Context, req *pb.{old_rpc}Request) (*pb.{old_rpc}Response, error) {{",
             f"+func (s *Server) {new_rpc}(ctx context.Context, req *pb.{new_rpc}Request) (*pb.{new_rpc}Response, error) {{",
             f"\tlog.Info(\"{new_rpc} called\")"],
            [f"-\tresp := &pb.{old_rpc}Response{{Success: true}}",
             f"+\tresp := &pb.{new_rpc}Response{{Success: true}}",
             "\treturn resp, nil"],
        ])
        relationships.append({"source": srv_path, "target": f"gen/{pkg}/{pkg}.pb.go", "kind": "direct"})

        # Client files (cross-service calls)
        for client_path, dep_old, dep_new in client_deps:
            dep_pkg = client_path.split("/")[1]
            add_file(client_path, [
                [f"-func Call{dep_old}(ctx context.Context, id string) error {{",
                 f"+func Call{dep_new}(ctx context.Context, id string) error {{",
                 f"\tclient := pb.New{dep_pkg.title()}ServiceClient(conn)"],
                [f"-\treq := &pb.{dep_old}Request{{Id: id}}",
                 f"+\treq := &pb.{dep_new}Request{{Id: id}}",
                 f"-\t_, err := client.{dep_old}(ctx, req)",
                 f"+\t_, err := client.{dep_new}(ctx, req)"],
            ])
            relationships.append({"source": client_path, "target": f"gen/{dep_pkg}/{dep_pkg}.pb.go", "kind": "direct"})
            relationships.append({"source": srv_path, "target": client_path, "kind": "direct"})

    # Middleware that uses auth
    add_file("internal/middleware/auth.go", [
        ["-func AuthInterceptor(ctx context.Context) error {",
         "-\tresp, err := authClient.VerifyToken(ctx, &pb.VerifyTokenRequest{Id: tokenID})",
         "+func AuthInterceptor(ctx context.Context) error {",
         "+\tresp, err := authClient.ValidateToken(ctx, &pb.ValidateTokenRequest{Id: tokenID})"],
    ])
    relationships.append({"source": "internal/middleware/auth.go", "target": "gen/auth/auth.pb.go", "kind": "direct"})

    # Gateway that routes to all services
    add_file("internal/gateway/router.go", [
        ["-\tauthResp, _ := authClient.VerifyToken(ctx, &authpb.VerifyTokenRequest{})",
         "+\tauthResp, _ := authClient.ValidateToken(ctx, &authpb.ValidateTokenRequest{})"],
        ["-\tuserResp, _ := userClient.GetUser(ctx, &userpb.GetUserRequest{Id: uid})",
         "+\tuserResp, _ := userClient.FetchUser(ctx, &userpb.FetchUserRequest{Id: uid})"],
        ["-\tpayResp, _ := payClient.ProcessPayment(ctx, &paypb.ProcessPaymentRequest{Id: pid})",
         "+\tpayResp, _ := payClient.ExecutePayment(ctx, &paypb.ExecutePaymentRequest{Id: pid})"],
    ])
    relationships.append({"source": "internal/gateway/router.go", "target": "gen/auth/auth.pb.go", "kind": "direct"})
    relationships.append({"source": "internal/gateway/router.go", "target": "gen/user/user.pb.go", "kind": "direct"})
    relationships.append({"source": "internal/gateway/router.go", "target": "gen/payment/payment.pb.go", "kind": "direct"})

    # Test files
    for pkg, old_rpc, new_rpc in [("auth", "VerifyToken", "ValidateToken"),
                                    ("user", "GetUser", "FetchUser"),
                                    ("payment", "ProcessPayment", "ExecutePayment")]:
        test_path = f"internal/{pkg}/server_test.go"
        add_file(test_path, [
            [f" func Test{old_rpc}(t *testing.T) {{",
             f"-\treq := &pb.{old_rpc}Request{{Id: \"test\"}}",
             f"+\treq := &pb.{new_rpc}Request{{Id: \"test\"}}",
             f"-\tresp, err := server.{old_rpc}(ctx, req)",
             f"+\tresp, err := server.{new_rpc}(ctx, req)"],
            [f"-\tassert.NotNil(t, resp.(*pb.{old_rpc}Response))",
             f"+\tassert.NotNil(t, resp.(*pb.{new_rpc}Response))"],
        ])
        relationships.append({"source": test_path, "target": f"internal/{pkg}/server.go", "kind": "direct"})

    # Integration test
    add_file("tests/integration_test.go", [
        ["-\tresp, err := authClient.VerifyToken(ctx, &authpb.VerifyTokenRequest{Id: \"1\"})",
         "+\tresp, err := authClient.ValidateToken(ctx, &authpb.ValidateTokenRequest{Id: \"1\"})"],
        ["-\tuserResp, _ := userClient.GetUser(ctx, &userpb.GetUserRequest{Id: \"1\"})",
         "+\tuserResp, _ := userClient.FetchUser(ctx, &userpb.FetchUserRequest{Id: \"1\"})"],
        ["-\tpayResp, _ := payClient.ProcessPayment(ctx, &paypb.ProcessPaymentRequest{Id: \"1\"})",
         "+\tpayResp, _ := payClient.ExecutePayment(ctx, &paypb.ExecutePaymentRequest{Id: \"1\"})"],
    ])
    relationships.append({"source": "tests/integration_test.go", "target": "gen/auth/auth.pb.go", "kind": "direct"})
    relationships.append({"source": "tests/integration_test.go", "target": "gen/user/user.pb.go", "kind": "direct"})
    relationships.append({"source": "tests/integration_test.go", "target": "gen/payment/payment.pb.go", "kind": "direct"})

    # Noise: Makefile, docs
    add_file("Makefile", [
        ["+proto-gen:", "+\tprotoc --go_out=gen/ proto/*.proto"],
    ])
    add_file("docs/rpc-reference.md", [
        ["+## Updated RPC Methods", "+- AuthService: ValidateToken",
         "+- UserService: FetchUser", "+- PaymentService: ExecutePayment"],
    ])

    # ALL files with renames must be together (everything except Makefile, docs)
    all_rename_files = set()
    for fd in file_diffs:
        fp = fd["file_path"]
        if fp in ("Makefile", "docs/rpc-reference.md"):
            continue
        for h in fd["hunks"]:
            if any(l.startswith("-") for l in h["lines"]) and any(l.startswith("+") for l in h["lines"]):
                all_rename_files.add(fp)
                break

    must_be_together = [sorted(all_rename_files)]

    num_files = len(file_diffs)
    num_hunks = sum(len(fd["hunks"]) for fd in file_diffs)

    return {
        "id": "go_grpc_circular_3_service_rename",
        "language": "go",
        "name": f"Go: gRPC 3-service circular rename — {num_files} files, {num_hunks} hunks",
        "description": (
            "3 gRPC services (auth, user, payment) each rename an RPC method. "
            "Services form a circular dependency: auth->user->payment->auth. "
            "Each has proto, generated code, server, client, and test files. "
            "A gateway and middleware also reference all 3 services. "
            "Integration test calls all 3. Plus Makefile and docs as noise. "
            f"ALL {len(all_rename_files)} files with renames must be in a single commit. "
            "The LLM is tempted to split by service (auth commit, user commit, payment commit) "
            "or by layer (proto commit, server commit, test commit) — both break the circular deps."
        ),
        "difficulty": "hyper_hard",
        "category": "grpc_circular_service_rename",
        "num_files": num_files,
        "num_hunks": num_hunks,
        "file_diffs": file_diffs,
        "file_relationships": relationships,
        "must_be_together": must_be_together,
        "must_be_ordered": [],
        "hunk_to_file": hunk_to_file,
    }


def main():
    generators = [generate_case1, generate_case2, generate_case3, generate_case4]
    for gen in generators:
        case = gen()
        out_path = DATA_DIR / f"{case['id']}.json"
        with open(out_path, "w") as f:
            json.dump(case, f, indent=2)
        print(f"Generated: {out_path.name}  ({case['num_files']} files, {case['num_hunks']} hunks, "
              f"{len(case['must_be_together'])} must_be_together groups)")


if __name__ == "__main__":
    main()

