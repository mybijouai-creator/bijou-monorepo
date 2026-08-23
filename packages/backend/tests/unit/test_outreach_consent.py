"""Tests for the outreach consent API (issue #14, the other half of PDPA).

Covers:
- POST /api/outreach/consent/record happy path
- POST /api/outreach/consent/record rejects invalid consent_type
- POST /api/outreach/consent/record rejects invalid channel
- GET /api/outreach/consent/status returns correct shape
- POST /api/outreach/consent/{id}/revoke marks revoked_at
- POST /api/outreach/consent/{id}/revoke refuses double-revoke
- POST /api/outreach/consent/{id}/revoke refuses cross-tenant access
- GET /api/outreach/consent/audit returns full history
- POST /api/outreach/consent/check-bulk bulk returns map

Tests use unittest.mock to stub the Supabase client. The
verify_session dependency is patched to return a known tenant_id.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_TENANT_ID = "607690ec-4ff7-4ef4-b98e-bfb00442fe95"
FAKE_OTHER_TENANT = "00000000-0000-0000-0000-000000000999"
FAKE_CONTACT_ID = "11111111-1111-1111-1111-111111111111"
FAKE_CONSENT_ID = "22222222-2222-2222-2222-222222222222"


def _make_supabase_mock():
    """A MagicMock that mimics the chainable Supabase client surface used
    by outreach_consent_api. Each queryable has a `.data` attribute
    on its `.execute()` result, and the chains return themselves for
    repeated filters."""
    sb = MagicMock()

    # .table(...).insert(...).execute() -> returns the inserted row
    insert_chain = sb.table.return_value.insert.return_value
    insert_chain.execute.return_value = MagicMock(
        data=[{
            "id": FAKE_CONSENT_ID,
            "tenant_id": FAKE_TENANT_ID,
            "contact_id": FAKE_CONTACT_ID,
            "consent_type": "opt_in",
            "consent_text": "I agree to receive updates",
            "channel": "web_form",
            "source": "manual",
            "ip_address": None,
            "user_agent": None,
            "granted_at": "2026-08-23T10:00:00+00:00",
            "expires_at": None,
            "revoked_at": None,
            "revoked_reason": None,
            "created_at": "2026-08-23T10:00:00+00:00",
        }]
    )

    # .table(...).update(...).eq(...).execute() -> returns the updated row
    update_chain = sb.table.return_value.update.return_value.eq.return_value
    update_chain.execute.return_value = MagicMock(
        data=[{
            "id": FAKE_CONSENT_ID,
            "tenant_id": FAKE_TENANT_ID,
            "contact_id": FAKE_CONTACT_ID,
            "consent_type": "opt_in",
            "consent_text": "I agree to receive updates",
            "channel": "web_form",
            "source": "manual",
            "ip_address": None,
            "user_agent": None,
            "granted_at": "2026-08-23T10:00:00+00:00",
            "expires_at": None,
            "revoked_at": "2026-08-23T11:00:00+00:00",
            "revoked_reason": "User request",
            "created_at": "2026-08-23T10:00:00+00:00",
        }]
    )

    # .table(...).select(...).eq(...).is_(...).order(...).limit(...).execute()
    # -> we'll fill this in per-test
    return sb


# ---------------------------------------------------------------------------
# POST /api/outreach/consent/record
# ---------------------------------------------------------------------------


def test_record_happy_path():
    sb = _make_supabase_mock()
    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            "/api/outreach/consent/record",
            json={
                "contact_id": FAKE_CONTACT_ID,
                "consent_type": "opt_in",
                "channel": "web_form",
                "consent_text": "I agree to receive updates",
                "source": "landing_page_form",
                "ip_address": "203.0.113.42",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["contact_id"] == FAKE_CONTACT_ID
        assert body["consent_type"] == "opt_in"
        assert body["channel"] == "web_form"
        assert body["tenant_id"] == FAKE_TENANT_ID


def test_record_rejects_invalid_consent_type():
    sb = _make_supabase_mock()
    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            "/api/outreach/consent/record",
            json={
                "contact_id": FAKE_CONTACT_ID,
                "consent_type": "maybe_later",  # not in the allowed set
                "channel": "web_form",
            },
        )
        assert r.status_code == 400
        assert "consent_type" in r.json()["detail"].lower()


def test_record_rejects_invalid_channel():
    sb = _make_supabase_mock()
    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            "/api/outreach/consent/record",
            json={
                "contact_id": FAKE_CONTACT_ID,
                "consent_type": "opt_in",
                "channel": "carrier_pigeon",  # not in the allowed set
            },
        )
        assert r.status_code == 400
        assert "channel" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/outreach/consent/status
# ---------------------------------------------------------------------------


def test_status_returns_active_consent():
    sb = _make_supabase_mock()
    active_row = {
        "id": FAKE_CONSENT_ID,
        "tenant_id": FAKE_TENANT_ID,
        "contact_id": FAKE_CONTACT_ID,
        "consent_type": "opt_in",
        "consent_text": "I agree",
        "channel": "web_form",
        "source": "manual",
        "ip_address": None,
        "user_agent": None,
        "granted_at": "2026-08-23T10:00:00+00:00",
        "expires_at": None,
        "revoked_at": None,
        "revoked_reason": None,
    }
    select_chain = sb.table.return_value.select.return_value
    select_chain.eq.return_value = select_chain
    select_chain.is_.return_value = select_chain
    select_chain.order.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=[active_row])

    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.get(
            "/api/outreach/consent/status",
            params={"contact_id": FAKE_CONTACT_ID},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["has_active_consent"] is True
        assert body["active_consent_type"] == "opt_in"
        assert body["channel"] == "web_form"


def test_status_returns_no_consent_when_empty():
    sb = _make_supabase_mock()
    select_chain = sb.table.return_value.select.return_value
    select_chain.eq.return_value = select_chain
    select_chain.is_.return_value = select_chain
    select_chain.order.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=[])  # no active consent

    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.get(
            "/api/outreach/consent/status",
            params={"contact_id": FAKE_CONTACT_ID},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["has_active_consent"] is False
        assert body["active_consent_type"] is None


# ---------------------------------------------------------------------------
# POST /api/outreach/consent/{id}/revoke
# ---------------------------------------------------------------------------


def test_revoke_happy_path():
    sb = _make_supabase_mock()
    # The .maybe_single() chain must return the existing row
    maybe_chain = sb.table.return_value.select.return_value
    maybe_chain.eq.return_value = maybe_chain
    maybe_chain.maybe_single.return_value.execute.return_value = MagicMock(
        data={
            "id": FAKE_CONSENT_ID,
            "tenant_id": FAKE_TENANT_ID,
            "revoked_at": None,
        }
    )

    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            f"/api/outreach/consent/{FAKE_CONSENT_ID}/revoke",
            json={"reason": "Customer asked to be removed"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["revoked_at"] is not None
        assert body["revoked_reason"] == "Customer asked to be removed"


def test_revoke_refuses_cross_tenant():
    """A revoke attempt on a row that belongs to a different tenant
    must 404 (not 403) so we don't acknowledge the existence of
    other tenants' rows."""
    sb = _make_supabase_mock()
    maybe_chain = sb.table.return_value.select.return_value
    maybe_chain.eq.return_value = maybe_chain
    maybe_chain.maybe_single.return_value.execute.return_value = MagicMock(
        data={
            "id": FAKE_CONSENT_ID,
            "tenant_id": FAKE_OTHER_TENANT,  # not the session's tenant
            "revoked_at": None,
        }
    )

    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            f"/api/outreach/consent/{FAKE_CONSENT_ID}/revoke",
            json={"reason": "Hostile attempt"},
        )
        assert r.status_code == 404


