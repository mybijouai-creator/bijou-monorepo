"""
Unit tests for the two new dashboard endpoints added to dashboard_api_simple.py:

  GET /api/dashboard/messages/{chat_jid}
  GET /api/dashboard/leads

These are integration-style unit tests that mock the Supabase client so
they run without a real database connection.  Because dashboard_api_simple.py
imports from supabase (which may not be fully installed in the test
environment), we mock the supabase module before importing.
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Patch the supabase import BEFORE dashboard_api_simple is imported,
# so the "from supabase import Client, create_client" line works even
# when the installed supabase package doesn't expose those names.
# ---------------------------------------------------------------------------

def _ensure_supabase_stubbed():
    """Inject stub supabase module into sys.modules if needed."""
    if "supabase" not in sys.modules or not hasattr(sys.modules["supabase"], "Client"):
        stub = types.ModuleType("supabase")
        stub.Client = object          # placeholder class
        stub.create_client = MagicMock()
        sys.modules["supabase"] = stub

    # Also stub google_auth_oauthlib if missing (imported lazily inside the module)
    if "google_auth_oauthlib" not in sys.modules:
        stub_gauth = types.ModuleType("google_auth_oauthlib")
        stub_flow = types.ModuleType("google_auth_oauthlib.flow")
        stub_flow.Flow = MagicMock()
        sys.modules["google_auth_oauthlib"] = stub_gauth
        sys.modules["google_auth_oauthlib.flow"] = stub_flow


_ensure_supabase_stubbed()


# Now it is safe to import the module under test
import importlib
if "src.core.dashboard_api_simple" in sys.modules:
    _das = sys.modules["src.core.dashboard_api_simple"]
else:
    _das = importlib.import_module("src.core.dashboard_api_simple")

get_messages_for_chat = _das.get_messages_for_chat
get_leads = _das.get_leads


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_supabase_mock(rows):
    """
    Return (client_mock, query_mock) where query_mock is the chainable
    object returned by client.table().  All chained calls (.select, .eq,
    .order, .limit) return query_mock itself; .execute() returns a
    SimpleNamespace with .data = rows.
    """
    response = SimpleNamespace(data=rows)

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = response

    client = MagicMock()
    client.table.return_value = query
    return client, query


# ---------------------------------------------------------------------------
# TestMessagesEndpoint
# ---------------------------------------------------------------------------

class TestMessagesEndpoint:
    """Tests for GET /api/dashboard/messages/{chat_jid}"""

    async def test_returns_empty_list_for_unknown_chat_jid(self):
        """When Supabase returns no rows, the endpoint returns []."""
        client_mock, _ = _make_supabase_mock([])

        with patch.object(_das, "get_supabase", return_value=client_mock):
            result = await get_messages_for_chat(
                chat_jid="999999999@lid",
                tenant_id="29d48db4-075f-45ee-8c00-a57f8fd3016a",
            )

        assert result == []

    async def test_decodes_percent_encoded_at_sign(self):
        """
        FastAPI decodes path parameters automatically, so by the time the
        handler receives chat_jid it is already decoded.  We simulate that
        here by passing the decoded value and assert the Supabase query uses
        the decoded form (containing '@').
        """
        client_mock, query_mock = _make_supabase_mock([])

        with patch.object(_das, "get_supabase", return_value=client_mock):
            decoded_jid = "104600321409056@lid"
            await get_messages_for_chat(
                chat_jid=decoded_jid,
                tenant_id="29d48db4-075f-45ee-8c00-a57f8fd3016a",
            )

        # Verify the query used the decoded JID (with '@')
        eq_calls = [str(call) for call in query_mock.eq.call_args_list]
        assert any("104600321409056@lid" in c for c in eq_calls), (
            f"Expected decoded JID in .eq() calls, got: {eq_calls}"
        )

    async def test_returns_messages_ordered_by_created_at(self):
        """
        When Supabase returns 3 rows they must appear in ASC order in the
        response (oldest first). The ordering is enforced by the SQL query,
        so we verify the .order() call uses desc=False and that the returned
        list preserves the row sequence the DB returns.
        """
        rows = [
            {"id": "aaa", "role": "user",     "content": "Hello",    "created_at": "2026-02-20T10:00:00+00:00"},
            {"id": "bbb", "role": "assistant", "content": "Hi there", "created_at": "2026-02-20T10:00:05+00:00"},
            {"id": "ccc", "role": "user",     "content": "Thanks",   "created_at": "2026-02-20T10:00:10+00:00"},
        ]
        client_mock, query_mock = _make_supabase_mock(rows)

        with patch.object(_das, "get_supabase", return_value=client_mock):
            result = await get_messages_for_chat(
                chat_jid="104600321409056@lid",
                tenant_id="29d48db4-075f-45ee-8c00-a57f8fd3016a",
            )

        # Verify order call uses ASC (desc=False)
        query_mock.order.assert_called_once_with("created_at", desc=False)

        # Verify returned shape and order
        assert len(result) == 3
        assert result[0]["id"] == "aaa"
        assert result[1]["id"] == "bbb"
        assert result[2]["id"] == "ccc"
        # Verify field mapping: created_at -> timestamp
        assert result[0]["timestamp"] == "2026-02-20T10:00:00+00:00"
        assert result[0]["content"] == "Hello"
        assert result[0]["role"] == "user"

    async def test_media_fields_pass_through_when_present(self):
        """
        2026-08-22/23: messages table gained media_url/media_type columns
        (add_message_media_columns.sql) so a human agent can see the
        customer's actual attachment, not just the AI's text summary of it.
        Confirms the endpoint's select+response-mapping actually surfaces
        them, and that a text-only row (no media columns in the DB response)
        still returns cleanly with both fields null.
        """
        rows = [
            {
                "id": "img1", "role": "user", "content": "📸 Image: a receipt",
                "created_at": "2026-02-20T10:00:00+00:00",
                "media_url": "https://bridge.example/media/abc123.jpg",
                "media_type": "image",
            },
            {
                "id": "txt1", "role": "user", "content": "Hello",
                "created_at": "2026-02-20T10:00:05+00:00",
                # No media_url/media_type keys at all — simulates a text-only
                # row or a pre-migration row read before the columns existed.
            },
        ]
        client_mock, query_mock = _make_supabase_mock(rows)

        with patch.object(_das, "get_supabase", return_value=client_mock):
            result = await get_messages_for_chat(
                chat_jid="104600321409056@lid",
                tenant_id="29d48db4-075f-45ee-8c00-a57f8fd3016a",
            )

        # The select must actually request the new columns from Supabase —
        # a passing test that never checks this would miss a regression
        # where someone reverts the .select() string but leaves the
        # response-mapping code in place (looks fine, silently returns null
        # for every row because the columns were never fetched).
        select_calls = [str(call) for call in query_mock.select.call_args_list]
        assert any("media_url" in c and "media_type" in c for c in select_calls), (
            f"Expected media_url/media_type in .select() calls, got: {select_calls}"
        )

        assert result[0]["media_url"] == "https://bridge.example/media/abc123.jpg"
        assert result[0]["media_type"] == "image"
        assert result[1]["media_url"] is None
        assert result[1]["media_type"] is None


# ---------------------------------------------------------------------------
# TestLeadsEndpoint
# ---------------------------------------------------------------------------

class TestLeadsEndpoint:
    """Tests for GET /api/dashboard/leads"""

    async def test_returns_empty_list_when_no_escalations(self):
        """When the escalations table has no rows for the tenant, return []."""
        client_mock, _ = _make_supabase_mock([])

        with patch.object(_das, "get_supabase", return_value=client_mock):
            result = await get_leads(tenant_id="29d48db4-075f-45ee-8c00-a57f8fd3016a")

        assert result == []
