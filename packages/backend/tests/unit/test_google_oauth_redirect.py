"""Regression: Google OAuth must redirect to the canonical public origin.

2026-08-10 outage. The callback built its redirect from
`PUBLIC_URL or str(request.base_url)`. Behind Fly's proxy the request host is
bijou-production.fly.dev, so a user finishing Google sign-up landed on
https://bijou-production.fly.dev/onboard/... instead of app.mybijou.xyz.

That is a different browser origin, and the dashboard stores its JWT in
localStorage (origin-scoped), so the session was invisible there and the user
was bounced to /login — presenting as "no QR page, no vertical, fully broken".

These tests pin the invariant: the redirect base never depends on the request.
"""
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Stub supabase so importing the module under test doesn't require the package
# or live credentials (same approach as test_auth_signup_error_mapping.py).
if "supabase" not in sys.modules:
    supabase_stub = types.ModuleType("supabase")
    setattr(supabase_stub, "create_client", lambda *a, **k: None)
    setattr(supabase_stub, "Client", object)
    sys.modules["supabase"] = supabase_stub

from src.saas.google_oauth import (  # noqa: E402
    CANONICAL_PUBLIC_URL,
    _public_base_url,
    get_google_config,
)


def test_public_base_url_defaults_to_canonical_host_not_fly():
    """With PUBLIC_URL unset we must still use the branded domain."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PUBLIC_URL", None)
        base = _public_base_url()
    assert base == "https://app.mybijou.xyz"
    assert "fly.dev" not in base


def test_public_base_url_honours_env_override():
    with patch.dict(os.environ, {"PUBLIC_URL": "https://staging.mybijou.xyz/"}):
        assert _public_base_url() == "https://staging.mybijou.xyz"


def test_public_base_url_strips_trailing_slash():
    with patch.dict(os.environ, {"PUBLIC_URL": "https://app.mybijou.xyz/"}):
        assert _public_base_url() == "https://app.mybijou.xyz"


@pytest.mark.parametrize("path", ["/dashboard", "/onboard/tok123"])
def test_redirect_targets_are_on_canonical_origin(path):
    """Both callback exits must build on the canonical origin."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PUBLIC_URL", None)
        url = f"{_public_base_url()}{path}"
    assert url.startswith("https://app.mybijou.xyz/")
    assert "bijou-production.fly.dev" not in url


def test_default_google_redirect_uri_is_canonical():
    """The OAuth redirect_uri default must not point at the raw Fly host."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GOOGLE_REDIRECT_URI", None)
        uri = get_google_config()["redirect_uri"]
    assert uri == f"{CANONICAL_PUBLIC_URL}/api/auth/google/callback"
    assert "fly.dev" not in uri
