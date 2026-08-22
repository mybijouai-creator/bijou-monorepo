#!/usr/bin/env python3
"""
Bijou Outreach Template Engine
================================
Provides industry-aware AI outreach capabilities:
  - validate_csv()            → parse + validate uploaded lead CSVs
  - enrich_contact()          → auto-fill missing fields from industry intelligence
  - build_generation_context()→ construct Gemini prompt for outreach message
  - generate_message()        → call Gemini, return generated message string
  - score_reply()             → score inbound reply against qualification signals
  - generate_reveal_message() → generate persona-switch reveal message
  - list_industry_packs()     → return metadata for all built-in industry packs

Called by:
  outreach_api.py → start_campaign() ONLY (at queue-build time, not send time)
  outreach_scheduler.py → handle_incoming_reply() for scoring

NOT called by:
  outreach_scheduler.py send loop (scheduler sends pre-generated strings verbatim)

Author: W3J Bijou AI
Version: 1.0.0
"""

import csv
import io
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Industry Intelligence Packs ────────────────────────────────────────────────

BUILT_IN_INDUSTRY_PACKS: Dict[str, Dict[str, Any]] = {
    "property_agent": {
        "label": "Property Agency / Real Estate",
        "hook_question": "How many WhatsApp leads do you miss after 6pm?",
        "pain_stat": "47% of property leads message after hours — most agents miss them",
        "roi_proof": "Agents using AI close 41% more deals — RM105k/mo extra on average",
        "avg_deal_value": 15000,
        "currency_default": "RM",
        "known_pain_points": [
            "Miss leads during viewings or after hours",
            "Repetitive WhatsApp questions waste 3hrs/day",
            "Unqualified leads eat agent time",
            "No follow-up system for warm leads",
        ],
        "undercover_script": (
            "Act as a genuine property buyer asking about a {sub_type} property "
            "in {area} with a realistic budget"
        ),
        "sub_type_budgets": {
            "luxury": "RM800k–RM2M",
            "affordable": "RM300k–RM500k",
            "commercial": "RM500k–RM5M",
            "default": "RM400k–RM700k",
        },
        "required_columns": ["phone", "contact_name", "area"],
        "recommended_columns": ["business_name", "sub_type", "pain_point_hint"],
        "personas_available": ["direct", "undercover_buyer", "peer_entrepreneur"],
        "qualification_signals": [
            "volume_pain", "hours_pain", "cost_pain", "quality_pain", "buying_signal",
        ],
    },
    "dental": {
        "label": "Dental Clinic",
        "hook_question": "Do you get appointment requests on WhatsApp after clinic hours?",
        "pain_stat": "45% of dental appointment requests arrive outside clinic hours",
        "roi_proof": "Clinics cut no-shows by 61% and add RM16k/mo revenue with AI",
        "avg_deal_value": 680,
        "currency_default": "RM",
        "known_pain_points": [
            "Front desk overwhelmed with WhatsApp during peak hours",
            "45% of booking requests come after 7pm",
            "Patients forget appointments — high no-show rate",
            "Insurance inquiry questions repeat daily",
        ],
        "undercover_script": (
            "Act as a patient asking about {sub_type} treatment pricing and insurance coverage"
        ),
        "required_columns": ["phone", "contact_name", "area"],
        "recommended_columns": ["business_name", "sub_type", "business_size"],
        "personas_available": ["direct", "undercover_buyer", "peer_entrepreneur"],
        "qualification_signals": [
            "volume_pain", "hours_pain", "cost_pain", "quality_pain", "buying_signal",
        ],
    },
    "gaming_cafe": {
        "label": "Gaming Cafe / Cyber Cafe",
        "hook_question": "Do you still get DMs at 1am asking about rates? 😄",
        "pain_stat": "80% of gaming cafe inquiries happen 8pm–2am — peak staff fatigue hours",
        "roi_proof": "Cafes cut RM800/mo part-time staff cost and grow membership by 133%",
        "avg_deal_value": 179,
        "currency_default": "RM",
        "known_pain_points": [
            "Late-night inquiries go unanswered",
            "Same 20 questions asked daily: rates, games, membership",
            "Tournament registration is manual chaos",
            "No automated way to promote events",
        ],
        "undercover_script": (
            "Act as a gamer asking about membership packages or upcoming tournaments"
        ),
        "required_columns": ["phone", "contact_name", "area"],
        "recommended_columns": ["business_name", "business_size"],
        "personas_available": ["direct", "undercover_buyer", "peer_entrepreneur"],
        "qualification_signals": [
            "volume_pain", "hours_pain", "cost_pain", "quality_pain", "buying_signal",
        ],
    },
    "fnb": {
        "label": "F&B / Restaurant / Cloud Kitchen",
        "hook_question": "During lunch rush, can your team still answer WhatsApp?",
        "pain_stat": "55% of restaurant reservations now come via WhatsApp",
        "roi_proof": "Restaurants add RM21k/mo revenue through AI reservation + upsell",
        "avg_deal_value": 195,
        "currency_default": "RM",
        "known_pain_points": [
            "Staff too busy cooking to reply WhatsApp at peak hours",
            "Reservation no-shows 20–25% — costly and avoidable",
            "Same dietary questions daily: halal, vegan, allergens",
            "No automated reminder system",
        ],
        "undercover_script": (
            "Act as a customer asking about table availability for {party_size} people "
            "on {day}, mention a dietary preference"
        ),
        "required_columns": ["phone", "contact_name", "area"],
        "recommended_columns": ["business_name", "sub_type", "pain_point_hint"],
        "personas_available": [
            "direct", "undercover_buyer", "peer_entrepreneur", "curious_customer",
        ],
        "qualification_signals": [
            "volume_pain", "hours_pain", "cost_pain", "quality_pain", "buying_signal",
        ],
    },
    "salon_spa": {
        "label": "Salon / Spa / Beauty",
        "hook_question": "Do customers book your slots on WhatsApp or do they still call?",
        "pain_stat": "60% of salon bookings now happen via WhatsApp DM",
        "roi_proof": "Salons save 10hrs/week admin time and cut no-shows by 40%",
        "avg_deal_value": 150,
        "currency_default": "RM",
        "known_pain_points": [
            "Bookings via WhatsApp are manual and chaotic",
            "No-shows with no penalty waste stylist time",
            "Price inquiry answers eat hours daily",
            "Hard to manage availability across multiple stylists",
        ],
        "undercover_script": (
            "Act as a customer asking about availability and price for {sub_type} treatment on {day}"
        ),
        "required_columns": ["phone", "contact_name", "area"],
        "recommended_columns": ["business_name", "sub_type"],
        "personas_available": ["direct", "undercover_buyer", "curious_customer"],
        "qualification_signals": ["volume_pain", "hours_pain", "cost_pain", "buying_signal"],
    },
    "auto_workshop": {
        "label": "Auto Workshop / Car Service",
        "hook_question": "How do customers book a service with you — call or WhatsApp?",
        "pain_stat": "70% of workshop inquiries are repetitive: price, availability, ETA",
        "roi_proof": "Workshops reduce service desk workload by 65% with AI triage",
        "avg_deal_value": 350,
        "currency_default": "RM",
        "known_pain_points": [
            "Mechanics distracted by WhatsApp during service",
            "Price and availability questions repeat constantly",
            "Service ETA follow-ups overwhelm staff",
            "Appointment slots managed manually",
        ],
        "undercover_script": (
            "Act as a car owner asking about servicing a {car_make} and rough cost estimate"
        ),
        "required_columns": ["phone", "contact_name", "area"],
        "recommended_columns": ["business_name", "business_size"],
        "personas_available": ["direct", "undercover_buyer", "peer_entrepreneur"],
        "qualification_signals": ["volume_pain", "cost_pain", "buying_signal"],
    },
    "logistics": {
        "label": "Logistics / Courier / Delivery",
        "hook_question": "How many 'where is my parcel?' messages do you get daily?",
        "pain_stat": "WISMO queries = 35% of all logistics support volume",
        "roi_proof": "AI cuts WISMO handling from 45 seconds/query to zero — fully automated",
        "avg_deal_value": 500,
        "currency_default": "RM",
        "known_pain_points": [
            "WISMO (where is my order?) queries flood staff daily",
            "Customer service team overwhelmed at scale",
            "No self-service tracking via WhatsApp",
            "Complaint escalation is slow and manual",
        ],
        "undercover_script": (
            "Act as a business owner inquiring about bulk shipment rates or tracking integration"
        ),
        "required_columns": ["phone", "contact_name", "area"],
        "recommended_columns": ["business_name", "business_size", "estimated_revenue"],
        "personas_available": ["direct", "peer_entrepreneur", "research_analyst"],
        "qualification_signals": ["volume_pain", "cost_pain", "quality_pain", "buying_signal"],
    },
    "custom": {
        "label": "Custom / Other Industry",
        "hook_question": None,  # Must be in campaign_config.industry_config
        "pain_stat": None,
        "roi_proof": None,
        "avg_deal_value": None,
        "currency_default": "RM",  # 2026-07-30: was "USD" — docstring says RM only
        "known_pain_points": [],
        "required_columns": ["phone", "contact_name", "industry_type"],
        "recommended_columns": ["business_name", "area", "pain_point_hint"],
        "personas_available": ["direct", "peer_entrepreneur"],
        "qualification_signals": ["volume_pain", "cost_pain", "buying_signal"],
    },
}


