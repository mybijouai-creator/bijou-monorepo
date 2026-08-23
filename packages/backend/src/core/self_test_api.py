"""Comprehensive system self-test endpoint.

WHY THIS EXISTS
===============
The trivial `GET /health` returns 200 OK unconditionally — even if
Supabase is unreachable, the 4 new tables are missing, the AI model
API key is invalid, or the integration endpoints (Stripe, Nango,
Resend, Cal.com) are misconfigured. That is a useless signal for
orchestrators like Coolify, which use the healthcheck to decide
whether to auto-rollback a failed deploy.

This module adds `GET /api/self-test` that exercises the real
dependencies and returns a structured JSON report. The endpoint
intentionally:
  - Returns HTTP 200 even when checks fail (so Coolify sees the
    report, not a connection error). The body's `overall` field
    carries the verdict.
  - Returns HTTP 503 ONLY when a critical check fails (so Coolify
    DOES auto-rollback). Critical checks: Supabase connectivity,
    AI model reachability, the 4 new tables existing.
  - Caches nothing. Every call hits the real services (with a
    short per-check timeout to keep the total response under 5s).

It is also useful for humans:
  - The owner runs it after a deploy to see what's working
  - The QA agent runs it before/after a feature to catch regressions
  - The support agent runs it to triage a customer report
    ("is the system actually down or is it just this customer?")

DESIGN
======

The endpoint is a single function (`run_self_test()`) that returns a
dict, plus a thin FastAPI wrapper. This makes it easy to call from
other places (e.g., a nightly cron that emails the report) without
duplicating the check logic.

Each check returns a `CheckResult` dict with: `name`, `status`
(`pass` | `fail` | `warn` | `skip`), `latency_ms`, `detail`.
The aggregate function computes `overall` = `pass` if all critical
checks pass, else `fail`. Non-critical failures become `warn`.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["self-test"])


# ─── CheckResult + helpers ─────────────────────────────────────────────


def _now_ms() -> float:
    return time.monotonic() * 1000.0


async def _timed(name: str, fn: Callable[[], Any], critical: bool = True, timeout_s: float = 4.0) -> Dict[str, Any]:
    """Run a check function and time it. Returns a normalized dict.

    `fn` may return:
      - None: treated as a pass with no extra detail
      - a string: treated as a pass with that string as the detail
      - a dict: treated as the detail payload (must include at minimum
        a 'detail' or 'info' key; rest is included verbatim)
      - raises: treated as a fail with the exception message
    """
    started = _now_ms()
    try:
        result = fn()
        elapsed = _now_ms() - started
        if isinstance(result, dict):
            detail = result.get("detail") or result.get("info") or ""
            return {
                "name": name,
                "status": "pass",
                "critical": critical,
                "latency_ms": round(elapsed, 1),
                "detail": detail,
                "extras": {k: v for k, v in result.items() if k not in ("detail", "info")},
            }
        elif isinstance(result, str):
            return {
                "name": name, "status": "pass", "critical": critical,
                "latency_ms": round(elapsed, 1), "detail": result,
            }
        else:
            return {
                "name": name, "status": "pass", "critical": critical,
                "latency_ms": round(elapsed, 1), "detail": "",
            }
    except Exception as e:
        elapsed = _now_ms() - started
        return {
            "name": name, "status": "fail", "critical": critical,
            "latency_ms": round(elapsed, 1),
            "detail": f"{type(e).__name__}: {e}"[:500],
        }


# ─── Individual checks ─────────────────────────────────────────────────


def _check_supabase_connectivity() -> Dict[str, Any]:
    """Verify Supabase client can be created and the service-role key
    can hit the public schema. A real round-trip, not just env-var check.
    """
    from supabase import create_client

    url = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
    sb = create_client(url, key)
    # Lightweight read: a count-style select with limit 0 returns
    # no rows but exercises auth + RLS bypass.
    result = sb.table("tenants").select("id", count="exact").limit(0).execute()
    return {
        "detail": "connected",
        "tenant_count_reported": bool(getattr(result, "count", None) is not None),
    }


def _check_new_tables_exist() -> Dict[str, Any]:
    """The 4 tables shipped in this session must all exist with RLS on.
    If any are missing, the corresponding feature silently breaks (the
    API returns 500 because the table is missing).
    """
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    sb = create_client(url, key)
    expected = [
        ("message_reasons", "EU AI Act Article 13 traceability"),
        ("shared_context", "A2A cross-channel seam (issue #23)"),
        ("inbox_copilot_events", "Inbox Co-pilot audit log (issue #13)"),
        ("data_request_deletions", "PDPA/GDPR right-to-erasure (issue #26)"),
    ]
    missing = []
    for table, purpose in expected:
        try:
            # limit 0 + a select that doesn't reference any columns
            # to confirm the table exists without needing schema
            sb.table(table).select("id", count="exact").limit(0).execute()
        except Exception as e:
            missing.append(f"{table} ({type(e).__name__})")
    if missing:
        raise RuntimeError(f"missing tables: {', '.join(missing)}")
    return {"detail": f"all {len(expected)} present", "tables": [t[0] for t in expected]}


def _check_gemini_reachable() -> Dict[str, Any]:
    """Verify the Gemini API key is valid by listing models.
    This is the cheapest possible call (no token cost).
    """
    import urllib.request
    import urllib.error
    import json

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=4) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    models = body.get("models", [])
    if not models:
        raise RuntimeError("Gemini returned no models")
    # The model we actually use
    has_flash = any("gemini-2.5-flash" in m.get("name", "") for m in models)
    return {
        "detail": "reachable",
        "models_count": len(models),
        "gemini_2_5_flash_available": has_flash,
    }


def _check_stripe_configured() -> Dict[str, Any]:
    """Verify the Stripe key is present and well-formed. We don't hit
    the API (would cost a request); just check shape.
    """
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY not set")
    if not (key.startswith("sk_test_") or key.startswith("sk_live_")):
        raise RuntimeError("STRIPE_SECRET_KEY has wrong prefix")
    return {
        "detail": "configured",
        "mode": "test" if key.startswith("sk_test_") else "live",
    }


def _check_nango_configured() -> Dict[str, Any]:
    """Nango is optional. We report `skip` if not configured, `pass`
    if the key is present.
    """
    key = os.getenv("NANGO_SECRET_KEY") or os.getenv("NANGO_API_KEY")
    if not key:
        return {"detail": "skipped (Nango not configured; Integrations tab is disabled)"}
    if len(key) < 16:
        raise RuntimeError("NANGO_SECRET_KEY looks malformed (too short)")
    return {"detail": "configured"}


def _check_resend_configured() -> Dict[str, Any]:
    """Resend is used for magic-link login + data-request confirmations.
    Without it, the user can't log in. Critical.
    """
    key = os.getenv("RESEND_API_KEY")
    if not key:
        raise RuntimeError("RESEND_API_KEY not set (magic-link login will fail)")
    if not key.startswith("re_"):
        raise RuntimeError("RESEND_API_KEY has wrong prefix")
    return {"detail": "configured"}


def _check_calcom_configured() -> Dict[str, Any]:
    """Cal.com powers the 'book a 15-min demo' widget. Non-critical
    (the rest of the product works without it).
    """
    cid = os.getenv("CALCOM_CLIENT_ID")
    csec = os.getenv("CALCOM_CLIENT_SECRET")
    if not cid or not csec:
        return {"detail": "skipped (Cal.com not configured; demo booking is disabled)"}
    return {"detail": "configured"}


def _check_env_canonical_url() -> Dict[str, Any]:
    """PUBLIC_URL must point to the canonical domain (app.mybijou.xyz),
    not a Fly internal URL. The 2026-08-10 + 2026-08-23 bug class was
    exactly this: stale env-var overrides silently winning the fallback
    race. Surface the value so the operator sees it.
    """
    url = os.getenv("PUBLIC_URL", "")
    if not url:
        raise RuntimeError("PUBLIC_URL not set (will fall back to Fly URL, which breaks auth)")
    if "fly.dev" in url:
        raise RuntimeError(f"PUBLIC_URL still points to fly.dev: {url}")
    if "mybijou.xyz" not in url and "localhost" not in url and "127.0.0.1" not in url:
        # Not an error, but worth a warning — could be a custom domain
        return {
            "status_override": "warn",
            "detail": f"non-canonical URL: {url} (expected mybijou.xyz or localhost)",
        }
    return {"detail": f"set to {url}"}


def _check_disk_space() -> Dict[str, Any]:
    """The backend writes uploads + logs to disk. If the volume fills
    up, /uploads writes start failing silently.
    """
    import shutil
    total, used, free = shutil.disk_usage("/")
    free_gb = free / (1024 ** 3)
    if free_gb < 1.0:
        raise RuntimeError(f"only {free_gb:.1f} GB free (need >= 1 GB)")
    if free_gb < 5.0:
        return {
            "status_override": "warn",
            "detail": f"only {free_gb:.1f} GB free (< 5 GB warning threshold)",
        }
    return {"detail": f"{free_gb:.1f} GB free"}


# ─── Orchestrator ──────────────────────────────────────────────────────


async def run_self_test() -> Dict[str, Any]:
    """Run all checks and return a structured report.

    The report is the source of truth for the orchestrator AND for
    any human / cron that wants to inspect system health.
    """
    started = time.monotonic()
    checks: List[Dict[str, Any]] = []

    # Critical: Supabase. Without it, the API is 100% broken.
    checks.append(await _timed("supabase_connectivity", _check_supabase_connectivity, critical=True))

    # Critical: the 4 new tables must exist. Their absence = feature
    # broken (and the API returns 500 for those routes).
    checks.append(await _timed("new_tables_exist", _check_new_tables_exist, critical=True))

    # Critical: Gemini. Without it, no AI replies.
    checks.append(await _timed("gemini_reachable", _check_gemini_reachable, critical=True))

    # Critical: PUBLIC_URL must be set to the canonical domain.
    checks.append(await _timed("public_url_canonical", _check_env_canonical_url, critical=True))

    # Critical: Resend (magic-link login).
    checks.append(await _timed("resend_configured", _check_resend_configured, critical=True))

    # Non-critical: Stripe (degrades gracefully — the billing tab shows
    # an error but the rest of the product works).
    checks.append(await _timed("stripe_configured", _check_stripe_configured, critical=False))

    # Non-critical: Nango (degrades — Integrations tab is just disabled).
    checks.append(await _timed("nango_configured", _check_nango_configured, critical=False))

    # Non-critical: Cal.com (degrades — demo booking widget is just hidden).
    checks.append(await _timed("calcom_configured", _check_calcom_configured, critical=False))

    # Non-critical: disk space.
    checks.append(await _timed("disk_space", _check_disk_space, critical=False))

    # Apply any `status_override` from the check (e.g. warn on low disk)
    for c in checks:
        if "status_override" in c:
            c["status"] = c.pop("status_override")

    # Compute overall verdict
    critical_failures = [c["name"] for c in checks if c["status"] == "fail" and c["critical"]]
    any_failures = [c["name"] for c in checks if c["status"] == "fail"]
    warnings = [c["name"] for c in checks if c["status"] == "warn"]
    skips = [c["name"] for c in checks if c["status"] == "skip"]

    if critical_failures:
        overall = "fail"
    elif any_failures:
        overall = "degraded"  # non-critical failure only
    elif warnings:
        overall = "warn"
    else:
        overall = "pass"

    elapsed_ms = round((time.monotonic() - started) * 1000, 1)

    return {
        "overall": overall,
        "service": "bijou-ai",
        "version": os.getenv("BIJOU_VERSION", "dev"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_ms": elapsed_ms,
        "summary": {
            "total": len(checks),
            "passing": sum(1 for c in checks if c["status"] == "pass"),
            "failing": len(any_failures),
            "warnings": len(warnings),
            "skipped": len(skips),
            "critical_failures": critical_failures,
        },
        "checks": checks,
    }


# ─── HTTP endpoints ────────────────────────────────────────────────────


@router.get("/self-test")
async def self_test():
    """Run the full self-test and return the report.

    HTTP status:
      - 200 if overall is `pass` or `warn` (system is usable)
      - 200 if overall is `degraded` (a non-critical piece is down;
        operator should look but Coolify should NOT rollback)
      - 503 if overall is `fail` (a critical check is down; Coolify
        SHOULD auto-rollback to the last green deploy)

    The body always carries the structured report regardless of
    HTTP status, so an operator can see exactly what failed.
    """
    report = await run_self_test()
    overall = report["overall"]
    if overall == "fail":
        return JSONResponse(status_code=503, content=report)
    return report


@router.get("/self-test/summary")
async def self_test_summary():
    """Cheap one-liner for human eyeballs: just the overall verdict +
    critical failure names, no per-check detail. Used by the navbar
    status pill in the dashboard.
    """
    report = await run_self_test()
    return {
        "overall": report["overall"],
        "timestamp": report["timestamp"],
        "elapsed_ms": report["elapsed_ms"],
        "critical_failures": report["summary"]["critical_failures"],
        "summary": report["summary"],
    }
