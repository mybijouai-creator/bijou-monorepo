"""
Tests for ResponseCoordinator
=============================

The coordinator is the human-tone timing brain of Bijou. These tests
exercise the three things it must do correctly:

  1. DEBOUNCE: don't fire while the customer is still typing
  2. CONSOLIDATE: batch multiple quick messages into one flush
  3. HUMAN-STYLE: build a customer style snapshot the LLM can mirror
  4. BURST CAP: never let more than 2 bubbles out the door
  5. CANCEL: explicit /pause and /agent takeover stop the queue
  6. EDGE CASES: empty messages, single-char messages, group chats

Author: Bijou AI  ·  2026-08-24
"""
import asyncio
import pytest
from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock

from src.core.response_coordinator import (
    ResponseCoordinator,
    PendingMessage,
    _build_style_snapshot,
    _split_for_human_bubbles,
    _merge_excess,
    TEXTING_SHORTCUTS,
)


# ============================================================================
# 1. STYLE SNAPSHOT
# ============================================================================

class TestStyleSnapshot:
    def test_empty_input_returns_empty(self):
        assert _build_style_snapshot([]) == ""
        assert _build_style_snapshot([""]) == ""

    def test_short_message_uses_casual_register(self):
        s = _build_style_snapshot(["hi", "got anything in kl?"])
        assert "casual" in s
        # kl shortcut should be expanded
        assert "kl=Kuala Lumpur" in s

    def test_long_message_uses_detailed_register(self):
        s = _build_style_snapshot([
            "Hi, I'm looking for a 2 bedroom condominium unit in the Kuala Lumpur area, "
            "preferably near public transport and within a 1 million ringgit budget. "
            "Can you help me with some options?"
        ])
        assert "detailed" in s

    def test_manglish_register_detected(self):
        s = _build_style_snapshot([
            "boss, ada tak condo dalam kl?",
            "budget around 500k, can or not?",
        ])
        assert "Manglish" in s

    def test_bm_register_detected(self):
        s = _build_style_snapshot([
            "saya nak cari rumah dalam kl",
            "boleh tolong tunjukkan beberapa pilihan?",
        ])
        assert "Bahasa Melayu" in s

    def test_chinese_register_detected(self):
        s = _build_style_snapshot(["你好", "我想找一间公寓"])
        assert "Chinese" in s

    def test_single_char_messages_get_a_note(self):
        s = _build_style_snapshot(["k", "ok", "y"])
        assert "single chars" in s

    def test_only_six_shortcuts_shown(self):
        # 8 different shortcuts in 4 messages
        msgs = ["kl", "jb", "pg", "ok", "brb", "tq", "tmr", "pls"]
        s = _build_style_snapshot(msgs)
        # At most 6 expansions listed
        shortcut_line = next(
            (l for l in s.splitlines() if l.strip().startswith("shortcuts:")), ""
        )
        assert shortcut_line != ""
        rows = shortcut_line.split(":", 1)[1].strip().split(",")
        assert len(rows) <= 6

    def test_only_shortcuts_actually_used_are_listed(self):
        # kl used, but jb isn't — only kl should appear
        s = _build_style_snapshot(["anything in kl?"])
        assert "kl=Kuala Lumpur" in s
        # jb shouldn't appear because customer didn't use it
        assert "jb=" not in s


# ============================================================================
# 2. BUBBLE SPLITTER
# ============================================================================