# ── Universal Qualification Signal Map ────────────────────────────────────────

UNIVERSAL_SIGNAL_MAP: Dict[str, Dict[str, Any]] = {
    "volume_pain": {
        "weight": 10,
        "keywords": [
            "too many", "so many", "can't keep up", "overwhelming",
            "busy", "non-stop", "piling up", "backlog", "100+", "hundreds",
        ],
    },
    "hours_pain": {
        "weight": 10,
        "keywords": [
            "after hours", "after 6", "late night", "weekend", "midnight",
            "sleep", "miss", "offline", "1am", "2am", "public holiday",
            "no one reply", "nobody answer",
        ],
    },
    "cost_pain": {
        "weight": 10,
        "keywords": [
            "staff", "hire", "salary", "expensive", "can't afford", "va",
            "virtual assistant", "part-time", "headcount", "labour cost",
        ],
    },
    "quality_pain": {
        "weight": 8,
        "keywords": [
            "slow", "inconsistent", "wrong info", "customer complain",
            "bad review", "lost client", "competitor", "they reply faster",
        ],
    },
    "buying_signal": {
        "weight": 15,
        "keywords": [
            "how much", "price", "demo", "show me", "interested",
            "try", "sign up", "free trial", "how does it work",
            "tell me more", "send info", "want to know more",
        ],
    },
}

