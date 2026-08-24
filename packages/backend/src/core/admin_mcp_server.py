"""
Bijou Admin — MCP Server v0.1  (2026-08-24)
============================================

A thin MCP wrapper around `src/saas/admin_frontend_api.py`. Exposes
the same 10 (well, 12) admin operations as MCP tools so the owner's
autonomous agent team can call them from inside an agent loop.

DESIGN
======

* This module does NOT re-implement any admin logic. Every tool is a
  one-liner that calls `/admin/api/*` over HTTP using the
  `ADMIN_API_KEY` env var as `X-Admin-Key` (the service-to-service
  auth path in `src/saas/admin_frontend_api.py::require_platform_admin`).
  This means the MCP server cannot drift from the UI: if the admin
  API is updated, the MCP picks it up automatically.

* Every call writes an `audit_log` row with `actor_type='mcp'` and a
  synthetic `actor_email='service:x-admin-key'`. The owner can grep
  the audit log for `actor_type=mcp` to see exactly which agent did
  what.

* Tools return the JSON body of the underlying admin endpoint, or
  raise on transport failure. We deliberately do NOT swallow errors
  here — agent code that catches `McpToolError` is more robust than
  agent code that silently ignores an empty dict.

WHY A SEPARATE MODULE
=====================

The user's CLAUDE.md says "DO NOT add new dependencies" and
"DO NOT add OpenAPI/Swagger generators". This module imports `httpx`
(already a dependency) and a tiny tool-registry pattern; no
external MCP framework. The agent team wires it into their own MCP
host (Mavis / Claude) by `from src.core.admin_mcp_server import TOOLS`.

USAGE
=====

```python
from src.core.admin_mcp_server import TOOLS, call_tool

# In the agent host's tool-registration loop:
for name, fn in TOOLS.items():
    register(name=name, description=fn.__doc__, fn=fn)

# Or call directly:
result = await call_tool("bijou_admin_health", {})
```
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


# ─── Config ───────────────────────────────────────────────────────────

# The base URL of the running Bijou backend. Defaults to localhost
# for dev; in production, set BIJOU_ADMIN_BASE_URL to e.g.
# https://app.mybijou.xyz (the MCP server runs alongside the same
# FastAPI app, so it could also be "http://localhost:8000" if
# colocated — but going through HTTPS to the canonical domain
# matches the rest of the integration test patterns).
DEFAULT_BASE_URL = os.getenv("BIJOU_ADMIN_BASE_URL", "http://localhost:8000").rstrip("/")


class McpToolError(RuntimeError):
    """Raised by a tool when the admin API returns non-2xx."""


async def _call_admin(
    method: str,
    path: str,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """HTTP client for /admin/api/* with X-Admin-Key auth.

    Raises McpToolError on transport or HTTP error so the agent host
    sees a real error (not a silent empty dict).
    """
    base = (os.getenv("BIJOU_ADMIN_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    key = (os.getenv("ADMIN_API_KEY") or "").strip()
    if not key:
        raise McpToolError(
            "ADMIN_API_KEY is not set in the MCP server's environment. "
            "Set it to the same value as on the Bijou backend."
        )

    url = f"{base}/admin/api{path}"
    headers = {"X-Admin-Key": key, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.request(method, url, json=json_body, params=params, headers=headers)
    except httpx.HTTPError as e:
        raise McpToolError(f"transport error calling {url}: {e}") from e

    if r.status_code >= 400:
        # Try to surface the JSON detail
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise McpToolError(f"{method} {url} -> {r.status_code}: {detail}")

    if r.status_code == 204 or not r.content:
        return {}

    try:
        return r.json()
    except json.JSONDecodeError as e:
        raise McpToolError(f"{method} {url} returned non-JSON: {e}") from e


# ─── Tool definitions ─────────────────────────────────────────────────
# Each tool is a thin async function. Its docstring is the tool's
# description in MCP — keep them tight.


async def bijou_admin_health() -> Dict[str, Any]:
    """Get a system overview: tenant count, MRR estimate, self-test verdict, key presence."""
    return await _call_admin("GET", "/health")


async def bijou_admin_list_tenants(limit: int = 50, search: Optional[str] = None) -> Dict[str, Any]:
    """List all tenants with usage + billing. `search` is case-insensitive substring on business_name/email."""
    params: Dict[str, Any] = {"limit": int(limit)}
    if search:
        params["search"] = search
    return await _call_admin("GET", "/tenants", params=params)


async def bijou_admin_get_tenant(tenant_id: str) -> Dict[str, Any]:
    """Full tenant detail: usage, WhatsApp devices, recent payments, KB docs."""
    return await _call_admin("GET", f"/tenants/{tenant_id}")


async def bijou_admin_list_users(limit: int = 50, search: Optional[str] = None) -> Dict[str, Any]:
    """List all users across all tenants with tenant link + platform-admin flag."""
    params: Dict[str, Any] = {"limit": int(limit)}
    if search:
        params["search"] = search
    return await _call_admin("GET", "/users", params=params)


async def bijou_admin_get_user(user_id: str) -> Dict[str, Any]:
    """Full user detail: tenant links, last_sign_in, platform-admin flag."""
    return await _call_admin("GET", f"/users/{user_id}")


async def bijou_admin_impersonate_user(user_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Mint a magic-link-style auth session for `user_id` (support case).

    Writes an audit row with actor_type='mcp'. v0.1 only records the
    audit row and resolves the user's email; the operator still has
    to use Supabase Studio to send the actual magic link. Phase 4
    wires the full flow.
    """
    body: Dict[str, Any] = {"user_id": user_id}
    if reason:
        body["reason"] = reason
    return await _call_admin("POST", f"/users/{user_id}/impersonate", json_body=body)


async def bijou_admin_list_migrations() -> Dict[str, Any]:
    """List all .sql files in migrations-py/ + their applied status."""
    return await _call_admin("GET", "/migrations")


async def bijou_admin_apply_migration(filename: str, force: bool = False) -> Dict[str, Any]:
    """Apply a specific .sql file (substring match). Writes an audit row.

    WARNING: schema changes are not reversible from this UI. force=True
    is rejected by the API in v0.1.
    """
    return await _call_admin(
        "POST", "/migrations/apply",
        json_body={"filename": filename, "force": bool(force)},
    )


async def bijou_admin_billing_summary() -> Dict[str, Any]:
    """Stripe revenue summary: MRR, active subs, recent refunds."""
    return await _call_admin("GET", "/billing/summary")


async def bijou_admin_billing_transactions(limit: int = 50) -> Dict[str, Any]:
    """Recent payment_transactions rows across all tenants."""
    return await _call_admin("GET", "/billing/transactions", params={"limit": int(limit)})


async def bijou_admin_issue_refund(
    charge_or_pi_id: str,
    amount_cents: Optional[int] = None,
    reason: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue a Stripe refund. Mirrored to payment_transactions and audited.

    Args:
        charge_or_pi_id: Stripe charge (ch_*) or payment-intent (pi_*) id.
        amount_cents: Partial-refund amount in cents; omit for full.
        reason: One of 'duplicate' | 'fraudulent' | 'requested_by_customer'.
        tenant_id: Optional; record the refund against this tenant.
    """
    body: Dict[str, Any] = {"charge_or_pi_id": charge_or_pi_id}
    if amount_cents is not None:
        body["amount_cents"] = int(amount_cents)
    if reason:
        body["reason"] = reason
    if tenant_id:
        body["tenant_id"] = tenant_id
    return await _call_admin("POST", "/billing/refund", json_body=body)


async def bijou_admin_list_keys() -> Dict[str, Any]:
    """List all configured env-var API keys, masked. Never returns a real secret."""
    return await _call_admin("GET", "/keys")


async def bijou_admin_test_integration(name: str) -> Dict[str, Any]:
    """Live-test a specific integration. name: 'supabase' | 'stripe' | 'gemini' | 'resend' | 'nango' | 'calcom' | 'bridge'."""
    return await _call_admin("POST", f"/keys/test/{name}")


async def bijou_admin_recent_audit(
    limit: int = 50,
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Recent audit_log rows, newest first. Filterable by actor/action/target_type."""
    params: Dict[str, Any] = {"limit": int(limit)}
    if actor_id:
        params["actor_id"] = actor_id
    if action:
        params["action"] = action
    if target_type:
        params["target_type"] = target_type
    return await _call_admin("GET", "/audit", params=params)


async def bijou_admin_impersonate_tenant_owner(tenant_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Mint a magic-link-style session for the primary owner of `tenant_id`."""
    body: Dict[str, Any] = {"tenant_id": tenant_id}
    if reason:
        body["reason"] = reason
    return await _call_admin("POST", f"/tenants/{tenant_id}/impersonate", json_body=body)


# ─── Registry ────────────────────────────────────────────────────────

TOOLS: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {
    "bijou_admin_health":                    bijou_admin_health,
    "bijou_admin_list_tenants":              bijou_admin_list_tenants,
    "bijou_admin_get_tenant":                bijou_admin_get_tenant,
    "bijou_admin_list_users":                bijou_admin_list_users,
    "bijou_admin_get_user":                  bijou_admin_get_user,
    "bijou_admin_impersonate_user":          bijou_admin_impersonate_user,
    "bijou_admin_impersonate_tenant_owner":  bijou_admin_impersonate_tenant_owner,
    "bijou_admin_list_migrations":           bijou_admin_list_migrations,
    "bijou_admin_apply_migration":           bijou_admin_apply_migration,
    "bijou_admin_billing_summary":           bijou_admin_billing_summary,
    "bijou_admin_billing_transactions":      bijou_admin_billing_transactions,
    "bijou_admin_issue_refund":              bijou_admin_issue_refund,
    "bijou_admin_list_keys":                 bijou_admin_list_keys,
    "bijou_admin_test_integration":          bijou_admin_test_integration,
    "bijou_admin_recent_audit":              bijou_admin_recent_audit,
}


async def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Single entry point. Raises KeyError if `name` is unknown."""
    fn = TOOLS[name]
    # Strip keys the function doesn't accept so MCP hosts that always
    # pass `{}` don't fail when the function takes no args.
    import inspect
    sig = inspect.signature(fn)
    filtered = {k: v for k, v in (arguments or {}).items() if k in sig.parameters}
    return await fn(**filtered)


# ─── CLI smoke test ───────────────────────────────────────────────────
# `python -m src.core.admin_mcp_server health` to verify wiring without
# booting an MCP host. Useful for the QA agent.

async def _smoke(name: str) -> None:
    try:
        out = await call_tool(name, {})
        print(json.dumps(out, indent=2, default=str))
    except McpToolError as e:
        print(f"❌ McpToolError: {e}")
    except KeyError:
        print(f"❌ unknown tool: {name}")
    except Exception as e:
        print(f"❌ unexpected: {type(e).__name__}: {e}")


if __name__ == "__main__":
    import asyncio
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "bijou_admin_health"
    asyncio.run(_smoke(target))
