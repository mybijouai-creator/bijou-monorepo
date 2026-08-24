"""Unit tests for the SharedContextClient.

Uses a real Supabase client connection — the tests run against a live
test project (set BIJOU_TEST_SUPABASE_URL + BIJOU_TEST_SUPABASE_KEY
env vars) or are skipped. The validator tests (channel/role/empty
content) run without a Supabase connection.
"""
import os
import pytest
from datetime import datetime, timezone, timedelta

from packages.voice.src.shared_context import (
    SharedContextClient,
    SharedContextTurn,
    CHANNELS,
    ROLES,
)


# ─── Pure validation tests (no Supabase needed) ───────────────────────

def test_channel_validation_accepts_known():
    # Should not raise for the 5 known channels
    for c in CHANNELS:
        SharedContextClient._validate(c, "user")


def test_channel_validation_rejects_unknown():
    with pytest.raises(ValueError, match="channel must be one of"):
        SharedContextClient._validate("fax", "user")


def test_role_validation_accepts_known():
    for r in ROLES:
        SharedContextClient._validate("voice", r)


def test_role_validation_rejects_unknown():
    with pytest.raises(ValueError, match="role must be one of"):
        SharedContextClient._validate("voice", "moderator")


def test_turn_model_basic():
    t = SharedContextTurn(
        id="00000000-0000-0000-0000-000000000000",
        tenant_id="11111111-1111-1111-1111-111111111111",
        customer_phone="+60174106981",
        channel="whatsapp",
        thread_id="60174106981@s.whatsapp.net",
        role="user",
        content="Hi!",
    )
    assert t.metadata == {}
    assert isinstance(t.created_at, datetime)


# ─── Live Supabase tests (skipped without env) ─────────────────────────

TEST_URL = os.environ.get("BIJOU_TEST_SUPABASE_URL", "")
TEST_KEY = os.environ.get("BIJOU_TEST_SUPABASE_KEY", "")

pytestmark = pytest.mark.skipif(
    not (TEST_URL and TEST_KEY),
    reason="BIJOU_TEST_SUPABASE_URL/KEY not set — set them to run live tests",
)


@pytest.fixture
def client():
    return SharedContextClient(supabase_url=TEST_URL, supabase_service_key=TEST_KEY)


@pytest.mark.asyncio
async def test_get_recent_context_returns_empty_for_unknown_phone(client):
    turns = await client.get_recent_context(
        tenant_id="00000000-0000-0000-0000-000000000000",
        customer_phone="+60000000000",
    )
    assert turns == []


@pytest.mark.asyncio
async def test_append_and_read_roundtrip(client):
    """Insert a voice turn, read it back, verify shape."""
    import uuid
    tenant_id = str(uuid.uuid4())
    phone = "+60174106999"
    call_id = f"v3:test_{uuid.uuid4().hex[:8]}"
    inserted_id = await client.append_voice_turn(
        tenant_id=tenant_id,
        customer_phone=phone,
        call_id=call_id,
        role="user",
        content="hello, this is a test",
        metadata={"test": True},
    )
    assert inserted_id
    turns = await client.get_recent_context(
        tenant_id=tenant_id,
        customer_phone=phone,
        since_hours=1,
    )
    assert len(turns) >= 1
    last = turns[0]
    assert last.content == "hello, this is a test"
    assert last.channel == "voice"
    assert last.role == "user"
    assert last.thread_id == call_id
    # Cleanup
    # (left for now — the test is idempotent and uses random tenant_ids)