WRONG_TARGET_SIGNALS = [
    "wrong number", "i'm a buyer", "not an agent", "i'm a customer",
    "don't contact", "remove me", "stop", "unsubscribe", "no thanks",
    "not interested", "please don't message",
]

QUALIFICATION_THRESHOLDS: Dict[str, int] = {
    "cold": 0,
    "warm": 15,
    "hot": 25,
    "qualified": 38,
}


# ── Language Detection ─────────────────────────────────────────────────────────

_CHINESE_NAME_RE = re.compile(
    r"\b(Lim|Tan|Wong|Lee|Ng|Chen|Chan|Ong|Goh|Teo|Chua|Koh|Yap|Ho|Teh|Chong|Lau|Loh|Sim|Foo)\b",
    re.IGNORECASE,
)
_MALAY_NAME_RE = re.compile(
    r"\b(Ahmad|Muhammad|Nurul|Siti|Mohd|Abdul|Hafiz|Razif|Farah|Nadia|Amirul|Haziq|Izzati|Aiman|Zulaikha)\b",
    re.IGNORECASE,
)
_INDIAN_NAME_RE = re.compile(
    r"\b(Ravi|Kumar|Priya|Raj|Suresh|Kavitha|Muthu|Siva|Gopal|Anand|Nisha|Deepa|Selvan|Velu)\b",
    re.IGNORECASE,
)


def detect_language(contact_name: str, area: str = "", country: str = "MY") -> str:
    """
    Auto-detect appropriate language/tone from contact name + country.

    Returns: 'manglish' | 'singlish' | 'en' | 'ms'
    """
    name = contact_name or ""
    if _CHINESE_NAME_RE.search(name):
        return "singlish" if country == "SG" else "manglish"
    if _MALAY_NAME_RE.search(name):
        return "ms" if country == "MY" else "manglish"
    if _INDIAN_NAME_RE.search(name):
        return "manglish"
    if country == "SG":
        return "singlish"
    if country in ("GB", "US", "AU", "NZ"):
        return "en"
    return "manglish"  # Default for MY and unknown


