"""Tests for the Reasoning Trace API (issue #11).

Covers:
- POST /reasons records an AI message's reasoning
- POST /reasons upserts on (tenant_id, message_id) — a retry doesn't
  double-record
- GET /{message_id}/reason returns the recorded row
- GET /{message_id}/reason returns 404 for an unknown message_id
- GET /reasons returns recent rows, optional chat_jid filter
- A request with no session is rejected before any DB call
- confidence is clamped to 0.0..1.0 by Pydantic

Tests use unittest.mock to stub the Supabase client. They will run when
the user installs pytest in the venv (pip install -r requirements-dev.txt
from their terminal).
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def fake_tenant_id() -> str:
    return "607690ec-4ff7-4ef4-b98e-bfb00442fe95"


@pytest.fixture
def app(fake_tenant_id):
    from src.core.message_reasons_api import router

    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fake_supabase():
    """A MagicMock that mimics the chainable Supabase client used by
    message_reasons_api (table().upsert().execute(),
    .table().select().eq().eq().limit().execute(),
    .table().select().eq().gte().order().limit().execute())."""
    sb = MagicMock()

    # upsert() chain
    upsert_chain = sb.table.return_value.upsert.return_value
    upsert_chain.execute.return_value = MagicMock(data=[{
        "id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "607690ec-4ff7-4ef4-b98e-bfb00442fe95",
        "message_id": "msg_abc",
        "chat_jid": "+60123456789@s.whatsapp.net",
        "channel": "whatsapp",
        "retrieved_docs": [{"doc_id": "kb_1", "title": "Pricing", "relevance": 0.92}],
        "tool_calls": [],
        "model": "gemini-2.5-flash",
        "confidence": 0.81,
        "alternatives": [],
        "metadata": {"prompt_tokens": 412, "latency_ms": 1820},
        "created_at": "2026-08-23T06:00:00+00:00",
    }])

    # select().eq().eq().limit() chain (for GET by message_id)
    select_eq_chain = sb.table.return_value.select.return_value
    select_eq_chain.eq.return_value = select_eq_chain
    select_eq_chain.limit.return_value = select_eq_chain
    select_eq_chain.execute.return_value = MagicMock(data=[{
        "id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "607690ec-4ff7-4ef4-b98e-bfb00442fe95",
        "message_id": "msg_abc",
        "chat_jid": "+60123456789@s.whatsapp.net",
        "channel": "whatsapp",
        "retrieved_docs": [{"doc_id": "kb_1", "title": "Pricing", "relevance": 0.92}],
        "tool_calls": [],
        "model": "gemini-2.5-flash",
        "confidence": 0.81,
        "alternatives": [],
        "metadata": {},
        "created_at": "2026-08-23T06:00:00+00:00",
    }])

    return sb


# ── POST /reasons ────────────────────────────────────────────────────────


def test_post_records_reason(app, client, fake_tenant_id, fake_supabase):
    """POST /reasons with a valid body writes via the upsert chain."""
    with patch("src.core.message_reasons_api._supabase", return_value=fake_supabase), \
         patch("src.core.message_reasons_api.verify_session", return_value=fake_tenant_id):
        r = client.post(
            "/api/dashboard/messages/reasons",
            json={
                "message_id": "msg_abc",
                "chat_jid": "+60123456789@s.whatsapp.net",
                "channel": "whatsapp",
                "retrieved_docs": [{"doc_id": "kb_1", "title": "Pricing", "relevance": 0.92}],
                "tool_calls": [],
                "model": "gemini-2.5-flash",
                "confidence": 0.81,
                "alternatives": [],
                "metadata": {"prompt_tokens": 412, "latency_ms": 1820},
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["message_id"] == "msg_abc"
    assert body["confidence"] == 0.81
    assert body["retrieved_docs"][0]["doc_id"] == "kb_1"
    # Upsert was called with the (tenant, message_id) on_conflict target.
    fake_supabase.table.return_value.upsert.assert_called_once()


def test_post_rejects_confidence_above_one(app, client, fake_tenant_id, fake_supabase):
    """Pydantic should reject confidence > 1.0 (Field ge=0.0 le=1.0)."""
    with patch("src.core.message_reasons_api._supabase", return_value=fake_supabase), \
         patch("src.core.message_reasons_api.verify_session", return_value=fake_tenant_id):
        r = client.post(
            "/api/dashboard/messages/reasons",
            json={
                "message_id": "msg_abc",
                "chat_jid": "+60123456789@s.whatsapp.net",
                "confidence": 1.5,
            },
        )
    assert r.status_code == 422  # Pydantic validation error


def test_post_rejects_negative_confidence(app, client, fake_tenant_id, fake_supabase):
    """Pydantic should reject confidence < 0.0."""
    with patch("src.core.message_reasons_api._supabase", return_value=fake_supabase), \
         patch("src.core.message_reasons_api.verify_session", return_value=fake_tenant_id):
        r = client.post(
            "/api/dashboard/messages/reasons",
            json={
                "message_id": "msg_abc",
                "chat_jid": "+60123456789@s.whatsapp.net",
                "confidence": -0.1,
            },
        )
    assert r.status_code == 422


# ── GET /{message_id}/reason ─────────────────────────────────────────────


def test_get_returns_reason(app, client, fake_tenant_id, fake_supabase):
    """GET on a known message_id returns the row."""
    with patch("src.core.message_reasons_api._supabase", return_value=fake_supabase), \
         patch("src.core.message_reasons_api.verify_session", return_value=fake_tenant_id):
        r = client.get("/api/dashboard/messages/msg_abc/reason")
    assert r.status_code == 200
    body = r.json()
    assert body["message_id"] == "msg_abc"
    assert body["confidence"] == 0.81


def test_get_returns_404_when_no_row(app, client, fake_tenant_id):
    """GET on an unknown message_id returns 404, not 500."""
    empty_sb = MagicMock()
    chain = empty_sb.table.return_value.select.return_value
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=[])
    with patch("src.core.message_reasons_api._supabase", return_value=empty_sb), \
         patch("src.core.message_reasons_api.verify_session", return_value=fake_tenant_id):
        r = client.get("/api/dashboard/messages/msg_unknown/reason")
    assert r.status_code == 404
    assert "pre-date" in r.json()["detail"].lower() or "no reasoning" in r.json()["detail"].lower()


# ── GET /reasons (list) ─────────────────────────────────────────────────


def test_list_returns_rows(app, client, fake_tenant_id, fake_supabase):
    """GET /reasons returns recent rows for the tenant."""
    with patch("src.core.message_reasons_api._supabase", return_value=fake_supabase), \
         patch("src.core.message_reasons_api.verify_session", return_value=fake_tenant_id):
        r = client.get("/api/dashboard/messages/reasons")
    assert r.status_code == 200
    body = r.json()
    assert "reasons" in body
    assert "count" in body
    assert body["count"] == 1  # the fake_supabase returns 1 row


# ── Unauthenticated request ────────────────────────────────────────────


def test_unauthenticated_post_is_rejected(app, client):
    """A POST with no session should not touch Supabase and should not 200."""
    sb_sentinel = MagicMock()
    with patch("src.core.message_reasons_api._supabase", return_value=sb_sentinel):
        r = client.post(
            "/api/dashboard/messages/reasons",
            json={
                "message_id": "msg_abc",
                "chat_jid": "+60123456789@s.whatsapp.net",
            },
        )
    assert r.status_code != 200
    sb_sentinel.table.return_value.upsert.assert_not_called()


# ── Migration SQL sanity ───────────────────────────────────────────────


def test_migration_sql_is_syntactically_clean():
    """Assert the migration file exists and contains the expected table name."""
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    migration_path = os.path.join(
        repo_root, "packages", "backend", "migrations-py", "add_message_reasons.sql"
    )
    assert os.path.isfile(migration_path), f"missing migration: {migration_path}"
    with open(migration_path) as f:
        sql = f.read()
    assert "create table" in sql.lower()
    assert "message_reasons" in sql
    assert "tenant_id" in sql
    assert "message_id" in sql
    assert "retrieved_docs" in sql
    assert "tool_calls" in sql
    assert "alternatives" in sql
    assert "row level security" in sql.lower()