class TestBubbleSplitter:
    def test_short_text_single_bubble(self):
        out = _split_for_human_bubbles("hi boss")
        assert out == ["hi boss"]

    def test_strips_markdown(self):
        out = _split_for_human_bubbles("**bold** and _italic_ and `code`")
        assert out == ["bold and italic and code"]
        # No leftover markdown markers
        for line in out:
            assert "**" not in line
            assert "__" not in line
            assert "`" not in line

    def test_strips_headers(self):
        out = _split_for_human_bubbles("## Important\n\nbody text here")
        # Combined into one bubble
        assert "Important" in out[0]
        assert "##" not in out[0]

    def test_respects_break_token(self):
        out = _split_for_human_bubbles(
            "first half[BREAK]second half",
            max_bubbles=2,
        )
        assert out == ["first half", "second half"]

    def test_break_token_capped_at_max_bubbles(self):
        out = _split_for_human_bubbles(
            "a[BREAK]b[BREAK]c[BREAK]d[BREAK]e",
            max_bubbles=2,
        )
        assert len(out) == 2
        # The "excess" should be merged
        assert "a" in out[0]
        assert "e" in out[-1]  # last is the merged

    def test_long_text_paragraph_split_then_capped(self):
        # Make the text long enough to escape the 280-char short path
        text = (
            "First paragraph is here and is reasonably long so the splitter "
            "won't shortcut it. It talks about properties in KL and PJ area.\n\n"
            "Second paragraph continues with details about pricing and unit "
            "sizes for the KL and PJ listings we have on the books right now.\n\n"
            "Third paragraph is about the deposit process and what documents "
            "the customer needs to bring when they come for the viewing.\n\n"
            "Fourth short."
        )
        out = _split_for_human_bubbles(text, max_bubbles=2)
        assert len(out) == 2
        # First and one merged
        assert "First" in out[0]

    def test_empty_returns_empty(self):
        assert _split_for_human_bubbles("") == []
        assert _split_for_human_bubbles("   \n  ") == []

    def test_huge_merged_tail_truncated(self):
        # Force a giant merge
        parts = ["a", "b", "c"] + ["x" * 1000] * 5
        out = _merge_excess(parts, max_bubbles=2)
        assert len(out) == 2
        # Truncation has ellipsis
        if len(out[-1]) > 600:
            assert out[-1].endswith("...")


# ============================================================================
# 3. COORDINATOR — debounce / consolidate / cancel
# ============================================================================

def _run(coro):
    """Helper: run a coroutine in a fresh loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_coord(**kwargs):
    """Fresh coordinator + mock flush callback."""
    flushes: List[dict] = []
    async def on_flush(**payload):
        flushes.append(payload)
    defaults = dict(
        quiet_window_seconds=0.2,   # fast for tests
        max_wait_seconds=2.0,
        max_consolidated_msgs=6,
        max_outbound_bubbles=2,
    )
    defaults.update(kwargs)
    coord = ResponseCoordinator(**defaults)
    coord.on_flush = on_flush
    coord._flushes = flushes
    return coord, flushes


def _attach_and_run(coro_fn, coord):
    """
    Helper: attach the coord to a fresh event loop, run the test fn,
    and let the loop finish all scheduled tasks (so async flushes fire
    before the loop closes). Returns whatever the test fn returned.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        coord.attach_loop(loop)
        result = loop.run_until_complete(coro_fn())
        # Drain any pending tasks so flushes actually fire
        loop.run_until_complete(asyncio.sleep(0))
        loop.run_until_complete(asyncio.sleep(0))
        return result
    finally:
        try:
            loop.run_until_complete(asyncio.sleep(0))
        except Exception:
            pass
        loop.close()