# ── TemplateEngine ─────────────────────────────────────────────────────────────

class TemplateEngine:
    """
    Industry-aware outreach template and AI generation engine.

    Usage:
        engine = TemplateEngine(gemini_api_key=os.getenv("GEMINI_API_KEY"))
        result = engine.validate_csv(csv_text)    # validate + parse CSV
        contact = engine.enrich_contact(contact)  # fill missing fields
        msg = await engine.generate_message(...)  # call Gemini
        score = engine.score_reply(reply, contact)# score a reply
    """

    def __init__(self, gemini_api_key: Optional[str] = None):
        self._api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self._model = None  # lazy-loaded on first generate call

    def _get_model(self):
        """Lazy-load Gemini model (allows unit tests without a real API key)."""
        if self._model is None:
            try:
                import google.generativeai as genai  # type: ignore
                genai.configure(api_key=self._api_key)
                self._model = genai.GenerativeModel("gemini-2.0-flash-exp")
            except Exception as exc:
                logger.error(f"Gemini model init failed: {exc}")
                raise
        return self._model

    # ── CSV Validation ──────────────────────────────────────────────────────

    def validate_csv(
        self,
        csv_content: str,
        industry_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Parse and validate a CSV string of lead contacts.

        Required CSV columns: phone
        Optional columns: contact_name, business_name, industry_type, sub_type,
                          area, country, language_pref, business_size,
                          estimated_revenue, whatsapp_active, online_presence,
                          pain_point_hint, competitor_used, source, persona,
                          priority, custom_note, max_followups, campaign_config_id,
                          do_not_contact

        Returns:
            {
                "valid":    [list of clean contact dicts],
                "invalid":  [{"row": int, "reason": str}],
                "warnings": [{"row": int, "warning": str}]
            }
        """
        valid: List[Dict[str, Any]] = []
        invalid: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []

        try:
            reader = csv.DictReader(io.StringIO(csv_content.strip()))
        except Exception as exc:
            return {
                "valid": [],
                "invalid": [{"row": 0, "reason": f"CSV parse error: {exc}"}],
                "warnings": [],
            }

        headers = reader.fieldnames or []
        if "phone" not in headers:
            return {
                "valid": [],
                "invalid": [{"row": 0, "reason": "Missing required column: phone"}],
                "warnings": [],
            }
        if "contact_name" not in headers:
            warnings.append({
                "row": 0,
                "warning": "No contact_name column — 'there' used as fallback greeting",
            })

        for row_num, row in enumerate(reader, start=2):
            phone_raw = (row.get("phone") or "").strip()
            phone = self._normalize_phone(phone_raw)
            if not phone:
                invalid.append({"row": row_num, "reason": f"Invalid phone: '{phone_raw}'"})
                continue

            if (row.get("do_not_contact") or "").lower() in ("true", "1", "yes"):
                invalid.append({"row": row_num, "reason": "do_not_contact=true — skipped"})
                continue

            # Resolve industry
            ind = (row.get("industry_type") or industry_type or "custom").strip().lower()
            if ind not in BUILT_IN_INDUSTRY_PACKS:
                warnings.append({
                    "row": row_num,
                    "warning": f"Unknown industry_type '{ind}' — defaulting to 'custom'",
                })
                ind = "custom"

            try:
                max_followups = int(row.get("max_followups") or 3)
            except (ValueError, TypeError):
                max_followups = 3

            contact: Dict[str, Any] = {
                "phone":                phone,
                "contact_name":         (row.get("contact_name") or "").strip() or None,
                "business_name":        (row.get("business_name") or "").strip() or None,
                "industry_type":        ind,
                "sub_type":             (row.get("sub_type") or "").strip() or None,
                "area":                 (row.get("area") or "").strip() or None,
                "country":              (row.get("country") or "MY").strip().upper() or "MY",
                "language_pref":        (row.get("language_pref") or "auto").strip().lower(),
                "business_size":        (row.get("business_size") or "").strip() or None,
                "estimated_revenue":    (row.get("estimated_revenue") or "").strip() or None,
                "whatsapp_active":      (row.get("whatsapp_active") or "unknown").strip().lower(),
                "online_presence":      (row.get("online_presence") or "unknown").strip().lower(),
                "pain_point_hint":      (row.get("pain_point_hint") or "").strip() or None,
                "competitor_used":      (row.get("competitor_used") or "").strip() or None,
                "source":               (row.get("source") or "manual").strip(),
                "persona":              (row.get("persona") or "direct").strip().lower(),
                "priority":             (row.get("priority") or "normal").strip().lower(),
                "custom_note":          (row.get("custom_note") or "").strip() or None,
                "max_followups":        max_followups,
                "campaign_config_id":   (row.get("campaign_config_id") or "").strip() or None,
            }
            valid.append(contact)

        return {"valid": valid, "invalid": invalid, "warnings": warnings}

    def _normalize_phone(self, raw: str) -> Optional[str]:
        """Strip +, spaces, dashes → pure digits 10–15 chars."""
        digits = re.sub(r"[^\d]", "", raw)
        return digits if 10 <= len(digits) <= 15 else None

    # ── Contact Enrichment ──────────────────────────────────────────────────

    def enrich_contact(
        self, contact: Dict[str, Any], campaign_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Auto-fill missing fields using industry intelligence + name detection.
        Returns the enriched contact dict (mutates in place and returns).
        """
        # Auto-detect language
        if not contact.get("language_pref") or contact["language_pref"] == "auto":
            contact["language_pref"] = detect_language(
                contact.get("contact_name") or "",
                contact.get("area") or "",
                contact.get("country") or "MY",
            )

        # Infer business_size from revenue
        if not contact.get("business_size"):
            rev = contact.get("estimated_revenue") or ""
            if "<50k" in rev:
                contact["business_size"] = "micro"
            elif "50k-200k" in rev:
                contact["business_size"] = "small"
            elif "200k-1M" in rev:
                contact["business_size"] = "mid"
            elif rev:
                contact["business_size"] = "large"
            else:
                contact["business_size"] = "small"

        # Attach inferred pain points from pack for prompt context
        pack = BUILT_IN_INDUSTRY_PACKS.get(contact.get("industry_type") or "custom", {})
        if not contact.get("pain_point_hint") and pack.get("known_pain_points"):
            contact["_inferred_pain"] = pack["known_pain_points"]

        return contact

    # ── Gemini Context Builder ──────────────────────────────────────────────

    def build_generation_context(
        self,
        contact: Dict[str, Any],
        step: int,
        campaign_config: Dict[str, Any],
        sequence_step_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build the full Gemini prompt for outreach message generation.

        This is the ONLY function that produces prompts — called once per contact
        at campaign-start time. The resulting message is stored in outbound_queue
        and sent verbatim by the scheduler.
        """
        pack = BUILT_IN_INDUSTRY_PACKS.get(contact.get("industry_type") or "custom", {})
        industry_cfg = campaign_config.get("industry_config") or {}
        meta = campaign_config.get("meta") or {}

        hook = industry_cfg.get("hook_question") or pack.get("hook_question") or "How do you handle WhatsApp inquiries?"
        pain_stat = industry_cfg.get("pain_stat") or pack.get("pain_stat") or ""
        roi_proof = industry_cfg.get("roi_proof") or pack.get("roi_proof") or ""

        product_name = meta.get("product_name") or "Bijou AI"
        product_url = meta.get("product_url") or "https://mybijou.xyz"
        persona = contact.get("persona") or "direct"

        _step_defaults: Dict[int, Dict[str, str]] = {
            0: {"label": "first_contact",        "goal": "start conversation, probe pain point",          "tone": "casual, curious, NOT salesy",              "max_length": "2 sentences max"},
            1: {"label": "followup_no_reply",     "goal": "gentle bump with a new angle",                 "tone": "breezy, zero pressure",                    "max_length": "1–2 sentences"},
            2: {"label": "value_add_followup",    "goal": "share an industry insight or data point",      "tone": "helpful expert",                           "max_length": "2–3 sentences + 1 stat"},
            3: {"label": "last_attempt",          "goal": "soft final offer, close loop gracefully",      "tone": "warm, zero pressure, link included",        "max_length": "2 sentences + link"},
        }
        step_info = sequence_step_config or _step_defaults.get(step, _step_defaults[0])

        _persona_instructions: Dict[str, str] = {
            "direct": (
                f"You are a friendly tech founder sharing {product_name}. "
                f"Mention you work on AI for businesses like theirs — brief, not salesy."
            ),
            "undercover_buyer": (
                f"You are a genuine {(contact.get('industry_type') or 'customer').replace('_', ' ')} customer. "
                f"Act naturally. DO NOT mention {product_name} or AI. "
                f"Start a real conversation about their service."
            ),
            "peer_entrepreneur": (
                f"You are a fellow business owner in the same industry. "
                f"Ask for their advice or share a relatable pain point. Sound like a peer, not a vendor."
            ),
            "curious_customer": (
                f"You are a curious potential customer testing their service quality. "
                f"Ask something genuine. React naturally to their reply."
            ),
            "research_analyst": (
                f"You are doing light industry research on WhatsApp adoption in Malaysian SMEs. "
                f"Ask one open question. Professional but conversational."
            ),
        }
        persona_instruction = _persona_instructions.get(persona, _persona_instructions["direct"])

        contact_name = contact.get("contact_name") or "there"
        business_name = contact.get("business_name") or "their business"
        industry = contact.get("industry_type") or "business"
        sub = contact.get("sub_type") or "general"
        area = contact.get("area") or "Malaysia"
        country = contact.get("country") or "MY"
        lang = contact.get("language_pref") or "manglish"
        biz_size = contact.get("business_size") or "small"
        pain = contact.get("pain_point_hint") or contact.get("_inferred_pain") or pack.get("known_pain_points", ["slow WhatsApp replies"])
        competitor = contact.get("competitor_used") or "unknown"
        note = contact.get("custom_note") or "none"

        no_mention = (
            f"DO NOT mention {product_name} or AI in this message"
            if persona != "direct" and step < 2
            else "Keep any product mention brief and natural"
        )

        prompt = f"""=== BIJOU OUTREACH MESSAGE GENERATOR ===

PRODUCT: {product_name} ({product_url})
STEP: {step} — {step_info.get('label', 'contact')}
GOAL: {step_info.get('goal')}
TONE: {step_info.get('tone')}
MAX LENGTH: {step_info.get('max_length')}

CONTACT CONTEXT:
- Name: {contact_name}
- Business: {business_name}
- Industry: {industry} ({sub})
- Location: {area}, {country}
- Language Style: {lang}
- Business Size: {biz_size}
- Known Pain: {pain}
- Competitor Used: {competitor}
- Extra Context: {note}

PERSONA: {persona}
YOUR ROLE: {persona_instruction}

INDUSTRY INTELLIGENCE (background only — do NOT quote directly):
- Key Hook: {hook}
- Industry Stat: {pain_stat}
- Proof Point: {roi_proof}

STRICT RULES:
1. {no_mention}
2. NEVER use: "I hope this finds you well", "As an AI", "Certainly!", "I'd be happy to"
3. NEVER write more than {step_info.get('max_length')}
4. ALWAYS personalise with their name and area/industry
5. Language style MUST match: {lang}
   - manglish: casual Malaysian English, mix of "lah", "can or not?", "got ah?" naturally
   - singlish: Singaporean style, "lah", "lor", "sia"
   - en: clean professional English
   - ms: Bahasa Malaysia primary
6. Sound like a REAL PERSON texting, not a marketing email
7. Pick ONE approach randomly from these three styles and apply it:
   A) Lead with a specific curiosity question about their business
   B) Lead with a casual observation about their industry/area
   C) Lead with a relatable situation or scenario they'd recognise

