"""
2026-08-23: oauth_refresh_token was captured on Cal.com OAuth connect but
never read back anywhere — once a tenant's access token expired, booking/
availability silently failed with a swallowed 401. Pins the fix: 401
detection and the refresh call's persistence.
"""

import sys
import types
from unittest.mock import MagicMock, patch

if "supabase" not in sys.modules:
    stub = types.ModuleType("supabase")
    stub.Client = object
    stub.create_client = MagicMock()
    sys.modules["supabase"] = stub

from src.core.services.tenant_calendar_service import TenantCalendarService


class TestIsUnauthorized:
    def test_detects_401_in_error_string(self):
        assert TenantCalendarService._is_unauthorized(
            {"success": False, "error": "Client error '401 Unauthorized' for url ..."}
        )

    def test_success_result_is_not_unauthorized(self):
        assert not TenantCalendarService._is_unauthorized({"success": True, "slots": {}})

    def test_other_error_is_not_unauthorized(self):
        assert not TenantCalendarService._is_unauthorized({"success": False, "error": "timeout"})

    def test_none_result_is_safe(self):
        assert not TenantCalendarService._is_unauthorized(None)


class TestRefreshOAuthToken:
    def test_no_refresh_token_returns_none(self):
        svc = TenantCalendarService(supabase_client=MagicMock())
        assert svc._refresh_oauth_token("tenant-1", {}) is None

    def test_successful_refresh_persists_new_tokens(self):
        db = MagicMock()
        svc = TenantCalendarService(supabase_client=db)
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {"access_token": "new-access", "refresh_token": "new-refresh"}

        with patch("httpx.post", return_value=fake_resp) as mock_post:
            result = svc._refresh_oauth_token("tenant-1", {"oauth_refresh_token": "old-refresh"})

        assert result == "new-access"
        mock_post.assert_called_once()
        assert mock_post.call_args.kwargs["data"]["grant_type"] == "refresh_token"
        assert mock_post.call_args.kwargs["data"]["refresh_token"] == "old-refresh"
        db.table.assert_called_with("tenant_calendars")

    def test_failed_refresh_returns_none_and_does_not_write(self):
        db = MagicMock()
        svc = TenantCalendarService(supabase_client=db)
        fake_resp = MagicMock(status_code=401, text="invalid_grant")

        with patch("httpx.post", return_value=fake_resp):
            result = svc._refresh_oauth_token("tenant-1", {"oauth_refresh_token": "old-refresh"})

        assert result is None
        db.table.assert_not_called()
