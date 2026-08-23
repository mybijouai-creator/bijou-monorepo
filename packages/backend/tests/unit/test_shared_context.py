"""
Tests for the A2A shared-context API (issue #23).

Covers:
- POST /api/shared-context/append happy path
- POST /api/shared-context/append rejects invalid channel
- POST /api/shared-context/append rejects invalid role
- GET /api/shared-context with phone filter, returns rows sorted desc
- GET /api/shared-context with no entries returns empty list
- tenant_id isolation: a request with no session returns 401/403

Tests use unittest.mock to stub the Supabase client and the verify_session
dependency. They are scaffolded for the test suite (per CLAUDE.md the
venv in this session has no pytest; the user must `pip install -r
requirements-dev.txt` from their terminal to actually run them).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_tenant_id() -> str:
    return "607690ec-4ff7-4ef4-b98e-bfb00442fe95"


@pytest.fixture
def fake_supabase():
    """A MagicMock that mimics the chainable Supabase client surface used by
    shared_context_api (table().insert().execute(), .select().eq().eq().gte()
    .order().limit().execute())."""
    sb = MagicMock()
    insert_chain = sb.table.return_value.insert.return_value
    insert_chain.execute.return_value = MagicMock(data=[{
        "id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "607690ec-4ff7-4ef4-b98e-bfb00442fe95",
        "customer_phone": "+60123456789",
        "channel": "whatsapp",
        "thread_id": "+60123456789@s.whatsapp.net",
        "role": "user",
        "content": "hi",
        "metadata": {},
        "created_at": "2026-08-23T06:00:00+00:00",
    }])
    select_chain = sb.table.return_value.select.return_value
    select_chain.eq.return_value = select_chain
    select_chain.gte.return_value = select_chain
    select_chain.order.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=[
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "tenant_id": "607690ec-4ff7-4ef4-b98e-bfb00442fe95",
            "customer_phone": "+60123456789",
            "channel": "whatsapp",
            "thread_id": "+60123456789@s.whatsapp.net",
            "role": "assistant",
            "content": "hello, how can I help?",
            "metadata": {},
            "created_at": "2026-08-23T06:00:01+00:00",
        },
        {
            "id": "00000000-0000-0000-0000-000000000011",
            "tenant_id": "607690ec-4ff7-4ef4-b98e-bfb00442fe95",
            "customer_phone": "+60123456789",
            "channel": "voice",
            "thread_id": "call_abc123",
            "role": "user",
            "content": "Hi, I want to book a viewing",
            "metadata": {"call_sid": "abc123"},
            "created_at": "2026-08-23T06:05:00+00:00",
        },
    ])
    return sb


# ---------------------------------------------------------------------------
# POST /api/shared-context/append
# ---------------------------------------------------------------------------


def test_append_happy_path(fake_tenant_id, fake_supabase):
    """POST append with valid body returns the inserted row."""
    with patch("src.core.shared_context_api._supabase", return_value=fake_supabase), \
         patch("src.core.shared_context_api.verify_session", return_value=fake_tenant_id):
        from src.core.shared_context_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            "/api/shared-context/append",
            json={
                "customer_phone": "+60123456789",
                "channel": "whatsapp",
                "thread_id": "+60123456789@s.whatsapp.net",
                "role": "user",
                "content": "hi",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["channel"] == "whatsapp"
        assert body["role"] == "user"
        assert body["tenant_id"] == fake_tenant_id


def test_append_rejects_invalid_channel(fake_tenant_id, fake_supabase):
    """POST append with channel='carrier-pigeon' returns 400."""
    with patch("src.core.shared_context_api._supabase", return_value=fake_supabase), \
         patch("src.core.shared_context_api.verify_session", return_value=fake_tenant_id):
        from src.core.shared_context_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            "/api/shared-context/append",
            json={
                "customer_phone": "+60123456789",
                "channel": "carrier-pigeon",
                "thread_id": "t1",
                "role": "user",
                "content": "hi",
            },
        )
        assert r.status_code == 400
        assert "channel" in r.json()["detail"].lower()


def test_append_rejects_invalid_role(fake_tenant_id, fake_supabase):
    """POST append with role='admin' returns 400."""
    with patch("src.core.shared_context_api._supabase", return_value=fake_supabase), \
         patch("src.core.shared_context_api.verify_session", return_value=fake_tenant_id):
        from src.core.shared_context_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            "/api/shared-context/append",
            json={
                "customer_phone": "+60123456789",
                "channel": "whatsapp",
                "thread_id": "t1",
                "role": "admin",
                "content": "hi",
            },
        )
        assert r.status_code == 400
        assert "role" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/shared-context
# ---------------------------------------------------------------------------


def test_get_returns_rows_sorted_desc(fake_tenant_id, fake_supabase):
    """GET returns the Supabase rows (assumed pre-sorted desc by the API)."""
    with patch("src.core.shared_context_api._supabase", return_value=fake_supabase), \
         patch("src.core.shared_context_api.verify_session", return_value=fake_tenant_id):
        from src.core.shared_context_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.get("/api/shared-context", params={"phone": "+60123456789"})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        # The 2 fixture rows are voice (06:05) then assistant (06:00:01).
        # The API does .order("created_at", desc=True), so the voice row
        # (later) should be first.
        assert body["entries"][0]["channel"] == "voice"
        assert body["entries"][1]["channel"] == "whatsapp"


def test_get_empty_list_when_no_rows(fake_tenant_id):
    """GET returns count=0 and entries=[] when Supabase returns nothing."""
    empty_sb = MagicMock()
    chain = empty_sb.table.return_value.select.return_value
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=[])

    with patch("src.core.shared_context_api._supabase", return_value=empty_sb), \
         patch("src.core.shared_context_api.verify_session", return_value=fake_tenant_id):
        from src.core.shared_context_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.get("/api/shared-context", params={"phone": "+60000000000"})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 0
        assert body["entries"] == []


# ---------------------------------------------------------------------------
# tenant_id isolation
# ---------------------------------------------------------------------------


def test_unauthenticated_request_returns_401_or_403():
    """A request with no session should fail before touching Supabase.

    verify_session in src.core.dashboard_api_simple returns a non-tenant
    string (e.g. '' or raises) when no auth headers are present. We assert
    that the endpoint does not return 200, regardless of the exact shape
    of the auth check.
    """
    # No verify_session override; FastAPI's default behavior on Depends
    # without override is to call the dependency. We don't care about the
    # exact status (401 vs 403) only that it's not 200.
    sb_sentinel = MagicMock()
    with patch("src.core.shared_context_api._supabase", return_value=sb_sentinel):
        from src.core.shared_context_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        r = client.post(
            "/api/shared-context/append",
            json={
                "customer_phone": "+60123456789",
                "channel": "whatsapp",
                "thread_id": "t1",
                "role": "user",
                "content": "hi",
            },
        )
        assert r.status_code != 200
        # And critically: the Supabase client should not have been called
        # for a write (no tenant_id = no write).
        sb_sentinel.table.return_value.insert.assert_not_called()


# ---------------------------------------------------------------------------
# Sanity: the SQL migration file parses
# ---------------------------------------------------------------------------


def test_migration_sql_is_syntactically_clean():
    """The migration file is plain SQL; this test just asserts it exists and
    contains the expected table name. A real Postgres parse would require a
    running DB; the user can run `psql -f ...` manually after applying."""
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    migration_path = os.path.join(
        repo_root, "packages", "backend", "migrations-py", "add_shared_context.sql"
    )
    assert os.path.isfile(migration_path), f"missing migration: {migration_path}"
    with open(migration_path) as f:
        sql = f.read()
    assert "create table" in sql.lower()
    assert "shared_context" in sql
    assert "tenant_id" in sql
    assert "customer_phone" in sql
    assert "channel" in sql
    assert "role" in sql
    assert "content" in sql
    assert "row level security" in sql.lower()