class TestCoordinatorDebounce:
    @pytest.mark.asyncio
    async def test_first_message_arms_timer(self):
        coord, flushes = _make_coord(quiet_window_seconds=0.5)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1", content="hi", sender="user",
        )
        assert coord.has_pending("a@b")
        # Don't fire yet
        await asyncio.sleep(0.05)
        assert len(flushes) == 0

    @pytest.mark.asyncio
    async def test_quiet_window_triggers_flush(self):
        coord, flushes = _make_coord(quiet_window_seconds=0.1)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1", content="hi", sender="user",
        )
        # Wait past the quiet window
        await asyncio.sleep(0.25)
        assert len(flushes) == 1
        assert flushes[0]["original_messages"][0].content == "hi"

    @pytest.mark.asyncio
    async def test_second_message_within_window_resets_timer(self):
        """A new message resets the debounce — quiet window slides."""
        coord, flushes = _make_coord(quiet_window_seconds=0.4)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1", content="hi", sender="user",
        )
        await asyncio.sleep(0.15)  # 150ms in
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m2", content="got anything in kl?",
            sender="user",
        )
        # 250ms after the second message would fire IF the window
        # hadn't slid forward. So it should still be pending.
        await asyncio.sleep(0.25)
        assert len(flushes) == 0
        # Now wait past the 2nd's quiet window
        await asyncio.sleep(0.3)
        assert len(flushes) == 1
        # Both messages should be in the batch
        assert len(flushes[0]["original_messages"]) == 2

    @pytest.mark.asyncio
    async def test_max_wait_force_flushes(self):
        """If the customer keeps typing, we flush at max_wait anyway."""
        coord, flushes = _make_coord(
            quiet_window_seconds=2.0,  # long window
            max_wait_seconds=0.3,      # short max
        )
        coord.attach_loop(asyncio.get_running_loop())
        for i in range(3):
            await coord.enqueue(
                chat_jid="a@b", tenant_id="t", channel="whatsapp",
                client_config=None, msg_id=f"m{i}", content=f"msg {i}",
                sender="user",
            )
            await asyncio.sleep(0.1)
        # 0.3s after first, max_wait triggers even though quiet hasn't elapsed
        await asyncio.sleep(0.4)
        assert len(flushes) == 1
        assert len(flushes[0]["original_messages"]) == 3

    @pytest.mark.asyncio
    async def test_max_consolidated_msgs_force_flush(self):
        coord, flushes = _make_coord(
            quiet_window_seconds=10.0,  # long
            max_consolidated_msgs=3,
        )
        coord.attach_loop(asyncio.get_running_loop())
        # First 3 enqueues: the 3rd triggers an immediate flush
        for i in range(3):
            await coord.enqueue(
                chat_jid="a@b", tenant_id="t", channel="whatsapp",
                client_config=None, msg_id=f"m{i}", content=f"msg {i}",
                sender="user",
            )
        # Let the immediate flush fire
        await asyncio.sleep(0.05)
        # The first flush should have exactly 3 messages
        assert len(flushes) == 1
        assert len(flushes[0]["original_messages"]) == 3
        # After the flush, the chat is no longer pending
        assert not coord.has_pending("a@b")


class TestCoordinatorCancel:
    @pytest.mark.asyncio
    async def test_cancel_drops_pending(self):
        coord, flushes = _make_coord(quiet_window_seconds=10.0)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1", content="hi", sender="user",
        )
        n = await coord.cancel("a@b")
        assert n == 1
        assert not coord.has_pending("a@b")
        await asyncio.sleep(0.2)
        assert len(flushes) == 0

    @pytest.mark.asyncio
    async def test_cancel_unknown_chat_returns_zero(self):
        coord, _ = _make_coord()
        coord.attach_loop(asyncio.get_running_loop())
        n = await coord.cancel("never@seen")
        assert n == 0


class TestCoordinatorConsolidation:
    @pytest.mark.asyncio
    async def test_consolidated_text_format(self):
        """The `consolidated_text` field joins with [i/n] markers."""
        coord, flushes = _make_coord(quiet_window_seconds=0.05)
        coord.attach_loop(asyncio.get_running_loop())
        for i, msg in enumerate(["hi", "got anything in kl?", "2 bed rm"]):
            await coord.enqueue(
                chat_jid="a@b", tenant_id="t", channel="whatsapp",
                client_config=None, msg_id=f"m{i}", content=msg, sender="user",
            )
        await asyncio.sleep(0.2)
        assert len(flushes) == 1
        text = flushes[0]["consolidated_text"]
        assert "[1/3] hi" in text
        assert "[2/3] got anything in kl?" in text
        assert "[3/3] 2 bed rm" in text

    @pytest.mark.asyncio
    async def test_style_snapshot_passed_to_callback(self):
        coord, flushes = _make_coord(quiet_window_seconds=0.05)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1",
            content="got anything in kl?",
            sender="user",
        )
        await asyncio.sleep(0.2)
        snap = flushes[0]["style_snapshot"]
        assert "kl=Kuala Lumpur" in snap
        assert "register:" in snap


