"""
Unit tests for /api/auth/signup error mapping.

Before 2026-08-09 the signup endpoint's outer `except Exception` was
mapping a narrow set of Supabase error message strings to 4xx codes
and falling through to a generic 500 for everything else. The fly-edge
proxy in front of app.mybijou.xyz returns a 500 with an empty body
when the origin takes too long or throws an uncaught exception — which
is what users were seeing.

The fix in `src/saas/auth_api.py` adds:
- specific handling for `supabase_auth.errors.AuthApiError` using its
  `.status` attribute (422 → 409, 429 → 429, 403 → 403, 400 → 400, etc.)
- a `httpx.HTTPError` branch that returns 503 (service unreachable)
- a final 500 with a `ref: <ExceptionType>` hint so the dashboard
  shows something non-vague AND we can grep Fly logs by exception class

These tests pin all of those mappings.
"""

import os
import sys
import types
import pytest
from unittest.mock import Mock, patch, MagicMock

if "supabase" not in sys.modules:
    supabase_stub = types.ModuleType("supabase")
    setattr(supabase_stub, "create_client", lambda *args, **kwargs: None)
    setattr(supabase_stub, "Client", object)
    sys.modules["supabase"] = supabase_stub

# Fake supabase_auth.errors so the `from supabase_auth.errors import AuthApiError`
# import in auth_api.py resolves to a real class we can raise.
if "supabase_auth" not in sys.modules:
    sa = types.ModuleType("supabase_auth")
    sa_errors = types.ModuleType("supabase_auth.errors")

    class AuthApiError(Exception):
        """Fake stand-in for supabase_auth.errors.AuthApiError."""
        def __init__(self, message, status=None, code=None):
            super().__init__(message)
            self.status = status
            self.code = code

    sa_errors.AuthApiError = AuthApiError
    sys.modules["supabase_auth"] = sa
    sys.modules["supabase_auth.errors"] = sa_errors

from fastapi import HTTPException  # noqa: E402

from src.saas import auth_api  # noqa: E402
from src.saas.auth_api import SignupRequest, signup  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _make_db():
    """Build a minimal fake supabase client. Only the methods the signup
    flow actually calls (or that the outer except handler expects) need
    to exist — everything else stays as a MagicMock so chained calls
    don't blow up."""
    db = MagicMock()
    db.auth.sign_up = MagicMock()
    # The cascade after sign_up uses these — leave them no-op so the
    # tests that DO want sign_up to succeed (and proceed into the
    # tenant/tenant_users cascade) get a clean run.
    db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
    db.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=None)
    return db


async def _raise(signup_exc):
    """Run the signup endpoint and surface whatever HTTPException it raises."""
    with patch("src.saas.auth_api.get_supabase", return_value=_make_db()):
        with patch("src.saas.auth_api.TenantManager") as tm_cls:
            tm = MagicMock()
            tm.create_tenant.return_value = None  # will fail before this matters
            tm_cls.return_value = tm
            try:
                await signup(SignupRequest(
                    email="test@example.com",
                    password="test1234",
                    business_name="Test Co",
                    phone="+60123456789",
                ))
            except HTTPException as http_exc:
                return http_exc
    return None


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_signup_already_registered_returns_409():
    """AuthApiError(status=422, message="User already registered") → 409."""
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        db.auth.sign_up.side_effect = auth_api.AuthApiError(
            "User already registered", status=422, code="user_already_exists"
        )
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager"):
            with pytest.raises(HTTPException) as ei:
                await signup(SignupRequest(
                    email="dup@example.com",
                    password="test1234",
                    business_name="Dup Co",
                    phone="+60123456789",
                ))
    assert ei.value.status_code == 409
    assert "already exists" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_signup_rate_limited_returns_429():
    """AuthApiError(status=429, message="Email rate limit exceeded") → 429."""
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        db.auth.sign_up.side_effect = auth_api.AuthApiError(
            "Email rate limit exceeded", status=429
        )
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager"):
            with pytest.raises(HTTPException) as ei:
                await signup(SignupRequest(
                    email="rl@example.com",
                    password="test1234",
                    business_name="RL Co",
                    phone="+60123456789",
                ))
    assert ei.value.status_code == 429
    assert "too many" in ei.value.detail.lower() or "rate" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_signup_signups_disabled_returns_403():
    """AuthApiError(status=403, message="Signups not allowed") → 403."""
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        db.auth.sign_up.side_effect = auth_api.AuthApiError(
            "Signups not allowed", status=403, code="signup_disabled"
        )
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager"):
            with pytest.raises(HTTPException) as ei:
                await signup(SignupRequest(
                    email="new@example.com",
                    password="test1234",
                    business_name="New Co",
                    phone="+60123456789",
                ))
    assert ei.value.status_code == 403
    assert "disabled" in ei.value.detail.lower() or "signups" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_signup_weak_password_returns_400():
    """AuthApiError(status=400, message="Password should be at least 6 characters") → 400."""
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        db.auth.sign_up.side_effect = auth_api.AuthApiError(
            "Password should be at least 6 characters", status=400
        )
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager"):
            with pytest.raises(HTTPException) as ei:
                await signup(SignupRequest(
                    email="weak@example.com",
                    password="123",
                    business_name="Weak Co",
                    phone="+60123456789",
                ))
    assert ei.value.status_code == 400
    assert "password" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_signup_legacy_string_match_rate_limit_returns_429():
    """Old (pre-2.x supabase-py) error string "rate limit" still maps to 429."""
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        # Plain Exception, not AuthApiError, to test the string-match fallback.
        db.auth.sign_up.side_effect = RuntimeError("Email rate limit exceeded")
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager"):
            with pytest.raises(HTTPException) as ei:
                await signup(SignupRequest(
                    email="rl2@example.com",
                    password="test1234",
                    business_name="RL2 Co",
                    phone="+60123456789",
                ))
    assert ei.value.status_code == 429


