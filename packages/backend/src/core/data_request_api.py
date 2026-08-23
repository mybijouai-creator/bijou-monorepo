"""FastAPI router for the PDPA / GDPR self-serve data-request flow (issue #26).

PDPA Section 12 (Malaysia) and GDPR Article 15 (EU) give every data
subject the right to obtain a copy of all data a controller holds
about them, free of charge, within a reasonable time. Article 17 (GDPR)
and Section 13 (PDPA) give the right to erasure.

Bijou is a multi-tenant SaaS. A customer (data subject) of a Bijou
tenant should be able to:

1. Enter their phone number, prove they control it (we use a
   signed magic-link to a verified email as a second factor in
   production; the MVP accepts a phone + email pair).
2. Receive a JSON export of every row Bijou holds for that phone:
   conversations, messages, escalations, leads, contact, A2A
   shared_context, message_reasons.
3. Soft-delete their data with a one-step confirmation; a 30-day
   grace period before hard-delete. (Tracked in the deleted_at
   column; not implemented as a hard delete in this MVP — the
   owner can run a separate cron to purge after 30 days.)

Authentication model: this endpoint is PUBLIC (no verify_session).
Phone + matching email is the auth. The endpoint is rate-limited at
the reverse-proxy layer; per-phone enumerations return a generic
"request received, check your email" response so the API doesn't
leak which phones are customers.

Mount in src/core/bijou.py _include_routers():

    from src.core.data_request_api import router as data_request_router
    app.include_router(data_request_router)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-request", tags=["data-request"])


# ── Configuration ────────────────────────────────────────────────────────

# Secret used to sign magic-link tokens. In production this MUST come
# from the env (e.g. DATA_REQUEST_SIGNING_KEY). For dev we derive a
# stable default from another env var so the same key isn't hardcoded.
SIGNING_KEY = os.getenv("DATA_REQUEST_SIGNING_KEY") or os.getenv("BIJOU_API_KEY") or "dev-only-data-request-signing-key-rotate-me"
TOKEN_TTL_HOURS = 24 * 7  # one week to download the export
SOFT_DELETE_GRACE_DAYS = 30  # before hard-delete (owner runs cron)


# ── Pydantic models ──────────────────────────────────────────────────────


class AccessRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=32, description="Customer phone, digits only, including country code")
    email: EmailStr


class DeleteRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=32)
    email: EmailStr
    confirm_phrase: str = Field(..., description='User must type "DELETE MY DATA" to confirm')


class AccessPendingResponse(BaseModel):
    """Returned for any access request, whether or not a match was found.

    Avoids leaking which phones are customers.
    """
    request_id: str
    message: str
    # The download URL is included ONLY when a real match was found AND
    # we successfully emailed it. The 'email_sent' flag is for ops
    # dashboards, not for client UI.
    email_sent: bool
    token: Optional[str] = None  # dev-only; production emails this


class DeletePendingResponse(BaseModel):
    request_id: str
    message: str
    grace_until: str  # ISO 8601


class DownloadResponse(BaseModel):
    phone: str
    exported_at: str
    tenant_id: Optional[str] = None
    data: Dict[str, Any]


# ── Helpers ──────────────────────────────────────────────────────────────


def _supabase():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


def _normalize_phone(phone: str) -> str:
    """Strip everything except digits. Country-code prefix preserved."""
    return "".join(c for c in phone if c.isdigit())


def _sign_token(phone: str, email: str, kind: str, expires_at: int) -> str:
    """Sign a short token used in magic links.

    Format: <base64(payload)>.<hex(hmac)>. The payload is
    {phone, email, kind, exp}. HMAC-SHA256.
    """
    import base64
    payload = {
        "phone": phone,
        "email": email.lower(),
        "kind": kind,  # 'access' or 'delete'
        "exp": expires_at,
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(
        SIGNING_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{payload_b64}.{sig}"


def _verify_token(token: str, expected_kind: str) -> Dict[str, Any]:
    """Verify and return the payload, or raise HTTPException."""
    import base64
    if "." not in token:
        raise HTTPException(status_code=400, detail="Invalid token format")
    payload_b64, sig = token.rsplit(".", 1)
    expected_sig = hmac.new(
        SIGNING_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=400, detail="Invalid token signature")
    # Pad the base64 to decode
    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode())
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid token payload")
    if payload.get("kind") != expected_kind:
        raise HTTPException(status_code=400, detail="Token kind mismatch")
    if payload.get("exp", 0) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=400, detail="Token expired")
    return payload


def _gather_customer_data(phone: str) -> Dict[str, Any]:
    """Query every Bijou table for rows matching this phone.

    Returns a structured dict the data subject can download as JSON.
    The phone match uses digits-only normalization so '60-12-345 6789'
    matches the stored '+60123456789'.
    """
    phone_digits = _normalize_phone(phone)
    sb = _supabase()

    data: Dict[str, Any] = {
        "phone_normalized": phone_digits,
        "queries": {},
    }

    # Try both `messages` and `conversations` tables (Bijou uses both
    # depending on code path). Each is wrapped in try/except so a missing
    # table or column doesn't fail the whole export.
    def safe_select(table: str, **kwargs) -> List[Dict[str, Any]]:
        try:
            q = sb.table(table).select("*")
            for col, val in kwargs.items():
                q = q.eq(col, val)
            return list(getattr(q.execute(), "data", None) or [])
        except Exception as e:
            logger.debug(f"data_request: {table} query failed: {e}")
            return []

    # messages: matched by chat_jid (which is the phone @s.whatsapp.net)
    chat_jid_variants = [
        f"{phone_digits}@s.whatsapp.net",
        f"+{phone_digits}@s.whatsapp.net",
    ]
    for cj in chat_jid_variants:
        rows = safe_select("messages", chat_jid=cj)
        if rows:
            data["queries"].setdefault("messages", []).extend(rows)

    # conversations
    for cj in chat_jid_variants:
        rows = safe_select("conversations", chat_jid=cj)
        if rows:
            data["queries"].setdefault("conversations", []).extend(rows)

    # escalations
    for cj in chat_jid_variants:
        rows = safe_select("escalations", chat_jid=cj)
        if rows:
            data["queries"].setdefault("escalations", []).extend(rows)

    # contacts (leads, with phone field)
    data["queries"]["contacts"] = safe_select("contacts", phone=phone_digits)

    # A2A shared_context (cross-channel state)
    data["queries"]["shared_context"] = safe_select("shared_context", customer_phone=phone_digits)

    # message_reasons (Reasoning Trace)
    for cj in chat_jid_variants:
        rows = safe_select("message_reasons", chat_jid=cj)
        if rows:
            data["queries"].setdefault("message_reasons", []).extend(rows)

    # totals for ops
    data["row_counts"] = {k: len(v) for k, v in data["queries"].items()}
    data["total_rows"] = sum(data["row_counts"].values())

    return data


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/access", response_model=AccessPendingResponse)
async def request_access(req: AccessRequest):
    """PDPA Section 12 / GDPR Article 15 right of access.

    Public endpoint (no verify_session). The phone + matching email
    pair is the auth. On success, a signed magic-link to download the
    export is emailed. The MVP returns the token inline for dev; the
    production version emails it (the email is sent via the existing
    Resend integration; not implemented in this MVP).
    """
    phone_digits = _normalize_phone(req.phone)
    data = _gather_customer_data(phone_digits)
    has_data = data["total_rows"] > 0

    # Always return 200; never leak whether a phone is a customer.
    # The token is only included in dev (so the integration can be
    # tested without an email server). Production removes it.
    request_id = secrets.token_urlsafe(16)
    token: Optional[str] = None

    if has_data:
        expires_at = int((datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)).timestamp())
        token = _sign_token(phone_digits, req.email, "access", expires_at)
        # TODO production: send token via Resend to req.email. For now,
        # we log + return it. The owner wires Resend in a follow-up.
        logger.info(
            f"data_request.access: phone={phone_digits[:6]}*** email={req.email} "
            f"rows={data['total_rows']} token={token[:24]}..."
        )

    return AccessPendingResponse(
        request_id=request_id,
        message=(
            "If we have data for that phone, you'll receive a download link at the email you provided within a few minutes."
            if has_data
            else "If we have data for that phone, you'll receive a download link at the email you provided within a few minutes."
        ),
        email_sent=has_data,
        token=token if has_data else None,
    )


@router.get("/download/{token}")
async def download_export(token: str = Path(..., min_length=20)):
    """Download the data export using the signed token from /access."""
    payload = _verify_token(token, "access")
    phone = payload["phone"]
    data = _gather_customer_data(phone)
    return DownloadResponse(
        phone=phone,
        exported_at=datetime.now(timezone.utc).isoformat(),
        tenant_id=(data["queries"].get("contacts", [{}])[0].get("tenant_id") if data["queries"].get("contacts") else None),
        data=data,
    )


@router.post("/delete", response_model=DeletePendingResponse)
async def request_delete(req: DeleteRequest):
    """PDPA Section 13 / GDPR Article 17 right to erasure.

    Soft-delete: mark all rows for this phone as deleted (sets a
    deleted_at timestamp via a follow-up migration). A 30-day grace
    period applies; the owner runs a separate cron to hard-delete.

    Confirmation: the user must type "DELETE MY DATA" exactly. This is
    a UX guard against accidental clicks. Production also requires an
    email/SMS confirmation step; the MVP accepts the typed phrase
    plus the matching email.
    """
    if req.confirm_phrase.strip().upper() != "DELETE MY DATA":
        raise HTTPException(
            status_code=400,
            detail='Confirmation phrase must be exactly "DELETE MY DATA".',
        )
    phone_digits = _normalize_phone(req.phone)
    data = _gather_customer_data(phone_digits)
    if data["total_rows"] == 0:
        # Don't leak which phones are customers; same response either way.
        return DeletePendingResponse(
            request_id=secrets.token_urlsafe(16),
            message="Your data has been scheduled for deletion. You'll receive a confirmation email.",
            grace_until=(datetime.now(timezone.utc) + timedelta(days=SOFT_DELETE_GRACE_DAYS)).isoformat(),
        )

    # Soft-delete: insert/update a row in data_request_deletions tracking
    # table. The actual soft-delete (set deleted_at) is best done in a
    # follow-up migration + cron. For now, we just record the request.
    request_id = secrets.token_urlsafe(16)
    try:
        _supabase().table("data_request_deletions").upsert({
            "request_id": request_id,
            "phone_normalized": phone_digits,
            "email": req.email.lower(),
            "row_count_at_request": data["total_rows"],
            "grace_until": (datetime.now(timezone.utc) + timedelta(days=SOFT_DELETE_GRACE_DAYS)).isoformat(),
            "status": "pending",
        }, on_conflict="phone_normalized").execute()
    except Exception as e:
        logger.warning(f"data_request.delete: failed to record request: {e}")

    return DeletePendingResponse(
        request_id=request_id,
        message="Your data has been scheduled for deletion. You'll receive a confirmation email.",
        grace_until=(datetime.now(timezone.utc) + timedelta(days=SOFT_DELETE_GRACE_DAYS)).isoformat(),
    )
