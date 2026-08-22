"""Unit tests for src/connectors/nango_client.py.

Mocks httpx.AsyncClient (pattern from test_escalation_notifier.py) and a fake
Supabase client (pattern from test_auth_login_response.py) — no real network
or database calls.
"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from src.connectors import nango_client


def _fake_supabase(connection_id="conn-abc"):
    """Fake supabase client whose .table(...).select(...)....maybe_single().execute()
    returns a row with the given connection_id (or None if connection_id is None)."""
    db = MagicMock()
    data = {"connection_id": connection_id} if connection_id else None
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=data)
    return db


# ─────────────────────────────────────────────────────────────────────
# create_connect_session
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_create_connect_session_posts_right_body_and_headers(mock_httpx):
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json = Mock(return_value={"data": {"token": "sess-tok", "connect_link": "https://x", "expires_at": "later"}})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_httpx.return_value.__aenter__.return_value = mock_client

    with patch.dict(os.environ, {"NANGO_SECRET_KEY": "secret-123"}, clear=False):
        result = await nango_client.create_connect_session(
            "tenant-1", "boss@example.com", allowed_integrations=["google-calendar"]
        )

    assert result["token"] == "sess-tok"
    mock_client.post.assert_awaited_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://api.nango.dev/connect/sessions"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-123"
    assert kwargs["json"]["tags"] == {"end_user_id": "tenant-1", "end_user_email": "boss@example.com"}
    assert kwargs["json"]["allowed_integrations"] == ["google-calendar"]


@pytest.mark.asyncio
async def test_create_connect_session_reads_fallback_env_var():
    """NANGO_API_KEY is accepted as a fallback for NANGO_SECRET_KEY."""
    with patch.dict(os.environ, {"NANGO_API_KEY": "fallback-key"}, clear=True):
        assert nango_client._secret_key() == "fallback-key"


def test_missing_key_raises_clear_error():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError):
            nango_client._secret_key()


# ─────────────────────────────────────────────────────────────────────
# proxy_request
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proxy_request_raises_clean_error_when_no_connection():
    """No connection recorded for tenant+integration -> ValueError, not a crash."""
    db = _fake_supabase(connection_id=None)

    with pytest.raises(ValueError, match="No connection"):
        await nango_client.proxy_request("tenant-1", "google-calendar", "GET", "/events", db)


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_proxy_request_sends_connection_headers(mock_httpx):
    mock_response = Mock(status_code=200)
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_httpx.return_value.__aenter__.return_value = mock_client

    db = _fake_supabase(connection_id="conn-abc")

    with patch.dict(os.environ, {"NANGO_SECRET_KEY": "secret-123"}, clear=False):
        resp = await nango_client.proxy_request("tenant-1", "google-calendar", "GET", "/events", db)

    assert resp is mock_response
    mock_client.request.assert_awaited_once()
    args, kwargs = mock_client.request.call_args
    assert args[0] == "GET"
    assert args[1] == "https://api.nango.dev/proxy/events"
    assert kwargs["headers"]["Connection-Id"] == "conn-abc"
    assert kwargs["headers"]["Provider-Config-Key"] == "google-calendar"


# ─────────────────────────────────────────────────────────────────────
# delete_connection
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_delete_connection_removes_local_row_even_if_remote_fails(mock_httpx):
    """Remote Nango delete raises -> local row is still deleted (documented
    ponytail tradeoff: don't block the user's disconnect on a flaky remote call)."""
    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(side_effect=RuntimeError("Nango unreachable"))
    mock_httpx.return_value.__aenter__.return_value = mock_client

    db = _fake_supabase(connection_id="conn-abc")

    with patch.dict(os.environ, {"NANGO_SECRET_KEY": "secret-123"}, clear=False):
        await nango_client.delete_connection("tenant-1", "google-calendar", db)

    # local delete chain was invoked despite the remote failure
    db.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.assert_called_once()


@pytest.mark.asyncio
async def test_delete_connection_with_no_remote_connection_still_clears_local_row():
    db = _fake_supabase(connection_id=None)

    await nango_client.delete_connection("tenant-1", "google-calendar", db)

    db.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.assert_called_once()


# ─────────────────────────────────────────────────────────────────────
# record_connection / list_tenant_connections
# ─────────────────────────────────────────────────────────────────────

def test_record_connection_upserts_expected_row():
    db = MagicMock()
    nango_client.record_connection("tenant-1", "google-calendar", "conn-abc", db)
    db.table.return_value.upsert.assert_called_once_with(
        {
            "tenant_id": "tenant-1",
            "integration_id": "google-calendar",
            "connection_id": "conn-abc",
            "status": "connected",
        },
        on_conflict="tenant_id,integration_id",
    )


def test_list_tenant_connections_returns_rows():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"integration_id": "google-calendar"}]
    )
    result = nango_client.list_tenant_connections("tenant-1", db)
    assert result == [{"integration_id": "google-calendar"}]


def test_list_tenant_connections_empty_returns_list_not_none():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=None)
    result = nango_client.list_tenant_connections("tenant-1", db)
    assert result == []
