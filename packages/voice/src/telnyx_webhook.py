"""Telnyx webhook receiver — STUB.

Real implementation lands after the voice service is deployed + a real
Telnyx phone number is bound. For now this file just defines the
expected webhook shape + a 200 OK no-op so the FastAPI app boots.

Webhook contract (Telnyx Call Control v2):

  POST /webhook/telnyx/{tenant_phone}
  Headers:
    Telnyx-Signature: t=<unix_ts>,v1=<hmac_sha256(telnyx_api_key, "<unix_ts>|<raw_body>")>
  Body (JSON):
    {
      "data": {
        "event_type": "call.initiated" | "call.answered" | "call.gather.ended"
                     | "call.speak.ended" | "call.dtmf" | "call.hangup",
        "payload": {
          "call_control_id": "v3:abc123",
          "from": "+60174106981",
          "to": "+60123456789",
          "direction": "incoming",
          "state": "answered",
          ...
        }
      },
      "meta": { "attempt": 1, "delivered_to": "https://..." }
    }
"""
from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Depends, Header
from fastapi.responses import JSONResponse

from .tenant_config import get_tenant_config_client, TenantConfig
from .shared_context import get_shared_context_client
from .orchestrator import VoiceOrchestrator, CallContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/telnyx", tags=["voice"])


@router.post("/{tenant_phone}")
async def handle_telnyx_event(
    tenant_phone: str,
    request: Request,
    telnyx_signature: Optional[str] = Header(None, alias="Telnyx-Signature"),
):
    """Receive a Telnyx voice webhook. STUB: returns 200 OK without
    processing. Real implementation verifies the HMAC, resolves the
    tenant from `tenant_phone`, and dispatches to the orchestrator.
    """
    body = await request.body()
    logger.info(
        "📞 telnyx webhook for %s, sig=%s, bytes=%d (STUB: not processing yet)",
        tenant_phone, (telnyx_signature or "<none>")[:40], len(body),
    )
    # TODO: verify HMAC, parse event, dispatch to orchestrator
    return JSONResponse({"ok": True, "stub": True})


@router.get("/_health")
async def webhook_health():
    """Diagnostic endpoint so Coolify's healthcheck can hit the webhook
    subtree without firing the signature check."""
    return {"ok": True, "service": "bijou-voice", "stub": True}
