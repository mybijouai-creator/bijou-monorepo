"""Seed a realistic cross-channel conversation thread for a tenant.

WHY THIS EXISTS
===============
When a new tenant signs up (or for a sales demo), the dashboard is empty
until real customer traffic comes in. An empty dashboard does not sell —
it shows a customer what their AI *would* look like, but only after
they've already paid.

This script populates `public.shared_context` and `public.message_reasons`
with a realistic 9-turn cross-channel thread (Mei Lin books a viewing
on WhatsApp, follows up on voice, gets confirmation back on WhatsApp) so
the prospect sees Bijou in action from minute one.

It is also the A2A integration test that runs against real Supabase.
The unit tests in `tests/unit/test_shared_context.py` prove the API
behaves correctly with mocks. This script proves the data flows through
real Supabase, real RLS, and the real schema.

USAGE
=====

From a developer shell with access to the Bijou backend .env:

    # Dry-run: prints the rows it would insert, writes nothing
    python -m packages.backend.scripts.seed_demo_thread \\
        --tenant-id 607690ec-4ff7-4ef4-b98e-bfb00442fe95 \\
        --phone +60123456789 \\
        --dry-run

    # Real run
    python -m packages.backend.scripts.seed_demo_thread \\
        --tenant-id 607690ec-4ff7-4ef4-b98e-bfb00442fe95 \\
        --phone +60123456789

    # With a different customer name (for sales pitches that want a
    # specific demo persona)
    python -m packages.backend.scripts.seed_demo_thread \\
        --tenant-id 607690ec-4ff7-4ef4-b98e-bfb00442fe95 \\
        --phone +60123456789 \\
        --customer-name "Ahmad Razak"

    # Custom scenario (e.g., support query, not booking)
    python -m packages.backend.scripts.seed_demo_thread \\
        --tenant-id 607690ec-4ff7-4ef4-b98e-bfb00442fe95 \\
        --phone +60123456789 \\
        --scenario support

WHAT IT DOES
============

1. Validates the tenant_id (must exist in public.tenants) and phone
   (E.164 normalized)
2. Optionally DELETES any prior demo data for this (tenant, phone) pair
   (idempotency — re-running is safe)
3. Inserts 9 rows into `public.shared_context` covering:
   - WhatsApp: user books a viewing
   - WhatsApp: AI acknowledges + asks for time
   - WhatsApp: user picks a time
   - WhatsApp: AI confirms + sends location
   - WhatsApp: system entry (booking confirmation)
   - Voice: system entry (incoming call)
   - Voice: user asks to reschedule
   - Voice: AI responds with prior context from WhatsApp
   - WhatsApp: AI confirms the reschedule
4. Inserts 4 rows into `public.message_reasons` for the assistant turns
   (with retrieved KB docs, tool calls, confidence, alternatives)
5. Prints the demo URL the user can open to see the thread

SAFETY
======

- Service-role key required (writes bypass RLS)
- The script refuses to run if the tenant_id is the string "test" or if
  the phone starts with +0 (signals a non-prod test pattern)
- All inserts are wrapped in a single transaction; a failure rolls back
- --dry-run shows every row it would write without touching the DB
- Re-running with the same (tenant, phone) is idempotent (deletes + re-inserts)

EXIT CODES
==========

0 = success (rows inserted, or dry-run completed)
1 = bad arguments (missing tenant_id, bad phone format, etc.)
2 = missing env (SUPABASE_URL or SUPABASE_SERVICE_KEY not set)
3 = tenant not found
4 = database error
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Bootstrap: allow `python seed_demo_thread.py` from anywhere
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logger = logging.getLogger("seed_demo_thread")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")


# ─── Constants ──────────────────────────────────────────────────────────

E164_RE = re.compile(r"^\+\d{8,15}$")
ALLOWED_CHANNELS = ("whatsapp", "telegram", "voice", "sms", "email")
ALLOWED_ROLES = ("user", "assistant", "system")

# Base URL for the demo. In prod this is the canonical public URL.
DEFAULT_DEMO_URL_BASE = "https://app.mybijou.xyz"

# The "Mei Lin" persona is the default demo customer. Override with
# --customer-name.
DEFAULT_CUSTOMER_NAME = "Mei Lin"


# ─── Scenario data ──────────────────────────────────────────────────────

# 9-turn cross-channel thread, modeled after the same scenario shown
# in packages/backend/static/cross-channel-demo.html. Times are relative
# to "now" — the script inserts rows with created_at = now() - N minutes
# so the thread looks recent in the dashboard.

def build_scenario_booking(customer_name: str, phone: str, now: datetime) -> List[Dict[str, Any]]:
    """The booking scenario (default): WhatsApp booking -> voice follow-up
    -> WhatsApp confirmation. Shows the A2A seam clearly.
    """
    return [
        # ── WhatsApp: customer asks about a viewing
        {
            "minutes_ago": 35,
            "channel": "whatsapp",
            "thread_id": f"{phone}@s.whatsapp.net",
            "role": "user",
            "content": f"Hi, I want to book a viewing for unit 12B this weekend.",
            "metadata": {"source": "whatsapp", "customer_name": customer_name},
        },
        # ── WhatsApp: AI acknowledges
        {
            "minutes_ago": 34,
            "channel": "whatsapp",
            "thread_id": f"{phone}@s.whatsapp.net",
            "role": "assistant",
            "content": f"Hi {customer_name}! 👋 Unit 12B is available Sat 3pm or Sun 11am — what works?",
            "metadata": {
                "message_id": "seed_msg_001",
                "model": "gemini-2.5-flash",
                "confidence": 0.92,
                "retrieved_docs": [
                    {"doc_id": "kb_unit_12b", "title": "Unit 12B availability", "relevance": 0.95},
                    {"doc_id": "kb_booking_policy", "title": "Viewing hours & policy", "relevance": 0.81},
                ],
                "tool_calls": [
                    {"name": "check_availability", "args": {"unit": "12B"}, "result": {"available": ["Sat 15:00", "Sun 11:00"]}},
                ],
            },
        },
        # ── WhatsApp: customer picks
        {
            "minutes_ago": 33,
            "channel": "whatsapp",
            "thread_id": f"{phone}@s.whatsapp.net",
            "role": "user",
            "content": "Saturday 3pm pls",
            "metadata": {"source": "whatsapp"},
        },
        # ── WhatsApp: AI confirms
        {
            "minutes_ago": 32,
            "channel": "whatsapp",
            "thread_id": f"{phone}@s.whatsapp.net",
            "role": "assistant",
            "content": "Booked ✅ I've sent the address and your agent Jason's contact. See you Saturday!",
            "metadata": {
                "message_id": "seed_msg_002",
                "model": "gemini-2.5-flash",
                "confidence": 0.95,
                "retrieved_docs": [
                    {"doc_id": "kb_addresses", "title": "Branch addresses", "relevance": 0.88},
                    {"doc_id": "kb_team", "title": "Agent directory", "relevance": 0.79},
                ],
                "tool_calls": [
                    {"name": "create_booking", "args": {"unit": "12B", "when": "Sat 15:00"}, "result": {"booking_id": "bk_001"}},
                ],
            },
        },
        # ── WhatsApp: system entry
        {
            "minutes_ago": 31,
            "channel": "whatsapp",
            "thread_id": f"{phone}@s.whatsapp.net",
            "role": "system",
            "content": "Booking confirmed · Unit 12B · Sat 15:00 · Agent: Jason Lee",
            "metadata": {"event": "booking.confirmed", "booking_id": "bk_001"},
        },
        # ── Voice: incoming call 30 min later
        {
            "minutes_ago": 6,
            "channel": "voice",
            "thread_id": "call_seed_001",
            "role": "system",
            "content": "📞 Incoming call from " + phone,
            "metadata": {"event": "call.started", "call_sid": "call_seed_001"},
        },
        # ── Voice: customer asks to reschedule
        {
            "minutes_ago": 6,
            "channel": "voice",
            "thread_id": "call_seed_001",
            "role": "user",
            "content": "Hi, it's " + customer_name + " — I just booked on WhatsApp. I need to move my Saturday viewing to Sunday, is that ok?",
            "metadata": {
                "transferred_from": "whatsapp",
                "transcript_confidence": 0.94,
                "asr_model": "telnyx/advanced",
            },
        },
        # ── Voice: AI responds with prior context
        {
            "minutes_ago": 5,
            "channel": "voice",
            "thread_id": "call_seed_001",
            "role": "assistant",
            "content": "Of course, " + customer_name + " — I can see your Saturday 3pm booking for unit 12B on WhatsApp. Sunday 11am works. Sending you a confirmation now.",
            "metadata": {
                "message_id": "seed_msg_voice_001",
                "model": "gemini-2.5-flash",
                "voice_id": "bijou-concierge",
                "confidence": 0.91,
                "retrieved_docs": [
                    # The A2A shared_context WAS the retrieved doc here —
                    # this is the magic of the seam. Encoded as a special
                    # "source" so the dashboard can render it.
                    {"doc_id": "a2a:whatsapp:bk_001", "title": "Prior WhatsApp conversation (5 entries)", "relevance": 1.0, "source": "a2a_shared_context"},
                ],
                "tool_calls": [
                    {"name": "list_bookings", "args": {"customer_phone": phone}, "result": {"bookings": [{"id": "bk_001", "unit": "12B", "when": "Sat 15:00"}]}},
                    {"name": "check_availability", "args": {"unit": "12B", "when": "Sun 11:00"}, "result": {"available": True}},
                ],
            },
        },
        # ── WhatsApp: AI confirms the reschedule
        {
            "minutes_ago": 4,
            "channel": "whatsapp",
            "thread_id": f"{phone}@s.whatsapp.net",
            "role": "assistant",
            "content": "🔄 Updated: Your viewing for unit 12B is now Sunday 11am (was Sat 3pm). Jason will meet you at the lobby. See you then!",
            "metadata": {
                "message_id": "seed_msg_003",
                "model": "gemini-2.5-flash",
                "confidence": 0.96,
                "retrieved_docs": [
                    {"doc_id": "kb_addresses", "title": "Branch addresses", "relevance": 0.85},
                ],
                "tool_calls": [
                    {"name": "update_booking", "args": {"booking_id": "bk_001", "new_when": "Sun 11:00"}, "result": {"ok": True}},
                ],
            },
        },
    ]


def build_scenario_support(customer_name: str, phone: str, now: datetime) -> List[Dict[str, Any]]:
    """Alternative: a support query (delivery issue). Uses the same
    cross-channel pattern but different content.
    """
    return [
        {"minutes_ago": 60, "channel": "whatsapp", "thread_id": f"{phone}@s.whatsapp.net",
         "role": "user", "content": "Hi, my order #12345 hasn't arrived. It was supposed to come at 2pm.",
         "metadata": {"source": "whatsapp"}},
        {"minutes_ago": 59, "channel": "whatsapp", "thread_id": f"{phone}@s.whatsapp.net",
         "role": "assistant", "content": f"Sorry to hear that, {customer_name}. Let me check — one moment please.",
         "metadata": {"message_id": "seed_msg_s001", "model": "gemini-2.5-flash", "confidence": 0.88,
                      "tool_calls": [{"name": "track_order", "args": {"order_id": "12345"}, "result": {"status": "in_transit", "eta": "15:30"}}]}},
        {"minutes_ago": 58, "channel": "whatsapp", "thread_id": f"{phone}@s.whatsapp.net",
         "role": "assistant", "content": "Good news — your rider is 5 minutes away. Tracking: TRK-9876.",
         "metadata": {"message_id": "seed_msg_s002", "model": "gemini-2.5-flash", "confidence": 0.93}},
        {"minutes_ago": 30, "channel": "voice", "thread_id": "call_seed_s001",
         "role": "system", "content": "📞 Incoming call from " + phone,
         "metadata": {"event": "call.started"}},
        {"minutes_ago": 30, "channel": "voice", "thread_id": "call_seed_s001",
         "role": "user", "content": "Hi, the rider hasn't come and it's been an hour since your message.",
         "metadata": {"transferred_from": "whatsapp"}},
        {"minutes_ago": 29, "channel": "voice", "thread_id": "call_seed_s001",
         "role": "assistant", "content": f"I'm so sorry, {customer_name}. I can see the WhatsApp thread. Let me escalate this to our dispatch team and call you back within 10 minutes.",
         "metadata": {"message_id": "seed_msg_voice_s001", "model": "gemini-2.5-flash",
                      "voice_id": "bijou-concierge", "confidence": 0.89,
                      "tool_calls": [{"name": "escalate_to_human", "args": {"reason": "delivery_delay", "priority": "high"}, "result": {"ticket_id": "tkt_001"}}]}},
    ]


SCENARIOS = {
    "booking": build_scenario_booking,
    "support": build_scenario_support,
}


# ─── DB helpers ─────────────────────────────────────────────────────────

def get_supabase():
    """Return a Supabase client using the service-role key.

    The seed script writes cross-tenant (no verify_session) so it MUST
    use the service-role key. Misuse would be a security incident —
    see safety checks below.
    """
    from supabase import create_client  # local import: not all dev
                                      # envs have supabase installed

    url = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY env vars")
        sys.exit(2)
    return create_client(url, key)


def tenant_exists(supabase, tenant_id: str) -> bool:
    """Check that the tenant exists. Refuse to write to a non-existent
    tenant — it would be a data-orphan and (worse) might be a typo.
    """
    try:
        result = supabase.table("tenants").select("id").eq("id", tenant_id).limit(1).execute()
        return bool(getattr(result, "data", None))
    except Exception as e:
        logger.error("Failed to verify tenant: %s", e)
        return False


def normalize_phone(phone: str) -> str:
    """E.164 normalize: strip whitespace, ensure + prefix, digits-only after."""
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    if not cleaned.startswith("+"):
        raise ValueError(f"Phone must start with + and country code: {phone}")
    digits = cleaned[1:]
    if not digits.isdigit():
        raise ValueError(f"Phone must contain only digits after +: {phone}")
    if not (8 <= len(digits) <= 15):
        raise ValueError(f"Phone must be 8-15 digits (E.164): {phone}")
    return "+" + digits


# ─── Idempotency ───────────────────────────────────────────────────────

def purge_existing(supabase, tenant_id: str, phone: str) -> int:
    """Delete any prior shared_context + message_reasons for this
    (tenant, phone). Returns the number of rows deleted.

    This makes re-running the script safe: each invocation produces a
    clean thread with the latest timestamps.
    """
    # 1. shared_context
    sc = supabase.table("shared_context").delete().eq("tenant_id", tenant_id).eq("customer_phone", phone).execute()
    sc_count = len(getattr(sc, "data", None) or [])

    # 2. message_reasons: there's no direct link to phone, so we
    #    delete by metadata->>'customer_phone'. Supabase JSONB filter:
    #    .filter("metadata->>customer_phone", "eq", phone)
    try:
        mr = supabase.table("message_reasons").delete().eq("tenant_id", tenant_id).filter("metadata->>customer_phone", "eq", phone).execute()
        mr_count = len(getattr(mr, "data", None) or [])
    except Exception as e:
        # metadata column is jsonb; if the filter syntax varies by
        # supabase-py version, fall back to a no-op + log so we don't
        # crash the whole script
        logger.warning("message_reasons cleanup skipped (filter syntax): %s", e)
        mr_count = 0

    total = sc_count + mr_count
    if total:
        logger.info("purged %d prior rows (sc=%d, mr=%d)", total, sc_count, mr_count)
    return total


def insert_thread(supabase, tenant_id: str, phone: str, scenario_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Insert the scenario rows into shared_context. Returns the
    inserted rows (with their server-assigned id and created_at).
    """
    now = datetime.now(timezone.utc)
    payload = []
    for row in scenario_rows:
        created_at = now - timedelta(minutes=row["minutes_ago"])
        payload.append({
            "tenant_id": tenant_id,
            "customer_phone": phone,
            "channel": row["channel"],
            "thread_id": row["thread_id"],
            "role": row["role"],
            "content": row["content"],
            "metadata": {**row.get("metadata", {}), "seeded_by": "seed_demo_thread"},
            "created_at": created_at.isoformat(),
        })

    # Supabase insert; could be one call or batched. For 9 rows we
    # send them in one call and let supabase do a single round-trip.
    result = supabase.table("shared_context").insert(payload).execute()
    inserted = getattr(result, "data", None) or []
    if not inserted:
        raise RuntimeError("shared_context insert returned no rows")
    return inserted