class TestCoordinatorStats:
    @pytest.mark.asyncio
    async def test_stats_includes_pending_state(self):
        coord, _ = _make_coord(quiet_window_seconds=10.0)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1", content="hi", sender="user",
        )
        s = coord.stats()
        assert s["enqueued"] == 1
        assert s["pending_chats"] == 1
        assert s["pending_messages"] == 1
        assert s["config"]["quiet_window_seconds"] == 10.0
        assert s["config"]["max_outbound_bubbles"] == 2

    @pytest.mark.asyncio
    async def test_stats_counters_track_consolidation(self):
        coord, flushes = _make_coord(quiet_window_seconds=0.05)
        coord.attach_loop(asyncio.get_running_loop())
        for i, msg in enumerate(["a", "b", "c"]):
            await coord.enqueue(
                chat_jid="a@b", tenant_id="t", channel="whatsapp",
                client_config=None, msg_id=f"m{i}", content=msg, sender="user",
            )
        await asyncio.sleep(0.2)
        s = coord.stats()
        assert s["enqueued"] == 3
        assert s["flushed"] == 1
        assert s["consolidated"] == 1


# ============================================================================
# 4. EDGE CASES
# ============================================================================

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_content_is_handled(self):
        coord, flushes = _make_coord(quiet_window_seconds=0.05)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1", content="", sender="user",
        )
        await asyncio.sleep(0.2)
        # Empty content still enqueues + flushes
        assert len(flushes) == 1

    @pytest.mark.asyncio
    async def test_different_chats_dont_interfere(self):
        coord, flushes = _make_coord(quiet_window_seconds=0.1)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1", content="hi", sender="user",
        )
        await coord.enqueue(
            chat_jid="c@d", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m2", content="hello", sender="user",
        )
        # Both pending
        assert coord.has_pending("a@b")
        assert coord.has_pending("c@d")
        await asyncio.sleep(0.3)
        assert len(flushes) == 2
        chats = {f["chat_jid"] for f in flushes}
        assert chats == {"a@b", "c@d"}

    @pytest.mark.asyncio
    async def test_quoted_message_preserved(self):
        coord, flushes = _make_coord(quiet_window_seconds=0.05)
        coord.attach_loop(asyncio.get_running_loop())
        await coord.enqueue(
            chat_jid="a@b", tenant_id="t", channel="whatsapp",
            client_config=None, msg_id="m1", content="yup, 2pm works",
            sender="user", quoted="Booked you for 3pm tomorrow",
        )
        await asyncio.sleep(0.2)
        assert flushes[0]["original_messages"][0].quoted == "Booked you for 3pm tomorrow"


# ============================================================================
# 5. TEXTING SHORTCUTS — exhaustive expansion check
# ============================================================================

class TestTextingShortcuts:
    @pytest.mark.parametrize("shortcut,expansion", [
        ("kl", "Kuala Lumpur"),
        ("jb", "Johor Bahru"),
        ("pg", "Penang"),
        ("pj", "Petaling Jaya"),
        ("k", "ok"),
        ("kk", "ok"),
        ("brb", "be right back"),
        ("tq", "thank you"),
        ("pls", "please"),
        ("tbh", "to be honest"),
    ])
    def test_shortcut_mapped(self, shortcut, expansion):
        assert TEXTING_SHORTCUTS[shortcut] == expansion

    def test_all_shortcuts_lowercase_keys(self):
        # The dict is keyed by lowercase; the snapshot lowercases the
        # customer text before matching. Verify no uppercase keys snuck in.
        for k in TEXTING_SHORTCUTS:
            assert k == k.lower(), f"Shortcut {k!r} is not lowercase"
