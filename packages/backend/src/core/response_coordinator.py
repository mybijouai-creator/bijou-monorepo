"""
Bijou Response Coordinator
==========================

Single source of truth for WHEN Bijou replies and HOW it shapes the reply.

Solves the three problems that made Bijou feel "like another AI":

  1. **Replies to every single message.** Real human agents wait for the
     customer to finish typing before they reply. We do the same: each
     inbound message enqueues a draft, and the coordinator waits for a
     quiet window (default 8s) before flushing the draft to the LLM.

  2. **3-7 tiny messages per reply.** The LLM is told to write
     paragraph-style answers; the burst manager then splits them into
     200-char WhatsApp bubbles. Customers hate this — it floods the chat
     and makes the AI obvious. We cap the final outbound at 2 messages
     total, and we tell the LLM to write short, single-bubble replies by
     default (one-shot answers; multi-bubble only if the user asked
     multiple distinct questions).

  3. **Doesn't match the customer's texting style.** If a customer types
     "kl" we should know they mean Kuala Lumpur. If they say "k", that's
     acknowledgement, not the letter. We feed the LLM a "customer style
     snapshot" with the last 5 inbound messages decoded: the average
     length, the language register (formal/casual/Manglish), common
     shortcuts, and explicit expansions of any kl/jb/penang/ok/k/brb
     style shortcuts. The LLM mirrors that style.

Design contract
---------------

The coordinator is a single instance per Bijou process. It owns a
`pending` dict keyed by `chat_jid`:

    pending[chat_jid] = {
        "messages":       [ {msg_id, content, sender, ts, quoted}, ... ],
        "first_received": datetime,
        "last_received":  datetime,
        "tenant_id":      str,
        "channel":        str,
        "client_config":  dict | None,
        "flush_at":       datetime | None,   # set when debounce timer armed
        "task":           asyncio.Task | None,
    }

`enqueue()` appends to the list, cancels any pending flush task, and
arms a new one. The flush task waits `QUIET_WINDOW_SECONDS` and then
calls the LLM once with the consolidated context.

If a new message arrives while we're waiting, we extend the timer
(sliding window). If a new message arrives after the LLM call has
started, we accept that this reply only covers what we had at flush
time — the next message will trigger a fresh flush.

We never sleep more than `MAX_WAIT_SECONDS` total before flushing,
even if the user keeps typing. This prevents ghosting on an active
chat. Default: 35s.

Public API
----------

    coordinator = ResponseCoordinator(
        quiet_window_seconds   = 8.0,
        max_wait_seconds       = 35.0,
        max_consolidated_msgs  = 6,
        max_outbound_bubbles   = 2,
    )
    await coordinator.enqueue(...)
    await coordinator.flush_now(chat_jid)       # for /agent takeover
    await coordinator.cancel(chat_jid)           # for explicit /pause
    stats = coordinator.stats()                  # for health endpoint

Wiring
------

In `bijou.py:process_message`, replace the immediate
`self._send_response_human_burst(...)` call with
`await self.response_coordinator.enqueue(...)`. The coordinator
internally calls back into the LLM + send path with the consolidated
context.

Author: Bijou AI
Date: 2026-08-24
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Malaysian / SEA texting shortcut expansions
# ---------------------------------------------------------------------------
# Used in two places:
#   1. The "customer style snapshot" the LLM sees (so it understands
#      shortcuts without having to guess).
#   2. The outbound reply — if the customer used a shortcut and the
#      LLM produces verbose expansion, we leave the LLM output alone
#      (the LLM is told to mirror, not to expand). The snapshot is just
#      context.
#
# Keep this list short and obvious. Adding every slang phrase makes the
# prompt noisy; the LLM already knows the common ones from pretraining.

TEXTING_SHORTCUTS: Dict[str, str] = {
    # Malaysian state / city shortcuts
    "kl":   "Kuala Lumpur",
    "pj":   "Petaling Jaya",
    "jb":   "Johor Bahru",
    "pg":   "Penang",
    "penang": "Penang",
    "kk":   "Kota Kinabalu",
    "sbh":  "Sabah",
    "swk":  "Sarawak",
    "sel":  "Selangor",
    "n9":   "Negeri Sembilan",
    "msia": "Malaysia",
    "my":   "Malaysia",
    "sg":   "Singapore",
    "s'pore": "Singapore",
    "spore":  "Singapore",
    "id":   "Indonesia",
    "th":   "Thailand",
    "ph":   "Philippines",
    # Acknowledgements
    "k":   "ok",
    "kk":  "ok",
    "oky": "ok",
    "okie": "ok",
    "ok":  "ok",
    "oke": "ok",
    "okeh": "ok",
    "ok2": "ok",
    "noted": "ok",
    "nt":  "noted",
    "np":  "no problem",
    "nvm": "never mind",
    # Time
    "brb":  "be right back",
    "bbl":  "be back later",
    "afk":  "away from keyboard",
    "ttyl": "talk to you later",
    "ttys": "talk to you soon",
    "asap": "as soon as possible",
    "lmk":  "let me know",
    "fyi":  "for your information",
    # Affirmative
    "y":     "yes",
    "ya":    "yes",
    "yup":   "yes",
    "yesh":  "yes",
    "yea":   "yes",
    "yeap":  "yes",
    "ya lah": "yes lah",
    "yep":   "yes",
    # Negative
    "n":     "no",
    "nd":    "no",
    "tdy":   "today",
    "tmr":   "tomorrow",
    "tmrw":  "tomorrow",
    "mlm":   "malem (tonight)",
    # Greetings
    "gm":   "good morning",
    "gn":   "good night",
    "tq":   "thank you",
    "ty":   "thank you",
    "tysm": "thank you so much",
    "pls":  "please",
    "plz":  "please",
    # Question starters
    "cmi":  "cannot make it",
    "tp":   "tapi (but)",
    "jk":   "just kidding",
    "lol":  "laughing out loud",
    "omg":  "oh my god",
    "wtf":  "what the f***",
    "tbh":  "to be honest",
    "imo":  "in my opinion",
    "imho": "in my humble opinion",
}


# ---------------------------------------------------------------------------
# Pending message
# ---------------------------------------------------------------------------

@dataclass
class PendingMessage:
    msg_id:    str
    content:   str
    sender:    str
    received_at: datetime
    quoted:    Optional[str] = None  # the text of the message this replies to
    media_type: Optional[str] = None
    media_url:  Optional[str] = None


@dataclass
class PendingConversation:
    chat_jid:      str
    tenant_id:     str
    channel:       str
    client_config: Optional[dict]
    messages:      List[PendingMessage] = field(default_factory=list)
    first_received: Optional[datetime] = None
    last_received:  Optional[datetime] = None
    last_customer_text: str = ""
    flush_task:    Optional[asyncio.Task] = None
    in_flight:     bool = False  # True while the LLM call is running


# ---------------------------------------------------------------------------
# Style snapshot
# ---------------------------------------------------------------------------

def _build_style_snapshot(recent_messages: List[str]) -> str:
    """
    Build a compact "customer style" hint for the LLM.

    Looks at the last ~5 messages from the customer and infers:
      - average length (chars)
      - dominant language register
      - common shortcuts they used
      - expanded meaning of any non-obvious shortcuts

    This is prepended to the LLM call as a system hint so it can mirror
    the customer. We DO NOT touch the user's text — we just tell the LLM
    what the customer is doing.
    """
    if not recent_messages:
        return ""

    sample = [m for m in recent_messages if m and m.strip()][-5:]
    if not sample:
        return ""

    avg_len = sum(len(m) for m in sample) / max(1, len(sample))
    max_len = max(len(m) for m in sample)
    min_len = min(len(m) for m in sample)

    # Find shortcuts actually used in the customer's recent messages
    used_shortcuts: Dict[str, str] = {}
    for m in sample:
        words = re.findall(r"[a-zA-Z']+", m.lower())
        for w in words:
            if w in TEXTING_SHORTCUTS and w not in used_shortcuts:
                used_shortcuts[w] = TEXTING_SHORTCUTS[w]

    # Detect register from signal words
    manglish_markers = sum(
        1 for m in sample
        if re.search(r"\b(boss|lah|lor|mah|leh|ala|weh|kak|abang)\b", m, re.I)
    )
    bm_markers = sum(
        1 for m in sample
        if re.search(r"\b(boleh|nak|mahu|saya|awak|anda|skrg|tgh)\b", m, re.I)
    )
    cn_markers = sum(1 for m in sample if re.search(r"[\u4e00-\u9fff]", m))
    ta_markers = sum(1 for m in sample if re.search(r"[\u0b80-\u0bff]", m))
    formality = "casual" if avg_len < 25 else "neutral" if avg_len < 80 else "detailed"

    lines = [
        "[Customer style snapshot — mirror this]",
        f"  msgs:        {len(sample)} recent",
        f"  avg_length:  {avg_len:.0f} chars (min {min_len}, max {max_len})",
        f"  register:    {formality}",
    ]
    if manglish_markers:
        lines.append(f"  language:    Manglish ({manglish_markers}/{len(sample)} msgs use lah/lor/boss)")
    elif bm_markers:
        lines.append(f"  language:    Bahasa Melayu")
    elif cn_markers:
        lines.append(f"  language:    Chinese ({cn_markers} msgs with CJK)")
    elif ta_markers:
        lines.append(f"  language:    Tamil ({ta_markers} msgs with Tamil script)")
    else:
        lines.append(f"  language:    English (mirror the customer's exact tone)")

    if used_shortcuts:
        # Show up to 6 expansions; the LLM already knows common ones but
        # we spell them out so it doesn't guess wrong on rare ones.
        rows = ", ".join(
            f"{k}={v}" for k, v in list(used_shortcuts.items())[:6]
        )
        lines.append(f"  shortcuts:   {rows}")

    if min_len <= 2:
        lines.append("  note:        customer is sending single chars (k, n, y) — treat as ack, not as questions to answer")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Burst finalizer — turn an LLM answer into 1-2 WhatsApp bubbles
# ---------------------------------------------------------------------------

def _split_for_human_bubbles(text: str, max_bubbles: int = 2) -> List[str]:
    """
    Final-stage splitter: take the LLM's full answer and turn it into
    AT MOST `max_bubbles` WhatsApp bubbles. The LLM has already been
    told to write short, so this is the safety net.

    Strategy:
      1. If `text` already has a [BREAK] token, honor it (LLM asked for it).
      2. If short enough, return as single bubble.
      3. If too long, split at the strongest natural boundary (newline,
         sentence, comma) and keep the first piece as-is if it carries
         the load (e.g. is longer than the rest).
      4. Never produce more than `max_bubbles` bubbles — merge the rest.
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    # Strip any markdown noise the LLM might leak (in the [BREAK] path too)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    if "[BREAK]" in text.upper():
        parts = re.split(r"\[BREAK\]", text, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) > max_bubbles:
            return _merge_excess(parts, max_bubbles)
        return parts

    # Strip any markdown noise the LLM might leak
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    if len(text) <= 280:
        return [text]

    # Try splitting by double newlines (paragraph boundary)
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if len(paragraphs) <= max_bubbles:
        return paragraphs

    # Too many paragraphs — merge excess into the last
    return _merge_excess(paragraphs, max_bubbles)