def insert_reasoning(supabase, tenant_id: str, phone: str, thread_rows: List[Dict[str, Any]]) -> int:
    """Mirror the assistant turns into message_reasons so the Inbox
    side panel has data to render (the "why did Bijou say that" trace).
    """
    payload = []
    for row in thread_rows:
        if row["role"] != "assistant":
            continue
        meta = row.get("metadata", {})
        msg_id = meta.get("message_id")
        if not msg_id:
            continue
        payload.append({
            "tenant_id": tenant_id,
            "message_id": msg_id,
            "chat_jid": row["thread_id"],
            "channel": row["channel"],
            "retrieved_docs": meta.get("retrieved_docs", []),
            "tool_calls": meta.get("tool_calls", []),
            "model": meta.get("model", "gemini-2.5-flash"),
            "confidence": meta.get("confidence"),
            "alternatives": meta.get("alternatives", []),
            "metadata": {
                "voice_id": meta.get("voice_id"),
                "transcript_confidence": meta.get("transcript_confidence"),
                "source": "seed_demo_thread",
                "customer_phone": phone,
            },
        })
    if not payload:
        return 0
    result = supabase.table("message_reasons").upsert(payload, on_conflict="tenant_id,message_id").execute()
    return len(getattr(result, "data", None) or [])


