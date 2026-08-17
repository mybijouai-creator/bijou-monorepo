"""
Unit tests for /api/auth/login response shape.

2026-08-17: the static login.html expects `data.email` and
`data.business_name` at the top level of the response, but the old login()
returned them only nested inside `data.user.email` (and didn't return
`business_name` at all). This caused
`localStorage.setItem("email", data.email)` to store the literal string
"undefined" in localStorage — which the dashboard then read back as
"undefined" / "—". User-facing symptom: "login is not working" because
the dashboard's identity panel rendered blank or wrong.

The Google OAuth path (`oauth_session()`) already returns `email` and
`business_name` at the top level; these tests pin the same contract for
the email/password login path so the two stay in sync.
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

if "supabase_auth" not in sys.modules:
    sa = types.ModuleType("supabase_auth")
    sa_errors = types.ModuleType("supabase_auth.errors")

    class AuthApiError(Exception):
        def __init__(self, message, status=None, code=None):
            super().__init__(message)
            self.status = status
            self.code = code

    sa_errors.AuthApiError = AuthApiError
    sys.modules["supabase_auth"] = sa
    sys.modules["supabase_auth.errors"] = sa_errors

from fastapi import HTTPException  # noqa: E402

from src.saas import auth_api  # noqa: E402
from src.saas.auth_api import LoginRequest, login, AuthResponse  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _mock_user(user_id="user-abc", email="boss@example.com"):
    u = MagicMock()
    u.id = user_id
    u.email = email
    return u


def _mock_session(access="jwt.access", refresh="jwt.refresh"):
    s = MagicMock()
    s.access_token = access
    s.refresh_token = refresh
    return s


def _login_response(user=None, session=None):
    """Build a fake supabase auth.sign_in_with_password return value."""
    resp = MagicMock()
    resp.user = user
    resp.session = session
    return resp


def _build_db(
    *,
    user_id="user-abc",
    access_token="jwt.access",
    refresh_token="jwt.refresh",
    tenant_users=None,
    business_name="Boss Co",
    user_email="boss@example.com",
):
    """Build a fake supabase client for the happy path:
    - auth.sign_in_with_password returns a real-shaped auth response
    - tenant_users has the link for this user
    - tenants row has the business_name
    """
    db = MagicMock()
    user = _mock_user(user_id=user_id, email=user_email)
    session = _mock_session(access=access_token, refresh=refresh_token)
    db.auth.sign_in_with_password = MagicMock(return_value=_login_response(user=user, session=session))
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"tenant_id": "tenant-xyz"}] if tenant_users is None else tenant_users
    )
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"business_name": business_name} if business_name else None
    )
    return db


# ─────────────────────────────────────────────────────────────────────
# Contract tests — the regression we're pinning
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_response_has_email_at_top_level():
    """`data.email` MUST exist at the top level of the response.
    Regression: previously only `data.user.email` was populated, so the
    static login.html stored the string "undefined" in localStorage.
    """
    with patch("src.saas.auth_api.get_supabase") as gs:
        gs.return_value = _build_db()
        result = await login(LoginRequest(
            email="boss@example.com",
            password="hunter2hunter2",
        ))

    assert isinstance(result, AuthResponse)
    assert result.email == "boss@example.com", (
        "login() must populate `email` at the top level of AuthResponse; "
        "the static login.html reads it as data.email."
    )


@pytest.mark.asyncio
async def test_login_response_has_business_name_at_top_level():
    """`data.business_name` MUST exist at the top level of the response,
    pulled from the tenants row. Regression: previously null → dashboard
    showed "Bijou" instead of the real business name.
    """
    with patch("src.saas.auth_api.get_supabase") as gs:
        gs.return_value = _build_db(business_name="Boss Holdings Sdn Bhd")
        result = await login(LoginRequest(
            email="boss@example.com",
            password="hunter2hunter2",
        ))

    assert result.business_name == "Boss Holdings Sdn Bhd", (
        "login() must populate `business_name` at the top level; "
        "otherwise the dashboard shell falls back to 'Bijou'."
    )


@pytest.mark.asyncio
async def test_login_response_keeps_existing_fields():
    """Sanity: the new fields are additive — tokens, tenant_id, and user
    must still be present and correct, so the fix doesn't regress any
    other consumer.
    """
    with patch("src.saas.auth_api.get_supabase") as gs:
        gs.return_value = _build_db()
        result = await login(LoginRequest(
            email="boss@example.com",
            password="hunter2hunter2",
        ))

    assert result.access_token == "jwt.access"
    assert result.refresh_token == "jwt.refresh"
    assert result.tenant_id == "tenant-xyz"
    assert result.email_confirmation_required is False
    assert result.user == {"id": "user-abc", "email": "boss@example.com"}


@pytest.mark.asyncio
async def test_login_business_name_missing_row_returns_none_not_500():
    """If the tenants row is missing, login() should return business_name=None
    (login itself still succeeds). The frontend `|| ""` defensive fallback
    handles the rest, and the dashboard has fallbacks too.
    """
    with patch("src.saas.auth_api.get_supabase") as gs:
        gs.return_value = _build_db(business_name=None)
        result = await login(LoginRequest(
            email="boss@example.com",
            password="hunter2hunter2",
        ))

    assert result.business_name is None
    assert result.email == "boss@example.com"


@pytest.mark.asyncio
async def test_login_business_name_lookup_error_does_not_break_login():
    """If the secondary business_name lookup itself errors (e.g. transient
    PostgREST blip), the login should still succeed — only `business_name`
    becomes None. The primary auth + tenant_resolution must not be
    collateral-damaged by a non-essential extra query.
    """
    db = _build_db()
    # Make the maybe_single().execute() call (the business_name lookup)
    # always blow up. The tenant_users .execute() path uses a different
    # mock and still returns the link, so the rest of login proceeds.
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = RuntimeError(
        "transient PostgREST 503"
    )

    with patch("src.saas.auth_api.get_supabase", return_value=db):
        result = await login(LoginRequest(
            email="boss@example.com",
            password="hunter2hunter2",
        ))

    assert result.business_name is None  # swallowed, login still OK
    assert result.access_token == "jwt.access"
    assert result.refresh_token == "jwt.refresh"
    assert result.tenant_id == "tenant-xyz"