def test_revoke_refuses_double_revoke():
    """Revoking an already-revoked row returns 400, not silent success."""
    sb = _make_supabase_mock()
    maybe_chain = sb.table.return_value.select.return_value
    maybe_chain.eq.return_value = maybe_chain
    maybe_chain.maybe_single.return_value.execute.return_value = MagicMock(
        data={
            "id": FAKE_CONSENT_ID,
            "tenant_id": FAKE_TENANT_ID,
            "revoked_at": "2026-08-23T09:00:00+00:00",  # already revoked
        }
    )

    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            f"/api/outreach/consent/{FAKE_CONSENT_ID}/revoke",
            json={"reason": "second try"},
        )
        assert r.status_code == 400
        assert "already revoked" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/outreach/consent/audit
# ---------------------------------------------------------------------------


def test_audit_returns_full_history():
    sb = _make_supabase_mock()
    rows = [
        {
            "id": "row-2",
            "tenant_id": FAKE_TENANT_ID,
            "contact_id": FAKE_CONTACT_ID,
            "consent_type": "opt_in",
            "channel": "web_form",
            "source": "landing_page",
            "granted_at": "2026-08-23T11:00:00+00:00",
            "revoked_at": None,
        },
        {
            "id": "row-1",
            "tenant_id": FAKE_TENANT_ID,
            "contact_id": FAKE_CONTACT_ID,
            "consent_type": "opt_in",
            "channel": "web_form",
            "source": "csv_import",
            "granted_at": "2026-01-15T08:00:00+00:00",
            "revoked_at": "2026-07-01T12:00:00+00:00",
            "revoked_reason": "Annual opt-out",
        },
    ]
    select_chain = sb.table.return_value.select.return_value
    select_chain.eq.return_value = select_chain
    select_chain.order.return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=rows)

    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.get(
            "/api/outreach/consent/audit",
            params={"contact_id": FAKE_CONTACT_ID},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert body["active_count"] == 1
        assert body["revoked_count"] == 1


# ---------------------------------------------------------------------------
# POST /api/outreach/consent/check-bulk
# ---------------------------------------------------------------------------


def test_check_bulk_returns_map():
    sb = _make_supabase_mock()
    cid_a = "11111111-1111-1111-1111-111111111111"
    cid_b = "22222222-2222-2222-2222-222222222222"
    cid_c = "33333333-3333-3333-3333-333333333333"
    select_chain = sb.table.return_value.select.return_value
    select_chain.eq.return_value = select_chain
    select_chain.in_.return_value = select_chain
    select_chain.is_.return_value = select_chain
    select_chain.order.return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=[
        # cid_a has consent, cid_b does not, cid_c has revoked consent
        {"contact_id": cid_a, "consent_type": "opt_in", "revoked_at": None, "granted_at": "2026-08-01"},
    ])

    with patch("src.core.outreach_consent_api._supabase", return_value=sb), \
         patch("src.core.outreach_consent_api.verify_session", return_value=FAKE_TENANT_ID):
        from src.core.outreach_consent_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        r = client.post(
            "/api/outreach/consent/check-bulk",
            params={"contact_ids": [cid_a, cid_b, cid_c]},
        )
        assert r.status_code == 200
        body = r.json()
        # cid_a has active consent (returns True)
        # cid_b has no active consent (returns False)
        # cid_c has no active consent either (not in result set)
        assert body[cid_a] is True
        assert body[cid_b] is False
        assert body[cid_c] is False