OUTPUT: Return ONLY the message text. No labels. No quotes. No explanation."""

        return prompt

    # ── Gemini Generation ───────────────────────────────────────────────────

    async def generate_message(
        self,
        contact: Dict[str, Any],
        step: int,
        campaign_config: Dict[str, Any],
    ) -> str:
        """
        Call Gemini with the built context. Returns generated message string.
        Falls back to a simple personalised template on any Gemini failure.
        """
        prompt = self.build_generation_context(contact, step, campaign_config)
        try:
            model = self._get_model()
            response = await model.generate_content_async(prompt)
            message = response.text.strip().strip('"').strip("'")
            return message
        except Exception as exc:
            logger.error(f"Gemini generation failed for {contact.get('phone')}: {exc}")
            # 2026-08-22 FIX: this had no fallback besides a single generic
            # canned line — and with the project's Gemini key currently
            # suspended (see bijou.py's "PRIMARY" routing comment for the
            # main chat pipeline, same root cause here), EVERY outreach
            # message was silently degrading to that one line per industry,
            # with zero personalization and no warning to the tenant that
            # the advertised "AI-personalized outreach" wasn't happening.
            # Try MiniMax (already the primary provider elsewhere in this
            # app) before giving up on personalization entirely.
            minimax_message = await self._try_minimax(prompt)
            if minimax_message:
                return minimax_message
            name = (contact.get("contact_name") or "there").split()[0]
            area = contact.get("area") or ""
            pack = BUILT_IN_INDUSTRY_PACKS.get(contact.get("industry_type") or "custom", {})
            hook = pack.get("hook_question") or "Quick question about your WhatsApp setup"
            return f"Hi {name}! {hook} 😊"

    async def _try_minimax(self, prompt: str) -> Optional[str]:
        """MiniMax fallback for generate_message() when Gemini is unavailable."""
        mm_key = os.getenv("MINIMAX_API_KEY")
        if not mm_key:
            return None
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                base_url=os.getenv("MINIMAX_API_ENDPOINT") or "https://api.minimax.io/v1",
                api_key=mm_key,
            )
            mm_model = os.getenv("MINIMAX_MODELS", "MiniMax-M3").split(",")[0].strip()
            resp = await client.chat.completions.create(
                model=mm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=300,
            )
            content = (resp.choices[0].message.content or "").strip().strip('"').strip("'")
            return content or None
        except Exception as exc:
            logger.error(f"MiniMax fallback generation failed: {exc}")
            return None

    # ── Reply Scoring ───────────────────────────────────────────────────────

    def score_reply(
        self,
        reply_text: str,
        contact: Dict[str, Any],
        campaign_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Score an inbound reply against qualification signals.

        Returns:
            {
                "interest_score":       int  (cumulative, ready to write to contacts.interest_score),
                "signals_hit":          list of signal names matched,
                "is_wrong_target":      bool,
                "is_buying_signal":     bool,
                "recommended_action":   "continue" | "reveal" | "escalate_to_human" | "mark_dead"
            }
        """
        reply_lower = (reply_text or "").lower()

        # Wrong target check (bail early)
        for signal in WRONG_TARGET_SIGNALS:
            if signal in reply_lower:
                return {
                    "interest_score": 0,
                    "signals_hit": [],
                    "is_wrong_target": True,
                    "is_buying_signal": False,
                    "recommended_action": "mark_dead",
                }

        # Build signal map — merge universal with any campaign overrides
        signal_map = {k: v.copy() for k, v in UNIVERSAL_SIGNAL_MAP.items()}
        if campaign_config:
            custom = (campaign_config.get("qualification_config") or {}).get("custom_signals") or {}
            signal_map.update(custom)

        signals_hit: List[str] = []
        total_score = 0
        is_buying_signal = False

        for signal_name, signal_data in signal_map.items():
            for keyword in signal_data.get("keywords") or []:
                if keyword in reply_lower:
                    if signal_name not in signals_hit:
                        signals_hit.append(signal_name)
                        total_score += signal_data.get("weight") or 5
                    if signal_name == "buying_signal":
                        is_buying_signal = True
                    break

        existing_score = int(contact.get("interest_score") or 0)
        new_score = existing_score + total_score

        persona = contact.get("persona") or "direct"
        if is_buying_signal or new_score >= QUALIFICATION_THRESHOLDS["qualified"]:
            action = "escalate_to_human"
        elif (
            new_score >= QUALIFICATION_THRESHOLDS["hot"]
            and persona in ("undercover_buyer", "curious_customer")
        ):
            action = "reveal"
        else:
            action = "continue"

        return {
            "interest_score": new_score,
            "signals_hit": signals_hit,
            "is_wrong_target": False,
            "is_buying_signal": is_buying_signal,
            "recommended_action": action,
        }

    # ── Reveal Message ──────────────────────────────────────────────────────

    async def generate_reveal_message(
        self,
        contact: Dict[str, Any],
        campaign_config: Dict[str, Any],
        conversation_summary: str = "",
    ) -> str:
        """
        Generate a persona-switch reveal message when interest threshold is hit.
        This transitions from the undercover/peer persona to revealing the product.
        """
        meta = campaign_config.get("meta") or {}
        reveal_cfg = campaign_config.get("reveal_config") or {}

        product_name = meta.get("product_name") or "Bijou AI"
        product_url = meta.get("product_url") or "https://mybijou.xyz"
        pitch_hook = reveal_cfg.get("pitch_hook") or f"We built an AI that handles WhatsApp 24/7 for businesses like yours"
        cta = reveal_cfg.get("cta") or "Can I show you how it works? 2 minutes, no strings attached."
        proof = reveal_cfg.get("proof_point") or ""
        tone = reveal_cfg.get("reveal_tone") or "genuine, friend sharing something useful, not salesy"

        persona = contact.get("persona") or "direct"
        name = (contact.get("contact_name") or "there").split()[0]
        industry = (contact.get("industry_type") or "business").replace("_", " ")
        area = contact.get("area") or "your area"
        lang = contact.get("language_pref") or "manglish"

        proof_line = f'5. Proof point (if it fits naturally): "{proof}"' if proof else ""

        pivot_instruction = (
            f"Honest, light acknowledgment that you were 'testing' their response — keep it fun, not creepy"
            if persona == "undercover_buyer"
            else "Natural pivot from the conversation to sharing something useful"
        )

        prompt = f"""You were acting as a {persona.replace('_', ' ')} chatting with {name}, a {industry} owner in {area}.

After a few exchanges, they're clearly engaged. Now write the REVEAL message.

Conversation context: {conversation_summary or 'A few friendly exchanges about their business'}

Include naturally (in this flow):
1. {pivot_instruction}
2. A genuine observation or compliment about how they handled the chat
3. ONE clear pitch: "{pitch_hook}"
4. Soft CTA: "{cta}"
{proof_line}
6. Brand URL naturally at the end: {product_url}

Tone: {tone}
Language: {lang} (manglish = natural Malaysian casual, "lah/leh" naturally — not forced)
Length: 4–6 sentences MAX. Short paragraphs preferred.

DO NOT:
- Sound like a sales script
- Use "I hope you don't mind"
- Use "As an AI"
- Be apologetic about the approach — keep it light and honest

OUTPUT: Return ONLY the message text."""

        try:
            model = self._get_model()
            response = await model.generate_content_async(prompt)
            return response.text.strip().strip('"').strip("'")
        except Exception as exc:
            logger.error(f"Reveal message generation failed: {exc}")
            return (
                f"Haha okay {name}, full transparency — I was actually testing how fast you guys reply 😄 "
                f"The real reason: we built {product_name} which does exactly what you just did, "
                f"but automatically 24/7. Worth a 2-min look? {product_url}"
            )

    # ── Industry Pack Helpers ───────────────────────────────────────────────

    def get_industry_pack(self, industry_type: str) -> Dict[str, Any]:
        """Return the intelligence pack for a given industry type."""
        return BUILT_IN_INDUSTRY_PACKS.get(industry_type, BUILT_IN_INDUSTRY_PACKS["custom"])

    def list_industry_packs(self) -> Dict[str, Any]:
        """
        Return metadata for all built-in industry packs (for the frontend /templates endpoint).
        Strips internal-only fields, returns frontened-friendly summary.
        """
        return {
            k: {
                "label": v.get("label"),
                "required_columns": v.get("required_columns", []),
                "recommended_columns": v.get("recommended_columns", []),
                "personas_available": v.get("personas_available", []),
                "qualification_signals": v.get("qualification_signals", []),
                "avg_deal_value": v.get("avg_deal_value"),
                "currency_default": v.get("currency_default", "RM"),
                "hook_question": v.get("hook_question"),
                "pain_stat": v.get("pain_stat"),
            }
            for k, v in BUILT_IN_INDUSTRY_PACKS.items()
        }
