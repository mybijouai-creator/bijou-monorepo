"""
Burst Manager - Human-style message chunking.
==============================================

Splits long LLM output into short "burst" chunks for natural-feeling delivery.
Supports [BREAK] token and sentence-based splitting.

FIXED: Keeps numbered/bulleted lists together, limits max bursts, enforces minimums.

Author: W3J Bijou Enterprise
"""

import re
from typing import List

# Token that LLM can emit to force a message break
BREAK_TOKEN = "[BREAK]"

# Absolute limits
# 2026-08-24: Tightened from 4 → 2 to stop the "3-7 tiny messages" problem.
# Real human WhatsApp agents almost never send more than 2 bubbles for one
# reply. If the customer types 3 quick messages, we still send ONE combined
# reply (the response_coordinator handles that consolidation BEFORE we
# even get to this layer). If the LLM really needs to break into 2 bubbles
# (e.g. answering two distinct questions), it can use [BREAK] explicitly.
MAX_BURSTS = 2
MIN_CHUNK_CHARS = 20  # Don't send tiny fragments — fold them into the previous bubble


def split_into_bursts(text: str, max_chunk_chars: int = 1000) -> List[str]:
    """
    Split text into short message chunks (bursts) for human-style delivery.

    NEW LOGIC:
    1. Cap at MAX_BURSTS (3) total messages - if longer, truncate or merge.
    2. Keep Markdown lists together (lines starting with *, -, 1., 2., etc.).
    3. Don't send tiny chunks (< MIN_CHUNK_CHARS unless it's emoji/short).
    4. Split by [BREAK] token first, then by paragraphs, then sentences.

    Args:
        text: Raw LLM output string.
        max_chunk_chars: Max characters per chunk (default 300 for WhatsApp).

    Returns:
        List of non-empty string chunks (max 3).
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    # PRIORITY 1: Split by [BREAK] token first
    # If LLM explicitly used [BREAK], honor it and return those chunks
    if "[BREAK]" in text.upper():
        raw_parts = re.split(r"\[BREAK\]", text, flags=re.IGNORECASE)
        chunks = [p.strip() for p in raw_parts if p.strip()]

        # Remove markdown if present
        chunks = [_strip_markdown(chunk) for chunk in chunks]

        # Cap at MAX_BURSTS
        if len(chunks) > MAX_BURSTS:
            chunks = chunks[:MAX_BURSTS]

        return chunks

    # PRIORITY 2: If text is short enough, return as-is
    if len(text) <= max_chunk_chars:
        return [_strip_markdown(text)]

    # PRIORITY 3: Split by double newlines (paragraphs)
    # This keeps numbered lists together (they use single newlines)
    segments = re.split(r"\n\s*\n", text)
    segments = [p.strip() for p in segments if p.strip()]

    chunks: List[str] = []

    for seg in segments:
        if len(seg) <= max_chunk_chars:
            chunks.append(seg)
            continue

        # Step 2: Try splitting by double newlines (paragraphs)
        paragraphs = re.split(r"\n\n+", seg)

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Check if this is a list block (multiple lines starting with *, -, 1., etc.)
            is_list_block = _is_list_block(para)

            if is_list_block:
                # Keep entire list together if possible
                if (
                    len(para) <= max_chunk_chars * 1.5
                ):  # Allow slightly longer for lists
                    chunks.append(para)
                    continue
                else:
                    # List is too long - split by list items but keep each item intact
                    list_items = _split_list_items(para)
                    current = ""
                    for item in list_items:
                        if len(current) + len(item) + 2 <= max_chunk_chars:
                            current = (
                                (current + "\n" + item).strip() if current else item
                            )
                        else:
                            if current:
                                chunks.append(current)
                            current = item
                    if current:
                        chunks.append(current)
                    continue

            # Not a list - split by sentences
            if len(para) <= max_chunk_chars:
                chunks.append(para)
                continue

            # Split by sentences
            sentences = re.split(r"(?<=[.!?])\s+", para)
            current = ""

            for sent in sentences:
                if not sent.strip():
                    continue

                if len(current) + len(sent) + 1 <= max_chunk_chars:
                    current = (current + " " + sent).strip() if current else sent
                else:
                    if current:
                        chunks.append(current)

                    # If single sentence is too long, split by chars
                    if len(sent) > max_chunk_chars:
                        remainder = sent
                        while len(remainder) > max_chunk_chars:
                            # Split at last space before max
                            break_at = remainder.rfind(" ", 0, max_chunk_chars + 1)
                            if break_at <= 0:
                                break_at = max_chunk_chars
                            chunks.append(remainder[:break_at].strip())
                            remainder = remainder[break_at:].strip()
                        current = remainder
                    else:
                        current = sent

            if current:
                chunks.append(current)

    # Step 3: Filter out tiny chunks (< MIN_CHUNK_CHARS) unless they're emoji/special
    filtered = []
    for chunk in chunks:
        if len(chunk) >= MIN_CHUNK_CHARS or _is_emoji_or_special(chunk):
            filtered.append(chunk)
        elif filtered:
            # Append tiny chunk to previous one
            filtered[-1] = filtered[-1] + " " + chunk

    # Step 4: Enforce MAX_BURSTS limit (merge excess into last chunk)
    if len(filtered) > MAX_BURSTS:
        # Keep first (MAX_BURSTS - 1) chunks, merge rest into last
        keep = filtered[: MAX_BURSTS - 1]
        merged_last = " ".join(filtered[MAX_BURSTS - 1 :])

        # If merged last is too long, truncate with ellipsis
        if len(merged_last) > max_chunk_chars * 2:
            merged_last = merged_last[: max_chunk_chars * 2 - 3] + "..."

        keep.append(merged_last)
        filtered = keep

    return [c for c in filtered if c]


def _is_list_block(text: str) -> bool:
    """
    Check if text is a list block (multiple lines starting with list markers).

    List markers:
    - Bullets: *, -, •
    - Numbers: 1., 2., 3., etc.
    - Checkboxes: [ ], [x], ✅, ❌
    """
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return False

    # Count how many lines start with list markers
    list_marker_pattern = r"^\s*(?:[*\-•]|\d+\.|\[[ xX]\]|[✅❌☑️])\s+"
    list_lines = sum(1 for line in lines if re.match(list_marker_pattern, line.strip()))

    # If more than 50% of lines are list items, it's a list block
    return list_lines >= len(lines) * 0.5


def _split_list_items(text: str) -> List[str]:
    """
    Split a list block into individual list items.

    Returns list of items, each starting with its marker.
    """
    lines = text.strip().split("\n")
    items = []
    current_item = ""

    list_marker_pattern = r"^\s*(?:[*\-•]|\d+\.|\[[ xX]\]|[✅❌☑️])\s+"

    for line in lines:
        if re.match(list_marker_pattern, line.strip()):
            # New list item
            if current_item:
                items.append(current_item.strip())
            current_item = line
        else:
            # Continuation of current item
            if current_item:
                current_item += "\n" + line
            else:
                # Not a list item, keep as-is
                current_item = line

    if current_item:
        items.append(current_item.strip())

    return items


def _is_emoji_or_special(text: str) -> bool:
    """
    Check if text is just emoji or special characters (allow short chunks).
    """
    text = text.strip()

    # Common emoji/special patterns
    if len(text) <= 5 and any(char in text for char in "😊👋🎉✅❌🔥💡🚀"):
        return True

    # Single emoji pattern
    emoji_pattern = r"^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251]+$"

    return bool(re.match(emoji_pattern, text))


def _strip_markdown(text: str) -> str:
    """
    Remove all markdown formatting from text.

    Removes: ** __ * _ ## ### `
    Keeps the text content only.
    """
    if not text:
        return text

    # Remove bold (**text** or __text__)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)

    # Remove italic (*text* or _text_)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)

    # Remove headers (### Header or ## Header)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Remove inline code (`code`)
    text = re.sub(r"`(.+?)`", r"\1", text)

    # Remove code blocks (```code```)
    text = re.sub(r"```[\s\S]*?```", "", text)

    return text.strip()
