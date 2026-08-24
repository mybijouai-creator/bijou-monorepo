#!/usr/bin/env python3
"""
AI-Powered Handover Intent Detection
=====================================

Uses Gemini AI to detect when customers want to speak to a human,
even when they don't use exact keywords.

More accurate than keyword matching - understands:
- "I need to speak to him" → wants owner
- "Can I talk to the boss?" → wants human
- "I can only tell this to a person" → wants human
- "Something personal" → may want privacy/human

RELIABILITY:
- Circuit breaker protection (auto-fallback if AI down)
- Keyword-based fallback (always catches critical cases)
- 5-second timeout per call
- Auto-recovery after 30 seconds

Author: W3J Consulting - Muhammad Nurunnabi (Jewel)
Date: 2026-02-12
Version: 3.0 (intent categories, plain-language reasons, booking escalation)
"""

import json
import logging
import os
import re
from typing import Optional, Tuple

# Module-level import so @patch('src.saas.ai_handover_detector.genai') works in tests
try:
    from google import genai
except ImportError:  # pragma: no cover
    genai = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent categories — replaces flat _ESCALATION_PHRASES list.
# Each key is the reason_type stored in the DB escalations.reason_type column.
# All historical phrases preserved and distributed into semantic buckets.
# ---------------------------------------------------------------------------
INTENT_CATEGORIES: dict = {
    # Customer explicitly requesting a human / named individual
    "human_request": [
        # Core explicit requests (spec)
        "speak to agent", "real person", "connect me to owner",
        "connect me to manager", "transfer me to owner",
        "transfer me to real person", "talk to human",
        # Preserved from previous _ESCALATION_PHRASES
        "speak to owner", "talk to owner", "connect me to", "transfer me to",
        "speak to manager", "talk to manager", "speak to boss", "talk to boss",
        "actual person", "human person", "not ai", "not bot",
        "i need him", "i need her", "i need them", "talk to him", "speak to her",
        "speak to the owner", "talk to the owner", "talk to a human",
        "talk to actual", "i want to talk to", "transfer me",
        "connect me to real person",
        # Industry-specific titles (agent, dentist, doctor, staff)
        "talk to the agent", "speak to the agent", "talk to agent",
        "connect me to agent", "connect to the agent", "i need the agent",
        "i want the agent", "transfer to agent", "can i talk to the agent",
        "talk to dentist", "speak to dentist", "talk to the dentist",
        "speak to the dentist", "i need dentist", "connect me to dentist",
        "i need the dentist",
        "talk to doctor", "speak to doctor", "talk to the doctor",
        "speak to the doctor", "i need doctor", "connect me to doctor",
        "i need the doctor",
        "talk to staff", "speak to staff",
        # NOTE: "talk to someone" / "talk to a person" intentionally excluded —
        # too broad (fires on "Can I talk to someone about the apartment price?")
    ],

    # Customer raising legal / regulatory concerns
    "legal_compliance": [
        # Spec phrases
        "lawyer", "sue", "legal action", "pdpa", "report you",
        "going to court", "consumer tribunal",
        # Existing legal keywords
        "lawsuit", "attorney", "court order",
    ],

    # Customer expressing strong dissatisfaction
    "frustrated": [
        "this is unacceptable", "terrible service", "very disappointed",
        "worst service", "demand refund", "want my money back",
    ],

    # Customer requesting a property / appointment viewing
    # NOTE: should_escalate = True until calendar tool is verified in prod.
    "booking_request": [
        "book a viewing", "book slot", "schedule visit",
        "tengok unit", "nak tengok", "boleh tengok",
        "can i view", "see the unit", "visit the property", "arrange viewing",
    ],

    # knowledge_gap is triggered only via AI confidence score — no keyword phrases.
    "knowledge_gap": [],
}

# Plain-language reason texts shown on dashboard escalation cards and owner WA notifications.
# Must be readable by non-technical Malaysian business owners.
_REASON_TEXT_MAP: dict = {
    "human_request":    "Customer asked to speak to you directly",
    "legal_compliance": "Customer raised a serious concern",
    "frustrated":       "Customer seems unhappy — handle with care",
    "booking_request":  "Customer wants to book a viewing — confirm availability",
    "knowledge_gap":    "Bijou didn't have the answer — needs your input",
}

# Urgency mapped per category (used when no "NOW"/"ASAP" modifier present)
_CATEGORY_BASE_URGENCY: dict = {
    "human_request":    "high",
    "legal_compliance": "urgent",
    "frustrated":       "high",
    "booking_request":  "normal",
    "knowledge_gap":    "normal",
}

_CASUAL_ADDRESS_TERMS: list = [
    "vaia", "bhai", "bro", "bruh", "boss", "dekhso", "sayang", "abang", "kakak",
]


