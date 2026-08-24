"""Service-to-service auth — JWT signed with BIJOU_API_KEY.

The voice service needs to call back into the Bijou backend for things
the voice service can't do locally (e.g. fetching KB document text from
S3/MinIO, billing events, knowledge base updates). To avoid a separate
service-account identity, we use a self-signed JWT that the backend's
existing API key verification accepts.

The shared secret is `BIJOU_API_KEY` (already in the .env). The JWT
payload mirrors the service-account shape the backend expects from its
own service-to-service calls.
"""
from __future__ import annotations

import os
import time
import jwt
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


# JWT lifetime — 5 min is plenty for a single Bijou backend call.
# We re-mint on every call rather than caching, so key rotation takes
# effect immediately without a process restart.
_TOKEN_LIFETIME_SECONDS = 300


def mint_service_token(
    *,
    service_name: str = "bijou-voice",
    scopes: Optional[list[str]] = None,
) -> str:
    """Return a short-lived JWT signed with BIJOU_API_KEY.

    The backend's auth layer verifies this token by re-computing the
    HMAC with the same shared secret. No asymmetric keys needed; we
    trust the network (voice + backend are in the same Coolify
    internal network) and the shared secret for the auth identity.
    """
    secret = os.environ.get("BIJOU_API_KEY", "").strip()
    if not secret:
        raise ValueError(
            "BIJOU_API_KEY not set — cannot mint service-to-service JWT"
        )
    now = int(time.time())
    payload = {
        "iss": service_name,
        "sub": service_name,
        "iat": now,
        "exp": now + _TOKEN_LIFETIME_SECONDS,
        "scope": " ".join(scopes or ["service:voice"]),
        "actor_type": "service",
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    logger.debug("🔐 minted service JWT (lifetime %ds, scopes=%s)", _TOKEN_LIFETIME_SECONDS, payload["scope"])
    return token


def build_auth_header() -> Dict[str, str]:
    """Return the {'Authorization': 'Bearer ...'} header for an outbound
    request to the Bijou backend. Convenience wrapper around
    `mint_service_token` for httpx callers.
    """
    return {"Authorization": f"Bearer {mint_service_token()}"}