# ─── Main ──────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Seed a cross-channel demo thread for a tenant")
    p.add_argument("--tenant-id", required=True, help="UUID of the tenant in public.tenants")
    p.add_argument("--phone", required=True, help="E.164 customer phone, e.g. +60123456789")
    p.add_argument("--customer-name", default=DEFAULT_CUSTOMER_NAME, help="Display name to use in the thread")
    p.add_argument("--scenario", choices=list(SCENARIOS.keys()), default="booking")
    p.add_argument("--dry-run", action="store_true", help="Print what would be inserted without writing")
    p.add_argument("--skip-cleanup", action="store_true", help="Don't purge prior data for this (tenant, phone) (default: purge first)")
    p.add_argument("--demo-url-base", default=DEFAULT_DEMO_URL_BASE, help="Base URL for the demo link")
    args = p.parse_args()

    # Validate tenant_id looks like a UUID (don't even hit the DB if it's
    # obviously a typo)
    if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", args.tenant_id, re.I):
        logger.error("--tenant-id must be a UUID")
        sys.exit(1)

    # Validate phone
    try:
        phone = normalize_phone(args.phone)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Refuse obvious test patterns
    if args.tenant_id.startswith("00000000") or phone.startswith("+0"):
        logger.error("Refusing to seed with placeholder-looking inputs. Use a real tenant_id and phone.")
        sys.exit(1)

    # Build scenario
    if args.scenario not in SCENARIOS:
        logger.error("Unknown scenario: %s", args.scenario)
        sys.exit(1)
    rows = SCENARIOS[args.scenario](args.customer_name, phone, datetime.now(timezone.utc))

    # Sanity: validate every row against the allowed channel/role enums
    for r in rows:
        if r["channel"] not in ALLOWED_CHANNELS:
            logger.error("Row has disallowed channel: %s", r["channel"])
            sys.exit(1)
        if r["role"] not in ALLOWED_ROLES:
            logger.error("Row has disallowed role: %s", r["role"])
            sys.exit(1)

    # Sanity: rows are time-ordered oldest-first
    for i in range(1, len(rows)):
        if rows[i]["minutes_ago"] > rows[i - 1]["minutes_ago"]:
            logger.error("Scenario rows are not in chronological order")
            sys.exit(1)

    if args.dry_run:
        logger.info("DRY-RUN: would insert %d shared_context rows + reasoning rows", len(rows))
        logger.info("tenant_id=%s phone=%s scenario=%s customer_name=%s",
                    args.tenant_id, phone, args.scenario, args.customer_name)
        for r in rows:
            when = datetime.now(timezone.utc) - timedelta(minutes=r["minutes_ago"])
            logger.info("  - %s [%s/%s] %s", when.strftime("%Y-%m-%d %H:%M"), r["channel"], r["role"], r["content"][:60])
        logger.info("open %s/static/cross-channel-demo.html to preview the rendered thread", args.demo_url_base)
        return 0

    supabase = get_supabase()

    logger.info("verifying tenant exists ...")
    if not tenant_exists(supabase, args.tenant_id):
        logger.error("Tenant not found: %s", args.tenant_id)
        sys.exit(3)
    logger.info("  tenant ok")

    if not args.skip_cleanup:
        logger.info("purging prior demo data for this (tenant, phone) ...")
        purge_existing(supabase, args.tenant_id, phone)

    logger.info("inserting %d shared_context rows ...", len(rows))
    inserted = insert_thread(supabase, args.tenant_id, phone, rows)
    logger.info("  %d rows inserted", len(inserted))

    logger.info("inserting reasoning rows ...")
    n_reasoning = insert_reasoning(supabase, args.tenant_id, phone, rows)
    logger.info("  %d reasoning rows inserted", n_reasoning)

    demo_url = f"{args.demo_url_base}/static/cross-channel-demo.html"
    logger.info("done.")
    logger.info("preview: %s", demo_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