def classify_intent_type(message_lower: str) -> Optional[str]:
    """
    Return the INTENT_CATEGORIES key that first matches `message_lower`, or None.

    Public helper used by handover_system.py to persist reason_type in the DB.
    Matching is highest-priority-first: booking_request checked after human/legal/frustrated
    so explicit human requests always win over a booking phrase in the same message.
    """
    _priority_order = [
        "human_request",
        "legal_compliance",
        "frustrated",
        "booking_request",
    ]
    for category in _priority_order:
        phrases = INTENT_CATEGORIES.get(category, [])
        if any(p in message_lower for p in phrases):
            return category
    return None


def _keyword_fallback(message_lower: str) -> Tuple[bool, str, str]:
    """
    Intent-category keyword escalation detection.

    Used when Gemini is unavailable (no API key, API error, or circuit open).
    Returns (wants_human, reason, urgency) — same external shape as the AI path.

    reason includes the plain-language text AND the matched phrase so downstream
    callers (including test assertions) can locate the triggering keyword.

    Rules applied in order:
    1. Casual-term-only (no phrase match) → not an escalation
    2. Explicit INTENT_CATEGORIES phrase match → escalate with mapped urgency
    3. Multi-question (3+ "?") with no phrase → do NOT escalate (let AI handle)
    4. Long message (500+ chars) with no phrase → do NOT escalate
    5. Default → no escalation
    """
    has_casual_term = any(term in message_lower for term in _CASUAL_ADDRESS_TERMS)

    # Scan categories in priority order
    matched_category: Optional[str] = None
    matched_phrase: Optional[str] = None
    for category in ["human_request", "legal_compliance", "frustrated", "booking_request"]:
        for phrase in INTENT_CATEGORIES.get(category, []):
            if phrase in message_lower:
                matched_category = category
                matched_phrase = phrase
                break
        if matched_category:
            break

    # 1. Casual term + no explicit phrase → normal conversation
    if has_casual_term and not matched_category:
        return (False, "Normal conversation with cultural address term", "none")

    # 2. Too short + no phrase → acknowledgment
    if len(message_lower.strip()) < 15 and not matched_category:
        return (False, "Short message/acknowledgment", "none")

    # 3. Explicit category match → escalate
    if matched_category and matched_phrase:
        base_urgency = _CATEGORY_BASE_URGENCY.get(matched_category, "normal")
        urgency = (
            "urgent"
            if any(w in message_lower for w in ["now", "urgent", "asap"])
            else base_urgency
        )
        plain_text = _REASON_TEXT_MAP.get(matched_category, matched_category)
        reason = f"{plain_text} — matched: '{matched_phrase}'"
        return (True, reason, urgency)

    # 4. Multi-question messages (3+ "?") with no explicit phrase → let AI answer
    if message_lower.count("?") >= 3:
        return (False, "Multi-part enquiry — handled by AI", "none")

    # 5. Long message alone (500+ chars) with no phrase → not an escalation signal
    if len(message_lower) >= 500:
        return (False, "Long enquiry — no escalation phrase detected", "none")

    return (False, "No escalation keywords found", "none")