@pytest.mark.asyncio
async def test_signup_network_error_returns_503():
    """httpx network errors → 503, not 500."""
    import httpx as real_httpx
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        db.auth.sign_up.side_effect = real_httpx.ConnectError("Connection refused")
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager"):
            with pytest.raises(HTTPException) as ei:
                await signup(SignupRequest(
                    email="net@example.com",
                    password="test1234",
                    business_name="Net Co",
                    phone="+60123456789",
                ))
    assert ei.value.status_code == 503
    assert "unreachable" in ei.value.detail.lower() or "service" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_signup_unknown_error_returns_500_with_ref():
    """Unknown exception → 500 with a `ref: <ExceptionType>` hint for log correlation."""
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        db.auth.sign_up.side_effect = ValueError("Some unexpected supabase quirk")
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager"):
            with pytest.raises(HTTPException) as ei:
                await signup(SignupRequest(
                    email="odd@example.com",
                    password="test1234",
                    business_name="Odd Co",
                    phone="+60123456789",
                ))
    assert ei.value.status_code == 500
    assert "ref: ValueError" in ei.value.detail


# ─────────────────────────────────────────────────────────────────────
# Regression: email-confirmation-pending must NOT be reported as
# "account already exists" (the 2026-08-10 signup outage).
#
# This project runs with GoTrue mailer_autoconfirm=false, so a brand-new
# successful signup returns session=None. The old code read that as
# "email already exists", returned 409, and deleted the tenant — which
# rejected 100% of new registrations and stranded the auth user.
# ─────────────────────────────────────────────────────────────────────

def _signup_response(identities, session):
    """Fake supabase auth.sign_up return value."""
    user = MagicMock()
    user.id = "user-abc"
    user.identities = identities
    resp = MagicMock()
    resp.user = user
    resp.session = session
    return resp


@pytest.mark.asyncio
async def test_signup_pending_confirmation_succeeds_and_keeps_tenant():
    """New user + confirmation required (session=None, one identity)
    → 200 with email_confirmation_required=True, tenant preserved."""
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        db.auth.sign_up.return_value = _signup_response(
            identities=[{"provider": "email"}], session=None,
        )
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager") as tm_cls:
            tm = MagicMock()
            tm.create_tenant.return_value = "tenant-123"
            tm_cls.return_value = tm
            result = await signup(SignupRequest(
                email="brand.new@example.com",
                password="test1234",
                business_name="Brand New Co",
                phone="+60123456789",
            ))

    assert result.email_confirmation_required is True
    assert result.access_token is None
    assert result.tenant_id == "tenant-123"
    # The tenant must survive — deleting it is what stranded users before.
    assert not db.table.return_value.delete.called


@pytest.mark.asyncio
async def test_signup_existing_email_empty_identities_returns_409():
    """Existing email → GoTrue returns identities == [] → 409."""
    with patch("src.saas.auth_api.get_supabase") as gs:
        db = _make_db()
        db.auth.sign_up.return_value = _signup_response(
            identities=[], session=None,
        )
        gs.return_value = db
        with patch("src.saas.auth_api.TenantManager") as tm_cls:
            tm_cls.return_value = MagicMock()
            with pytest.raises(HTTPException) as ei:
                await signup(SignupRequest(
                    email="taken@example.com",
                    password="test1234",
                    business_name="Taken Co",
                    phone="+60123456789",
                ))
    assert ei.value.status_code == 409
    assert "already exists" in ei.value.detail.lower()