def _merge_excess(parts: List[str], max_bubbles: int) -> List[str]:
    """Keep the first (max_bubbles - 1) parts, merge the rest."""
    if len(parts) <= max_bubbles:
        return parts
    keep = parts[: max_bubbles - 1]
    merged = " ".join(parts[max_bubbles - 1 :])
    # If the merged last is still very long, truncate with an ellipsis
    if len(merged) > 600:
        merged = merged[:597] + "..."
    keep.append(merged)
    return keep


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class ResponseCoordinator:
    """
    Owns the "when do we reply" decision for every chat Bijou is in.

    See module docstring for the design contract.
    """

    def __init__(
        self,
        quiet_window_seconds: float = 8.0,
        max_wait_seconds:     float = 35.0,
        max_consolidated_msgs: int = 6,
        max_outbound_bubbles:  int = 2,
        on_flush: Optional[Callable[..., Awaitable[None]]] = None,
    ):
        self.quiet_window  = quiet_window_seconds
        self.max_wait      = max_wait_seconds
        self.max_msgs      = max_consolidated_msgs
        self.max_bubbles   = max_outbound_bubbles

        # `on_flush` is the async callback that does the actual LLM call
        # + send. It receives a single dict: {
        #   chat_jid, tenant_id, channel, client_config,
        #   consolidated_text,   # newline-joined customer messages
        #   style_snapshot,      # the customer style hint
        #   bubbles,             # post-split (max 2)
        #   original_messages,   # list of PendingMessage
        # }
        # and is responsible for calling send_message with each bubble.
        self.on_flush = on_flush

        self._pending: Dict[str, PendingConversation] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Stats for /api/self-test
        self._stats = {
            "enqueued":  0,
            "flushed":   0,
            "cancelled": 0,
            "consolidated": 0,  # flushes where > 1 message was combined
        }

    # -- public API ---------------------------------------------------------

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind to the event loop. Must be called before enqueue() in
        async contexts that aren't running on the main loop yet."""
        self._loop = loop

    async def enqueue(
        self,
        *,
        chat_jid:      str,
        tenant_id:     str,
        channel:       str,
        client_config: Optional[dict],
        msg_id:        str,
        content:       str,
        sender:        str,
        quoted:        Optional[str] = None,
        media_type:    Optional[str] = None,
        media_url:     Optional[str] = None,
    ) -> None:
        """
        Add an inbound message to the chat's pending batch.

        - If a flush is already scheduled for this chat, the timer is
          reset (sliding quiet window).
        - If the batch is already at max_consolidated_msgs, we flush
          immediately rather than dropping the message.
        - If a flush is currently in flight (LLM call running), we
          enqueue this message and arm a fresh timer for after the
          current flush completes.
        """
        now = datetime.now(timezone.utc)
        if chat_jid not in self._pending:
            self._pending[chat_jid] = PendingConversation(
                chat_jid=chat_jid,
                tenant_id=tenant_id,
                channel=channel,
                client_config=client_config,
            )
        conv = self._pending[chat_jid]
        # Update tenant_id/channel if they changed (shouldn't, but safe)
        conv.tenant_id = tenant_id
        conv.channel   = channel
        if client_config is not None:
            conv.client_config = client_config

        conv.messages.append(PendingMessage(
            msg_id=msg_id, content=content or "", sender=sender,
            received_at=now, quoted=quoted, media_type=media_type,
            media_url=media_url,
        ))
        if conv.first_received is None:
            conv.first_received = now
        conv.last_received = now
        if content:
            conv.last_customer_text = content

        self._stats["enqueued"] += 1
        logger.info(
            f"📥 enqueued chat={chat_jid} batch={len(conv.messages)} "
            f"idle_for={(now - conv.last_received).total_seconds():.1f}s"
        )

        # If the batch is full, flush now
        if len(conv.messages) >= self.max_msgs:
            await self._arm_flush(conv, immediate=True)
            return

        # Otherwise arm (or re-arm) the quiet-window timer
        await self._arm_flush(conv, immediate=False)

    async def flush_now(self, chat_jid: str) -> None:
        """Force an immediate flush. Used by /agent takeover and tests."""
        conv = self._pending.get(chat_jid)
        if not conv or not conv.messages:
            return
        await self._do_flush(conv)

    async def cancel(self, chat_jid: str) -> int:
        """
        Cancel any pending flush for this chat. Returns the number of
        pending messages dropped (0 if nothing was pending).
        """
        conv = self._pending.get(chat_jid)
        if not conv:
            return 0
        n = len(conv.messages)
        if conv.flush_task and not conv.flush_task.done():
            conv.flush_task.cancel()
        self._pending.pop(chat_jid, None)
        if n:
            self._stats["cancelled"] += 1
        return n

    def stats(self) -> dict:
        """Snapshot of coordinator state for the /api/self-test endpoint."""
        return {
            **self._stats,
            "pending_chats": len(self._pending),
            "pending_messages": sum(
                len(c.messages) for c in self._pending.values()
            ),
            "in_flight_chats": sum(
                1 for c in self._pending.values() if c.in_flight
            ),
            "config": {
                "quiet_window_seconds": self.quiet_window,
                "max_wait_seconds":     self.max_wait,
                "max_consolidated_msgs": self.max_msgs,
                "max_outbound_bubbles": self.max_bubbles,
            },
        }

    def has_pending(self, chat_jid: str) -> bool:
        """True if a flush is already scheduled for this chat."""
        conv = self._pending.get(chat_jid)
        if not conv:
            return False
        return bool(conv.flush_task and not conv.flush_task.done())

    # -- internals ----------------------------------------------------------

    async def _arm_flush(
        self, conv: PendingConversation, immediate: bool = False
    ) -> None:
        """Schedule (or reschedule) the flush task for this chat."""
        # Cancel any existing pending task
        if conv.flush_task and not conv.flush_task.done():
            conv.flush_task.cancel()
            try:
                await conv.flush_task
            except (asyncio.CancelledError, Exception):
                pass

        if immediate:
            delay = 0
        else:
            # Sliding quiet window: how long since last message?
            idle_for = (datetime.now(timezone.utc) - conv.last_received).total_seconds()
            delay = max(0, self.quiet_window - idle_for)
            # Cap by max_wait
            total_wait = (datetime.now(timezone.utc) - conv.first_received).total_seconds() + delay
            if total_wait > self.max_wait:
                delay = max(0, self.max_wait - (datetime.now(timezone.utc) - conv.first_received).total_seconds())

        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.get_event_loop()

        conv.flush_task = self._loop.create_task(
            self._delayed_flush(conv, delay),
            name=f"bijou-flush-{conv.chat_jid}",
        )

    async def _delayed_flush(
        self, conv: PendingConversation, delay: float
    ) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            # Re-check the conversation is still pending us
            current = self._pending.get(conv.chat_jid)
            if current is not conv:
                return  # superseded by a cancel()
            if not conv.messages:
                return
            await self._do_flush(conv)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"❌ flush task crashed for {conv.chat_jid}: {e}")

    async def _do_flush(self, conv: PendingConversation) -> None:
        """Take the pending batch and run it through the LLM."""
        if conv.in_flight:
            logger.info(f"⏳ flush already in flight for {conv.chat_jid}, will reschedule")
            await self._arm_flush(conv, immediate=False)
            return

        conv.in_flight = True
        try:
            # Snapshot the messages, then clear
            batch = list(conv.messages)
            if not batch:
                return
            self._pending.pop(conv.chat_jid, None)

            n = len(batch)
            if n > 1:
                self._stats["consolidated"] += 1
            self._stats["flushed"] += 1

            # Build consolidated context
            consolidated = "\n".join(
                f"[{i+1}/{n}] {m.content}" + (f" (replying to: {m.quoted})" if m.quoted else "")
                for i, m in enumerate(batch)
            )
            style_snapshot = _build_style_snapshot([m.content for m in batch])

            logger.info(
                f"📤 flushing chat={conv.chat_jid} batch={n} "
                f"first_to_last={ (batch[-1].received_at - batch[0].received_at).total_seconds():.1f}s"
            )

            if self.on_flush is None:
                logger.warning("ResponseCoordinator.on_flush not wired — dropping batch")
                return

            await self.on_flush(
                chat_jid=conv.chat_jid,
                tenant_id=conv.tenant_id,
                channel=conv.channel,
                client_config=conv.client_config,
                consolidated_text=consolidated,
                style_snapshot=style_snapshot,
                original_messages=batch,
            )
        finally:
            conv.in_flight = False
            conv.flush_task = None


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_coordinator: Optional[ResponseCoordinator] = None


def get_coordinator() -> ResponseCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = ResponseCoordinator()
    return _coordinator