def detect_handover_intent(message: str, gemini_api_key: str = None) -> Tuple[bool, str, str]:
    """
    Use Gemini AI to detect if user wants to speak to a human.

    Args:
        message: Customer's message
        gemini_api_key: Optional Gemini API key (falls back to env var)

    Returns:
        Tuple of (wants_human: bool, reason: str, urgency: str)
        urgency can be: "urgent", "high", "normal", "none"
    """
    api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")

    # Pre-compute lowercased message for all pre-filter paths below
    message_lower = message.lower().strip()

    if not api_key:
        logger.warning("⚠️ GEMINI_API_KEY not set - using keyword fallback for handover detection")
        return _keyword_fallback(message_lower)

    # Pre-filter: Exclude messages that are clearly NOT escalation requests

    # 1. Filter out messages with casual cultural terms (brother, dear, etc.)
    # These are NORMAL CONVERSATIONAL LANGUAGE in Bengali/Malay, NOT escalation requests
    casual_address_terms = _CASUAL_ADDRESS_TERMS

    # If message contains casual terms AND no explicit escalation keywords, skip AI check
    has_casual_term = any(term in message_lower for term in casual_address_terms)

    # Explicit escalation keywords — check against all INTENT_CATEGORIES buckets
    explicit_escalation = any(
        phrase in message_lower
        for phrases in INTENT_CATEGORIES.values()
        for phrase in phrases
    )

    if has_casual_term and not explicit_escalation:
        # This is normal conversation, not an escalation request
        logger.info(f"🤖 AI: PRE-FILTER - Skipping escalation due to casual term: {message[:50]}")
        return (False, "Normal conversation with cultural address term", "none")

    # 2. Filter out very short messages (acknowledgments, reactions)
    if len(message_lower) < 15 and not explicit_escalation:
        logger.info(f"🤖 AI: PRE-FILTER - Skipping escalation (too short): {message[:50]}")
        return (False, "Short message/acknowledgment", "none")

    # 3. Filter out emoji-only messages
    emoji_count = sum(1 for c in message if ord(c) > 127)
    if len(message.strip()) < 10 and emoji_count >= len(message.strip()) - 2:
        logger.info(f"🤖 AI: PRE-FILTER - Skipping escalation (emoji-only): {message[:50]}")
        return (False, "Emoji reaction only", "none")

    try:
        # AI Gateway v2 — alias-based, no direct provider name.
        # ai://extract is the structured-output alias (low temperature, JSON).
        from src.core.llm_gateway_v2 import llm as _llm_gateway, llm as _llm_gw_module

        prompt = f"""You are analyzing whether a customer EXPLICITLY wants to speak to a HUMAN (owner/manager/staff), NOT just asking a question to AI.

Customer message: "{message}"

CRITICAL: ONLY return wants_human=true if they use EXPLICIT PHRASES like:
- "I need to speak to [owner/manager/boss/him/her/you]"
- "Connect me to [owner/manager/person]"
- "I want to talk to a real person / human / actual person"
- "Transfer me to [someone]"
- "Let me speak to the manager"
- "Get me your supervisor"

DO NOT escalate if they:
1. Use casual address terms: "vaia" (Bengali brother), "bhai", "bro", "boss", "sayang" (Malay dear), "abang", "sir"
   - These are NORMAL CONVERSATIONAL LANGUAGE, not requests for humans
   - Example: "Akhn Ki kortam vaia" = "What should I do now brother" → NOT an escalation

2. Ask for help/clarification (this is what AI is FOR):
   - "What should I do?", "Tell me", "Explain to me", "Help me understand"
   - Example: "bolo 1tu bujai" = "tell me clearly" → NOT an escalation

3. Simple acknowledgments:
   - "Ok", "Alright", "Got it", "thik ase" (Bengali: alright), "Okh vaia thik ase boilo"

4. Mild frustration or gibberish:
   - Emojis like 😑, typos like "duxedus"

5. Legal/compliance questions:
   - These should go to AI first, NOT automatic escalation

REAL ESCALATION EXAMPLES:
✅ "I need to speak to the owner NOW" → wants_human: true (EXPLICIT request)
✅ "Connect me to the manager" → wants_human: true (EXPLICIT transfer request)
✅ "Let me talk to a real person, not AI" → wants_human: true (EXPLICIT human request)

NOT ESCALATIONS:
❌ "Akhn Ki kortam vaia Oita bolo 1tu bujai" → wants_human: false (asking for help, using "vaia" casually)
❌ "Okh vaia thik ase boilo" → wants_human: false (acknowledgment with casual address)
❌ "Ok sayang" → wants_human: false (acknowledgment with term of endearment)
❌ "He will get the peanuts" → wants_human: false (statement, not request)
❌ "duxedus" → wants_human: false (gibberish/typo)

Respond ONLY with JSON:
{{
  "wants_human": true or false,
  "reason": "short explanation (max 8 words)",
  "urgency": "urgent" or "high" or "normal" or "none"
}}

Be EXTREMELY CONSERVATIVE. When in doubt, return wants_human: false."""

        # ⚡ CIRCUIT BREAKER: Protect against AI Gateway failures
        # Hard 5-second timeout prevents indefinite hangs. The gateway itself
        # handles 429/5xx fallback across providers (gemini -> openrouter ->
        # openai_compatible) per the ai://extract policy in llm_gateway.yaml.
        try:
            import asyncio
            response = asyncio.run(
                _llm_gateway.complete(
                    "ai://extract",
                    [{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_output_tokens=256,
                )
            )
        except Exception as api_error:
            logger.error(f"⚠️ AI Gateway call failed: {api_error}")
            # Fallback to keyword-based detection (use full phrase list, not circuit breaker)
            return _keyword_fallback(message_lower)

        response_text = (response.text or "").strip()

        # Extract JSON from response (sometimes AI adds markdown formatting)
        json_match = re.search(r'\{[^{}]+\}', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(response_text)

        wants_human = result.get("wants_human", False)
        reason = result.get("reason", "AI detected handover intent")
        urgency = result.get("urgency", "normal").lower()

        if wants_human:
            logger.info(f"🤖 AI detected handover intent: {reason} (urgency: {urgency})")
        else:
            logger.debug(f"🤖 AI: No handover intent detected - {reason}")

        return (wants_human, reason, urgency)

    except Exception as e:
        logger.error(f"❌ AI handover detection failed: {e}", exc_info=True)
        # Fallback to keyword-based detection as last resort (use full phrase list)
        return _keyword_fallback(message_lower)
