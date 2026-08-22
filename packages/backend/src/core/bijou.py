#!/usr/bin/env python3
"""
W3J Bijou AI WhatsApp Enterprise - Production Version
======================================================

Enterprise-grade WhatsApp AI customer support agent with:
- TRACE Empathy Framework (ASI → CAE → SRP → ERS)
- Multi-language support (Malay, Mandarin, Tamil, English, Manglish)
- Supabase PostgreSQL for multi-tenant data
- Message polling from WhatsApp bridge
- Human escalation system
- Google Sheets integration (service account)
- Cost optimization and auto-recovery

Author: W3J Bijou AI
Version: 2.2.0-production
"""

import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

# Load environment variables from .env file
load_dotenv()

# Add project root to path (parent of src/)
project_root = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, project_root)

# Import Phase 2 SaaS components
try:
    from src.saas.knowledge_upload import KnowledgeUploader
    from src.saas.message_filter import MessageFilter

    MESSAGE_FILTER_AVAILABLE = True
except ImportError as e:
    MessageFilter = None
    KnowledgeUploader = None
    MESSAGE_FILTER_AVAILABLE = False

# Import core components
try:
    from src.core.burst_manager import split_into_bursts
except ImportError as e:
    split_into_bursts = None  # type: ignore

try:
    from src.core.command_parser import CommandParser
    from src.core.multi_language import (
        Language,
        LanguageContext,
        MultiLanguageProcessor,
    )
except ImportError as e:
    logging.warning("⚠️ Running with limited imports - some features may not work")
    MultiLanguageProcessor = None
    CommandParser = None
    Language = None
    LanguageContext = None

# Import Phase 4 components (media handling and tool orchestration)
try:
    from src.core.media_handler import MediaHandler
    from src.core.tool_orchestrator import ToolOrchestrator
except ImportError as e:
    logging.warning("⚠️ Phase 4 tools not available - running in text-only mode")
    MediaHandler = None
    ToolOrchestrator = None

# Import Voice Response Service (Phase 7: Voice TTS)
try:
    from src.core.voice_service import VoiceResponseService, get_voice_service
    VOICE_SERVICE_AVAILABLE = True
except ImportError as e:
    VoiceResponseService = None
    get_voice_service = None
    VOICE_SERVICE_AVAILABLE = False
    logging.warning("⚠️ Voice Service not available - text-only responses")

# Import LLM Gateway (key rotator for rate limit handling)
try:
    from src.core.llm_gateway import RoundRobinRotator

    LLM_GATEWAY_AVAILABLE = True
except ImportError as e:
    RoundRobinRotator = None  # type: ignore
    LLM_GATEWAY_AVAILABLE = False

# Import Proactive Messaging System
try:
    from src.core.proactive_messaging import ProactiveMessagingSystem

    PROACTIVE_MESSAGING_AVAILABLE = True
except ImportError as e:
    ProactiveMessagingSystem = None  # type: ignore
    PROACTIVE_MESSAGING_AVAILABLE = False

# Import Channel Adapters (Multi-channel support: WhatsApp + Telegram)
try:
    from src.channels import (
        TelegramAdapter,
        UnifiedMessage,
        telegram_webhook_handler,
    )

    TELEGRAM_AVAILABLE = TelegramAdapter is not None
except ImportError as e:
    TelegramAdapter = None  # type: ignore
    UnifiedMessage = None  # type: ignore
    telegram_webhook_handler = None  # type: ignore
    TELEGRAM_AVAILABLE = False

# ==================== PHASE 1 SAAS IMPORTS ====================
# Import SaaS components for Phase 1 (persona system & lead conversion)
try:
    from src.saas import (
        CommandHandler,
        HandoverSystem,
        LeadConverter,
        PersonaManager,
        ReportingEngine,
    )
    from src.saas.owner_notifications import OwnerNotificationSystem

    SAAS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ Phase 1 SaaS modules not available: {e}")
    CommandHandler = None
    HandoverSystem = None
    LeadConverter = None
    PersonaManager = None
    ReportingEngine = None
    OwnerNotificationSystem = None
    SAAS_AVAILABLE = False

try:
    from src.saas.function_caller import FunctionCaller

    FUNCTION_CALLING_AVAILABLE = True
except ImportError as e:
    FunctionCaller = None
    FUNCTION_CALLING_AVAILABLE = False

# ==================== TRACE EMPATHY FRAMEWORK IMPORTS ====================
# ASI → CAE → SRP pipeline; gated by TRACE_ENABLED env var.
# Lazy-instantiated at first use via _get_trace_agents() below.
try:
    from src.agents.asi import AffectiveStateIdentifier as _ASIClass
    from src.agents.cae import CausalAnalysisEngine as _CAEClass
    from src.agents.srp import StrategicResponsePlanner as _SRPClass

    TRACE_AGENTS_AVAILABLE = True
except ImportError as _trace_import_err:
    _ASIClass = None  # type: ignore
    _CAEClass = None  # type: ignore
    _SRPClass = None  # type: ignore
    TRACE_AGENTS_AVAILABLE = False
    logging.warning(f"⚠️ TRACE agents not importable: {_trace_import_err}")
# ==========================================================================

# Module-level lazy singletons — created once when TRACE_ENABLED=true
_trace_asi: Any = None
_trace_cae: Any = None
_trace_srp: Any = None


def _agent_feature_enabled(env_flag: str, tenant_id: Optional[str]) -> bool:
    """Gate an agent feature: the env flag must be 'true' AND (if AGENT_TENANT_ALLOWLIST
    is set) the tenant must be in it. Empty allowlist = all tenants. This is how a
    feature is enabled for ONE test tenant before a graduated rollout."""
    if os.getenv(env_flag, "false").lower() != "true" or not tenant_id:
        return False
    allow = [t.strip() for t in os.getenv("AGENT_TENANT_ALLOWLIST", "").split(",") if t.strip()]
    return (not allow) or (tenant_id in allow)


def _get_trace_agents() -> Optional[tuple]:
    """
    Lazy-init TRACE empathy agents (ASI + CAE + SRP) on first call.

    Returns:
        Tuple (asi, cae, srp) or None when TRACE_ENABLED is false/unset.
    """
    if os.getenv("TRACE_ENABLED", "false").lower() != "true":
        return None

    global _trace_asi, _trace_cae, _trace_srp

    if not TRACE_AGENTS_AVAILABLE or not _ASIClass or not _CAEClass or not _SRPClass:
        return None

    if _trace_asi is None:
        try:
            _trace_asi = _ASIClass()
            _trace_cae = _CAEClass()
            _trace_srp = _SRPClass()
            logging.getLogger(__name__).info(
                "🧠 TRACE agents initialised (ASI + CAE + SRP)"
            )
        except Exception as _trace_init_err:
            logging.getLogger(__name__).error(
                f"❌ TRACE agent init failed: {_trace_init_err}"
            )
            return None

    return (_trace_asi, _trace_cae, _trace_srp)


# Import Google Sheets webhook integration
try:
    from src.integrations.sheets_webhook import sheets_webhook

    SHEETS_WEBHOOK_AVAILABLE = True
except ImportError as e:
    sheets_webhook = None  # type: ignore
    SHEETS_WEBHOOK_AVAILABLE = False

# ==================== PHASE 2 TENANT ROUTING IMPORTS ====================
try:
    from src.saas.tenant_router import TenantRouter

    TENANT_ROUTING_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ Phase 2 tenant routing not available: {e}")
    TenantRouter = None
    TENANT_ROUTING_AVAILABLE = False
# =============================================================

# ==================== JID UTILITY IMPORTS ====================
try:
    from src.core.jid_utils import (
        normalize_device_jid,
        is_lid_jid,
        build_conversation_key,
        resolve_phone_jid,
    )

    JID_UTILS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ JID utils not available: {e}")
    # Safe no-op fallbacks so the rest of bijou.py never crashes on missing module
    def normalize_device_jid(jid):  # type: ignore[misc]
        return jid

    def is_lid_jid(jid):  # type: ignore[misc]
        return False if not jid else jid.endswith("@lid")

    def build_conversation_key(tenant_id, device_jid, chat_jid):  # type: ignore[misc]
        return f"{tenant_id or ''}::{device_jid or ''}::{chat_jid or ''}"

    async def resolve_phone_jid(supabase_client, chat_jid, tenant_id):  # type: ignore[misc]
        return None  # type: ignore[return-value]

    JID_UTILS_AVAILABLE = False
# =============================================================

# Configure logging with UTF-8 encoding for Windows
import io

log_file_path = os.getenv("LOG_FILE", "/data/logs/bijou.log")
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

# Create UTF-8 stream handler for console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - [%(levelname)s] - %(name)s - %(message)s")
)

# Create UTF-8 file handler
file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - [%(levelname)s] - %(name)s - %(message)s")
)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    handlers=[console_handler, file_handler],
)
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

# ============================================================
# VISION AI CONFIGURATION (Gemini 2.5 Flash Vision)
# ============================================================

VISION_SYSTEM_INSTRUCTION = """You are an expert image analysis AI optimized for OCR and visual understanding.

<core_capabilities>
- Extract text with 100% accuracy (OCR)
- Identify objects, layouts, and visual context
- Detect languages (English, Malay, Chinese, Tamil, Manglish)
- Assess image quality and readability
</core_capabilities>

<output_requirements>
- Always return valid JSON matching the schema
- Use "description" field for main analysis
- Use "ocr_text" field for exact text extraction
- Provide confidence scores (0.0-1.0)
- Assess image_quality: "excellent", "good", "fair", "poor", "unreadable"
</output_requirements>

<fallback_protocol>
If image is blurry or unreadable:
- Set image_quality: "poor" or "unreadable"
- Set confidence: < 0.5
- In description, state: "Image quality is insufficient for accurate OCR. Please send a clearer photo."
</fallback_protocol>
"""

# OCR detection keywords (multi-language)
OCR_KEYWORDS_ENGLISH = [
    "text say", "what text", "read the text", "what does it say",
    "what say", "read this", "transcribe", "what's written",
    "what written", "words say", "says what", "explain", "what this says"
]

OCR_KEYWORDS_MALAY = [
    "apa tulis", "baca ni", "ini tulis apa", "apa kata",
    "tulis apa", "baca ini", "apa cakap", "cakap apa"
]

OCR_KEYWORDS_MANGLISH = [
    "what tulis", "read lah", "baca what", "say what ah"
]

ALL_OCR_KEYWORDS = OCR_KEYWORDS_ENGLISH + OCR_KEYWORDS_MALAY + OCR_KEYWORDS_MANGLISH


def build_vision_prompt(
    user_message: Optional[str] = None,
    industry: str = "general",
    is_ocr_request: bool = False
) -> str:
    """
    Build structured vision prompt with industry-specific context.

    Args:
        user_message: Optional user question/caption
        industry: "general", "dental", "property", "fnb"
        is_ocr_request: True if user explicitly asked for text extraction

    Returns:
        Structured prompt string with XML tags
    """

    # Industry-specific role definitions
    industry_roles = {
        "dental": """<role>Dental AI Assistant</role>
<specialty>Analyzing dental X-rays, teeth photos, and oral health imagery</specialty>
<disclaimer>You are an AI assistant, not a licensed dentist. Provide observations but recommend professional consultation for diagnosis.</disclaimer>""",

        "property": """<role>Real Estate AI Assistant</role>
<specialty>Analyzing room layouts, floor plans, property photos, and architectural features</specialty>
<focus>Identify key features, estimated condition, spatial layout, and notable design elements.</focus>""",

        "fnb": """<role>Food & Beverage AI Assistant</role>
<specialty>Analyzing menus, food photos, pricing lists, and restaurant signage</specialty>
<priority>Extract menu items, prices, ingredients, and dish descriptions with 100% accuracy.</priority>""",

        "general": """<role>General Visual AI Assistant</role>
<specialty>Universal image analysis with focus on text extraction and context understanding</specialty>"""
    }

    # Build prompt structure
    role_context = industry_roles.get(industry.lower(), industry_roles["general"])

    # Task definition based on request type
    if is_ocr_request:
        task = """<task>TEXT EXTRACTION PRIORITY</task>
<instructions>
1. Extract EVERY SINGLE WORD visible in the image
2. Preserve formatting: headings, bullet points, line breaks
3. Transcribe text EXACTLY as written (do not summarize)
4. If text is in multiple languages, specify which language per section
5. If text is partially obscured, indicate: [text unclear] where applicable
</instructions>"""
    else:
        task = """<task>COMPREHENSIVE IMAGE ANALYSIS</task>
<instructions>
1. If text is visible, extract it word-for-word (OCR priority)
2. Describe visual elements: objects, colors, layout, context
3. Identify key features relevant to user's question
4. Provide specific details (not generic observations)
5. If image quality is poor, state limitations clearly
</instructions>"""

    # User question context
    if user_message:
        user_context = f"""<user_question>{user_message}</user_question>
<instruction>Answer the user's question using ACTUAL content from the image. Do not give generic responses.</instruction>"""
    else:
        user_context = """<instruction>Provide a natural, detailed description of what you see. If there's text, include the full transcription.</instruction>"""

    # Combine all parts
    full_prompt = f"""{role_context}

{task}

{user_context}

<output_format>
Return JSON with this exact structure:
{{
    "description": "Natural language description/answer to user's question",
    "ocr_text": "Exact text extracted from image (empty string if no text)",
    "confidence": 0.95,
    "image_quality": "excellent|good|fair|poor|unreadable",
    "detected_language": "en|ms|zh|ta|manglish|mixed",
    "has_text": true|false
}}
</output_format>"""

    return full_prompt

# ============================================================

# Initialize FastAPI for health checks
app = FastAPI(title="Bijou AI WhatsApp Enterprise", version="2.2.0")

# Add CORS middleware for frontend access
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Local dev
        "http://localhost:3001",
        "https://mybijou.xyz",  # Production domain
        "https://www.mybijou.xyz",  # Production domain (www)
        "*",  # Allow all origins temporarily for testing
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Fly edge / CDN cache-bust middleware (added 2026-08-06)
# =============================================================================
# Background: After the v266 deploy the Python process was serving the new
# /signup (with Google button + brand-green mark.svg) but the Fly edge proxy
# in front of app.mybijou.xyz kept returning the OLD response (no Google
# button, broken logo) for hours — even after a full machine restart. The
# static mount already sets Cache-Control: no-store, but the Fly edge
# ignored it and served a cached response keyed on URL+ETag+Last-Modified.
#
# Fix: a middleware that forces every response to carry
#   Cache-Control: no-store, no-cache, must-revalidate, max-age=0
#   Pragma: no-cache
#   Expires: 0
#   Surrogate-Control: no-store  ← tells the Fly edge / any CDN to not cache
#
# This is safe because the dashboard is auth-gated and not CDN-friendly
# anyway. We can tighten it later if a public marketing page ever needs CDN.
@app.middleware("http")
async def _no_cache_everything(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    # Surrogate-Control is the CDN-specific header. Fly's edge respects it.
    response.headers["Surrogate-Control"] = "no-store"
    return response

# Mount static files for dashboard.
# We replace Starlette's default StaticFiles with a subclass that sets
# Cache-Control: no-store so the Fly edge proxy / any reverse proxy in
# front of app.mybijou.xyz never serves a stale logo / favicon after
# a deploy. (2026-07-25 — first observed when the Signal Gem brand
# refresh hit the container but the app.mybijou.xyz edge kept serving
# the pre-refresh file for hours.)
class _NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response is not None:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

static_path = Path(__file__).parent.parent.parent / "static"
if static_path.exists():
    app.mount("/static", _NoCacheStaticFiles(directory=str(static_path)), name="static")
    logger.info(f"✅ Static files mounted from {static_path} (Cache-Control: no-store)")

# Helper function to get Supabase client for FastAPI routes
def get_supabase():
    """
    Get Supabase client instance for API routes.
    Uses service role key to bypass RLS policies.
    """
    from supabase import Client, create_client

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")

    return create_client(supabase_url, supabase_key)

# Defer router includes to prevent import-time blocking
def _include_routers():
    """Lazily include API routers to speed up startup"""
    try:
        from src.core.dashboard_api_simple import router as dashboard_router
        app.include_router(dashboard_router)
        logger.info("✅ Dashboard API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import dashboard API: {e}")

    # Connector (Composio) OAuth-connect API — only when the feature is enabled.
    # tenant_id is taken from the authenticated session (verify_session), never
    # from client input, by overriding the router's require_tenant dependency.
    if os.getenv("ENABLE_COMPOSIO", "false").lower() == "true":
        try:
            from src.connectors.oauth_api import router as connectors_router, require_tenant
            from src.core.dashboard_api_simple import verify_session
            app.dependency_overrides[require_tenant] = verify_session
            app.include_router(connectors_router)
            logger.info("✅ Connectors (Composio) API routes included")
        except ImportError as e:
            logger.warning(f"⚠️ Could not import connectors API: {e}")

    # Nango integration-connection API — replaces the Composio scaffold above.
    # Only mounted when a Nango secret key is configured.
    if os.getenv("NANGO_SECRET_KEY") or os.getenv("NANGO_API_KEY"):
        try:
            from src.connectors.nango_api import router as nango_router
            app.include_router(nango_router)
            logger.info("✅ Nango integrations API routes included")
        except ImportError as e:
            logger.warning(f"⚠️ Could not import Nango integrations API: {e}")

    try:
        from src.saas.onboarding_api import router as onboarding_router
        app.include_router(onboarding_router)
        logger.info("✅ Onboarding API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import onboarding API: {e}")

    try:
        from src.saas.onboarding_complete import router as onboarding_complete_router
        app.include_router(onboarding_complete_router)
        logger.info("✅ Onboarding Complete API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import onboarding complete API: {e}")

    try:
        from src.saas.admin_api import router as admin_router
        app.include_router(admin_router)
        logger.info("✅ Admin API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import admin API: {e}")

    try:
        from src.saas.knowledge_api import router as knowledge_router
        app.include_router(knowledge_router)
        logger.info("✅ Knowledge API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import knowledge API: {e}")

    try:
        from src.saas.settings_api import router as settings_router
        app.include_router(settings_router)
        logger.info("✅ Settings API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import settings API: {e}")

    try:
        from src.saas.media_api import router as media_router
        app.include_router(media_router)
        logger.info("✅ Media API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import media API: {e}")

    try:
        from src.saas.learning_api import router as learning_router
        app.include_router(learning_router)
        logger.info("✅ Learning API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import learning API: {e}")

    try:
        from src.saas.payment_api import router as payment_router
        app.include_router(payment_router)
        logger.info("✅ Payment API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import payment API: {e}")

    try:
        from src.saas.auth_api import router as auth_router
        app.include_router(auth_router)
        logger.info("✅ Auth API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import auth API: {e}")

    try:
        from src.integrations.call_booking_api import router as call_booking_router
        app.include_router(call_booking_router)
        logger.info("✅ Call Booking API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import call booking API: {e}")

    # Business Profile API (TASK 5: Business info and handover)
    try:
        from src.saas.business_profile_api import router as business_profile_router
        app.include_router(business_profile_router)
        logger.info("✅ Business Profile API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import business profile API: {e}")

    try:
        from src.saas.contacts_api import router as contacts_router
        app.include_router(contacts_router)
        logger.info("✅ Contacts CRM API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import contacts API: {e}")

    try:
        from src.api.support import router as support_router
        app.include_router(support_router)
        logger.info("✅ Support Ticket API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import support API: {e}")

    # Setup / Pre-Go-Live Sandbox API (dry-run "Test Bijou" chat)
    try:
        from src.saas.setup_api import router as setup_router
        app.include_router(setup_router)
        logger.info("✅ Setup Sandbox API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import setup API: {e}")

    try:
        from src.saas.kb_import_api import router as kb_import_router
        app.include_router(kb_import_router)
        logger.info("✅ KB Listing Importer routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import KB import API: {e}")

    try:
        from src.api.help_chat import router as help_chat_router
        app.include_router(help_chat_router)
        logger.info("✅ Help Chat API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import Help Chat API: {e}")

    try:
        from src.core.outreach_api import router as outreach_router
        app.include_router(outreach_router)
        logger.info("✅ Outreach API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import Outreach API: {e}")

    try:
        from src.saas.kb_templates_api import router as kb_templates_router
        app.include_router(kb_templates_router)
        logger.info("✅ KB Templates API routes included")
    except ImportError as e:
        logger.warning(f"⚠️ Could not import KB Templates API: {e}")

# Include Proactive Messaging API routes
try:
    from src.core.proactive_api import router as proactive_router

    app.include_router(proactive_router)
    logger.info("✅ Proactive Messaging API routes included")
except ImportError as e:
    logger.warning(f"⚠️ Could not import proactive messaging API: {e}")

# Include Google OAuth API routes
try:
    from src.saas.google_oauth import router as google_oauth_router

    app.include_router(google_oauth_router)
    logger.info("✅ Google OAuth API routes included")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Google OAuth API: {e}")

# Global Bijou instance for webhook access
bijou_instance = None


async def _wa_keepalive_monitor():
    """
    Background task: ping bridge every 5 min.
    If bridge is up but a device shows disconnected, mark tenant offline in DB
    and notify the owner so they can re-scan QR.
    """
    import httpx
    INTERVAL = 300  # 5 minutes
    _notified: set = set()  # track which tenant_ids were already notified

    while True:
        try:
            await asyncio.sleep(INTERVAL)
        except asyncio.CancelledError:
            logger.debug("🔕 Keepalive monitor stopped (shutdown)")
            return
        try:
            if not bijou_instance:
                continue

            bridge_url = os.getenv("BRIDGE_URL", "")
            bridge_user = os.getenv("BRIDGE_USER", "")
            bridge_pass = os.getenv("BRIDGE_PASSWORD", "")
            if not bridge_url:
                continue

            auth = (bridge_user, bridge_pass) if bridge_user else None
            async with httpx.AsyncClient(timeout=10) as client:
                # 1. Check bridge health — pass auth credentials (bridge now requires auth on /health)
                try:
                    health = await client.get(f"{bridge_url}/health", auth=auth)
                    if health.status_code not in (200, 204):
                        logger.warning(f"⚠️ [KEEPALIVE] Bridge unhealthy: {health.status_code}")
                        continue
                except Exception as e:
                    logger.warning(f"⚠️ [KEEPALIVE] Bridge unreachable: {e}")
                    continue

                # 2. Check device list for disconnected sessions
                try:
                    devices_resp = await client.get(
                        f"{bridge_url}/app/devices",
                        auth=auth,
                    )
                    if devices_resp.status_code != 200:
                        continue
                    devices = devices_resp.json() if isinstance(devices_resp.json(), list) else []
                except Exception:
                    continue

            if not bijou_instance.db_conn:
                continue

            db = bijou_instance.db_conn
            for device in devices:
                device_id = device.get("device_id") or device.get("id", "")
                is_connected = device.get("is_connected") or device.get("state") == "logged_in"

                if not device_id or is_connected:
                    # Clear notified set if reconnected
                    if device_id in _notified and is_connected:
                        _notified.discard(device_id)
                    continue

                # Device is offline — find tenant
                try:
                    result = db.table("whatsapp_devices").select("tenant_id").eq("device_id", device_id).execute()
                    if not result.data:
                        continue
                    tenant_id = result.data[0]["tenant_id"]

                    # Update tenant as disconnected
                    db.table("tenants").update({
                        "whatsapp_connected": False,
                        "updated_at": datetime.now().isoformat(),
                    }).eq("id", tenant_id).execute()

                    # Notify owner once per disconnect cycle
                    if tenant_id not in _notified:
                        _notified.add(tenant_id)
                        logger.warning(f"📴 [KEEPALIVE] Device {device_id} offline — tenant {tenant_id} marked disconnected")
                        if bijou_instance.owner_jid:
                            bijou_instance.send_message(
                                bijou_instance.owner_jid,
                                f"⚠️ *WhatsApp Session Offline*\n\nDevice `{device_id}` has disconnected.\n\nPlease open the dashboard → Settings → WhatsApp and re-scan the QR code to reconnect.",
                                tenant_id=tenant_id,
                            )
                except Exception as e:
                    logger.debug(f"[KEEPALIVE] Error processing device {device_id}: {e}")

            # Stale device cleanup: auto-remove DB entries for devices no
            # longer registered in the bridge (e.g. after DEVICE_REMOVED events)
            try:
                bridge_device_ids = {
                    d.get("device_id") or d.get("id", "")
                    for d in devices
                    if d.get("device_id") or d.get("id")
                }
                db_devices = db.table("whatsapp_devices").select("device_id").execute()
                for db_dev in (db_devices.data or []):
                    db_device_id = db_dev.get("device_id", "")
                    if db_device_id and db_device_id not in bridge_device_ids:
                        db.table("whatsapp_devices").delete().eq("device_id", db_device_id).execute()
                        logger.warning(
                            f"🗑️ [KEEPALIVE] Removed stale device {db_device_id} "
                            f"— no longer registered in bridge"
                        )
            except Exception as _cleanup_err:
                logger.debug(f"[KEEPALIVE] Stale device cleanup error: {_cleanup_err}")

        except Exception as e:
            logger.debug(f"[KEEPALIVE] Monitor cycle error: {e}")


async def _ensure_tenant_tokens():
    """
    Startup backfill: assign signup_token to any tenant that doesn't have one.
    Runs once at startup, non-blocking. Prevents dashboard 401 loops for tenants
    created before Phase 4.2 or inserted via admin without a token.
    """
    import secrets as _secrets
    try:
        supabase = get_supabase()
        if not supabase:
            return
        response = await asyncio.to_thread(
            lambda: supabase.table("tenants").select("id,name").is_("signup_token", "null").execute()
        )
        if not response.data:
            logger.info("✅ All tenants have signup_token — no backfill needed")
            return
        fixed = 0
        for tenant in response.data:
            tid = tenant["id"]
            tname = tenant.get("name", "unknown")
            token = _secrets.token_urlsafe(32)
            await asyncio.to_thread(
                lambda t=tid, tk=token: supabase.table("tenants").update({"signup_token": tk}).eq("id", t).execute()
            )
            dashboard_url = f"{os.getenv('PUBLIC_URL', 'https://app.mybijou.xyz')}/dashboard?tenant_id={tid}&token={token}"
            logger.info(f"✅ Auto-assigned signup_token to tenant {tid} ({tname})")
            logger.info(f"   Dashboard URL: {dashboard_url}")
            fixed += 1
        logger.info(f"✅ signup_token backfill complete: {fixed} tenant(s) updated")
    except Exception as e:
        logger.warning(f"⚠️ signup_token backfill failed (non-fatal): {e}")


@app.on_event("startup")
async def startup_event():
    """Initialize Bijou AI when FastAPI starts (for uvicorn direct launch)"""
    global bijou_instance

    # First, include routers (deferred import)
    _include_routers()

    if bijou_instance is None:
        logger.info("🚀 FastAPI startup - Initializing Bijou AI...")
        try:
            bijou_instance = BijouAI()
            logger.info("✅ Bijou AI initialized successfully")
        except Exception as e:
            logger.critical(f"🚨 Failed to initialize Bijou AI: {e}")
            raise

    # Store in app state for dependencies
    app.state.bijou = bijou_instance

    # Check database migrations (non-blocking)
    try:
        await check_database_migrations()
    except Exception as e:
        logger.warning(f"⚠️ Migration check failed (non-fatal): {e}")

    # Register Telegram webhook if enabled
    if bijou_instance.telegram_enabled and bijou_instance.telegram_adapter:
        await register_telegram_webhook()

    # Provision Supabase Storage bucket (idempotent)
    try:
        from src.saas.storage_setup import ensure_bijou_media_bucket
        supabase_for_storage = get_supabase()
        bucket_result = await ensure_bijou_media_bucket(supabase_for_storage)
        logger.info(f"🪣 Storage bucket status: {bucket_result}")
    except Exception as e:
        logger.warning(f"⚠️ Storage bucket setup failed (non-fatal): {e}")

    async def _bg(coro, label=""):
        """Wrap fire-and-forget tasks so CancelledError at shutdown is silent."""
        try:
            await coro
        except asyncio.CancelledError:
            logger.debug(f"🔕 Background task '{label}' stopped (shutdown)")
        except Exception as e:
            logger.warning(f"⚠️ Background task '{label}' error: {e}")

    # Start proactive messaging scheduler if enabled
    if bijou_instance.proactive_messaging:
        asyncio.create_task(_bg(bijou_instance.proactive_messaging.start(), "proactive_messaging"))
        logger.info("✅ Proactive messaging scheduler started")

    # Start Outreach scheduler
    try:
        from src.channels.bridge_adapter import BridgeAdapter
        from src.core.outreach_scheduler import OutreachScheduler
        _supabase_for_outreach = get_supabase()
        _bridge_for_outreach = BridgeAdapter(base_url=bijou_instance.bridge_url)
        outreach_scheduler = OutreachScheduler(
            db_connection=_supabase_for_outreach,
            bridge_adapter=_bridge_for_outreach,
        )
        asyncio.create_task(_bg(outreach_scheduler.start(), "outreach_scheduler"))
        app.state.outreach_scheduler = outreach_scheduler
        logger.info("✅ Outreach scheduler started")
    except Exception as _oe:
        logger.warning(f"⚠️ Outreach scheduler could not start (non-fatal): {_oe}")

    # Start WhatsApp bridge keepalive monitor
    asyncio.create_task(_bg(_wa_keepalive_monitor(), "keepalive_monitor"))
    logger.info("✅ WhatsApp keepalive monitor started")

    # Backfill signup_token for any tenants missing it (idempotent, non-blocking)
    asyncio.create_task(_bg(_ensure_tenant_tokens(), "token_backfill"))


async def check_database_migrations():
    """
    Check if required database migrations are applied.
    This runs on startup to ensure the database schema is ready.
    """
    db_type = os.getenv("DB_TYPE", "sqlite")
    logger.info(f"🔍 Checking {db_type.upper()} database migrations...")

    if db_type == "supabase":
        # For Supabase, check if call booking tables exist
        supabase_client = get_supabase()
        if not supabase_client:
            logger.warning("⚠️ Supabase client not available - skipping migration check")
            return

        # Check call booking tables
        call_booking_tables = [
            "call_bookings", "call_availability", "call_types",
            "call_settings", "holiday_exceptions", "availability_overrides"
        ]

        missing_tables = []
        for table_name in call_booking_tables:
            try:
                await asyncio.to_thread(
                    lambda: supabase_client.table(table_name).select("count").limit(1).execute()
                )
            except Exception as e:
                if "does not exist" in str(e).lower():
                    missing_tables.append(table_name)

        if missing_tables:
            logger.warning(f"⚠️ Call booking migration not applied - missing tables: {missing_tables}")
            logger.info("💡 Run: python scripts/apply_call_booking_migration.py")
        else:
            logger.info("✅ All call booking tables exist")

    else:
        # For SQLite, tables are created automatically in _init_sqlite()
        logger.info("✅ SQLite tables will be created automatically")


async def register_telegram_webhook():
    """Register Telegram webhook URL with Telegram API"""
    global bijou_instance

    public_url = os.getenv("PUBLIC_URL", "").strip()
    if not public_url:
        logger.warning(
            "⚠️ PUBLIC_URL not set - Telegram webhook not registered. "
            "Set PUBLIC_URL to your server's public URL (e.g., https://your-app.fly.dev)"
        )
        return

    webhook_url = f"{public_url.rstrip('/')}/webhook/telegram"

    try:
        # Use httpx for async HTTP request to Telegram API
        import httpx

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        api_url = f"https://api.telegram.org/bot{telegram_token}/setWebhook"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                api_url,
                json={"url": webhook_url},
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    logger.info(f"✅ Telegram webhook registered: {webhook_url}")
                else:
                    logger.error(f"❌ Telegram webhook registration failed: {data}")
            else:
                logger.error(
                    f"❌ Telegram webhook registration failed: HTTP {response.status_code}"
                )
    except ImportError:
        logger.error("❌ httpx not installed - cannot register Telegram webhook (httpx required in production)")
        raise
    except Exception as e:
        logger.error(f"❌ Telegram webhook registration error: {e}")


# Pydantic models for GOWA webhook (v8.x multi-device format)
class GOWAMessagePayload(BaseModel):
    """GOWA webhook message payload structure"""
    id: str
    chat_id: str
    from_: str = Field(alias="from")  # Use alias because 'from' is Python keyword
    from_lid: Optional[str] = None
    from_name: Optional[str] = None
    timestamp: str
    is_from_me: bool = False
    body: Optional[str] = None  # Text content
    # Media fields
    image: Optional[str | dict] = None
    video: Optional[str | dict] = None
    audio: Optional[str | dict] = None
    document: Optional[str | dict] = None
    sticker: Optional[str | dict] = None
    video_note: Optional[str | dict] = None
    # Special message types
    contact: Optional[dict] = None
    location: Optional[dict] = None
    live_location: Optional[dict] = None
    # Reply context
    replied_to_id: Optional[str] = None
    quoted_body: Optional[str] = None
    # Flags
    view_once: Optional[bool] = None
    forwarded: Optional[bool] = None

    class Config:
        populate_by_name = True  # Allow both 'from' and 'from_' field names

class GOWAWebhookMessage(BaseModel):
    """GOWA webhook top-level structure"""
    event: str  # "message", "message.reaction", "message.ack", etc.
    device_id: str
    payload: GOWAMessagePayload


@app.post("/api/webhook")
async def external_webhook(request: Request, authorization: str = Header(None)):
    """
    Handle external webhooks (e.g., from Forms, Landing Pages).
    Routes data through ToolOrchestrator for lead capture.
    """
    # ✅ FIX #7: Add comprehensive validation
    try:
        # Validate content-type
        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            logger.warning(f"⚠️ Invalid webhook content-type: {content_type}")
            raise HTTPException(
                status_code=400,
                detail="Content-Type must be application/json"
            )

        # Parse JSON body
        try:
            data = await request.json()
        except Exception as parse_error:
            logger.warning(f"⚠️ Malformed webhook JSON (client error): {parse_error}")
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON payload"
            )

        # Validate non-empty payload
        if not data:
            logger.warning("⚠️ Webhook received empty payload")
            raise HTTPException(
                status_code=400,
                detail="Webhook payload cannot be empty"
            )

        logger.info(f"📥 Incoming Webhook: {data}")

        # TODO: Trigger Lead Capture (Async/Fire-and-forget logic here)
        # This would integrate with ToolOrchestrator when available

        return {"status": "received", "data": data}

    except HTTPException:
        raise  # Re-raise validation errors as-is
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Webhook processing failed: {str(e)}"
        )


# ── Pure helpers for missed-call detection (module-level, fully testable) ──────

def is_missed_call(message: Dict) -> bool:
    """Return True when *message* represents a missed WhatsApp call.

    Detection is intentionally dual-mode:
    - ``message_type == "missed_call"``  (bridge sends explicit type)
    - ``content == "📞 MISSED_CALL"``   (synthesised sentinel in webhook handler)
    Either condition is sufficient so the logic is robust to bridge variations.
    """
    msg_type = message.get("message_type", "") or ""
    content = message.get("content", "") or ""
    # Legacy field name used by older bridge payloads
    body = message.get("body", "") or ""
    return (
        msg_type == "missed_call"
        or content == "📞 MISSED_CALL"
        or body == "📞 MISSED_CALL"
    )


MISSED_CALL_SYSTEM_CONTEXT = (
    "[SYSTEM CONTEXT: This customer just tried to call our "
    "WhatsApp number but the call was not answered. "
    "Do NOT mention you are an AI unless asked. "
    "Greet them warmly, acknowledge the missed call naturally, "
    "ask how you can help, and if they indicate urgency or emergency "
    "offer to escalate to a human immediately.]"
)


def build_missed_call_context() -> str:
    """Return the AI system-context string to inject for missed-call messages."""
    return MISSED_CALL_SYSTEM_CONTEXT


# ── End pure helpers ───────────────────────────────────────────────────────────


class BijouAI:
    """
    Production Bijou AI WhatsApp Agent

    Features:
    - Message polling from WhatsApp bridge
    - Multi-language detection and response
    - Database abstraction (SQLite or Supabase)
    - Human escalation
    - Cost optimization
    - Auto-recovery
    """

    def __init__(self):
        """Initialize Bijou AI system"""
        logger.info("🚀 Initializing Bijou AI WhatsApp Enterprise v2.2.0")

        # Configuration
        self.config = self._load_config()
        self.running = True
        self.poll_count = 0
        self.executor = ThreadPoolExecutor(max_workers=5)

        # Database setup - initialize early for SaaS components
        self.db_type = os.getenv("DB_TYPE", "sqlite")  # sqlite or supabase
        self.db_conn = None

        # Initialize database connection NOW (needed by HandoverSystem, TenantRouter, etc.)
        try:
            self._init_database()
            logger.info(f"✅ Database connection initialized: {self.db_type}")
        except Exception as e:
            logger.warning(f"⚠️ Database initialization failed: {e}")
            logger.info("⚠️ SaaS features will be disabled without database")

        # LLM Gateway: Round-robin key rotator for 429 handling
        self.llm_rotator = None
        if LLM_GATEWAY_AVAILABLE and RoundRobinRotator:
            try:
                self.llm_rotator = RoundRobinRotator()
                logger.info("✅ LLM Gateway (RoundRobinRotator) initialized")
            except Exception as e:
                logger.warning(f"⚠️ LLM Gateway init failed: {e}")

        # Component initialization
        self.ml_processor = MultiLanguageProcessor() if MultiLanguageProcessor else None
        self.command_parser = CommandParser() if CommandParser else None
        self.escalated_chats = {}
        # Webhook mode - no polling needed
        self.last_poll_time = datetime.now()
        self.processed_message_ids = set()

        # ✅ Rate limiter: Prevent message floods (AI-to-AI loops, spam)
        # Format: {chat_jid: {"count": int, "window_start": datetime}}
        self.rate_limiter: Dict[str, Dict] = {}
        self.rate_limit_max = int(os.getenv("RATE_LIMIT_MESSAGES_PER_MINUTE", "10"))
        self.rate_limit_window = 60  # seconds

        # ✅ Self-echo detection: Bridge echoes our sent messages back; skip if incoming matches recent send
        # Format: {chat_jid: [{"content_preview": str, "sent_at": datetime}, ...]}
        self.recent_sent: Dict[str, List[Tuple[str, datetime]]] = {}
        self.recent_sent_ttl = 120  # seconds - how long to remember our sends
        self.recent_sent_max_per_chat = 5  # keep last N sends per chat

        # Webhook mode flag
        self.webhook_mode = os.getenv("WEBHOOK_MODE", "true").lower() == "true"

        # Bridge connection (must be set before media handler)
        self.bridge_url = os.getenv("BRIDGE_URL", "http://localhost:8080").rstrip("/")
        if self.bridge_url.endswith("/api"):
            self.bridge_url = self.bridge_url[: -len("/api")]
        self.bridge_db_path = os.getenv(
            "BRIDGE_DB_PATH"
        )  # None if not set - forces HTTP API mode
        self.bridge_api_key = os.getenv("BRIDGE_API_KEY", "")  # For authentication
        self.whatsapp_device_id = os.getenv("WHATSAPP_DEVICE_ID", os.getenv("DEFAULT_TENANT_ID", "default"))  # Device ID for GOWA bridge

        # Phase 4: Initialize media handler and tool orchestrator
        self.media_handler = None
        self.tool_orchestrator = None
        if MediaHandler and ToolOrchestrator:
            try:
                self.media_handler = MediaHandler(bridge_url=self.bridge_url)
                self.tool_orchestrator = ToolOrchestrator(bridge_url=self.bridge_url)
                logger.info("✅ Phase 4 tools initialized (media + orchestrator)")
            except Exception as e:
                logger.warning(f"⚠️ Phase 4 tools initialization failed: {e}")

        # ==================== PHASE 7: VOICE RESPONSE SERVICE ====================
        # CRITICAL CHANGE: Voice OUTPUT (TTS) is now DISABLED
        # Gemini handles voice INPUT (transcription) in media processing
        # Bijou replies in TEXT only - no voice messages sent
        self.voice_service = None
        voice_enabled = False  # Force disabled - no voice output
        logger.info("🎤 Voice: INPUT enabled (Gemini transcription), OUTPUT disabled (text-only replies)")
        # =========================================================================

        # ==================== MULTI-CHANNEL: TELEGRAM SUPPORT ====================
        self.telegram_adapter = None
        self.telegram_enabled = False
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

        if telegram_token and TELEGRAM_AVAILABLE:
            try:
                self.telegram_adapter = TelegramAdapter(token=telegram_token)
                self.telegram_enabled = True
                logger.info("✅ Telegram channel initialized")
            except Exception as e:
                logger.warning(f"⚠️ Telegram initialization failed: {e}")
        elif telegram_token and not TELEGRAM_AVAILABLE:
            logger.warning(
                "⚠️ TELEGRAM_BOT_TOKEN set but python-telegram-bot not installed"
            )
        # =========================================================================

        # Owner JID for notifications
        # Owner JID - NEVER hardcode! Must come from env or database
        self.owner_jid = os.getenv("OWNER_WHATSAPP_JID", "")
        if not self.owner_jid:
            logger.warning("⚠️ OWNER_WHATSAPP_JID not set - owner commands will not work")

        # Owner linked devices (persistent mapping)
        # Format: {"84950644740196@lid": "+601160600963@s.whatsapp.net"}
        self.owner_linked_devices = self._load_owner_devices()

        # ==================== PHASE 2: INITIALIZE MULTI-TENANT ROUTING ====================
        self.tenant_router = None
        self.multi_tenant_enabled = (
            os.getenv("ENABLE_MULTI_TENANT", "false").lower() == "true"
        )

        if self.multi_tenant_enabled and TENANT_ROUTING_AVAILABLE and self.db_conn:
            try:
                logger.info("🏢 Initializing Phase 2 multi-tenant routing...")
                self.tenant_router = TenantRouter(supabase_client=self.db_conn)
                logger.info("✅ TenantRouter initialized (Phase 2)")
            except Exception as e:
                logger.error(f"❌ TenantRouter initialization failed: {e}")
                self.multi_tenant_enabled = False
        elif TENANT_ROUTING_AVAILABLE:
            try:
                self.tenant_router = TenantRouter()
                logger.info("✅ TenantRouter initialized (standalone mode)")
            except Exception as e:
                logger.warning(f"⚠️ TenantRouter initialization failed: {e}")
                self.tenant_router = None

        # ==================== PHASE 1: INITIALIZE SAAS COMPONENTS ====================
        self.command_handler = None
        self.handover_system = None
        self.persona_manager = None
        self.lead_converter = None
        self.reporting_engine = None
        self.notification_system = None

        # Debug logging for HandoverSystem initialization
        logger.info(f"🔍 HandoverSystem check: SAAS_AVAILABLE={SAAS_AVAILABLE}, db_conn={self.db_conn is not None}")

        if SAAS_AVAILABLE and self.db_conn:
            try:
                logger.info("🚀 Initializing Phase 1 SaaS components...")

                # HandoverSystem (required for LeadConverter)
                enable_handover = (
                    os.getenv("ENABLE_HANDOVER_QUEUE", "false").lower() == "true"
                )
                logger.info(f"🔍 ENABLE_HANDOVER_QUEUE={os.getenv('ENABLE_HANDOVER_QUEUE')} -> enable_handover={enable_handover}, HandoverSystem class available={HandoverSystem is not None}")

                if enable_handover and HandoverSystem:
                    self.handover_system = HandoverSystem(
                        supabase_client=self.db_conn,
                        memory_system=None,
                        send_message_callback=self.send_message,
                    )
                    logger.info("✅ HandoverSystem initialized (Phase 1)")
                else:
                    logger.warning(f"⚠️ HandoverSystem NOT initialized: enable_handover={enable_handover}, HandoverSystem={HandoverSystem is not None}")

                # PersonaManager
                enable_persona = (
                    os.getenv("ENABLE_PERSONA_SYSTEM", "false").lower() == "true"
                )
                if enable_persona and PersonaManager:
                    self.persona_manager = PersonaManager(
                        supabase_client=self.db_conn, owner_jid=self.owner_jid
                    )
                    logger.info("✅ PersonaManager initialized (Phase 1)")

                # LeadConverter
                enable_leads = (
                    os.getenv("ENABLE_LEAD_CONVERSION", "false").lower() == "true"
                )
                if enable_leads and LeadConverter and self.handover_system:
                    self.lead_converter = LeadConverter(
                        supabase_client=self.db_conn,
                        handover_system=self.handover_system,
                        send_message_callback=self.send_message,
                    )
                    logger.info("✅ LeadConverter initialized (Phase 1)")

                # CommandHandler (@bijou commands)
                enable_commands = (
                    os.getenv("ENABLE_BIJOU_COMMANDS", "true").lower() == "true"
                )
                if enable_commands and CommandHandler:
                    self.command_handler = CommandHandler(
                        owner_jid=self.owner_jid,
                        admin_controller=None,
                        memory_system=None,
                        tool_orchestrator=None,
                        db_conn=self.db_conn,
                    )
                    logger.info("✅ CommandHandler initialized (@bijou commands)")

                # Structured Tool Calling (Phase 5)
                if FUNCTION_CALLING_AVAILABLE and self.tool_orchestrator:
                    from src.saas.function_caller import FunctionCaller

                    self.function_caller = FunctionCaller(
                        tool_orchestrator=self.tool_orchestrator,
                        gemini_api_key=os.getenv("GEMINI_API_KEY"),
                    )
                    logger.info("✅ FunctionCaller initialized (Robust Tool Calling)")

                # Knowledge Engine (Phase 6)
                from src.core.knowledge_engine import KnowledgeEngine

                self.knowledge_engine = KnowledgeEngine()
                logger.info("✅ KnowledgeEngine initialized (Business Context Support)")

                # Vertical Template Loader (Multi-Vertical AI System - Phase 2)
                from src.saas.vertical_loader import VerticalTemplateLoader

                self.vertical_loader = VerticalTemplateLoader(supabase_client=self.db_conn)
                logger.info("✅ VerticalTemplateLoader initialized (Domain-Specific Prompts)")

                # ReportingEngine (Daily/Weekly Reports)
                enable_reports = (
                    os.getenv("ENABLE_AUTO_REPORTS", "true").lower() == "true"
                )
                if enable_reports and ReportingEngine:
                    self.reporting_engine = ReportingEngine(
                        memory_system=None,
                        supabase_client=self.db_conn,
                        pricing_engine=None,
                        send_message_callback=self.send_message,
                    )
                    logger.info("✅ ReportingEngine initialized (Daily Reports)")

                # OwnerNotificationSystem (Proactive Alerts)
                enable_notifications = (
                    os.getenv("ENABLE_OWNER_NOTIFICATIONS", "true").lower() == "true"
                )
                logger.info(f"🔍 ENABLE_OWNER_NOTIFICATIONS={os.getenv('ENABLE_OWNER_NOTIFICATIONS')} -> enable_notifications={enable_notifications}, OwnerNotificationSystem available={OwnerNotificationSystem is not None}")

                if enable_notifications and OwnerNotificationSystem:
                    self.notification_system = OwnerNotificationSystem(
                        owner_jid=self.owner_jid,
                        bridge_url=self.bridge_url,
                        supabase_client=self.db_conn,
                        analyzer=getattr(self.persona_manager, "analyzer", None)
                        if self.persona_manager
                        else None,
                        send_message_callback=self.send_message,
                    )
                    logger.info(
                        "✅ OwnerNotificationSystem initialized (Proactive Alerts)"
                    )
                else:
                    logger.warning(f"⚠️ OwnerNotificationSystem NOT initialized: enable_notifications={enable_notifications}, class available={OwnerNotificationSystem is not None}")

                # NotificationGroupsManager (3-Tier Notification System)
                self.groups_manager = None
                enable_groups = (
                    os.getenv("ENABLE_NOTIFICATION_GROUPS", "true").lower() == "true"
                )
                logger.info(f"🔍 ENABLE_NOTIFICATION_GROUPS={os.getenv('ENABLE_NOTIFICATION_GROUPS')} -> enable_groups={enable_groups}")

                if enable_groups:
                    try:
                        from src.saas.notification_groups import NotificationGroupsManager

                        self.groups_manager = NotificationGroupsManager(
                            supabase_client=self.db_conn,
                            bridge_url=self.bridge_url,
                            bridge_api_key=self.bridge_api_key,
                            owner_jid=self.owner_jid,
                            whatsapp_device_id=self.whatsapp_device_id
                        )
                        logger.info("✅ NotificationGroupsManager initialized (3-Tier System)")
                    except Exception as e:
                        logger.warning(f"⚠️ NotificationGroupsManager initialization failed: {e}")

                # Help Ticket Manager
                self.ticket_manager = None
                try:
                    from src.core.ticket_manager import TicketManager
                    self.ticket_manager = TicketManager(self.db_conn)
                    logger.info("✅ TicketManager initialized (help ticket system)")
                except Exception as e:
                    logger.warning(f"⚠️ TicketManager init failed: {e}")

                logger.info("✅ Phase 1 SaaS components initialized successfully")
            except Exception as e:
                logger.warning(f"⚠️ Phase 1 SaaS initialization failed: {e}")
        else:
            self.ticket_manager = None
        # =========================================================================

        # ==================== PHASE 2: MESSAGE FILTER & KNOWLEDGE ====================
        self.message_filter = None
        self.knowledge_uploader = None

        if MESSAGE_FILTER_AVAILABLE and self.db_conn:
            try:
                logger.info("🚀 Initializing Phase 2 Message Filter & Knowledge...")

                # MessageFilter (testing mode, ignore list, business hours)
                self.message_filter = MessageFilter(supabase_client=self.db_conn)
                logger.info("✅ MessageFilter initialized (Phase 2)")

                # KnowledgeUploader (document parsing and storage)
                self.knowledge_uploader = KnowledgeUploader(
                    supabase_client=self.db_conn
                )
                logger.info("✅ KnowledgeUploader initialized (Phase 2)")

                logger.info("✅ Phase 2 Filter & Knowledge components initialized")
            except Exception as e:
                logger.warning(
                    f"⚠️ Phase 2 Filter & Knowledge initialization failed: {e}"
                )
        # =========================================================================

        # ==================== PROACTIVE MESSAGING SYSTEM ====================
        self.proactive_messaging = None
        enable_proactive = (
            os.getenv("ENABLE_PROACTIVE_MESSAGING", "true").lower() == "true"
        )

        if enable_proactive and PROACTIVE_MESSAGING_AVAILABLE and self.db_conn:
            try:
                logger.info("📢 Initializing Proactive Messaging System...")

                # Get the bridge adapter for sending messages
                bridge_adapter = None
                try:
                    from src.channels.bridge_adapter import BridgeAdapter

                    bridge_adapter = BridgeAdapter(base_url=self.bridge_url)
                except ImportError:
                    logger.warning(
                        "⚠️ BridgeAdapter not available, proactive messaging will use fallback"
                    )

                self.proactive_messaging = ProactiveMessagingSystem(
                    db_connection=self.db_conn,
                    channel_adapter=bridge_adapter if bridge_adapter else self,
                )
                logger.info("✅ ProactiveMessagingSystem initialized")

                # Wire proactive system into call_booking_api so new bookings
                # automatically schedule 24h + 1h WA reminders.
                try:
                    from src.integrations.call_booking_api import set_proactive_system
                    set_proactive_system(self.proactive_messaging)
                except Exception as _wire_err:
                    logger.warning(f"⚠️ Could not wire proactive system into call_booking_api: {_wire_err}")

                # Note: Scheduler will be started in FastAPI startup event (async context)

            except Exception as e:
                logger.warning(f"⚠️ Proactive messaging initialization failed: {e}")
        # =========================================================================

        # ==================== ADVANCED REMINDER SYSTEM ====================
        self.reminder_system = None
        self.business_template_seeder = None
        enable_reminders = (
            os.getenv("ENABLE_ADVANCED_REMINDERS", "true").lower() == "true"
        )

        if enable_reminders and self.db_conn:
            try:
                logger.info("🔔 Initializing Advanced Reminder System...")

                # Advanced Reminder System - handles business-specific scheduling
                from src.core.advanced_reminder_system import AdvancedReminderSystem
                self.reminder_system = AdvancedReminderSystem(bijou_instance=self)
                logger.info("✅ AdvancedReminderSystem initialized (Business Reminders)")

                # Business Template Seeder - auto-seeds templates based on business type
                from src.saas.business_template_seeder import BusinessTemplateSeeder
                self.business_template_seeder = BusinessTemplateSeeder(supabase_client=self.db_conn)
                logger.info("✅ BusinessTemplateSeeder initialized (Auto Templates)")

            except Exception as e:
                logger.warning(f"⚠️ Advanced reminder system initialization failed: {e}")
        # =========================================================================

        logger.info(f"📊 Database: {self.db_type.upper()}")
        logger.info(f"🌉 Bridge: {self.bridge_url}")
        logger.info(f"📱 Owner: {self.owner_jid}")
        logger.info(f"🌐 Languages: {self.config['languages']}")
        logger.info(
            f"🎭 Render mode: {self.config.get('render_mode', 'human')} (bot=raw, human=persona)"
        )
        logger.info(
            f"🔔 Mode: {'WEBHOOK (push)' if self.webhook_mode else 'POLLING (pull)'}"
        )
        logger.info(
            f"📱 Channels: WhatsApp{'+ Telegram' if self.telegram_enabled else ' only'}"
        )

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _load_config(self) -> Dict:
        """Load configuration from environment"""
        return {
            "polling_interval": int(os.getenv("POLLING_INTERVAL", "2")),
            "languages": os.getenv("PRIMARY_LANGUAGES", "ms,zh,ta,en,en-my").split(","),
            "ai_model": os.getenv("AI_MODEL", "gemini-2.5-flash"),
            "max_retries": int(os.getenv("MAX_RETRIES", "3")),
            "gemini_api_key": os.getenv("GEMINI_API_KEY"),
            "openai_api_key": os.getenv("OPENAI_API_KEY"),
            "environment": os.getenv("ENVIRONMENT", "production"),
            "debug": os.getenv("DEBUG", "false").lower() == "true",
            "render_mode": os.getenv("RENDER_MODE", "human").lower(),  # 'bot' | 'human'
            # Max output tokens for LLM (prevents truncated mid-sentence responses)
            "max_output_tokens": int(os.getenv("MAX_TOKENS", "1024")),
        }

    def _ensure_db_initialized(self):
        """Lazy initialization of database on first use"""
        if self.db_conn is None and self.db_type:
            try:
                self._init_database()
            except Exception as e:
                logger.warning(f"⚠️ Database init failed: {e}")

    def _init_database(self):
        """Initialize database connection based on DB_TYPE"""
        try:
            if self.db_type == "supabase":
                self._init_supabase()
            else:
                self._init_sqlite()

            logger.info(f"✅ Database initialized: {self.db_type}")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            logger.info("⚠️ Running without database persistence")

    def _init_sqlite(self):
        """Initialize SQLite database"""
        import sqlite3

        db_path = os.getenv("BIJOU_DB_PATH", "/data/bijou.db")

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.db_conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = self.db_conn.cursor()

        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_jid TEXT NOT NULL,
                message_id TEXT,
                message_content TEXT,
                detected_language TEXT,
                detected_emotion TEXT,
                response TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                tenant_id TEXT DEFAULT 'default'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS escalations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_jid TEXT NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME,
                tenant_id TEXT DEFAULT 'default'
            )
        """)

        # ==================== PROACTIVE MESSAGING SCHEMA ====================
        # Apply proactive messaging tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_messages (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                recipient TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                scheduled_time TIMESTAMP NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                metadata TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                message_template TEXT NOT NULL,
                target_segment TEXT NOT NULL,
                scheduled_time TIMESTAMP NOT NULL,
                status TEXT NOT NULL,
                recipients TEXT NOT NULL,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS silence_rules (
                tenant_id TEXT PRIMARY KEY,
                silence_days INTEGER NOT NULL,
                message_template TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                last_check TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customer_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                customer_jid TEXT NOT NULL,
                last_message_at TIMESTAMP NOT NULL,
                message_count INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, customer_jid)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lead_followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                customer_jid TEXT NOT NULL,
                initial_contact_at TIMESTAMP NOT NULL,
                followup_count INTEGER DEFAULT 0,
                last_followup_at TIMESTAMP,
                next_followup_at TIMESTAMP,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==================== CALL BOOKING SCHEMA ====================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_bookings (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                customer_jid TEXT NOT NULL,
                customer_name TEXT,
                customer_phone TEXT,
                scheduled_time TIMESTAMP NOT NULL,
                duration_minutes INTEGER DEFAULT 30,
                call_type TEXT DEFAULT 'consultation',
                status TEXT DEFAULT 'scheduled',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reminder_sent BOOLEAN DEFAULT FALSE,
                confirmation_sent BOOLEAN DEFAULT FALSE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                day_of_week INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                timezone TEXT DEFAULT 'Asia/Kuala_Lumpur',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, day_of_week, start_time)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                duration_minutes INTEGER DEFAULT 30,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==================== ENHANCED AVAILABILITY SYSTEM ====================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT UNIQUE NOT NULL,
                timezone TEXT DEFAULT 'Asia/Kuala_Lumpur',
                buffer_minutes INTEGER DEFAULT 15,
                max_calls_per_day INTEGER DEFAULT 8,
                max_calls_per_hour INTEGER DEFAULT 2,
                advance_booking_days INTEGER DEFAULT 30,
                allow_same_day_booking BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS holiday_exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                date TEXT NOT NULL,
                title TEXT,
                description TEXT,
                is_recurring BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, date)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS availability_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                is_available BOOLEAN DEFAULT FALSE,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, date)
            )
        """)
        # =====================================================================

        self.db_conn.commit()
        logger.info(f"📁 SQLite initialized at: {db_path}")

    def _init_supabase(self):
        """Initialize Supabase PostgreSQL connection"""
        try:
            import jwt

            from supabase import Client, create_client

            supabase_url = os.getenv("SUPABASE_URL")
            # Use SERVICE_KEY for admin operations (bypasses RLS)
            supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv(
                "SUPABASE_KEY"
            )

            if not supabase_url or not supabase_key:
                raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")

            # Decode key to check role
            try:
                decoded = jwt.decode(supabase_key, options={"verify_signature": False})
                key_role = decoded.get("role", "unknown")
                logger.info(f"🔑 Using Supabase key with role: {key_role}")
                if key_role != "service_role":
                    logger.warning(
                        f"⚠️ Using '{key_role}' key - RLS policies will apply!"
                    )
            except Exception:
                logger.warning("⚠️ Could not decode Supabase key")

            self.db_conn: Client = create_client(supabase_url, supabase_key)
            logger.info(f"☁️ Supabase initialized: {supabase_url}")

        except ImportError:
            logger.error("❌ supabase-py not installed. Run: pip install supabase")
            raise
        except Exception as e:
            logger.error(f"❌ Supabase initialization failed: {e}")
            raise

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully.
        NOTE: Only set self.running = False here. Do NOT call sys.exit() or
        executor.shutdown() — uvicorn already handles SIGINT/SIGTERM cleanly
        and calling sys.exit() from a signal handler while asyncio is running
        causes SystemExit to propagate through the event loop, resulting in
        'Task exception was never retrieved' errors for fire-and-forget tasks.
        """
        logger.info(f"🛑 Received signal {signum}, shutting down gracefully...")
        self.running = False

    def _load_owner_devices(self) -> Dict[str, str]:
        """Load owner linked devices from database or file"""
        devices = {}

        # Try to load from Supabase first
        if self.db_type == "supabase" and self.db_conn:
            try:
                result = self.db_conn.table("owner_devices").select("*").execute()  # noaudit - system-level: loads all tenants' devices once at startup
                for row in result.data:
                    devices[row["device_jid"]] = row["owner_jid"]
                logger.info(
                    f"✅ Loaded {len(devices)} owner linked devices from Supabase"
                )
                return devices
            except Exception as e:
                logger.debug(f"Could not load devices from Supabase: {e}")

        # Fallback to local file
        devices_file = os.path.join("/data", "owner_devices.json")
        if os.path.exists(devices_file):
            try:
                with open(devices_file, "r") as f:
                    devices = json.load(f)
                logger.info(f"✅ Loaded {len(devices)} owner linked devices from file")
            except Exception as e:
                logger.warning(f"⚠️ Could not load owner devices file: {e}")

        return devices

    def _register_linked_device(self, device_jid: str):
        """Register a linked device as belonging to owner"""
        self.owner_linked_devices[device_jid] = self.owner_jid

        # Save to database
        if self.db_type == "supabase" and self.db_conn:
            try:
                self.db_conn.table("owner_devices").upsert(  # noaudit - system-level: no per-tenant context at device registration
                    {
                        "device_jid": device_jid,
                        "owner_jid": self.owner_jid,
                        "registered_at": datetime.now().isoformat(),
                    }
                ).execute()
                logger.info(f"✅ Registered linked device in Supabase: {device_jid}")
            except Exception as e:
                logger.warning(f"⚠️ Could not save to Supabase: {e}")

        # Always save to local file as backup
        devices_file = os.path.join("/data", "owner_devices.json")
        try:
            os.makedirs("/data", exist_ok=True)
            with open(devices_file, "w") as f:
                json.dump(self.owner_linked_devices, f, indent=2)
            logger.info(f"✅ Registered linked device in file: {device_jid}")
        except Exception as e:
            logger.warning(f"⚠️ Could not save owner devices file: {e}")

    def poll_new_messages(self) -> List[Dict]:
        """
        Poll WhatsApp bridge for new messages

        Returns list of new messages to process
        """
        self.poll_count += 1

        try:
            # Method 1: Try direct database access (fastest) - only if path is set
            if self.bridge_db_path and os.path.exists(self.bridge_db_path):
                return self._poll_from_bridge_db()

            # Method 2: Fallback to HTTP API
            return self._poll_from_bridge_api()

        except Exception as e:
            if self.poll_count % 10 == 0:  # Log every 10th error to reduce noise
                logger.error(f"❌ POLL {self.poll_count} - Error polling: {e}")
            return []

    def _poll_from_bridge_db(self) -> List[Dict]:
        """Poll directly from bridge SQLite database"""
        import sqlite3

        try:
            conn = sqlite3.connect(self.bridge_db_path, check_same_thread=False)
            cursor = conn.cursor()

            # Get new messages since last poll
            query = """
                SELECT id, chat_jid, sender, content, timestamp
                FROM messages
                WHERE is_from_me = 0
                AND datetime(substr(timestamp, 1, 19)) > datetime(?)
                ORDER BY timestamp ASC
                LIMIT 50
            """

            last_poll_str = self.last_poll_time.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(query, (last_poll_str,))
            rows = cursor.fetchall()
            conn.close()

            # Convert to dict and filter already processed
            messages = []
            for row in rows:
                msg_id = row[0]
                if msg_id not in self.processed_message_ids:
                    messages.append(
                        {
                            "id": msg_id,
                            "chat_jid": row[1],
                            "sender": row[2],
                            "content": row[3],
                            "timestamp": row[4],
                        }
                    )

            if messages:
                logger.info(
                    f"[POLL {self.poll_count}] Found {len(messages)} new message(s)"
                )

            return messages

        except Exception as e:
            logger.error(f"[ERROR] Error reading bridge DB: {e}")
            raise

    def _poll_from_bridge_api(self) -> List[Dict]:
        """Fallback: Poll via bridge HTTP API"""
        try:
            # Use timestamp 1 second in the past to avoid missing messages
            since_time = (self.last_poll_time - timedelta(seconds=1)).isoformat()

            logger.debug(f"[POLL] Querying bridge with since={since_time}")

            response = requests.get(
                f"{self.bridge_url}/api/messages",
                params={"since": since_time},
                timeout=30,  # Increased from 5s to handle cloud latency
            )

            if response.status_code == 200:
                messages = response.json().get("messages", [])

                # Handle None case
                if messages is None:
                    messages = []

                # Filter by timestamp AND already processed IDs (for current session only)
                new_messages = []
                for msg in messages:
                    msg_id = msg.get("id")
                    msg_timestamp = msg.get("timestamp")

                    # Skip if already processed in this session
                    if msg_id in self.processed_message_ids:
                        logger.debug(f"[POLL] Skipping already-processed ID: {msg_id}")
                        continue

                    # Skip if message is older than last poll time
                    if msg_timestamp:
                        try:
                            msg_time = datetime.fromisoformat(
                                msg_timestamp.replace("Z", "+00:00")
                            )
                            if msg_time <= self.last_poll_time:
                                logger.debug(
                                    f"[POLL] Skipping old message from {msg_time.isoformat()}"
                                )
                                continue
                        except Exception as e:
                            logger.debug(
                                f"[POLL] Timestamp parse failed for {msg_id}: {e}"
                            )
                            pass  # If timestamp parsing fails, include the message

                    new_messages.append(msg)

                if new_messages:
                    logger.info(
                        f"[POLL {self.poll_count}] Found {len(new_messages)} new message(s) via API (total returned: {len(messages)})"
                    )
                elif messages:
                    logger.debug(
                        f"[POLL {self.poll_count}] Bridge returned {len(messages)} messages but all were filtered"
                    )

                return new_messages
            else:
                logger.warning(f"[WARN] Bridge API returned {response.status_code}")
                return []

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Bridge API request failed: {e}")
            return []

    # ==================== TAKEOVER / BLACKLIST HELPERS ====================

    async def _get_conversation_status(self, supabase, tenant_id: str, chat_jid: str) -> str:
        """
        Return 'human' if agent has taken over this chat, else 'ai'.

        Status is tracked via escalations table (status='in_progress' means human is handling).
        Conversations table does NOT have a status column - using escalations for takeover tracking.
        """
        try:
            # Check escalations table for active human takeover
            result = (
                supabase.table("escalations")
                .select("status")
                .eq("tenant_id", tenant_id)
                .eq("chat_jid", chat_jid)
                .eq("status", "in_progress")  # Active escalation = human mode
                .limit(1)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return "human"  # Human agent is actively handling this chat
            return "ai"  # No active escalation = AI mode
        except Exception as e:
            logger.warning(f"⚠️ Could not read conversation status for {chat_jid}: {e}")
            return "ai"  # fail-open: AI handles if DB is unreachable

    async def _is_number_blacklisted(self, supabase, tenant_id: str, chat_jid: str) -> bool:
        """Return True if this phone number is in the blocked_numbers table for this tenant."""
        try:
            # Normalize: strip @s.whatsapp.net / @lid suffix
            phone = chat_jid.split("@")[0] if "@" in chat_jid else chat_jid
            result = (
                supabase.table("blocked_numbers")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("phone_number", phone)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            return len(result.data) > 0
        except Exception as e:
            logger.warning(f"⚠️ Blacklist check failed for {chat_jid}: {e}")
            return False  # fail-open: never accidentally block

    # ======================================================================

    async def process_message(self, message: Dict):
        """Process a single incoming message with TRACE framework"""
        try:
            msg_id = message.get("id")
            chat_jid = message.get("chat_jid")
            content = message.get("content", "")
            is_from_me = message.get("is_from_me", False)
            media_type = message.get("media_type")
            media_url = message.get("media_url")
            filename = message.get("filename")
            sender = message.get("sender", "")
            from_name = message.get("from_name", "")  # Contact name from WhatsApp
            channel = message.get("channel")  # Extract channel early for use throughout function

            # 🐛 DEBUG: Log media fields to diagnose missing media processing
            if media_type:
                logger.info(f"📎 Media detected - Type: {media_type}")
                logger.info(
                    f"   media_url: {media_url if media_url else 'MISSING/NULL'}"
                )
                logger.info(f"   filename: {filename if filename else 'N/A'}")
                logger.info(f"   message_id: {msg_id}")

                # 🔧 FIX: Construct media_url if missing (bridge pattern)
                if not media_url:
                    bridge_url = self.config.get(
                        "bridge_url", os.getenv("BRIDGE_URL", "")
                    )
                    if bridge_url:
                        media_url = (
                            f"{bridge_url}/api/media/{msg_id}?chat_jid={chat_jid}"
                        )
                        logger.info(f"   🔧 Constructed media_url: {media_url}")
                    else:
                        logger.warning(
                            f"   ⚠️ Cannot construct media_url - BRIDGE_URL not configured"
                        )

            # === PHASE 2: Multi-Tenant Routing ===
            tenant_id = None
            client_config = None
            if self.tenant_router:
                try:
                    # Get business_jid and device_id for tenant routing
                    business_jid = message.get("business_jid")
                    device_id = message.get("device_id")

                    # Normalize device JID (strip :N suffix) and stamp onto message
                    # so downstream functions (_save_message) can read it without
                    # repeating the extraction logic.
                    _raw_device_jid = normalize_device_jid(business_jid) if business_jid else None
                    message["device_jid"] = _raw_device_jid

                    # Use identify_tenant with device_id priority (business account) for correct routing
                    tenant_id = await self.tenant_router.identify_tenant(
                        chat_jid=chat_jid, sender=sender, business_jid=business_jid, device_id=device_id
                    )

                    if tenant_id:
                        logger.info(
                            f"🏢 Tenant ID: {tenant_id} | chat_jid: {chat_jid} | business_jid: {business_jid}"
                        )
                        message["tenant_id"] = tenant_id

                        # Load client config
                        client_config = await self.tenant_router.get_client_config(
                            tenant_id
                        )
                        if client_config:
                            # Store tenant_id in config for persona lookup
                            client_config["tenant_id"] = tenant_id
                            logger.info(
                                f"⚙️ Client config loaded: {client_config.get('business_name', 'N/A')}"
                            )
                        else:
                            # FALLBACK: Tenant exists in whatsapp_devices but missing client_config
                            # This happens during incomplete onboarding or manual device registration
                            logger.warning(
                                f"⚠️ No client_config found for tenant {tenant_id} - using default persona"
                            )
                            client_config = {
                                "tenant_id": tenant_id,
                                "business_name": "Business Assistant",
                                "industry": "general",
                                "persona_name": "Bijou",
                                "tone": "friendly_professional",
                                "language": "en",
                                "timezone": "Asia/Kuala_Lumpur",
                                "business_description": "A helpful AI assistant",
                                "core_values": "helpful, professional, friendly",
                                "response_style": "concise and clear"
                            }
                            logger.info(f"⚙️ Using fallback config for tenant {tenant_id}")
                    else:
                        # No tenant found - this is a test user or customer visiting owner's WhatsApp
                        # Bijou should still respond as the owner's AI assistant (demo/test mode)
                        logger.warning(
                            f"⚠️ No tenant found for chat_jid: {chat_jid}, sender: {sender}, business_jid: {business_jid}"
                        )
                        logger.info(f"💼 Treating as demo/test visitor - Bijou will respond as owner's AI assistant")

                        # Use default tenant ID (owner's personal assistant mode)
                        # Requires DEFAULT_TENANT_ID to be set in .env — if absent, message is dropped safely
                        tenant_id = os.getenv("DEFAULT_TENANT_ID")
                        if not tenant_id:
                            logger.error(
                                f"❌ No tenant found for {chat_jid} and DEFAULT_TENANT_ID not set — dropping message"
                            )
                            return
                        message["tenant_id"] = tenant_id

                        # Load default client config for owner's assistant
                        client_config = await self.tenant_router.get_client_config(tenant_id)
                        if client_config:
                            client_config["tenant_id"] = tenant_id
                            logger.info(f"⚙️ Using default config for demo mode")
                        else:
                            # FALLBACK: Default tenant missing client_config
                            logger.warning(
                                f"⚠️ No client_config for DEFAULT_TENANT_ID {tenant_id} - using fallback"
                            )
                            client_config = {
                                "tenant_id": tenant_id,
                                "business_name": "Business Assistant",
                                "industry": "general",
                                "persona_name": "Bijou",
                                "tone": "friendly_professional",
                                "language": "en",
                                "timezone": "Asia/Kuala_Lumpur",
                                "business_description": "A helpful AI assistant",
                                "core_values": "helpful, professional, friendly",
                                "response_style": "concise and clear"
                            }
                            logger.info(f"⚙️ Using fallback config for demo mode")

                        # Continue processing - DO NOT send robotic welcome message
                        # Bijou acts as your FOH AI assistant for all visitors

                except Exception as e:
                    logger.error(f"❌ Tenant routing failed: {e}")
            # === END PHASE 2 ===

            # === PHASE 2.25: Blacklist & Human-Takeover Guard ===
            if tenant_id and not is_from_me:
                try:
                    _supabase = getattr(self, "supabase", None) or getattr(
                        self.tenant_router, "supabase", None
                    )
                    if _supabase:
                        # 1. Blacklist check — silently drop message if number is blocked
                        if await self._is_number_blacklisted(_supabase, tenant_id, chat_jid):
                            logger.info(
                                f"🚫 [BLACKLIST] Dropping message from {chat_jid} (tenant={tenant_id})"
                            )
                            return  # Hard stop — no AI reply, no escalation

                        # 2. Takeover check — AI stays silent if human agent is handling chat
                        _conv_status = await self._get_conversation_status(
                            _supabase, tenant_id, chat_jid
                        )
                        if _conv_status == "human":
                            logger.info(
                                f"🙋 [TAKEOVER] Human agent active for {chat_jid} — AI skipping (tenant={tenant_id})"
                            )
                            # Still save the message so human agent sees it in dashboard
                            try:
                                _device_jid = message.get("device_jid")
                                _chat_type = "group" if chat_jid and chat_jid.endswith("@g.us") else "individual"
                                await self._save_message(
                                    chat_jid, tenant_id, "user", content or "",
                                    device_jid=_device_jid, chat_type=_chat_type,
                                    media_url=media_url, media_type=media_type,
                                )
                                # Update conversations table so inbox shows latest message
                                if self.db_type == "supabase" and self.db_conn:
                                    self.db_conn.table("conversations").insert({
                                        "tenant_id": tenant_id,
                                        "chat_jid": chat_jid,
                                        "message_id": msg_id,
                                        "message_content": content or "",
                                        "sender": sender,
                                        "contact_name": from_name or "",
                                        "is_from_me": False,
                                        "ai_response": None,
                                        "timestamp": datetime.now().isoformat(),
                                        "created_at": datetime.now().isoformat(),
                                    }).execute()
                                logger.info(f"💾 [TAKEOVER] Message saved for human agent: {msg_id}")
                            except Exception as _save_err:
                                logger.warning(f"⚠️ [TAKEOVER] Failed to save message: {_save_err}")
                            return  # Human has the wheel — AI stays quiet
                except Exception as e:
                    logger.warning(f"⚠️ PHASE 2.25 guard failed (fail-open): {e}")
            # === END PHASE 2.25 ===

            # === PHASE 2.5: Message Filter Check ===
            # Check if we should reply based on testing mode, ignore list, business hours
            if tenant_id and self.message_filter:
                try:
                    # Extract sender phone number (remove @s.whatsapp.net or @lid)
                    sender_phone = (
                        sender.split("@")[0] if sender and "@" in sender else sender
                    )

                    # Check if this is first message from sender (for welcome message logic)
                    is_first_message = False  # TODO: Track in conversation history

                    should_reply, reason = self.message_filter.should_reply(
                        tenant_id=tenant_id,
                        sender_number=sender_phone,
                        is_first_message=is_first_message,
                    )

                    if not should_reply:
                        logger.info(f"🚫 Message filter: NOT replying - {reason}")

                        # Special case: Outside business hours - AI stays silent (no bot-like auto-reply)
                        # But allow escalations to bypass business hours
                        if reason and reason.startswith("OUTSIDE_HOURS"):
                            escalation_keywords = [
                                "speak to",
                                "talk to human",
                                "real person",
                                "manager",
                                "not helping",
                                "doesn't understand",
                                "urgent",
                                "emergency",
                            ]
                            message_text = (content or "").lower()
                            if any(
                                keyword in message_text
                                for keyword in escalation_keywords
                            ):
                                logger.info(
                                    "🔓 Bypassing business hours for escalation request"
                                )
                                should_reply = True
                            else:
                                logger.info(
                                    f"🤫 AI staying silent - outside business hours (no auto-reply)"
                                )

                        if not should_reply:
                            # Mark as processed and skip
                            self.processed_message_ids.add(msg_id)
                            return
                    else:
                        logger.debug(f"✅ Message filter: OK to reply")

                except Exception as e:
                    logger.error(f"❌ Message filter check failed: {e}", exc_info=True)
                    # Fail-open: Allow reply if filter check fails
            # === END PHASE 2.5 ===

            # ✅ CRITICAL FIX 0: Reject OLD messages (history sync / replay)
            # Bridge re-sends old messages on reconnect - we must NOT respond to them
            msg_timestamp = message.get("timestamp") or message.get("Time")
            max_age_minutes = int(os.getenv("WEBHOOK_MAX_MESSAGE_AGE_MINUTES", "15"))
            if msg_timestamp:
                try:
                    if isinstance(msg_timestamp, str):
                        ts = datetime.fromisoformat(
                            msg_timestamp.replace("Z", "+00:00")
                        )
                    else:
                        ts = msg_timestamp
                    if hasattr(ts, "tzinfo") and ts.tzinfo:
                        now = datetime.now(ts.tzinfo)
                    else:
                        now = datetime.now()
                    age_seconds = (now - ts).total_seconds()
                    if age_seconds > max_age_minutes * 60:
                        logger.info(
                            f"⏭️ Skipping OLD message (replay): {msg_id} age={age_seconds / 60:.0f}min"
                        )
                        self.processed_message_ids.add(msg_id)
                        return
                except Exception as e:
                    logger.debug(f"Timestamp parse failed for {msg_id}: {e}")

            # ✅ CRITICAL FIX 1: Check if already processed (in-session deduplication)
            if msg_id in self.processed_message_ids:
                return  # Silent skip for already processed

            # ✅ CRITICAL FIX 2: Ignore our own messages (prevents infinite loops)
            if is_from_me:
                logger.info(f"⏭️ Skipping our own message {msg_id}")
                self.processed_message_ids.add(msg_id)  # Mark as processed
                return

            # ✅ CRITICAL FIX 3: Ignore empty/typing indicator messages (unless has media)
            # IMPORTANT: Don't add to processed_message_ids - WhatsApp sends empty messages first, then full message
            if not media_type and (not content or len(content.strip()) < 2):
                logger.info(f"⏭️ Skipping empty/typing message {msg_id} from {chat_jid} (waiting for full message)")
                return  # Don't mark as processed - wait for actual content

            # ✅ CRITICAL FIX 3.5: Ignore HEARTBEAT_OK and automated bot messages
            # Prevents Bijou from responding to Clawdbot's automated heartbeat checks
            IGNORED_KEYWORDS = [
                "HEARTBEAT_OK",
                "AUTO:",
                "BOT:",
                "[SYSTEM]",
                "[AUTOMATED]",
            ]
            if content and any(keyword in content for keyword in IGNORED_KEYWORDS):
                logger.info(f"🤖 Ignoring automated message: {content[:50]}...")
                self.processed_message_ids.add(msg_id)
                return

            # ✅ CRITICAL FIX 4: AI-to-AI Loop Prevention (narrow - only obvious AI self-intros)
            # Relaxed for user request: "Bijou must respond to its name regardless of other bots."
            # We ONLY block if we see specific "I go quiet..." phrases that indicate looping behavior.
            ai_indicators = [
                "I go quiet if another AI",
                "AI conversation loop",
            ]
            content_lower = content.lower() if content else ""
            if any(indicator.lower() in content_lower for indicator in ai_indicators):
                logger.warning(
                    f"🤖 AI-to-AI loop detected! Skipping message from {chat_jid}"
                )
                logger.warning(f"   Content preview: {content[:100]}...")
                self.processed_message_ids.add(msg_id)
                return

            # ✅ CRITICAL FIX 5: Rate Limiting (prevents flood attacks and runaway loops)
            now = datetime.now()
            if chat_jid not in self.rate_limiter:
                self.rate_limiter[chat_jid] = {"count": 0, "window_start": now}

            rate_data = self.rate_limiter[chat_jid]
            elapsed = (now - rate_data["window_start"]).total_seconds()

            # Reset window if expired
            if elapsed > self.rate_limit_window:
                rate_data["count"] = 0
                rate_data["window_start"] = now

            # Check rate limit
            rate_data["count"] += 1
            if rate_data["count"] > self.rate_limit_max:
                logger.warning(
                    f"🚫 Rate limit exceeded for {chat_jid}: "
                    f"{rate_data['count']}/{self.rate_limit_max} messages in {elapsed:.0f}s"
                )
                self.processed_message_ids.add(msg_id)
                return

            content = content.strip() if content else ""

            # ✅ CRITICAL FIX 6: Self-echo / Daydream prevention
            # Bridge echoes our sent messages back; skip if incoming matches our recent send
            if content and chat_jid in self.recent_sent:
                incoming_preview = content[:150].strip()
                for sent_preview, sent_at in list(self.recent_sent[chat_jid]):
                    if (now - sent_at).total_seconds() > self.recent_sent_ttl:
                        continue
                    # Match: incoming is our echo (exact or significant overlap)
                    if (
                        incoming_preview == sent_preview[:150]
                        or sent_preview[:80] in incoming_preview
                        or incoming_preview[:80] in sent_preview
                    ):
                        logger.warning(
                            f"🔄 Self-echo detected! Skipping our own message echoed back from bridge"
                        )
                        logger.warning(
                            f"   chat: {chat_jid} | preview: {incoming_preview[:60]}..."
                        )
                        self.processed_message_ids.add(msg_id)
                        return
            logger.info(f"🔍 Processing message {msg_id}")
            logger.info(f"   chat_jid: {chat_jid}")
            logger.info(f"   sender: {sender}")
            if content:
                logger.info(f"   content: {content[:100]}...")
            if media_type:
                logger.info(f"📎 Media: {media_type}")

            # === PHASE 1: Owner Command Detection ===
            # Extract owner phone from JID for comparison (handles @lid and @s.whatsapp.net)
            owner_phone = self.owner_jid.split("@")[0].replace("+", "")
            sender_phone = sender.split("@")[0] if "@" in sender else sender
            chat_phone = chat_jid.split("@")[0] if "@" in chat_jid else chat_jid

            # Owner can send from:
            # 1. Direct DM: chat_jid = owner_jid (from env)
            # 2. Group chat: sender = owner_jid (from env)
            # 3. Linked device: chat_jid = 84950644740196@lid (mapped to owner)
            is_owner_dm = chat_phone == owner_phone  # DM from owner phone
            is_owner_sender = sender_phone == owner_phone  # Owner in group chat
            is_owner_linked = chat_jid in self.owner_linked_devices  # Linked device

            is_owner = is_owner_dm or is_owner_sender or is_owner_linked

            # Debug logging for owner detection (use INFO for visibility)
            if content.startswith("/owner"):
                logger.info(f"🔍 Owner Detection for /owner command:")
                logger.info(f"   Owner JID: {self.owner_jid}")
                logger.info(f"   Owner Phone: {owner_phone}")
                logger.info(f"   Chat JID: {chat_jid}")
                logger.info(f"   Chat Phone: {chat_phone}")
                logger.info(f"   Sender: {sender}")
                logger.info(f"   Sender Phone: {sender_phone}")
                logger.info(f"   Is Owner DM: {is_owner_dm}")
                logger.info(f"   Is Owner Sender: {is_owner_sender}")
                logger.info(f"   Is Owner Linked Device: {is_owner_linked}")
                logger.info(
                    f"   Registered Devices: {list(self.owner_linked_devices.keys())}"
                )
                logger.info(f"   Final Is Owner: {is_owner}")

            # Special case: Register linked device command (works even if not registered yet)
            if content.startswith("/owner") and chat_jid.endswith("@lid"):
                # Check if this is the owner trying to register their linked device
                # Allow registration if message contains secret phrase
                if "register device" in content.lower() and self.owner_jid in content:
                    logger.info(f"🔑 Owner device registration request from {chat_jid}")
                    self._register_linked_device(chat_jid)
                    self.send_message(
                        chat_jid,
                        f"✅ Linked device registered!\n\n"
                        f"Device: {chat_jid}\n"
                        f"Owner: {self.owner_jid}\n\n"
                        f"You can now use /owner commands from this device.",
                        tenant_id=tenant_id,
                    )
                    self.processed_message_ids.add(msg_id)
                    return

            # === GROUP REGISTRATION COMMAND ===
            # Owner OR secondary owner can manually create groups and register them with Bijou
            # Format: "Register group: Bijou Escalations" (from group chat)
            secondary_owner_jid = os.getenv("SECONDARY_OWNER_JID", "").strip()
            is_secondary_owner = secondary_owner_jid and sender == secondary_owner_jid

            if (is_owner or is_secondary_owner) and content and "register group" in content.lower():
                if hasattr(self, "groups_manager") and self.groups_manager:
                    try:
                        # Check if message is from a group chat
                        if not chat_jid.endswith("@g.us"):
                            self.send_message(
                                chat_jid,
                                "⚠️ Please send this command FROM the group you want to register.",
                                tenant_id=tenant_id,
                            )
                            self.processed_message_ids.add(msg_id)
                            return

                        # Extract group name from message
                        # Format: "Register group: Bijou Escalations"
                        parts = content.split(":", 1)
                        if len(parts) < 2:
                            self.send_message(
                                chat_jid,
                                "⚠️ Format: Register group: <group name>\n\n"
                                "Valid names:\n"
                                "• Bijou Escalations\n"
                                "• Bijou Hot Leads\n"
                                "• Bijou Updates",
                                tenant_id=tenant_id,
                            )
                            self.processed_message_ids.add(msg_id)
                            return

                        group_name = parts[1].strip()
                        group_jid = chat_jid

                        logger.info(f"📝 Registering group: {group_name} ({group_jid})")

                        # Register the group
                        success = await self.groups_manager.register_group_manually(
                            tenant_id=tenant_id,
                            group_name=group_name,
                            group_jid=group_jid
                        )

                        if success:
                            self.send_message(
                                chat_jid,
                                f"✅ Group registered successfully!\n\n"
                                f"Name: {group_name}\n"
                                f"Type: {group_jid}\n\n"
                                f"Bijou will now send notifications to this group.",
                                tenant_id=tenant_id,
                            )
                        else:
                            self.send_message(
                                chat_jid,
                                f"❌ Failed to register group. Please check:\n"
                                f"• Group name is correct\n"
                                f"• Group isn't already registered\n\n"
                                f"Valid names:\n"
                                f"• Bijou Escalations\n"
                                f"• Bijou Hot Leads\n"
                                f"• Bijou Updates",
                                tenant_id=tenant_id,
                            )

                        self.processed_message_ids.add(msg_id)
                        return

                    except Exception as e:
                        logger.error(f"❌ Group registration failed: {e}")
                        self.send_message(
                            chat_jid,
                            f"❌ Registration failed: {str(e)}",
                            tenant_id=tenant_id,
                        )
                        self.processed_message_ids.add(msg_id)
                        return
            # === END GROUP REGISTRATION ===

            # === HELP TICKET GROUP HANDLER ===
            # Every message in the registered "help_tickets" group becomes a tracked ticket.
            # Owner commands (@bijou close, @bijou escalate) are also handled here.
            if (
                chat_jid.endswith("@g.us")
                and hasattr(self, "ticket_manager")
                and self.ticket_manager
                and content
            ):
                try:
                    if self.db_conn:
                        _tg_result = self.db_conn.table("notification_groups") \
                            .select("group_type") \
                            .eq("group_jid", chat_jid) \
                            .limit(1) \
                            .execute()
                        _is_ticket_group = (
                            _tg_result.data
                            and _tg_result.data[0].get("group_type") == "help_tickets"
                        )
                    else:
                        _is_ticket_group = False

                    if _is_ticket_group:
                        _tk_result = await self.ticket_manager.handle_group_message(
                            tenant_id=tenant_id,
                            group_jid=chat_jid,
                            sender_jid=sender,
                            sender_name=from_name or "",
                            content=content,
                        )
                        if _tk_result.get("reply"):
                            self.send_message(chat_jid, _tk_result["reply"], tenant_id=tenant_id)
                        self.processed_message_ids.add(msg_id)
                        return
                except Exception as _tk_err:
                    logger.error(f"❌ Ticket group handler error: {_tk_err}")
            # === END HELP TICKET GROUP HANDLER ===

            # === @BIJOU OWNER COMMANDS ===
            if (
                is_owner
                and content
                and content.strip().startswith("@bijou")
                and self.command_handler
                and os.getenv("ENABLE_BIJOU_COMMANDS", "true").lower() == "true"
            ):
                logger.info(f"🤖 @bijou command from owner: {content[:60]}")
                try:
                    response = await self.command_handler.handle_command(
                        message=message,
                        chat_jid=chat_jid,
                        sender=sender,
                        tenant_id=tenant_id,
                    )
                    if response:
                        self.send_message(chat_jid, response, tenant_id=tenant_id)
                except Exception as e:
                    logger.error(f"❌ @bijou command error: {e}")
                    self.send_message(
                        chat_jid,
                        f"❌ Command error: {str(e)[:100]}",
                        tenant_id=tenant_id,
                    )
                self.processed_message_ids.add(msg_id)
                return
            # === END @BIJOU COMMANDS ===

            # === CUSTOMER @BIJOU ESCALATE (DM, non-owner) ===
            # Customers can type "@bijou escalate" in their private DM to request a human.
            if (
                not is_owner
                and not chat_jid.endswith("@g.us")
                and content
                and "@bijou escalate" in content.strip().lower()
            ):
                logger.info(f"🤝 Customer escalation via @bijou: {sender}")
                self.send_message(
                    chat_jid,
                    "⏳ *Escalation Requested*\n\n"
                    "You've asked to speak with a human agent — our team has been notified. 🙏\n"
                    "We'll join this conversation shortly. In the meantime, feel free to describe your issue.",
                    tenant_id=tenant_id,
                )
                _owner_wa = os.getenv("BIJOU_OWNER_WA", "").strip()
                if _owner_wa:
                    _cust_alert = (
                        f"🤝 *Customer Escalation (via @bijou)*\n"
                        f"📞 {from_name or 'Customer'} — {self._format_phone(sender)}\n"
                        f"💬 Requested human handover in private chat"
                    )
                    asyncio.create_task(
                        self._notify_bijou_owner(owner_wa=_owner_wa, message=_cust_alert, tenant_id=tenant_id)
                    )
                self.processed_message_ids.add(msg_id)
                return
            # === END CUSTOMER ESCALATE ===

            if is_owner and content.startswith("/owner"):
                if hasattr(self, "persona_manager") and self.persona_manager:
                    try:
                        logger.info(f"👑 Owner command detected from {sender}")
                        logger.info(f"🎯 Processing owner command: {content}")
                        result = self.persona_manager.process_owner_command(
                            raw_command=content,
                            chat_jid=chat_jid,
                            owner_jid=self.owner_jid,
                            tenant_id=tenant_id,
                        )
                        self.send_message(
                            chat_jid,
                            result.get("message", "✅ Command executed"),
                            tenant_id=tenant_id,
                        )
                        self.processed_message_ids.add(msg_id)
                        return  # Don't process as normal message
                    except Exception as e:
                        logger.error(f"❌ Owner command failed: {e}")
                        self.send_message(
                            chat_jid,
                            f"❌ Command failed: {str(e)}",
                            tenant_id=tenant_id,
                        )
                        self.processed_message_ids.add(msg_id)
                        return
                else:
                    # Persona manager not available, send helpful message
                    self.send_message(
                        chat_jid,
                        f"⚠️ Owner commands detected but persona system not initialized.\n\n"
                        f"Your device: {chat_jid}\n"
                        f"Is recognized as owner: {is_owner}\n\n"
                        f"To register this linked device, send:\n"
                        f"/owner register device {self.owner_jid}",
                        tenant_id=tenant_id,
                    )
                    self.processed_message_ids.add(msg_id)
                    return
            # === END PHASE 1 ===

            # Check if escalated
            if self.is_escalated(chat_jid):
                logger.info(f"⏸️ Chat {chat_jid} is escalated - skipping AI response")
                return

            # === GROUP CHAT DETECTION ===
            from src.core.jid_utils import is_group_chat

            if is_group_chat(chat_jid):
                # Check if group chat support is enabled (global setting)
                enable_groups = os.getenv("ENABLE_GROUP_CHAT_SUPPORT", "false").lower() == "true"

                # Check tenant-specific setting if client_config is available
                if client_config:
                    enable_groups = client_config.get("enable_group_chat", enable_groups)

                if not enable_groups:
                    logger.info(f"⏭️ Skipping group chat (support disabled): {chat_jid}")
                    # Mark as processed to prevent re-processing
                    self.processed_message_ids.add(msg_id)
                    return
                else:
                    logger.info(f"📢 Processing group chat (support enabled): {chat_jid}")
                    # Add metadata for group chat processing
                    message["is_group_chat"] = True

                    # Update chat_type for silent mode processing
                    chat_type = "group"
            else:
                # Direct message (default)
                message["is_group_chat"] = False
                chat_type = "direct"
            # === END GROUP CHAT DETECTION ===

            # === SILENT OBSERVE MODE ===
            # Check for quiet/active commands FIRST (before silent mode check)
            # Support both @bijou commands and simple /commands
            if content:
                content_lower = content.strip().lower()

                # Simple command check (no @bijou needed)
                if content_lower in ["/quiet", "/active", "/status", "/help"]:
                    from src.core.silent_mode import get_silent_mode

                    silent_mode = get_silent_mode()

                    if content_lower == "/quiet":
                        response = silent_mode.enable()
                    elif content_lower == "/active":
                        response = silent_mode.disable()
                    elif content_lower == "/status":
                        response = silent_mode.get_status()
                    elif content_lower == "/help":
                        response = """
🤖 **Bijou AI Commands**

**Silent Mode:**
• `/quiet` or `@bijou quiet` - Enable silent observe mode
• `/active` or `@bijou active` - Return to normal mode
• `/status` or `@bijou status` - Check current mode

**Other Commands:**
• `@bijou help` - Show this help
• `@bijou summarize` - Summarize conversation
• `@bijou escalate` - Request human agent

**Silent Mode:** I'll only respond when:
- Directly mentioned or asked a question
- In direct 1-on-1 chat
- Urgent keywords detected

Use `/quiet` to reduce my chattiness!
                        """.strip()

                    self.send_message(chat_jid, response, tenant_id=tenant_id)
                    self.processed_message_ids.add(msg_id)
                    return

                # @bijou command check
                if self.command_parser and self.command_parser.is_command(content):
                    command = self.command_parser.parse(content)
                    if command:
                        if command.type == "quiet":
                            from src.core.silent_mode import get_silent_mode

                            silent_mode = get_silent_mode()
                            response = silent_mode.enable()
                            self.send_message(chat_jid, response, tenant_id=tenant_id)
                            self.processed_message_ids.add(msg_id)
                            return
                        elif command.type == "active":
                            from src.core.silent_mode import get_silent_mode

                            silent_mode = get_silent_mode()
                            response = silent_mode.disable()
                            self.send_message(chat_jid, response, tenant_id=tenant_id)
                            self.processed_message_ids.add(msg_id)
                            return
                        elif command.type == "status":
                            from src.core.silent_mode import get_silent_mode

                            silent_mode = get_silent_mode()
                            response = silent_mode.get_status()
                            self.send_message(chat_jid, response, tenant_id=tenant_id)
                            self.processed_message_ids.add(msg_id)
                            return
                        elif command.type == "help":
                            help_text = """
🤖 **Bijou AI Commands**

**Silent Mode:**
• `/quiet` or `@bijou quiet` - Enable silent observe mode
• `/active` or `@bijou active` - Return to normal mode
• `/status` or `@bijou status` - Check current mode

**Other Commands:**
• `@bijou help` - Show this help
• `@bijou summarize` - Summarize conversation
• `@bijou escalate` - Request human agent

**Silent Mode:** I'll only respond when:
- Directly mentioned or asked a question
- In direct 1-on-1 chat
- Urgent keywords detected

Use `/quiet` to reduce my chattiness!
                            """
                            self.send_message(
                                chat_jid, help_text.strip(), tenant_id=tenant_id
                            )
                            self.processed_message_ids.add(msg_id)
                            return

            # Check if silent mode is enabled and we should stay quiet
            if content:
                from src.core.silent_mode import get_silent_mode

                silent_mode = get_silent_mode()

                # chat_type already set by group chat detection above
                # (defaults to "direct" for non-group chats, "group" for group chats)

                # Check if we should respond
                should_respond = silent_mode.should_respond(
                    message=content,
                    sender=sender,
                    chat_type=chat_type,
                    is_command=False,  # Commands already handled above
                )

                if not should_respond:
                    logger.info(f"🤫 Silent mode: Observing without response")
                    self.processed_message_ids.add(msg_id)
                    return
            # === END SILENT OBSERVE MODE ===

            # === HUMAN HANDOVER CHECK ===
            # If a human agent has taken over this conversation, skip AI entirely
            # Uses escalations table (conversations table has NO status column — causes 400 errors)
            if tenant_id and chat_jid:
                try:
                    from src.core.dashboard_api_simple import get_supabase as _get_supabase
                    _db = _get_supabase()
                    # ✅ FIX: Query escalations table (not conversations) for human-takeover state
                    _esc = (
                        _db.table("escalations")
                        .select("status")
                        .eq("tenant_id", tenant_id)
                        .eq("chat_jid", chat_jid)
                        .eq("status", "in_progress")
                        .limit(1)
                        .execute()
                    )
                    if _esc.data and len(_esc.data) > 0:
                        logger.info(
                            f"👤 Human handover active for {chat_jid} — skipping AI response"
                        )
                        self.processed_message_ids.add(msg_id)
                        return
                except Exception as _he:
                    logger.warning(f"⚠️ Human handover check failed (non-fatal): {_he}")
            # === END HUMAN HANDOVER CHECK ===

            # Phase 4: Process media if present
            # Process media using Gemini's native multimodal capabilities
            media_insight = None
            # media_mime: best-effort content-type captured from the bridge's
            # download response, so human agents can render the raw
            # attachment (see _save_message media_url/media_type/media_mime).
            # Stays None on the human-takeover early-return path (line ~2254)
            # since that path never downloads the media.
            media_mime = None
            if media_type and media_url:
                try:
                    logger.info(
                        f"📥 Processing {media_type} with Gemini multimodal API"
                    )
                    logger.info(f"   Downloading from: {media_url}")

                    # Download media from bridge (with API key auth)
                    import httpx

                    download_headers = {}

                    # Bridge uses HTTP Basic Auth (username:password)
                    bridge_user = os.getenv("BRIDGE_USER", "bijou")
                    bridge_password = os.getenv("BRIDGE_PASSWORD", "")

                    async with httpx.AsyncClient(timeout=30.0) as http_client:
                        media_response = await http_client.get(
                            media_url,
                            headers=download_headers,
                            auth=(bridge_user, bridge_password),
                            timeout=30
                        )
                    logger.info(f"   Download response: HTTP {media_response.status_code}")
                    if media_response.status_code == 200:
                        media_mime = media_response.headers.get("content-type")

                    # 2026-08-22 FIX: this download had NO size cap at all —
                    # httpx.get() buffers the entire body into memory
                    # (media_response.content) regardless of size. The
                    # dedicated MediaHandler class (media_handler.py) already
                    # implements a proper streaming 25MB cap but is never
                    # called from this path (confirmed: no other reference in
                    # this file). A full streaming rewrite here would touch
                    # ~9 downstream .content/.headers references across the
                    # image/audio/document branches below — too invasive to
                    # do safely in one pass. This is the contained version:
                    # reject anything over the configured cap AFTER download
                    # (same buffering cost as before, but no oversized blob
                    # gets forwarded to Gemini/docx/openpyxl parsing below).
                    _media_max_bytes = int(os.getenv("MEDIA_MAX_SIZE_MB", "25")) * 1024 * 1024
                    _media_too_large = (
                        media_response.status_code == 200
                        and len(media_response.content) > _media_max_bytes
                    )
                    if _media_too_large:
                        logger.warning(
                            f"⚠️ Media from {media_url} is {len(media_response.content) / 1024 / 1024:.1f}MB, "
                            f"exceeds {_media_max_bytes / 1024 / 1024:.0f}MB cap — rejecting before processing"
                        )
                        if media_type in ["audio", "ptt"]:
                            media_insight = "🎤 That voice message is too large for me to process. Could you send a shorter one or type your message instead?"
                        elif media_type in ["image", "sticker"]:
                            media_insight = "📷 That image is too large for me to process. Could you send a smaller one?"
                        else:
                            media_insight = f"📎 That {media_type} is too large for me to process. Could you send a smaller file?"
                    elif media_response.status_code == 200:
                        # Gemini can process images and audio natively
                        if media_type in ["image", "sticker"]:
                        # Image processing with Gemini Vision
                            from google import genai
                            from google.genai import types

                            if not hasattr(self, "genai_client"):
                                self.genai_client = genai.Client(
                                    api_key=self.config["gemini_api_key"]
                                )

                            # Upload image to Gemini
                            image_part = types.Part.from_bytes(
                                data=media_response.content,
                                mime_type=media_response.headers.get(
                                    "content-type", "image/jpeg"
                                ),
                            )

                            # Build vision prompt using structured approach
                            content_lower = (content or "").lower()

                            # Detect OCR intent (multi-language)
                            is_ocr_request = any(
                                keyword in content_lower
                                for keyword in ALL_OCR_KEYWORDS
                            )

                            # Get industry context
                            industry = (
                                client_config.get("industry", "general").lower()
                                if client_config
                                else "general"
                            )

                            # Auto-detect dental/property/fnb from content if not set
                            if industry == "general":
                                if any(k in content_lower for k in ["teeth", "tooth", "xray", "dental"]):
                                    industry = "dental"
                                    logger.info("🦷 Detected dental context from keywords")
                                elif any(k in content_lower for k in ["room", "house", "layout", "floor plan"]):
                                    industry = "property"
                                    logger.info("🏠 Detected property context from keywords")
                                elif any(k in content_lower for k in ["menu", "price", "dish", "food"]):
                                    industry = "fnb"
                                    logger.info("🍽️ Detected F&B context from keywords")

                            # Build structured prompt
                            vision_prompt = build_vision_prompt(
                                user_message=content,
                                industry=industry,
                                is_ocr_request=is_ocr_request
                            )

                            logger.info(
                                f"🔍 Vision analysis mode: {industry.upper()} | "
                                f"OCR request: {is_ocr_request}"
                            )

                            vision_response = self.genai_client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=[image_part, vision_prompt],  # ✅ Image first (per Google docs)
                                config=types.GenerateContentConfig(
                                    system_instruction=VISION_SYSTEM_INSTRUCTION,
                                    temperature=0.1,  # ✅ Deterministic for OCR accuracy
                                    max_output_tokens=2048,  # ✅ Handle dense menus/forms
                                    response_mime_type="application/json",  # ✅ Structured output
                                ),
                            )

                            # Parse JSON response with graceful fallback
                            raw_response = vision_response.text.strip()

                            try:
                                vision_data = json.loads(raw_response)
                                vision_text = vision_data.get("description", raw_response)
                                ocr_text = vision_data.get("ocr_text", "")
                                confidence = vision_data.get("confidence", 0.5)
                                image_quality = vision_data.get("image_quality", "unknown")
                                has_text = vision_data.get("has_text", False)
                                detected_lang = vision_data.get("detected_language", "unknown")

                                # Use OCR text if available and user asked for it
                                if is_ocr_request and ocr_text:
                                    vision_text = f"{vision_text}\n\n[Exact text from image]:\n{ocr_text}"

                                logger.info(
                                    f"✅ Image analyzed successfully with Gemini 2.5 Flash Vision"
                                )
                                logger.info(
                                    f"   Quality: {image_quality} | Confidence: {confidence:.2f} | "
                                    f"Has text: {has_text} | Language: {detected_lang}"
                                )

                                # Warn if low confidence or poor quality
                                if confidence < 0.5 or image_quality in ["poor", "unreadable"]:
                                    logger.warning(
                                        f"⚠️ Low-confidence vision result - image may be blurry or unreadable"
                                    )

                            except (json.JSONDecodeError, AttributeError) as e:
                                # Fallback to old behavior if JSON parsing fails
                                vision_text = raw_response
                                confidence = 0.5
                                image_quality = "unknown"
                                logger.warning(
                                    f"⚠️ Vision response not valid JSON - using raw text. Error: {e}"
                                )
                                logger.warning(f"   Raw response: {raw_response[:200]}...")

                            media_insight = f"📸 Image: {vision_text}"
                            logger.info(f"   Vision analysis (first 200 chars): {vision_text[:200]}...")


                        elif media_type in ["audio", "ptt"]:
                            # 🎤 Deepgram STT: transcribe WhatsApp OGG/Opus voice notes
                            # natively (no ffmpeg) so the note flows through the normal AI
                            # pipeline exactly like typed text. On any miss (missing
                            # DEEPGRAM_API_KEY, network error, empty transcript) we fall back
                            # to the existing "couldn't process" placeholder — never crash.
                            from src.core.media_handler import transcribe_audio_deepgram

                            _dg_transcript = await transcribe_audio_deepgram(
                                audio_bytes=media_response.content,
                                mimetype=media_response.headers.get(
                                    "content-type", "audio/ogg"
                                ),
                            )
                            if _dg_transcript:
                                media_insight = f"🎤 Audio: {_dg_transcript}"
                                logger.info(
                                    f"✅ Voice note transcribed via Deepgram "
                                    f"({len(_dg_transcript)} chars)"
                                )
                            else:
                                # Graceful fallback: preserve prior placeholder behavior.
                                media_insight = (
                                    "🎤 I received your voice message but couldn't process "
                                    "the audio. Could you please type your message instead?"
                                )
                                logger.warning(
                                    "⚠️ Deepgram unavailable/failed for voice note — "
                                    "using placeholder fallback"
                                )

                        elif media_type in ["document"]:
                            # Document pipeline — Gemini-native multimodal first,
                            # text fallback for DOCX/TXT, graceful error handling.
                            filename = msg_dict.get("filename", "document")
                            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                            content_type = media_response.headers.get("content-type", "application/octet-stream")

                            # Map extension to correct MIME type (headers can be wrong)
                            EXT_MIME = {
                                "pdf":  "application/pdf",
                                "jpg":  "image/jpeg", "jpeg": "image/jpeg",
                                "png":  "image/png",  "webp": "image/webp",
                                "gif":  "image/gif",
                                "txt":  "text/plain", "md": "text/plain", "csv": "text/plain",
                                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            }
                            mime = EXT_MIME.get(ext, content_type)

                            # Gemini-native types: PDF + images sent as documents
                            GEMINI_NATIVE = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"}

                            from google import genai
                            from google.genai import types as gtypes
                            if not hasattr(self, "genai_client"):
                                self.genai_client = genai.Client(api_key=self.config["gemini_api_key"])

                            if mime in GEMINI_NATIVE:
                                # ✅ Send directly to Gemini — handles scanned PDFs, image docs, IC scans, receipts, contracts
                                try:
                                    doc_part = gtypes.Part.from_bytes(
                                        data=media_response.content,
                                        mime_type=mime,
                                    )
                                    user_q = content or "Summarise this document and extract all key information."
                                    doc_response = self.genai_client.models.generate_content(
                                        model="gemini-2.5-flash",
                                        contents=[doc_part, user_q],
                                        config=gtypes.GenerateContentConfig(
                                            system_instruction=(
                                                "You are an expert document analyst. "
                                                "Extract and summarise all key information: "
                                                "text, numbers, dates, names, tables, and any other content. "
                                                "For scanned or image-based documents, perform OCR and extract all visible text. "
                                                "Be thorough and structured."
                                            ),
                                            temperature=0.1,
                                            max_output_tokens=3000,
                                        ),
                                    )
                                    doc_text = doc_response.text.strip()
                                    media_insight = f"📄 Document analysed ({filename}):\n{doc_text}"
                                    logger.info(f"✅ Gemini document analysis complete ({len(doc_text)} chars) — {filename}")
                                except Exception as gemini_doc_err:
                                    logger.warning(f"⚠️ Gemini document analysis failed ({filename}): {gemini_doc_err}")
                                    media_insight = f"📄 I received '{filename}' but had trouble reading it. Could you describe what's inside?"

                            elif ext in ["txt", "csv", "md"]:
                                # Plain text — decode and pass through
                                raw_txt = media_response.content.decode("utf-8", errors="ignore")[:6000]
                                media_insight = f"📄 Document ({filename}) content:\n{raw_txt}"
                                logger.info(f"✅ Plain text document decoded ({len(raw_txt)} chars)")

                            elif ext in ["docx", "doc"]:
                                # DOCX — python-docx text extraction then optionally summarise
                                try:
                                    import io
                                    import docx as _docx
                                    _doc = _docx.Document(io.BytesIO(media_response.content))
                                    raw_txt = "\n".join([p.text for p in _doc.paragraphs if p.text.strip()])[:6000]
                                    if raw_txt.strip():
                                        media_insight = f"📄 Document ({filename}) content:\n{raw_txt}"
                                        logger.info(f"✅ DOCX extracted ({len(raw_txt)} chars)")
                                    else:
                                        media_insight = f"📄 Received '{filename}' but it appears to be empty or image-only. Could you share the contents as text?"
                                except Exception as docx_err:
                                    logger.warning(f"⚠️ DOCX extraction failed: {docx_err}")
                                    media_insight = f"📄 I received '{filename}' but couldn't read it. Please copy and paste the content directly."

                            elif ext in ["xlsx", "xls"]:
                                # Excel — openpyxl if available
                                try:
                                    import io
                                    import openpyxl
                                    wb = openpyxl.load_workbook(io.BytesIO(media_response.content), read_only=True, data_only=True)
                                    rows = []
                                    for ws in wb.worksheets[:3]:  # max 3 sheets
                                        rows.append(f"[Sheet: {ws.title}]")
                                        for row in ws.iter_rows(max_row=50, values_only=True):
                                            if any(c is not None for c in row):
                                                rows.append("\t".join(str(c) if c is not None else "" for c in row))
                                    raw_txt = "\n".join(rows)[:5000]
                                    media_insight = f"📊 Spreadsheet ({filename}):\n{raw_txt}"
                                    logger.info(f"✅ Excel extracted ({len(raw_txt)} chars)")
                                except Exception as xlsx_err:
                                    logger.warning(f"⚠️ Excel extraction failed: {xlsx_err}")
                                    media_insight = f"📊 I received '{filename}' but couldn't read the spreadsheet. Please share key data as text."

                            else:
                                media_insight = f"📄 I received a file ({filename}). I can read PDFs, images, Word docs, Excel sheets, and text files. This format ({ext}) isn't fully supported — could you share the contents as text?"
                                logger.info(f"📄 Unsupported document type: {ext} — {filename}")
                        else:
                            logger.info(
                                f"📎 {media_type} media - responding to text only"
                            )
                    else:
                        logger.warning(
                            f"Failed to download media: HTTP {media_response.status_code} from {media_url}"
                        )
                        # ✅ FIX: Provide fallback response when media download fails
                        if media_type in ["audio", "ptt"]:
                            media_insight = "🎤 I received your voice message but couldn't process the audio. Could you please type your message instead?"
                            logger.warning(f"   Setting fallback for audio: {media_insight}")
                        elif media_type in ["image", "sticker"]:
                            media_insight = "📷 I received your image but couldn't process it. Could you describe what you're showing me?"
                            logger.warning(f"   Setting fallback for image: {media_insight}")
                        else:
                            media_insight = f"📎 I received your {media_type} but couldn't process it. Could you tell me more about it?"
                            logger.warning(f"   Setting fallback for {media_type}: {media_insight}")

                        # Fallback for localhost issues - log extensively
                        if "localhost" in media_url or "127.0.0.1" in media_url:
                             logger.warning("   💡 Tip: If using Docker, ensure BRIDGE_URL is accessible from the container network (e.g. host.docker.internal or explicit IP)")

                except Exception as media_error:
                    logger.error(f"❌ Media processing error: {media_error}")
                    logger.error(f"   Media type: {media_type}")
                    logger.error(f"   Media URL: {media_url}")
                    # ✅ FIX: Provide fallback response on error
                    if media_type in ["audio", "ptt"]:
                        media_insight = "🎤 I received your voice message but had trouble processing it. Could you please type your message?"
                    elif media_type in ["image", "sticker"]:
                        media_insight = "📷 I received your image but had trouble viewing it. Could you describe what you're showing me?"
                    else:
                        media_insight = f"📎 I received your {media_type} but had trouble processing it. Could you tell me more?"
                    logger.warning(f"   Setting error fallback: {media_insight}")
            elif media_type and not media_url:
                logger.warning(f"⚠️ Media message received but media_url is missing!")
                logger.warning(f"   Media type: {media_type}")
                logger.warning(f"   Message ID: {msg_id}")
                logger.warning(
                    f"   This indicates the WhatsApp Bridge is not sending media_url field"
                )
                # Add acknowledgment for media without processing
                media_insight = f"📎 Received {media_type} (processing unavailable - media URL missing)"

            # Enhance message with media insights
            enhanced_content = content
            clean_user_message = content  # ← NEW: Preserve clean message for notifications

            if media_insight:
                # Extract clean transcription/description for notifications
                if "🎤 Audio:" in media_insight:
                    clean_user_message = media_insight.replace("🎤 Audio:", "").strip()
                elif "📷 Image:" in media_insight:
                    clean_user_message = media_insight.replace("📷 Image:", "").strip()
                elif "📎" in media_insight:
                    clean_user_message = media_insight

                # Check if this is an error fallback or successful processing
                is_error_fallback = any(phrase in media_insight.lower() for phrase in [
                    "couldn't process", "had trouble", "processing unavailable",
                    "couldn't", "trouble processing", "trouble viewing"
                ])

                # Make it clear to AI that IT analyzed the media, not the user
                if content:
                    # User sent media WITH a caption/question
                    # For notifications: combine media description + caption
                    if clean_user_message and content:
                        clean_user_message = f"{clean_user_message} (caption: {content})"

                    # Different handling for images vs audio
                    if media_type in ["image", "sticker"]:
                        enhanced_content = f"[CRITICAL INSTRUCTION: You just analyzed an image using vision AI. Here's exactly what you saw: {media_insight}]\n\n[The user is now asking you about this image: \"{content}\"]\n\n[You MUST answer their question using the detailed image analysis above. DO NOT give generic responses like 'usually these slides explain...' - use the ACTUAL content you saw in the image. Be specific and helpful.]"
                    else:
                        enhanced_content = f"[YOU ANALYZED THE MEDIA AND SAW: {media_insight}]\n\nNow respond to the user's question: {content}"
                else:
                    # User sent media WITHOUT a caption
                    if is_error_fallback:
                        # Media processing failed - use error message for both AI and notifications
                        clean_user_message = media_insight  # Error messages are clean enough
                        enhanced_content = f"[SYSTEM: You received a voice/media message but couldn't process it. Ask the user to type their message instead.]\n\n{media_insight}"
                    else:
                        # Media processing SUCCEEDED - respond to what you saw/heard
                        # IMPORTANT: Make this VERY explicit to override any error messages in conversation history
                        if media_type in ["audio", "ptt"]:
                            enhanced_content = f"[IMPORTANT: Audio processing succeeded this time! {media_insight}]\n\n[INSTRUCTION: Ignore any previous errors. Respond naturally to what the user just said in their voice message. Do not mention any technical issues.]"
                        elif media_type in ["image", "sticker"]:
                            enhanced_content = f"[IMPORTANT: Image analysis succeeded this time! {media_insight}]\n\n[INSTRUCTION: Ignore any previous errors. Describe what you see in this image or make a natural comment about it. Do not say you can't see it or had trouble - you analyzed it successfully!]"
                        else:
                            enhanced_content = f"[IMPORTANT: Media processing succeeded this time! {media_insight}]\n\n[INSTRUCTION: Ignore any previous errors. Respond naturally to the media content. Do not mention technical issues.]"

            # ✅ FIX: Detect explicit language preference requests
            language_override = None
            content_lower = (content or "").lower()
            if any(phrase in content_lower for phrase in ["speak english", "in english", "english please", "use english", "reply in english", "respond in english"]):
                language_override = "en"
                enhanced_content = f"[SYSTEM: User requested English. Respond ONLY in English.]\n\n{enhanced_content}"
                logger.info("🌐 User requested ENGLISH - overriding language detection")
            elif any(phrase in content_lower for phrase in ["说中文", "用中文", "speak chinese", "in chinese", "chinese please"]):
                language_override = "zh"
                enhanced_content = f"[SYSTEM: User requested Chinese. Respond ONLY in Chinese.]\n\n{enhanced_content}"
                logger.info("🌐 User requested CHINESE - overriding language detection")
            elif any(phrase in content_lower for phrase in ["cakap melayu", "speak malay", "in malay", "bahasa melayu"]):
                language_override = "ms"
                enhanced_content = f"[SYSTEM: User requested Malay. Respond ONLY in Malay.]\n\n{enhanced_content}"
                logger.info("🌐 User requested MALAY - overriding language detection")

            # === MISSED CALL CONTEXT OVERRIDE ===
            # Handle missed call messages with special AI context to ensure natural responses
            message_type = message.get("message_type", "")
            if is_missed_call(message):
                # 🔍 DEBUG: Log all missed call details for troubleshooting
                logger.info(f"🔍 MISSED CALL DEBUG - Full details:")
                logger.info(f"   Chat JID (who called): {chat_jid}")
                logger.info(f"   Sender (who called): {sender}")
                logger.info(f"   Chat Phone: {chat_phone}")
                logger.info(f"   Sender Phone: {sender_phone}")
                logger.info(f"   Owner JID: {self.owner_jid}")
                logger.info(f"   Owner Phone: {owner_phone}")
                logger.info(f"   is_owner_dm: {is_owner_dm}")
                logger.info(f"   is_owner_sender: {is_owner_sender}")
                logger.info(f"   is_owner_linked: {is_owner_linked}")
                logger.info(f"   Final is_owner: {is_owner}")

                # ✅ FIX: Skip AI responses for owner's own missed calls to prevent self-notification loop
                if is_owner_dm or is_owner_sender or is_owner_linked:
                    logger.info(f"🚫 FILTERING OUT: Owner called their own business number - no AI response needed")
                    logger.info(f"   This prevents the owner from getting AI responses to their own missed calls")
                    # For owner's calls, just log and don't process as customer missed call
                    return {
                        "response": "",  # No AI response needed
                        "language": "en",
                        "confidence": 1.0,
                        "emotion": "neutral",
                        "formality": "casual",
                        "strategy": "SKIP_OWNER_CALL",
                        "escalation": False,
                        "processing_time_ms": 0
                    }
                else:
                    # Customer missed call - provide AI follow-up
                    logger.info(f"✅ PROCESSING: Real customer {chat_jid} called business - providing AI follow-up")
                    enhanced_content = build_missed_call_context()
                    clean_user_message = "📞 Missed call"  # For notifications
                    logger.info(f"📞 Customer missed call follow-up triggered for {chat_jid}")
            # === END MISSED CALL CONTEXT OVERRIDE ===

            # Detect language
            if self.ml_processor:
                lang_context = self.ml_processor.detect_language(enhanced_content)
                # Override if user explicitly requested a language
                if language_override:
                    logger.info(f"🌐 Overriding detected language with user preference: {language_override}")
                logger.info(
                    f"🌐 Detected: {lang_context.primary_language.value} (confidence: {lang_context.confidence_score:.2f})"
                )
            else:
                lang_context = None

            # === CASUAL ACKNOWLEDGMENT DETECTION (3-Tier Notification System) ===
            # Detect simple "thank you", "ok", "got it" messages and handle them early
            if self.groups_manager:
                try:
                    import asyncio
                    from src.saas.notification_groups import is_casual_acknowledgment, NotificationGroupType

                    if is_casual_acknowledgment(clean_user_message):
                        logger.info(f"👍 Casual acknowledgment detected: '{clean_user_message}'")

                        # Send friendly acknowledgment response
                        if "thank" in clean_user_message.lower() or "terima kasih" in clean_user_message.lower() or "appreciate" in clean_user_message.lower():
                            response = "You're welcome! 😊"
                        elif any(emoji in clean_user_message for emoji in ["👍", "🙏", "👌"]):
                            response = "👍"
                        else:
                            response = "Got it! 😊"

                        # Send response
                        self._send_response_human_burst(
                            chat_jid, response, channel=channel, tenant_id=tenant_id
                        )

                        # Notify Updates group
                        if self.groups_manager:
                            logger.info(f"📢 TRIGGERING: Acknowledgment notification to Updates group")
                            logger.info(f"   Customer: {self._format_phone(sender)} ({from_name})")
                            logger.info(f"   Message: {clean_user_message[:50]}...")

                            asyncio.create_task(
                                self.groups_manager.send_notification(
                                    tenant_id=tenant_id,
                                    group_type=NotificationGroupType.UPDATES,
                                    notification_data={
                                        "customer_jid": chat_jid,
                                        "customer_phone": self._format_phone(sender),
                                        "customer_name": from_name,
                                        "message": clean_user_message,
                                        "update_type": "acknowledgment",
                                        "context": f"Casual acknowledgment: \"{clean_user_message[:50]}{'...' if len(clean_user_message) > 50 else ''}\""
                                    }
                                )
                            )
                        else:
                            logger.error(f"❌ NOTIFICATION SKIPPED: groups_manager is None!")
                            logger.error(f"   Check if NotificationGroupsManager initialized at startup")

                        # Mark as processed and skip AI response generation
                        self.processed_message_ids.add(msg_id)
                        return
                except Exception as e:
                    logger.warning(f"⚠️ Casual acknowledgment detection failed: {e}")
            # === END CASUAL ACKNOWLEDGMENT DETECTION ===

            # === KEYWORD TEMPLATE CHECK ===
            # Short-circuit before AI if message matches a canned keyword template
            if tenant_id and content and hasattr(self, "message_filter") and self.message_filter:
                try:
                    template_reply = await self.message_filter.check_keyword_templates(
                        tenant_id=tenant_id,
                        message_content=content,
                    )
                    if template_reply:
                        logger.info(
                            f"🎯 Keyword template matched — sending canned reply "
                            f"(tenant={tenant_id})"
                        )
                        self._send_response_human_burst(
                            chat_jid,
                            template_reply,
                            channel=channel,
                            tenant_id=tenant_id,
                        )
                        self.processed_message_ids.add(msg_id)
                        return
                except Exception as _kt_err:
                    logger.warning(
                        f"⚠️ Keyword template check failed (non-fatal): {_kt_err}"
                    )
            # === END KEYWORD TEMPLATE CHECK ===

            # === PHASE 5: Robust Function Calling (Structured Tool Calling) ===
            tool_output = None
            if (
                hasattr(self, "function_caller")
                and self.function_caller
                and self.function_caller.enabled
            ):
                logger.info(f"🔧 Testing Intent: {enhanced_content}")
                func_result = await self.function_caller.detect_and_execute(
                    enhanced_content, chat_jid, user_context=client_config
                )

                if func_result:
                    # If this is a confirmation request, send only the confirmation message
                    if func_result.get("status") == "pending_confirmation":
                        self._send_response_human_burst(
                            chat_jid,
                            func_result["message"],
                            channel=channel,
                            tenant_id=tenant_id,
                        )
                        self.processed_message_ids.add(msg_id)
                        return

                    # Tool summary for LLM context
                    tool_output = f"\n\n[SYSTEM: You successfully executed a tool. Result: {json.dumps(func_result)}]"
                    logger.info("✅ Function called successfully - enriching response")

            # Generate AI response with client config (and tool output if any)
            final_content = enhanced_content + (tool_output if tool_output else "")
            response = await self._generate_response(
                final_content, lang_context, chat_jid, client_config=client_config
            )

            # === MEDIA ATTACHMENT PARSER ===
            # Strip [SEND_FILE:uuid] tokens from response and append signed URLs
            _send_file_ids = re.findall(r'\[SEND_FILE:([a-f0-9-]{36})\]', response or "")
            if _send_file_ids and self.db_conn and self.db_type == "supabase":
                response = re.sub(r'\[SEND_FILE:[a-f0-9-]{36}\]', '', response).strip()
                try:
                    from src.saas.storage_setup import generate_signed_url
                    for _file_id in _send_file_ids:
                        try:
                            _mr = self.db_conn.table("media_library") \
                                .select("original_name, stored_filename, send_count") \
                                .eq("id", _file_id).eq("tenant_id", tenant_id).execute()
                            if _mr.data:
                                _rec = _mr.data[0]
                                _signed = generate_signed_url(
                                    self.db_conn, tenant_id,
                                    _rec["stored_filename"], expires_in=86400
                                )
                                if _signed:
                                    response = response.rstrip() + f"\n\n📎 {_rec['original_name']}\n{_signed}"
                                    # Increment send_count
                                    self.db_conn.table("media_library") \
                                        .update({"send_count": (_rec.get("send_count") or 0) + 1}) \
                                        .eq("id", _file_id).execute()
                                    logger.info(f"📎 Appended signed URL for media {_file_id} to response")
                        except Exception as _mfe:
                            logger.warning(f"⚠️ Media attachment failed for {_file_id}: {_mfe}")
                except ImportError:
                    pass
            # === END MEDIA ATTACHMENT PARSER ===

            # === PHASE 1: Lead Qualification Check ===
            if (
                hasattr(self, "lead_converter")
                and self.lead_converter
                and not is_from_me
            ):
                try:
                    # Analyze conversation for lead signals
                    # Returns (LeadStatus, qualification_data) tuple
                    lead_status, qualification_data = (
                        self.lead_converter.analyze_lead_quality(
                            customer_jid=sender,
                            conversation_history=[
                                {"role": "user", "content": enhanced_content},
                                {"role": "assistant", "content": response},
                            ],
                            latest_message=enhanced_content,
                        )
                    )

                    # Check if handover should be triggered
                    should_handover, handover_reason = (
                        self.lead_converter.should_trigger_handover(
                            enhanced_content, lead_status
                        )
                    )

                    # Append CTA based on lead quality
                    if should_handover:
                        cta = self.lead_converter.generate_cta(
                            lead_status, qualification_data
                        )
                        if cta:
                            response = response + "\n\n" + cta

                        # Trigger handover for qualified/hot leads
                        if lead_status.value in ["qualified", "hot"]:
                            logger.info(
                                f"🎯 Qualified lead detected: {lead_status.value} - {handover_reason}"
                            )
                            # Note: trigger_agent_handover requires customer_name parameter
                            # For now, extract name from chat_jid or use placeholder
                            customer_name = (
                                sender.split("@")[0] if "@" in sender else sender
                            )
                            self.lead_converter.trigger_agent_handover(
                                chat_jid=chat_jid,
                                customer_name=customer_name,
                                qualification_data=qualification_data,
                                conversation_summary=f"User: {enhanced_content}\nAI: {response}",
                            )

                    # Send Hot Leads notification for WARM/HOT/QUALIFIED leads
                    # Route to Hot Leads group (3-tier notification system)
                    if lead_status and lead_status.value in ["warm", "hot", "qualified"]:
                        if self.groups_manager:
                            from src.saas.notification_groups import NotificationGroupType

                            # Build reason string from qualification data
                            signals = []
                            if qualification_data.get("budget"):
                                signals.append("budget mentioned")
                            if qualification_data.get("location"):
                                signals.append("location specified")
                            if qualification_data.get("timeline"):
                                signals.append("timeline discussed")
                            if qualification_data.get("property_type"):
                                prop_type = qualification_data.get("property_type")
                                if hasattr(prop_type, 'value'):
                                    signals.append(f"{prop_type.value} property")

                            reason = f"Lead Status: {lead_status.value.upper()} | Signals: {', '.join(signals) if signals else 'Buying intent detected'}"

                            logger.info(f"🔥 TRIGGERING: Hot lead notification to Hot Leads group")
                            logger.info(f"   Customer: {self._format_phone(sender)} ({from_name})")
                            logger.info(f"   Lead Status: {lead_status.value}")
                            logger.info(f"   Engagement Score: {qualification_data.get('engagement_score', 0)}")
                            logger.info(f"   Reason: {reason}")

                            asyncio.create_task(
                                self.groups_manager.send_notification(
                                    tenant_id=tenant_id,
                                    group_type=NotificationGroupType.HOT_LEADS,
                                    notification_data={
                                        "customer_jid": chat_jid,
                                        "customer_phone": self._format_phone(sender),
                                        "customer_name": from_name,
                                        "message": clean_user_message,
                                        "ai_response": response,
                                        "reason": reason,
                                        "lead_status": lead_status.value,
                                        "engagement_score": qualification_data.get("engagement_score", 0),
                                        "conversation_summary": f"Customer: {clean_user_message[:150]}...\nBijou: {response[:150]}..."
                                    }
                                )
                            )

                            # PROACTIVE: Also send direct DM to owner if lead is HOT
                            if lead_status.value == "hot":
                                asyncio.create_task(
                                    self._send_direct_owner_notification(
                                        tenant_id=tenant_id,
                                        message=f"🔥 *HOT LEAD DETECTED*\n\n*Customer:* {from_name} ({self._format_phone(sender)})\n*Status:* {lead_status.value.upper()}\n*Reason:* {reason}\n\n*Last Message:* {clean_user_message}"
                                    )
                                )
                        else:
                            logger.warning(f"⚠️ Hot lead detected but groups_manager is None - using legacy notification")
                            # Fallback to legacy notification system
                            asyncio.create_task(
                                self.notification_system.notify_hot_lead(
                                    chat_jid=chat_jid,
                                    reason=f"Lead status: {lead_status.value}",
                                    conversation_summary=f"Customer: {clean_user_message[:150]}...\nBijou: {response[:150]}...",
                                    sender_jid=sender,
                                    from_name=from_name,
                                )
                            )
                except Exception as e:
                    logger.warning(f"⚠️ Lead qualification failed: {e}")
            # === END PHASE 1 ===

            # Send response with Human Vibe (typing + burst) - via executor to avoid blocking event loop
            # === PHASE 7: VOICE RESPONSE LOGIC (DISABLED) ===
            # Voice OUTPUT is now disabled - Bijou replies in text only
            # Voice INPUT (transcription) is handled by Gemini in media processing above
            # Always send text response with Human Vibe (typing + burst splitting)
            # _send_response_human_burst submits to thread executor (non-blocking)
            self._send_response_human_burst(
                chat_jid, response, channel=channel, tenant_id=tenant_id
            )
            send_success = True  # executor fn is fire-and-forget; True = queued
            # === END PHASE 7 ===

            # === PROACTIVE OWNER NOTIFICATIONS (3-Tier System) ===
            if self.notification_system and not is_from_me:
                try:
                    # Get conversation history (scoped to tenant for multi-tenant safety)
                    conversation_history = self._get_conversation_history(
                        chat_jid, limit=10, tenant_id=tenant_id
                    )

                    # Check if this is a new customer (first or second message)
                    is_new_customer = len(conversation_history) <= 1

                    # === AUTO-SAVE CONTACT TO CRM ===
                    if self.db_type == "supabase" and self.db_conn:
                        try:
                            _property_keywords = ["price", "rent", "buy", "sell", "property", "unit", "available", "booking", "berapa", "harga", "rumah", "lot", "land", "condo", "apartment", "agent", "view", "sqft", "psf", "bedroom", "bathroom"]
                            _msg_lower = (content or "").lower()
                            _tag = "inquiry" if any(k in _msg_lower for k in _property_keywords) else "lead"
                            _phone = chat_jid.replace("@s.whatsapp.net", "").replace("@g.us", "") if chat_jid else ""
                            _contact_data = {
                                "tenant_id": tenant_id,
                                "jid": chat_jid,
                                "phone": _phone,
                                "last_message_at": datetime.utcnow().isoformat(),
                            }
                            if is_new_customer:
                                _contact_data.update({
                                    "name": from_name or _phone,
                                    "tag": "hot_lead" if (lead_status and lead_status.value in ["warm", "hot", "qualified"]) else (_tag if (not lead_status or lead_status.value == 'unknown') else "lead"),
                                    "source": "whatsapp",
                                    "status": "active",
                                    "first_message_at": datetime.utcnow().isoformat(),
                                })
                            else:
                                # Update tag for existing customer if lead status improved
                                if lead_status and lead_status.value in ["warm", "hot", "qualified"]:
                                    _contact_data["tag"] = "hot_lead"  # Map to standard CRM tag

                            self.db_conn.table("contacts").upsert(
                                _contact_data,
                                on_conflict="tenant_id,jid"
                            ).execute()
                        except Exception as _crm_err:
                            logger.debug(f"Contact upsert skipped: {_crm_err}")

                    # Detect notification triggers
                    import asyncio

                    # Import notification group types
                    if self.groups_manager:
                        from src.saas.notification_groups import NotificationGroupType

                    # New customer alert - route to Updates group
                    if is_new_customer:
                        if self.groups_manager:
                            # Use 3-tier notification system
                            asyncio.create_task(
                                self.groups_manager.send_notification(
                                    tenant_id=tenant_id,
                                    group_type=NotificationGroupType.UPDATES,
                                    notification_data={
                                        "customer_jid": chat_jid,
                                        "customer_phone": self._format_phone(sender),
                                        "customer_name": from_name,
                                        "message": clean_user_message,
                                        "ai_response": response,
                                        "update_type": "new_customer"
                                    }
                                )
                            )
                            logger.info(f"📢 New customer routed to Updates group for {chat_jid}")
                        else:
                            # Fallback to legacy notification system
                            asyncio.create_task(
                                self.notification_system.notify_new_conversation(
                                    chat_jid=chat_jid,
                                    first_message=clean_user_message,
                                    ai_response=response,
                                    sender_jid=sender,
                                    from_name=from_name,
                                )
                            )
                            logger.info(f"📢 New customer notification sent for {chat_jid}")

                    # === HOT LEAD DETECTION REMOVED ===
                    # Hot lead detection is now handled by lead_converter AI system (see PHASE 1 above)
                    # This eliminates keyword overlap issues (e.g., "urgent" triggering both hot leads and escalations)
                    # Lead Converter analyzes buying intent using AI, not brittle keywords

                    # Escalation detection using HandoverSystem
                    if self.handover_system:
                        should_escalate, escalation_reason, priority = (
                            self.handover_system.should_escalate(
                                message=enhanced_content,
                                chat_jid=chat_jid,
                                emotion=None,  # LanguageContext doesn't have emotion attribute
                                conversation_history=None,
                            )
                        )

                        if should_escalate:
                            logger.info(
                                f"🚨 ESCALATION DETECTED: {escalation_reason} (priority: {priority.value})"
                            )

                            # Create escalation record in database
                            escalation_id = "FAILED_TO_CREATE"
                            try:
                                escalation_id = await self.handover_system.create_escalation(
                                    tenant_id=tenant_id,
                                    chat_jid=chat_jid,
                                    reason=escalation_reason,
                                    priority=priority,
                                    metadata={
                                        "trigger_message": enhanced_content,
                                        "ai_response": response,
                                        "primary_language": lang_context.primary_language.value
                                        if lang_context
                                        and hasattr(lang_context, "primary_language")
                                        else None,
                                        "formality_level": lang_context.formality_level.value
                                        if lang_context
                                        and hasattr(lang_context, "formality_level")
                                        else None,
                                    },
                                )
                                if escalation_id:
                                    logger.info(
                                        f"✅ Escalation record created: {escalation_id}"
                                    )
                            except Exception as db_error:
                                logger.error(
                                    f"❌ Failed to create escalation record: {db_error}"
                                )

                            # Send owner notification - route to Escalation Queue
                            try:
                                if self.groups_manager:
                                    # Use 3-tier notification system
                                    logger.info(f"🚨 TRIGGERING: Escalation notification to Escalation Queue")
                                    logger.info(f"   Customer: {self._format_phone(sender)} ({from_name})")
                                    logger.info(f"   Reason: {escalation_reason}")
                                    logger.info(f"   Priority: {priority.value}")
                                    logger.info(f"   Escalation ID: {escalation_id}")

                                    asyncio.create_task(
                                        self.groups_manager.send_notification(
                                            tenant_id=tenant_id,
                                            group_type=NotificationGroupType.ESCALATION,
                                            notification_data={
                                                "customer_jid": chat_jid,
                                                "customer_phone": self._format_phone(sender),
                                                "customer_name": from_name,
                                                "message": clean_user_message,
                                                "ai_response": response,
                                                "reason": escalation_reason,
                                                "escalation_id": escalation_id,
                                                "priority": priority.value
                                            }
                                        )
                                    )

                                    # ── Critical escalation → direct ping to Bijou platform owner ──
                                    # Triggers when priority is high/critical OR message contains
                                    # platform-breaking keywords (login failure, billing, API down)
                                    _critical_kw = [
                                        "cannot login", "can't login", "cant login",
                                        "api down", "service down", "system down",
                                        "payment fail", "billing issue", "charge wrong",
                                        "data loss", "data missing", "data gone",
                                        "urgent scale", "not working at all",
                                    ]
                                    _bijou_owner_wa = os.getenv("BIJOU_OWNER_WA", "").strip()
                                    if _bijou_owner_wa and (
                                        priority.value in ["critical", "high"]
                                        or any(kw in clean_user_message.lower() for kw in _critical_kw)
                                    ):
                                        _biz_name = getattr(self, "business_name", None) or tenant_id[:8]
                                        _owner_alert = (
                                            f"🚨 *CRITICAL ESCALATION*\n"
                                            f"🏢 *{_biz_name}*\n"
                                            f"📞 {from_name} — {self._format_phone(sender)}\n"
                                            f"⚠️ *Priority:* {priority.value.upper()}\n"
                                            f"💬 *Reason:* {escalation_reason}\n\n"
                                            f"*Message:* _{clean_user_message}_\n\n"
                                            f"_Reply ASAP — platform issue detected._"
                                        )
                                        asyncio.create_task(
                                            self._notify_bijou_owner(
                                                owner_wa=_bijou_owner_wa,
                                                message=_owner_alert,
                                                tenant_id=tenant_id,
                                            )
                                        )
                                        logger.warning(
                                            f"🚨 Critical escalation → pinging Bijou owner {_bijou_owner_wa}"
                                        )
                                    logger.error(f"❌ NOTIFICATION SKIPPED: groups_manager is None!")
                                    # Fallback to direct owner notification
                                    asyncio.create_task(
                                        self._send_direct_owner_notification(
                                            tenant_id=tenant_id,
                                            message=f"🚨 *ESCALATION ALERT*\n\n*Customer:* {from_name} ({self._format_phone(sender)})\n*Reason:* {escalation_reason}\n*Priority:* {priority.value.upper()}\n*Escalation ID:* {escalation_id}\n\n*Message:* {clean_user_message}"
                                        )
                                    )
                                    # Fallback to legacy notification system
                                    notified = (
                                        await self.notification_system.notify_escalation(
                                            chat_jid=chat_jid,
                                            trigger=clean_user_message,
                                            conversation_context=response,
                                            tenant_id=tenant_id,
                                            sender_jid=sender,
                                            from_name=from_name,
                                        )
                                    )
                                    if notified:
                                        logger.info(
                                            f"✅ Escalation notification sent to owner for {chat_jid}"
                                        )
                                    else:
                                        logger.error(
                                            f"❌ Escalation notification failed for {chat_jid}"
                                        )
                            except Exception as notif_error:
                                logger.error(
                                    f"❌ Failed to send escalation notification: {notif_error}",
                                    exc_info=True,
                                )
                    else:
                        # Fallback: Simple keyword detection if HandoverSystem not available
                        escalation_keywords = [
                            "human",
                            "person",
                            "manager",
                            "urgent",
                            "immediately",
                            "asap",
                            "complaint",
                        ]
                        if any(
                            keyword in enhanced_content.lower()
                            for keyword in escalation_keywords
                        ):
                            logger.warning(
                                f"⚠️ Escalation keyword detected but HandoverSystem not initialized!"
                            )
                            try:
                                notified = (
                                    await self.notification_system.notify_escalation(
                                        chat_jid=chat_jid,
                                        trigger=enhanced_content,
                                        conversation_context=response,
                                        tenant_id=tenant_id,
                                    )
                                )
                                if notified:
                                    logger.info(
                                        f"✅ Escalation notification sent (fallback) for {chat_jid}"
                                    )
                                else:
                                    logger.error(
                                        f"❌ Escalation notification failed (fallback) for {chat_jid}"
                                    )
                            except Exception as notif_error:
                                logger.error(
                                    f"❌ Fallback escalation notification failed: {notif_error}",
                                    exc_info=True,
                                )

                except Exception as e:
                    logger.warning(f"⚠️ Owner notification failed (non-blocking): {e}")
            # === END NOTIFICATIONS ===

            # Save to database (messages table)
            _device_jid = message.get("device_jid")
            _chat_type = "group" if chat_jid and chat_jid.endswith("@g.us") else "individual"
            await self._save_message(
                chat_jid, tenant_id, "user", enhanced_content,
                device_jid=_device_jid, chat_type=_chat_type,
                media_url=media_url, media_type=media_type, media_mime=media_mime,
            )
            await self._save_message(
                chat_jid, tenant_id, "assistant", response,
                device_jid=_device_jid, chat_type=_chat_type,
            )

            # Save conversation record with AI metadata (for dashboard/analytics)
            try:
                if self.db_type == "supabase" and self.db_conn:
                    self.db_conn.table("conversations").insert({
                        "tenant_id": tenant_id,
                        "chat_jid": chat_jid,
                        "message_id": msg_id,
                        "message_content": enhanced_content,
                        "sender": sender,
                        "is_from_me": False,
                        "detected_language": lang_context.primary_language.value if lang_context else "unknown",
                        "ai_response": response,
                        "timestamp": datetime.now().isoformat(),
                        "created_at": datetime.now().isoformat(),
                    }).execute()
                    logger.debug(f"✅ Conversation record created for {chat_jid}")

                    # Send customer message event to Google Sheets
                    if SHEETS_WEBHOOK_AVAILABLE and sheets_webhook:
                        customer_phone = self._format_phone(sender)
                        asyncio.create_task(
                            sheets_webhook.send_message_event(
                                tenant_id=tenant_id,
                                customer_jid=chat_jid,
                                customer_phone=customer_phone,
                                customer_name=from_name or customer_phone,
                                message_id=msg_id,
                                message_content=enhanced_content,
                                sender_type="customer",
                                timestamp=datetime.now().isoformat(),
                            )
                        )
                        logger.debug(f"📊 Sheets webhook queued for customer message {msg_id}")

                    # CRITICAL FIX: Only send AI response webhook if WhatsApp send succeeded
                    # This prevents false "sent" logs when bridge returns 401/404/500
                    if SHEETS_WEBHOOK_AVAILABLE and sheets_webhook and response and send_success:
                        asyncio.create_task(
                            sheets_webhook.send_message_event(
                                tenant_id=tenant_id,
                                customer_jid=chat_jid,
                                customer_phone=customer_phone,
                                customer_name=from_name or customer_phone,
                                message_id=f"{msg_id}_response",  # Unique ID for response
                                message_content=response,
                                sender_type="assistant",
                                timestamp=datetime.now().isoformat(),
                            )
                        )
                        logger.debug(f"📊 Sheets webhook queued for AI response to {msg_id}")
                    elif not send_success and response:
                        # Store failed message for retry
                        logger.error(
                            f"❌ WhatsApp send failed for {chat_jid} - NOT logging to Sheets | "
                            f"Response: {response[:100]}..."
                        )
                        # TODO: Store in failed_messages table for retry queue
                        # For now, just log the failure so customer doesn't get ghosted silently

            except Exception as conv_error:
                logger.warning(f"⚠️ Failed to save conversation record (non-fatal): {conv_error}")

            # No cleanup needed - Gemini processes media directly from bytes

            # Mark as processed
            self.processed_message_ids.add(msg_id)

            logger.info(f"✅ Message {msg_id} processed successfully")

        except Exception as e:
            logger.error(f"❌ Error processing message {message.get('id')}: {e}")

    async def _generate_response(
        self,
        user_message: str,
        lang_context: Optional[LanguageContext],
        chat_jid: str = None,
        render_mode: str = "human",
        tool_metadata: Optional[Dict] = None,
        client_config: Optional[Dict] = None,
    ) -> str:
        """
        Generate AI response with multi-model fallback:
        1. Gemini 2.5 Flash (primary)
        2. OpenAI GPT-4o-mini (fallback)

        Args:
            user_message: User's message content.
            lang_context: Detected language context (optional).
            chat_jid: Chat/recipient ID for history and persona.
            render_mode: Default "human" (Persona Engine). Use "bot" for raw LLM output.
            tool_metadata: If a Tool was executed this turn and returns
                {"render_mode": "bot"}, that forces skipping Persona Engine for
                this response only.

        TRACE framework integrated via _trace_pipeline() below.
        Set TRACE_ENABLED=true to activate (ASI → CAE → SRP pipeline).
        ERS / HandoverSystem runs via existing path — unchanged.
        """
        # === SANDBOX (dry-run test) GUARD ===
        # Set by /api/setup/test-message via client_config["sandbox"] = True.
        # When active: NO consequential tool executes and NOTHING is written to
        # the DB (conversation_logs / agent-memory / trajectory). Tool calls are
        # replaced with a stub so the model still composes a natural reply.
        # Strict no-op when falsy — live behavior is completely unchanged.
        _sandbox = bool((client_config or {}).get("sandbox"))

        def _sandbox_stub(_name: str) -> Dict[str, Any]:
            return {
                "status": "sandbox",
                "message": (
                    f"[Sandbox test] Bijou would run '{_name}' here, "
                    "but actions are disabled in test mode."
                ),
            }

        # Dynamic mode: Tool executed with render_mode="bot" forces raw LLM output
        if tool_metadata and tool_metadata.get("render_mode") == "bot":
            render_mode = "bot"
            logger.debug(
                "render_mode=bot: Tool requested raw output, skipping Persona Engine"
            )

        # Knowledge Engine Context (Phase 2)
        knowledge_context = ""
        if self.knowledge_uploader:
            tenant_id = client_config.get("tenant_id") if client_config else None
            if tenant_id:
                try:
                    # Get combined knowledge from all uploaded documents
                    import asyncio

                    if asyncio.iscoroutinefunction(
                        self.knowledge_uploader.get_combined_knowledge
                    ):
                        # ✅ FIX: Use asyncio.run() instead of creating new event loop
                        # This handles the case when there's already a running loop
                        try:
                            # Try to get existing running loop
                            loop = asyncio.get_running_loop()
                            # If we're already in an async context, create a task
                            import concurrent.futures

                            with concurrent.futures.ThreadPoolExecutor() as pool:
                                knowledge_context = pool.submit(
                                    lambda: asyncio.run(
                                        self.knowledge_uploader.get_combined_knowledge(
                                            tenant_id
                                        )
                                    )
                                ).result()
                        except RuntimeError:
                            # No running loop, safe to use asyncio.run()
                            knowledge_context = asyncio.run(
                                self.knowledge_uploader.get_combined_knowledge(
                                    tenant_id
                                )
                            )
                    else:
                        knowledge_context = (
                            self.knowledge_uploader.get_combined_knowledge(tenant_id)
                        )

                    if knowledge_context:
                        logger.info(
                            f"🧠 Injecting {len(knowledge_context)} chars of business context"
                        )
                except Exception as e:
                    logger.error(f"❌ Error getting knowledge context: {e}")
                    knowledge_context = ""

        # === RENDER MODE: bot = raw LLM output, human = Persona Engine ===
        # TEMPORARY FIX: Always use file-based prompt (bypass persona manager)
        # This ensures the updated bijou_system_prompt.txt is used instead of cached DB persona
        system_instruction = self._get_default_system_prompt(
            knowledge_context=knowledge_context
        )
        logger.debug("Using file-based system prompt (persona manager bypassed)")

        # === VERTICAL TEMPLATE INJECTION ===
        # Load domain-specific AI instructions based on tenant's assigned vertical
        # (property, dental, fnb, w3j) - includes calendar booking workflows, etc.
        if hasattr(self, "vertical_loader") and tenant_id:
            try:
                vertical_prompt = self.vertical_loader.get_tenant_vertical_prompt(tenant_id)
                if vertical_prompt:
                    system_instruction += (
                        "\n\n========================================\n"
                        "DOMAIN-SPECIFIC EXPERTISE\n"
                        "========================================\n"
                        f"{vertical_prompt}\n"
                    )
                    logger.info(f"📋 Vertical template injected for tenant {tenant_id[:8]}...")
            except Exception as e:
                logger.error(f"Error loading vertical template: {e}")
        # === END VERTICAL TEMPLATE ===

        # === MANGLISH MODE INJECTION ===
        # If tenant has manglish_mode enabled, append Malaysian English instruction
        if client_config and client_config.get("manglish_mode"):
            system_instruction += (
                "\n\n## Language Style: Manglish Mode ACTIVE\n"
                "You MUST communicate in natural Malaysian English (Manglish). "
                "Naturally mix in common Malaysian expressions such as 'lah', 'leh', 'lor', 'mah', 'kan', 'wah', 'aiyo'. "
                "Keep the tone warm, friendly, and relatable to a Malaysian audience. "
                "Example: 'No worries lah, I help you check!' instead of 'No worries, I will check for you.'"
            )
            logger.debug("🇲🇾 Manglish mode injected into system prompt")
        # === END MANGLISH MODE ===

        # === TRACE EMPATHY PIPELINE (ASI → CAE → SRP) ===
        # Gated by TRACE_ENABLED=true. Appends strategy addendum to system_instruction.
        # Does NOT replace the existing prompt — only enhances it.
        _trace_bundle = _get_trace_agents()
        if _trace_bundle is not None:
            _asi, _cae, _srp = _trace_bundle
            try:
                # Note: full conv history loads later; agents work on current message context
                _conv_hist = None
                # ── Stage 1: ASI – Affective State Identifier ──────────────────────
                _emotional_state: Dict[str, Any] = await asyncio.to_thread(
                    _asi.identify_emotion,
                    user_message,
                    _conv_hist,
                )
                logger.info(
                    f"🎭 TRACE/ASI | emotion={_emotional_state.get('emotion')} "
                    f"confidence={_emotional_state.get('confidence', 0):.2f} "
                    f"intensity={_emotional_state.get('intensity')} "
                    f"tenant={tenant_id[:8] if tenant_id else 'n/a'}"
                )

                # ── Stage 2: CAE – Causal Analysis Engine ──────────────────────────
                _causal_breakdown: Dict[str, Any] = await asyncio.to_thread(
                    _cae.analyze_cause,
                    user_message,
                    _emotional_state.get("emotion", "neutral"),
                    float(_emotional_state.get("confidence", 0.5)),
                    _conv_hist,
                )
                logger.info(
                    f"🔍 TRACE/CAE | global_cause={_causal_breakdown.get('global_cause', '')[:60]} "
                    f"urgency={_causal_breakdown.get('urgency_level')} "
                    f"situation={_causal_breakdown.get('situation_type')}"
                )

                # ── Stage 3: SRP – Strategic Response Planner ──────────────────────
                _response_strategy: Dict[str, Any] = await asyncio.to_thread(
                    _srp.plan_strategy,
                    user_message,
                    _emotional_state.get("emotion", "neutral"),
                    float(_emotional_state.get("confidence", 0.5)),
                    _causal_breakdown.get("global_cause", ""),
                    _causal_breakdown.get("unmet_need", ""),
                    _causal_breakdown.get("urgency_level", "medium"),
                    _conv_hist,
                )
                _rag_chunks: Dict = _response_strategy.get("knowledge_retrieved", {})
                logger.info(
                    f"🗺️  TRACE/SRP | strategy={_response_strategy.get('strategy')} "
                    f"rag_keys={list(_rag_chunks.keys())} "
                    f"confidence={_response_strategy.get('confidence', 0):.2f}"
                )

                # ── Stage 4: Enhance system prompt with strategy addendum ───────────
                _strategy_name: str = _response_strategy.get("strategy", "interpretation")
                _rag_text: str = ""
                for _rag_cat, _rag_entries in _rag_chunks.items():
                    if _rag_entries:
                        _rag_text += f"\n  [{_rag_cat}] " + " | ".join(_rag_entries[:3])

                system_instruction += (
                    "\n\n========================================\n"
                    "TRACE EMPATHY GUIDANCE (live context)\n"
                    "========================================\n"
                    f"Customer emotional state : {_emotional_state.get('emotion', 'neutral').upper()} "
                    f"(intensity: {_emotional_state.get('intensity', 'medium')}, "
                    f"confidence: {_emotional_state.get('confidence', 0.5):.0%})\n"
                    f"Root cause               : {_causal_breakdown.get('global_cause', '')}\n"
                    f"Unmet need               : {_causal_breakdown.get('unmet_need', '')}\n"
                    f"Urgency                  : {_causal_breakdown.get('urgency_level', 'medium').upper()}\n"
                    f"Recommended strategy     : {_strategy_name.upper()} — "
                    f"{_response_strategy.get('rationale', '')}\n"
                    f"Empathy behaviours       : {', '.join(_response_strategy.get('behavioural_taxonomy', _response_strategy.get('behavioral_taxonomy', [])))}\n"
                    f"Response guidance        :\n"
                    + "\n".join(
                        f"  • {g}"
                        for g in _response_strategy.get("response_guidance", [])
                    )
                    + (f"\nKnowledge base hints:{_rag_text}" if _rag_text else "")
                    + "\n========================================"
                )
                logger.debug(
                    f"💡 TRACE addendum injected ({len(system_instruction)} chars total)"
                )

            except Exception as _trace_err:
                logger.warning(f"⚠️ TRACE pipeline error (non-fatal, falling back): {_trace_err}")
        # === END TRACE EMPATHY PIPELINE ===

        # === MEDIA LIBRARY INJECTION ===
        # Lists the tenant's uploaded media files so Bijou can attach them via [SEND_FILE:uuid]
        if tenant_id and hasattr(self, "db_conn") and self.db_conn and self.db_type == "supabase":
            try:
                _ml = self.db_conn.table("media_library") \
                    .select("id, original_name, description, tags, file_type") \
                    .eq("tenant_id", tenant_id) \
                    .execute()
                if _ml.data:
                    _lines = [
                        "\n\n## 📎 SENDABLE MEDIA FILES",
                        "You can attach a file to your reply by placing [SEND_FILE:uuid] at the END of your reply.",
                        "Only do this when the file genuinely helps the customer. Never invent an ID.",
                    ]
                    for _m in _ml.data:
                        _tags = ", ".join(_m.get("tags") or []) or "(no trigger keywords set)"
                        _desc = _m.get("description") or ""
                        _line = f"  • [{_m['id']}] {_m['original_name']} ({_m['file_type']})"
                        if _desc:
                            _line += f" — {_desc}"
                        _line += f" | send when customer asks about: {_tags}"
                        _lines.append(_line)
                    system_instruction += "\n".join(_lines)
                    logger.debug(f"📎 Media library: {len(_ml.data)} files injected into prompt")
            except Exception as _mle:
                logger.debug(f"Media library injection skipped: {_mle}")
        # === END MEDIA LIBRARY INJECTION ===
        # === END RENDER MODE ===

        # Retrieve conversation history (last 10 messages) via _get_conversation_history
        conversation_history = (
            self._get_conversation_history(chat_jid, limit=10, tenant_id=tenant_id) if chat_jid else []
        )

        # Build context-aware prompt from history
        if conversation_history:
            lines = []
            for m in conversation_history[-10:]:
                role = m.get("role", "")
                parts = m.get("parts", [])
                text = parts[0].get("text", "") if parts else ""
                if role == "user" and text:
                    lines.append(f"User: {text}")
                elif role == "model" and text:
                    lines.append(f"Bijou: {text}")
            full_context = (
                "Previous conversation:\n"
                + "\n".join(lines)
                + f"\n\nUser: {user_message}"
            )
        else:
            full_context = user_message

        # === Agent memory READ (Phase 1, flag-gated; default off = no change) ===
        if _agent_feature_enabled("ENABLE_AGENT_MEMORY", tenant_id) and chat_jid:
            try:
                from src.core.agent_memory import MemoryStore

                _mem = MemoryStore(self.db_conn).get(tenant_id, chat_jid)
                if _mem.get("summary") or _mem.get("facts"):
                    full_context = (
                        f"[Memory of this customer] summary: {_mem.get('summary', '')}; "
                        f"facts: {_mem.get('facts', {})}\n\n" + full_context
                    )
            except Exception as _mre:
                logger.debug(f"agent memory read skipped: {_mre}")
        # === END agent memory READ ===

        # === Gateway-primary agent (Phase 2, flag-gated) ===
        # When ENABLE_AGENT_LOOP is on for this tenant, run the tool-calling loop through
        # the OmniRoute gateway (OpenAI-compatible, multi-provider). On ANY error it falls
        # through to the Gemini path below — so it can never break a reply. Flag off = skipped.
        if _agent_feature_enabled("ENABLE_AGENT_LOOP", tenant_id) and chat_jid:
            _gw_ep = os.getenv("CUSTOM_API_ENDPOINT") or os.getenv("CUSTOME_API_ENDOINT")
            _gw_key = os.getenv("CUSTOM_API_KEY") or os.getenv("CUSTOME_API_KEY")
            if _gw_ep and _gw_key:
                try:
                    from types import SimpleNamespace

                    from openai import OpenAI

                    from src.core.gateway_agent import run_gateway_agent

                    _gw_client = OpenAI(base_url=_gw_ep, api_key=_gw_key)
                    _decls = (
                        self.function_caller.get_function_declarations()
                        if getattr(self, "function_caller", None) and self.function_caller.enabled
                        else []
                    )
                    _guard_fn = None
                    if _agent_feature_enabled("ENABLE_ACTION_GUARD", tenant_id):
                        from src.core.action_guard import ActionGuard

                        _ag = ActionGuard(self.db_conn)
                        _guard_fn = lambda _n: _ag.check(tenant_id, _n)  # noqa: E731

                    async def _gw_exec(_name, _args):
                        # SANDBOX: short-circuit BEFORE the real executor runs.
                        if _sandbox:
                            logger.info(f"🧪 Sandbox: '{_name}' NOT executed (test mode)")
                            return _sandbox_stub(_name)
                        _ctx = dict(client_config) if client_config else {}
                        _ctx["chat_jid"] = chat_jid
                        return await self.function_caller._execute_function(
                            SimpleNamespace(name=_name, args=_args), chat_jid, user_context=_ctx
                        )

                    # Multi-provider fallback chain for zero-interruption replies. Ordered
                    # fast/cheap -> capable, spanning DIFFERENT gateway backends (cc/kr/aug/ddgw)
                    # so no single provider's quota can take the agent offline. _complete() in
                    # gateway_agent.py skips any model that errors and rolls to the next.
                    # (Avoids antigravity/* and auto/* — those exhaust first: 429 / 503.)
                    _models = (
                        os.getenv("AI_GATEWAY_MODELS")
                        or "cc/claude-haiku-4-5-20251001,kr/claude-haiku-4.5,aug/claude-haiku-4.5,"
                        "cc/claude-sonnet-5,aug/claude-sonnet-4.6,cc/claude-opus-4-8,"
                        "ddgw/claude-3-5-haiku-20241022"
                    ).split(",")
                    _gres = await run_gateway_agent(
                        system=system_instruction,
                        user_message=user_message,
                        history=conversation_history,
                        declarations=_decls,
                        client=_gw_client,
                        model_chain=[m.strip() for m in _models if m.strip()],
                        execute_tool=_gw_exec,
                        guard=_guard_fn,
                    )
                    _greply = (_gres.get("reply") or "").strip()
                    if _greply:
                        if _agent_feature_enabled("ENABLE_AGENT_MEMORY", tenant_id) and not _sandbox:
                            try:
                                from src.core.agent_memory import MemoryStore

                                _ms = MemoryStore(self.db_conn)
                                _pv = _ms.get(tenant_id, chat_jid)
                                _roll = (
                                    f"{_pv.get('summary', '')} | U:{user_message} B:{_greply}"
                                ).strip()[-1500:]
                                _ms.update(tenant_id, chat_jid, _pv.get("facts", {}) or {}, _roll)
                            except Exception as _me:
                                logger.debug(f"gw memory write skipped: {_me}")
                        if _agent_feature_enabled("ENABLE_AGENT_TRAJECTORY", tenant_id) and not _sandbox:
                            try:
                                from src.core.trajectory_log import TrajectoryLog

                                TrajectoryLog(self.db_conn).record(
                                    tenant_id, chat_jid, _gres.get("steps", [])
                                )
                            except Exception as _te:
                                logger.debug(f"gw trajectory skipped: {_te}")
                        logger.info("✅ Response generated via gateway agent (OmniRoute)")
                        return _greply
                except Exception as _gae:
                    logger.warning(f"⚠️ Gateway agent failed, falling back to Gemini path: {_gae}")
        # === END gateway-primary agent ===

        # Build OpenAI-format messages once (used by MiniMax + later fallbacks).
        # Tool-calling stays on Gemini (function declarations don't survive the
        # OpenAI-format conversion for non-Gemini providers).
        _messages = [{"role": "system", "content": system_instruction}]
        if conversation_history:
            for _m in conversation_history[-10:]:
                _r = _m.get("role", "")
                _parts = _m.get("parts", [])
                _text = _parts[0].get("text", "") if _parts else ""
                if not _text:
                    continue
                _role = "user" if _r == "user" else "assistant"
                _messages.append({"role": _role, "content": _text})
        _messages.append({"role": "user", "content": user_message})

        # === MiniMax PRIMARY (OpenAI-compatible, since 2026-08-04) ===
        # Gemini API key on the project is currently SUSPENDED (Consumer suspended,
        # 403 PERMISSION_DENIED), so we hit MiniMax first to avoid the 2+ minute
        # Gemini retry-then-timeout cycle that bricks the Test Bijou sandbox +
        # any live chat request. Keep Gemini below as a fallback for when the
        # key is reactivated.
        mm_endpoint = os.getenv("MINIMAX_API_ENDPOINT") or "https://api.minimax.io/v1"
        mm_key = os.getenv("MINIMAX_API_KEY")
        logger.info(
            f"🧪 MiniMax check: mm_endpoint={mm_endpoint!r}, "
            f"mm_key_set={bool(mm_key)}, mm_key_len={len(mm_key) if mm_key else 0}"
        )
        if mm_key:
            mm_models = os.getenv("MINIMAX_MODELS", "MiniMax-M3,MiniMax-M2.7").split(",")
            # Build the per-request user context for tool dispatch. tenant_id is
            # already on the envelope (client_config), so we just thread it
            # through to _call_function via the OpenAI tool-calling path.
            mm_user_context = {
                "tenant_id": client_config.get("tenant_id") if client_config else None,
            }
            for mm_model in [m.strip() for m in mm_models if m.strip()]:
                try:
                    # Use the FunctionCaller's OpenAI-compatible path so
                    # MiniMax gets the same 11 function declarations Gemini
                    # gets. Falls back to the plain path if FunctionCaller
                    # is not enabled / not initialized.
                    fc = getattr(self, "function_caller", None)
                    if fc and getattr(fc, "enabled", False):
                        content = await fc.call_with_openai_tools(
                            messages=list(_messages),
                            model=mm_model,
                            api_key=mm_key,
                            base_url=mm_endpoint,
                            temperature=0.7,
                            max_tokens=1024,
                            user_context=mm_user_context,
                        )
                    else:
                        # No function caller (or disabled) — keep the old
                        # text-only path so the agent still responds.
                        from openai import OpenAI
                        mm_client = OpenAI(base_url=mm_endpoint, api_key=mm_key)
                        resp = mm_client.chat.completions.create(
                            model=mm_model,
                            messages=_messages,
                            temperature=0.7,
                            max_tokens=1024,
                        )
                        content = (resp.choices[0].message.content or "").strip()
                        import re
                        content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
                    if content:
                        logger.info(
                            f"✅ Response via MiniMax ({mm_model})"
                            + (" + tool calls" if fc and getattr(fc, "enabled", False) else "")
                        )
                        return content
                except Exception as model_err:
                    logger.warning(f"⚠️ MiniMax model {mm_model} failed: {model_err}")
                    continue
        # === END MiniMax PRIMARY ===

        # Try Gemini 2.5 Flash (with RoundRobinRotator for 429 handling)
        try:
            from google import genai
            from google.genai import types

            # Get API key from rotator or fallback to config
            api_key = None
            if self.llm_rotator:
                api_key = self.llm_rotator.get_next_key()
            if not api_key:
                api_key = self.config.get("gemini_api_key")

            if not api_key:
                raise ValueError(
                    "No Gemini API key available (GEMINI_API_KEY or GEMINI_API_KEYS)"
                )

            max_retries = 3
            last_error = None

            for attempt in range(max_retries):
                try:
                    client = genai.Client(api_key=api_key)
                    max_tokens = self.config.get("max_output_tokens", 1024)

                    # ✅ FIX: Add function declarations so LLM can call tools (escalation, calendar, etc.)
                    tools = None
                    if hasattr(self, 'function_caller') and self.function_caller and self.function_caller.enabled:
                        try:
                            functions = self.function_caller.get_function_declarations()
                            if functions:
                                tools = [types.Tool(function_declarations=functions)]
                                logger.debug(f"🔧 {len(functions)} function declarations added to LLM")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not load function declarations: {e}")

                    config_params = {
                        "temperature": 0.7,
                        "max_output_tokens": max_tokens,
                        "system_instruction": system_instruction,
                    }
                    if tools:
                        config_params["tools"] = tools

                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=full_context,
                        config=types.GenerateContentConfig(**config_params),
                    )

                    # ✅ FIX: Handle function calls if LLM decided to call tools
                    tenant_id = client_config.get("tenant_id") if client_config else None
                    if response.candidates and len(response.candidates) > 0:
                        candidate = response.candidates[0]

                        # ✅ CRITICAL FIX: Gemini returns function calls in content.parts, NOT candidate.function_calls
                        function_calls_found = []
                        if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts'):
                            for part in candidate.content.parts:
                                if hasattr(part, 'function_call') and part.function_call:
                                    function_calls_found.append(part.function_call)

                        # Execute function calls if any were found
                        if function_calls_found:
                            logger.info(f"🔧 LLM called {len(function_calls_found)} function(s)")

                            # Execute function calls
                            tool_results = []
                            for func_call in function_calls_found:
                                try:
                                    logger.info(f"🔧 Executing: {func_call.name}({func_call.args})")
                                    # Inject chat_jid into user_context so tools like escalate_to_human can access it
                                    tool_context = dict(client_config) if client_config else {}
                                    tool_context["chat_jid"] = chat_jid

                                    # === ActionGuard (Phase 3, flag-gated): consequential tools
                                    # do NOT auto-fire without a per-tenant 'allow' policy ===
                                    _guard_mode = "allow"
                                    if _agent_feature_enabled("ENABLE_ACTION_GUARD", tenant_id) and not _sandbox:
                                        try:
                                            from src.core.action_guard import ActionGuard

                                            _guard_mode = ActionGuard(self.db_conn).check(tenant_id, func_call.name)
                                        except Exception as _ge:
                                            logger.debug(f"ActionGuard check skipped: {_ge}")
                                    if _sandbox:
                                        # SANDBOX: short-circuit BEFORE the real executor runs.
                                        logger.info(f"🧪 Sandbox: '{func_call.name}' NOT executed (test mode)")
                                        result = _sandbox_stub(func_call.name)
                                    elif _guard_mode != "allow":
                                        logger.info(f"🛡️ ActionGuard: '{func_call.name}' -> {_guard_mode} (not auto-executed)")
                                        result = {
                                            "status": "blocked",
                                            "guard": _guard_mode,
                                            "message": (
                                                f"Action '{func_call.name}' needs confirmation before it runs."
                                                if _guard_mode == "confirm"
                                                else f"Action '{func_call.name}' is not permitted for this tenant."
                                            ),
                                        }
                                    else:
                                        result = await self.function_caller._execute_function(
                                            func_call,
                                            chat_jid,
                                            user_context=tool_context
                                        )

                                    if result.get("status") == "success":
                                        logger.info(f"✅ Function {func_call.name} executed successfully")
                                        # Log successful tool call for dashboard visibility
                                        if tenant_id and self.db_conn and not _sandbox:
                                            try:
                                                self.db_conn.table("conversation_logs").insert({
                                                    "tenant_id": tenant_id,
                                                    "chat_jid": chat_jid,
                                                    "event_type": "tool_call",
                                                    "tool_name": func_call.name,
                                                    "success": True,
                                                    "metadata": {"args": dict(func_call.args)},
                                                }).execute()
                                            except Exception as log_err:
                                                logger.debug(f"Could not log successful tool call: {log_err}")
                                    elif result.get("status") == "error":
                                        logger.error(f"❌ Function {func_call.name} failed: {result.get('error')}")
                                        # Log to database for dashboard visibility
                                        if tenant_id and self.db_conn and not _sandbox:
                                            try:
                                                self.db_conn.table("conversation_logs").insert({
                                                    "tenant_id": tenant_id,
                                                    "chat_jid": chat_jid,
                                                    "event_type": "tool_failure",
                                                    "tool_name": func_call.name,
                                                    "success": False,
                                                    "error_message": str(result.get('error')),
                                                }).execute()
                                            except Exception as log_err:
                                                logger.debug(f"Could not log tool failure: {log_err}")


                                    tool_results.append({
                                        "status": result.get("status"),
                                        "message": result.get("error") if result.get("error") else "Success",
                                        "data": result
                                    })

                                except Exception as e:
                                    logger.error(f"❌ Error executing function {func_call.name}: {e}")
                                    # Log failure to database
                                    if tenant_id and self.db_conn and not _sandbox:
                                        try:
                                            self.db_conn.table("conversation_logs").insert({
                                                "tenant_id": tenant_id,
                                                "chat_jid": chat_jid,
                                                "event_type": "tool_failure",
                                                "tool_name": func_call.name,
                                                "success": False,
                                                "error_message": str(e),
                                            }).execute()
                                        except Exception as log_err:
                                            logger.debug(f"Could not log tool failure: {log_err}")


                                    tool_results.append({
                                        "status": "error",
                                        "error": str(e)
                                    })

                            # Send tool results back to Gemini for a final natural language response
                            import json
                            full_context += f"\n\nTool Execution Results:\n{json.dumps(tool_results)}"

                            # === TrajectoryLog (Phase 3, flag-gated): record the agent's tool steps ===
                            if _agent_feature_enabled("ENABLE_AGENT_TRAJECTORY", tenant_id) and chat_jid and not _sandbox:
                                try:
                                    from src.core.trajectory_log import TrajectoryLog

                                    _steps = [
                                        {
                                            "tool": fc.name,
                                            "args": dict(fc.args) if getattr(fc, "args", None) else {},
                                            "result": tr,
                                        }
                                        for fc, tr in zip(function_calls_found, tool_results)
                                    ]
                                    TrajectoryLog(self.db_conn).record(tenant_id, chat_jid, _steps)
                                except Exception as _tle:
                                    logger.debug(f"trajectory log skipped: {_tle}")
                            # === END TrajectoryLog ===

                            logger.info("🔧 Sending tool execution results to Gemini for final response...")
                            response = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=full_context,
                                config=types.GenerateContentConfig(**config_params),
                            )

                    logger.info("✅ Response generated via Gemini 2.5 Flash")

                    # ✅ FIX: Handle case where response only has function calls (no text)
                    if response.text:
                        _reply = response.text.strip()
                    else:
                        # Function calls executed, return confirmation
                        logger.info("ℹ️ Response contained only function calls, returning confirmation")
                        _reply = "I've processed your request."

                    # === Agent memory WRITE (Phase 1, flag-gated; rolling summary, no extra LLM call) ===
                    if _agent_feature_enabled("ENABLE_AGENT_MEMORY", tenant_id) and chat_jid and not _sandbox:
                        try:
                            from src.core.agent_memory import MemoryStore

                            _ms = MemoryStore(self.db_conn)
                            _prev = _ms.get(tenant_id, chat_jid)
                            _rolling = (
                                f"{_prev.get('summary', '')} | U:{user_message} B:{_reply}"
                            ).strip()[-1500:]
                            _ms.update(tenant_id, chat_jid, _prev.get("facts", {}) or {}, _rolling)
                        except Exception as _mwe:
                            logger.debug(f"agent memory write skipped: {_mwe}")
                    # === END agent memory WRITE ===

                    return _reply
                except Exception as err:
                    last_error = err
                    err_str = str(err).lower()
                    # 429 Resource Exhausted - mark key and retry with next
                    if (
                        "429" in err_str
                        or "resource exhausted" in err_str
                        or "quota" in err_str
                        or "rate limit" in err_str
                    ) and self.llm_rotator:
                        self.llm_rotator.mark_rate_limited(api_key)
                        next_key = self.llm_rotator.get_next_key()
                        if next_key and next_key != api_key:
                            api_key = next_key
                            logger.info(
                                "🔄 429 detected, retrying with next API key..."
                            )
                            continue
                    raise last_error

        except Exception as gemini_error:
            logger.warning(
                f"⚠️ Gemini failed ({gemini_error}), trying AI gateway fallback..."
            )

            # NOTE: MiniMax is now the PRIMARY provider (moved above the Gemini
            # block on 2026-08-04 when the Gemini key was suspended). Gemini is
            # itself the fallback for the gateway/OmniRoute text-only path below.
            # Reuse the _messages list built earlier in the function.
            messages = _messages

            # 1) OmniRoute AI gateway (LEGACY — kept as fallback in case MiniMax is down)
            #    OpenAI-compatible, multi-provider: free pool + paid Claude.
            #    Accept both the corrected and legacy (typo) env var names so the
            #    backend stays in sync through the CUSTOM_API_ENDPOINT rename.
            gw_endpoint = (
                os.getenv("CUSTOM_API_ENDPOINT")
                or os.getenv("CUSTOME_API_ENDOINT")
                or self.config.get("ai_gateway_endpoint")
            )
            gw_key = os.getenv("CUSTOM_API_KEY") or os.getenv("CUSTOME_API_KEY") or self.config.get("ai_gateway_key")
            if gw_endpoint and gw_key:
                gw_models = (
                    os.getenv("AI_GATEWAY_MODELS")
                    or "auto/best-fast,antigravity/gemini-2.5-flash,cc/claude-haiku-4-5-20251001"
                ).split(",")
                try:
                    from openai import OpenAI

                    gw_client = OpenAI(base_url=gw_endpoint, api_key=gw_key)
                    for gw_model in [m.strip() for m in gw_models if m.strip()]:
                        try:
                            resp = gw_client.chat.completions.create(
                                model=gw_model,
                                messages=messages,
                                temperature=0.7,
                                max_tokens=1024,
                            )
                            content = (resp.choices[0].message.content or "").strip()
                            if content:
                                logger.info(
                                    f"✅ Response via AI gateway ({getattr(resp, 'model', None) or gw_model})"
                                )
                                return content
                        except Exception as gw_err:
                            logger.warning(f"⚠️ Gateway model {gw_model} failed: {gw_err}")
                except Exception as gw_init_err:
                    logger.warning(f"⚠️ AI gateway unavailable: {gw_init_err}")

            # 2) Direct OpenAI as the final fallback (if an OpenAI key is configured).
            try:
                from openai import OpenAI

                if not hasattr(self, "openai_client"):
                    self.openai_client = OpenAI(api_key=self.config.get("openai_api_key"))

                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1024,
                )
                logger.info("✅ Response generated via OpenAI GPT-4o-mini (fallback)")
                return response.choices[0].message.content.strip()

            except Exception as openai_error:
                logger.error(
                    f"❌ All AI providers failed. Gemini: {gemini_error}, OpenAI: {openai_error}"
                )
                return "I apologize, but I'm having trouble processing your request right now. Please try again in a moment or type '@bijou escalate' to speak with a human agent."

    def _enforce_short_message(self, response: str) -> str:
        """
        Enforce WhatsApp-style short messages

        Rules:
        - Max 300 characters (increased from 200 to avoid mid-sentence cuts)
        - Max 4 lines
        - If longer, truncate at sentence boundary
        """
        # Remove excessive newlines
        response = "\n".join(
            [line.strip() for line in response.split("\n") if line.strip()]
        )

        # Hard limit: 300 characters (balance between brevity and completeness)
        if len(response) > 300:
            # Try to truncate at sentence boundary
            sentences = response.split(". ")
            short_response = sentences[0]

            # Add more sentences if under 300 chars
            for i in range(1, len(sentences)):
                test_response = short_response + ". " + sentences[i]
                if len(test_response) <= 300:
                    short_response = test_response
                else:
                    break

            # Ensure it ends with punctuation
            if not short_response.endswith(
                (".", "!", "?", "😊", "🙂", "👍", "✨", "🎯")
            ):
                short_response += "!"

            response = short_response

        # Limit to 4 lines max (increased from 3)
        lines = response.split("\n")
        if len(lines) > 4:
            response = "\n".join(lines[:4])

        return response

    def _get_default_system_prompt(self, knowledge_context: str = "") -> str:
        """Get the default Bijou system prompt from bijou_system_prompt.txt file"""
        try:
            # Read from the updated system prompt file
            prompt_file = Path(__file__).parent / "bijou_system_prompt.txt"
            if prompt_file.exists():
                prompt = prompt_file.read_text(encoding="utf-8")

                # Append knowledge context if available
                if knowledge_context:
                    prompt += f"\n\n## 🧠 ADDITIONAL BUSINESS CONTEXT & KNOWLEDGE\n{knowledge_context}\n"

                return prompt.strip()  # Ensure it's stripped after appending
            else:
                logger.warning(f"System prompt file not found: {prompt_file}")
                # Fallback to minimal prompt
                return """You are Bijou, W3J Consulting's AI assistant.

BE BRIEF - Max 30 words on WhatsApp. Text like a human friend, not a company.
NO MARKDOWN - Plain text only.
BE HELPFUL - Answer directly, then stop."""
        except Exception as e:
            logger.error(f"Failed to load system prompt: {e}")
            # Fallback to minimal prompt
            return """You are Bijou, W3J Consulting's AI assistant.

BE BRIEF - Max 30 words on WhatsApp. Text like a human friend, not a company.
NO MARKDOWN - Plain text only.
BE HELPFUL - Answer directly, then stop."""

    def _send_voice_response(
        self,
        chat_jid: str,
        text_response: str,
        language: Optional[str] = None,
        tenant_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """
        Generate and send voice response via WhatsApp PTT using OpenAI TTS.

        Args:
            chat_jid: Recipient WhatsApp JID
            text_response: Text to convert to speech
            language: Language code (auto-detect if None)
            tenant_id: Tenant ID
            channel: Channel (whatsapp/telegram)

        Returns:
            True if voice sent successfully, False otherwise
        """
        if not self.voice_service:
            logger.debug("Voice service not available")
            return False

        try:
            logger.info(f"🎤 Generating voice for response ({len(text_response)} chars)...")

            # ✅ FIX: Skip voice for automated/system messages
            SKIP_VOICE_KEYWORDS = ["HEARTBEAT_OK", "AUTO:", "BOT:", "[SYSTEM]", "[AUTOMATED]"]
            if any(keyword in text_response for keyword in SKIP_VOICE_KEYWORDS):
                logger.info(f"⏭️ Skipping voice for automated message: {text_response[:50]}...")
                return False

            # Generate voice audio using OpenAI TTS
            voice_data = self.voice_service.generate_voice(
                text=text_response,
                language=language,
                emotion=None,  # Auto-detect
                tenant_id=tenant_id,
            )

            if not voice_data:
                logger.warning("Voice generation failed - OpenAI TTS returned None")
                return False

            file_path = voice_data.get("path")
            if not file_path:
                logger.warning("Voice generation returned no file path")
                return False

            # Send via WhatsApp bridge (only WhatsApp supports PTT)
            if channel and channel != "whatsapp":
                logger.warning(f"Voice responses only supported on WhatsApp, not {channel}")
                return False

            # Use BridgeAdapter.send_audio() method for sending voice notes
            from src.channels.bridge_adapter import BridgeAdapter

            # ✅ FIX: Pass API key for authentication
            bridge_adapter = BridgeAdapter(base_url=self.bridge_url, api_key=self.bridge_api_key)

            # Send as PTT (push-to-talk) audio
            logger.info(f"📤 Sending voice message to {chat_jid}...")
            success = bridge_adapter.send_audio(chat_jid, file_path, ptt=True)

            if success:
                logger.info(f"✅ Voice message sent successfully")

                # Record for self-echo detection
                self._record_sent_message(chat_jid, text_response)

                # Cleanup audio file (VoiceService also cleans up old files)
                try:
                    import os
                    os.remove(file_path)
                except Exception as e:
                    logger.debug(f"Failed to cleanup voice file: {e}")

                return True
            else:
                logger.error(f"❌ Voice send failed via bridge")
                return False

        except Exception as e:
            logger.error(f"❌ Voice response error: {e}", exc_info=True)
            return False

    def _split_long_message(self, message: str, max_len: int = 3800) -> list:
        """
        Split message into chunks under max_len for platform limits (WA/TG ~4096).
        Prefer splitting at paragraph or sentence boundaries.
        """
        if not message or len(message) <= max_len:
            return [message] if message else []

        chunks = []
        remaining = message
        while remaining:
            if len(remaining) <= max_len:
                chunks.append(remaining.strip())
                break
            chunk = remaining[:max_len]
            # Prefer break at newline, then ". ", then " "
            for sep in ("\n\n", "\n", ". ", " "):
                idx = chunk.rfind(sep)
                if idx > max_len // 2:
                    chunk = chunk[: idx + len(sep)].rstrip()
                    remaining = remaining[idx + len(sep) :].lstrip()
                    break
            else:
                remaining = remaining[max_len:]
                chunk = chunk.rstrip()
            if chunk:
                chunks.append(chunk)
        return chunks

    def send_typing_action(
        self, chat_jid: str, channel: str = None, tenant_id: str = None,
        action: str = "start",
    ) -> bool:
        """
        Send typing indicator to recipient via GOWA /send/chat-presence.

        Args:
            chat_jid: WhatsApp JID (e.g. 601234567890@s.whatsapp.net) or Telegram chat_id.
            channel: "whatsapp" or "telegram". Auto-detected if None.
            tenant_id: Tenant UUID for device_id lookup.
            action: "start" (composing) or "stop" (paused). Default "start".

        Returns:
            True if the presence was sent successfully, False otherwise.
        """
        if channel is None:
            if "@" in chat_jid:
                channel = "whatsapp"
            elif chat_jid.lstrip("-").isdigit():
                channel = "telegram"
            else:
                channel = "whatsapp"

        if channel == "telegram" and self.telegram_enabled and self.telegram_adapter:
            return self.telegram_adapter.send_typing_action(chat_jid)

        # WhatsApp: GOWA /send/chat-presence
        try:
            import base64
            resolved_tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID")

            # Build auth headers — same pattern as send_message
            headers = {"Content-Type": "application/json"}
            if self.bridge_api_key and ":" in self.bridge_api_key:
                auth_str = base64.b64encode(self.bridge_api_key.encode()).decode()
                headers["Authorization"] = f"Basic {auth_str}"
            elif self.bridge_api_key:
                headers["X-API-Key"] = self.bridge_api_key

            # Resolve device_id for this tenant
            device_id = self.whatsapp_device_id
            if resolved_tenant_id and resolved_tenant_id != "default" and self.db_conn:
                try:
                    result = (
                        self.db_conn.table("whatsapp_devices")
                        .select("device_id")
                        .eq("tenant_id", resolved_tenant_id)
                        .execute()
                    )
                    if result.data:
                        device_id = result.data[0]["device_id"]
                except Exception as dev_lookup_err:
                    logger.debug(f"Could not resolve device_id for tenant {resolved_tenant_id}: {dev_lookup_err}")
                    # Fall back to default device_id

            headers["X-Device-Id"] = device_id

            # Guard: 0-prefix phone in JID causes bridge panic
            if "@" in chat_jid and chat_jid.split("@")[0].startswith("0"):
                logger.debug(f"⌨️ Skipping typing-presence for 0-prefix JID {chat_jid}")
                return False

            resp = requests.post(
                f"{self.bridge_url}/send/chat-presence",
                json={"phone": chat_jid, "action": action},
                headers=headers,
                timeout=3,
            )
            if resp.status_code != 200:
                logger.debug(
                    f"⌨️ chat-presence {action} → {resp.status_code} for {chat_jid}"
                )
            return resp.status_code == 200
        except Exception as presence_err:
            logger.debug(f"⌨️ chat-presence fire-and-forget failed: {presence_err}")
            return False

    def _send_response_human_burst(
        self, chat_jid: str, response: str, channel: str = None, tenant_id: str = None
    ) -> None:
        """
        Send response with Human Vibe: typing indicators + burst chunks.
        Runs in executor for non-blocking behavior (1000 users won't freeze).
        """
        # Run in executor to avoid blocking webhook/poll loop
        self.executor.submit(
            self._do_send_response_human_burst,
            chat_jid,
            response,
            channel,
            tenant_id,
        )

    def _do_send_response_human_burst(
        self, chat_jid: str, response: str, channel: str = None, tenant_id: str = None
    ) -> None:
        """
        Internal: execute typing + burst send loop. Runs in thread.
        """
        if not response or not response.strip() or response.strip() == "HEARTBEAT_OK":
            return
        # Split into bursts (or single chunk if burst_manager unavailable)
        chunks = (
            split_into_bursts(response, max_chunk_chars=200)
            if split_into_bursts
            else [response.strip()]
        )
        for i, chunk in enumerate(chunks):
            if not chunk:
                continue
            # Start typing indicator (GOWA /send/chat-presence action=start)
            self.send_typing_action(chat_jid, channel=channel, tenant_id=tenant_id, action="start")
            # Simulate typing speed: len * 0.05 seconds (cap at 2.5s)
            delay = min(len(chunk) * 0.05, 2.5)
            if delay > 0:
                time.sleep(delay)
            # Stop typing indicator before sending — clears the "typing..." bubble
            self.send_typing_action(chat_jid, channel=channel, tenant_id=tenant_id, action="stop")
            self.send_message(chat_jid, chunk, channel=channel, tenant_id=tenant_id)

    def send_message(
        self, chat_jid: str, message: str, channel: str = None, tenant_id: str = None
    ) -> bool:
        """
        Send message via appropriate channel (WhatsApp or Telegram).

        Args:
            chat_jid: Recipient ID (WhatsApp JID or Telegram chat_id).
            message: Text message to send.
            channel: Optional channel override ("whatsapp" or "telegram").
                     If not provided, auto-detects based on chat_jid format.

        Returns:
            True if sent successfully, False otherwise.
        """
        import time

        if not message or not message.strip() or message.strip() == "HEARTBEAT_OK":
            # HEARTBEAT_OK is a silent internal acknowledgment used by Gemini
            # to signal it has nothing valuable to add. We skip sending it to user.
            if message.strip() == "HEARTBEAT_OK":
                logger.info(f"🤫 Internal Heartbeat for {chat_jid} - Staying silent")
            return True

        # Safety net: if [BREAK] token leaked through, convert to newlines
        # (Proper splitting happens in _do_send_response_human_burst, but
        #  some code paths call send_message directly with raw LLM output)
        if "[BREAK]" in message.upper():
            import re as _re
            message = _re.sub(r"\[BREAK\]", "\n\n", message, flags=_re.IGNORECASE).strip()

        # Auto-detect channel if not specified
        if channel is None:
            # Telegram chat_ids are typically numeric (positive for users, negative for groups)
            # WhatsApp JIDs contain @ (e.g., 60123456789@s.whatsapp.net or @lid)
            if "@" in chat_jid:
                channel = "whatsapp"
            elif chat_jid.lstrip("-").isdigit():
                channel = "telegram"
            else:
                # Default to WhatsApp for backwards compatibility
                channel = "whatsapp"

        # Split if over platform limit (WA/TG ~4096)
        chunks = self._split_long_message(message)

        # Route to appropriate channel
        if channel == "telegram" and self.telegram_enabled and self.telegram_adapter:
            try:
                for i, chunk in enumerate(chunks):
                    success = self.telegram_adapter.send_text(chat_jid, chunk)
                    if not success:
                        logger.error(
                            f"❌ [TG] Send failed to {chat_jid} (chunk {i + 1}/{len(chunks)})"
                        )
                        return False
                    self._record_sent_message(chat_jid, chunk)
                logger.info(f"📤 [TG] Sent to {chat_jid}: {message[:50]}...")
                return True
            except Exception as e:
                logger.error(f"❌ [TG] Send error: {e}")
                return False
        else:
            # Default: WhatsApp via bridge with retry logic
            max_retries = 3
            retry_delays = [2, 5, 10]  # seconds

            try:
                for i, chunk in enumerate(chunks):
                    # GOWA bridge uses /send/message endpoint, not /api/send
                    url = f"{self.bridge_url}/send/message"
                    resolved_tenant_id = (
                        tenant_id or os.getenv("DEFAULT_TENANT_ID") or "default"
                    )
                    # GOWA expects "phone" and "message" fields, not "recipient"
                    # Guard: 0-prefix phone numbers (e.g. 0191234567@s.whatsapp.net)
                    # cause a bridge panic. Skip and warn — these are un-normalized DB entries.
                    if "@" in chat_jid and chat_jid.split("@")[0].startswith("0"):
                        logger.warning(
                            f"⚠️ [SEND] Skipping send to {chat_jid}: "
                            f"0-prefix phone would cause bridge panic. "
                            f"Check DB for un-normalized phone numbers."
                        )
                        success = True  # treat as sent — this is a data issue, not transient
                        continue
                    payload = {
                        "phone": chat_jid,
                        "message": chunk,
                    }

                    # Setup authentication headers for bridge
                    import base64 as _b64
                    headers = {"Content-Type": "application/json"}
                    _bridge_user = os.getenv("BRIDGE_USER", "")
                    _bridge_pass = os.getenv("BRIDGE_PASSWORD", "")
                    if self.bridge_api_key and ':' in self.bridge_api_key:
                        # Basic Auth format (username:password)
                        auth_str = _b64.b64encode(self.bridge_api_key.encode()).decode()
                        headers["Authorization"] = f"Basic {auth_str}"
                    elif _bridge_user and _bridge_pass:
                        # BRIDGE_USER + BRIDGE_PASSWORD (production standard)
                        auth_str = _b64.b64encode(f"{_bridge_user}:{_bridge_pass}".encode()).decode()
                        headers["Authorization"] = f"Basic {auth_str}"
                    elif self.bridge_api_key:
                        # API key format
                        headers["X-API-Key"] = self.bridge_api_key

                    # Add device ID header - CRITICAL FOR MULTI-TENANT
                    # Look up tenant's device_id from database, not static config
                    device_id = self.whatsapp_device_id  # Default fallback
                    if resolved_tenant_id and resolved_tenant_id != "default" and self.db_conn:
                        try:
                            result = self.db_conn.table("whatsapp_devices").select("device_id").eq("tenant_id", resolved_tenant_id).execute()
                            if result.data and len(result.data) > 0:
                                device_id = result.data[0]["device_id"]
                                logger.debug(f"🔍 Looked up device_id={device_id} for tenant {resolved_tenant_id}")
                            else:
                                logger.warning(f"⚠️ No device_id found for tenant {resolved_tenant_id}, using default: {device_id}")
                        except Exception as lookup_error:
                            logger.error(f"❌ Failed to lookup device_id for tenant {resolved_tenant_id}: {lookup_error}")

                    # Auto-discover device_id from bridge if local lookup returned invalid value
                    if not device_id or device_id in ("default", "", None):
                        try:
                            _disc = requests.get(
                                f"{self.bridge_url}/app/devices",
                                headers={k: v for k, v in headers.items() if k != "Content-Type"},
                                timeout=5,
                            )
                            if _disc.ok:
                                _devs = _disc.json()
                                if isinstance(_devs, list) and _devs:
                                    device_id = _devs[0].get("device_id") or _devs[0].get("id", "")
                                    logger.info(f"🔍 [SEND] Auto-discovered device_id={device_id} from bridge")
                                    # Cache to DB so future sends skip the discovery step
                                    if device_id and self.db_conn and resolved_tenant_id and resolved_tenant_id != "default":
                                        try:
                                            self.db_conn.table("whatsapp_devices").upsert({
                                                "tenant_id": resolved_tenant_id,
                                                "device_id": device_id,
                                                "updated_at": datetime.now().isoformat(),
                                            }, on_conflict="tenant_id").execute()
                                        except Exception as _cache_err:
                                            logger.debug(f"⚠️ Could not cache device_id: {_cache_err}")
                        except Exception as _disc_err:
                            logger.warning(f"⚠️ [SEND] device_id auto-discovery failed: {_disc_err}")

                    if device_id and device_id not in ("default", "", None):
                        headers["X-Device-Id"] = device_id
                    else:
                        logger.error(f"❌ [SEND] No valid device_id for tenant {resolved_tenant_id} — bridge will reject")

                    logger.debug(
                        f"📤 Sending to bridge: {url} with device_id={device_id}, phone={chat_jid}, tenant={resolved_tenant_id}"
                    )

                    # Retry loop for transient errors
                    success = False
                    last_error = None

                    for attempt in range(max_retries):
                        try:
                            response = requests.post(url, json=payload, headers=headers, timeout=30)

                            if response.status_code == 200:
                                success = True
                                break

                            # BUG-5 FIX: If 404 (device not found), recover by deriving device_id from tenant
                            if response.status_code == 404 and resolved_tenant_id and resolved_tenant_id != "default":
                                recovered_device_id = f"bijou-{resolved_tenant_id}"
                                logger.warning(
                                    f"⚠️ [WA] 404 for device {device_id} — recovering with derived ID {recovered_device_id}"
                                )
                                # Update DB so future sends use the correct device_id
                                if self.db_conn:
                                    try:
                                        self.db_conn.table("whatsapp_devices").update({
                                            "device_id": recovered_device_id,
                                            "updated_at": datetime.now().isoformat(),
                                        }).eq("tenant_id", resolved_tenant_id).execute()
                                    except Exception as _upd_err:
                                        logger.warning(f"⚠️ [WA] Could not update device_id in DB: {_upd_err}")
                                # Swap device_id and retry immediately
                                device_id = recovered_device_id
                                headers["X-Device-Id"] = device_id
                                response = requests.post(url, json=payload, headers=headers, timeout=30)
                                if response.status_code == 200:
                                    success = True
                                    break

                            # Check if error is retryable (bridge DB connection issues)
                            error_text = response.text if response.text else ""
                            is_retryable = (
                                "driver: bad connection" in error_text
                                or "failed to save cached sessions" in error_text
                                or "context deadline exceeded" in error_text
                                or response.status_code == 500
                            )

                            last_error = f"status {response.status_code}: {error_text}"

                            if not is_retryable or attempt == max_retries - 1:
                                # Not retryable or final attempt - fail immediately
                                break

                            # Wait before retry (exponential backoff)
                            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                            logger.warning(
                                f"⚠️ [WA] Bridge error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {error_text[:100]}"
                            )
                            time.sleep(delay)

                        except requests.exceptions.Timeout as e:
                            last_error = f"timeout: {e}"
                            if attempt < max_retries - 1:
                                delay = retry_delays[
                                    min(attempt, len(retry_delays) - 1)
                                ]
                                logger.warning(
                                    f"⚠️ [WA] Timeout (attempt {attempt + 1}/{max_retries}), retrying in {delay}s"
                                )
                                time.sleep(delay)
                        except Exception as e:
                            last_error = str(e)
                            # Network errors are generally retryable
                            if attempt < max_retries - 1:
                                delay = retry_delays[
                                    min(attempt, len(retry_delays) - 1)
                                ]
                                logger.warning(
                                    f"⚠️ [WA] Connection error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {e}"
                                )
                                time.sleep(delay)

                    if not success:
                        # Extract status code and response body for debugging
                        status_code = "unknown"
                        response_body = str(last_error)[:200] if last_error else "no error details"

                        # Try to extract status code from last_error string
                        if last_error and "status " in last_error:
                            try:
                                status_code = last_error.split("status ")[1].split(":")[0].strip()
                            except Exception as e:
                                logger.debug(f"Could not parse status code from error string: {e}")

                        logger.error(
                            f"❌ [WA] Send failed | tenant={resolved_tenant_id} | to={chat_jid} | "
                            f"status={status_code} | body={response_body}"
                        )
                        return False

                    # Only record message if send succeeded
                    self._record_sent_message(chat_jid, chunk)
                    logger.info(f"✅ Message sent | to={chat_jid} | chunk={i + 1}/{len(chunks)}")

                logger.info(f"📤 [WA] Sent to {chat_jid}: {message[:50]}...")
                return True
            except Exception as e:
                logger.error(f"❌ [WA] Unexpected send error: {e}")
                return False

    def _get_conversation_history(
        self, chat_jid: str, limit: int = 10, tenant_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve conversation history for chat_jid from messages table.

        Queries the messages table for last N messages, formats as
        [{"role": "user", "parts": [{"text": "..."}]}, {"role": "model", "parts": [...]}, ...].

        Args:
            chat_jid: Chat/conversation ID.
            limit: Max number of messages (default 10).
            tenant_id: Tenant UUID — used to scope the query and prevent cross-tenant leaks.
                       If not provided the query still filters by chat_jid, but providing it
                       is strongly preferred for multi-tenant safety.

        Returns:
            List of message dicts in Gemini-style format.
        """
        result: List[Dict] = []
        if not chat_jid or not self.db_conn:
            return result

        try:
            if self.db_type == "supabase":
                query = (
                    self.db_conn.table("messages")
                    .select("role, content, created_at")
                    .eq("chat_jid", chat_jid)
                )
                if tenant_id:
                    query = query.eq("tenant_id", tenant_id)
                else:
                    logger.warning(
                        f"⚠️ _get_conversation_history called without tenant_id for {chat_jid} — "
                        "cross-tenant isolation not enforced for this query"
                    )
                resp = (
                    query
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                if not resp.data:
                    return result
                for msg in reversed(resp.data):
                    role = msg.get("role", "user")
                    content = (msg.get("content") or "").strip()
                    if content:
                        gemini_role = "model" if role == "assistant" else "user"
                        result.append(
                            {"role": gemini_role, "parts": [{"text": content}]}
                        )
                logger.debug(f"📚 Retrieved {len(result)} messages for {chat_jid}")
            elif self.db_type == "sqlite":
                cursor = self.db_conn.cursor()
                cursor.execute(
                    """
                    SELECT message_content, response FROM conversations
                    WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?
                    """,
                    (chat_jid, limit // 2),
                )
                for row in reversed(cursor.fetchall()):
                    user_content = (row[0] or "").strip()
                    ai_content = (row[1] or "").strip()
                    if user_content:
                        result.append(
                            {"role": "user", "parts": [{"text": user_content}]}
                        )
                    if ai_content:
                        result.append(
                            {"role": "model", "parts": [{"text": ai_content}]}
                        )
        except Exception as e:
            logger.warning(f"⚠️ Failed to retrieve history for {chat_jid}: {e}")
        return result

    def _record_sent_message(self, chat_jid: str, message: str) -> None:
        """Record a sent message for self-echo detection (bridge echoes our sends back)."""
        if not message or not chat_jid:
            return
        now = datetime.now()
        preview = (message or "").strip()[:200]
        if chat_jid not in self.recent_sent:
            self.recent_sent[chat_jid] = []
        self.recent_sent[chat_jid].append((preview, now))
        # Trim: keep only last N, drop expired
        cutoff = now - timedelta(seconds=self.recent_sent_ttl)
        self.recent_sent[chat_jid] = [
            (p, t) for p, t in self.recent_sent[chat_jid] if t > cutoff
        ][-self.recent_sent_max_per_chat :]

    async def _send_direct_owner_notification(self, tenant_id: str, message: str) -> bool:
        """
        Send a direct WhatsApp notification to the owner.
        Uses OWNER_WHATSAPP_JID from environment or tenant config.
        """
        try:
            owner_jid = os.getenv("OWNER_WHATSAPP_JID")

            # If not in env, try to get from tenant config
            if not owner_jid and self.db_conn:
                tenant_result = self.db_conn.table("tenants").select("whatsapp_jid").eq("id", tenant_id).execute()
                if tenant_result.data:
                    owner_jid = tenant_result.data[0].get("whatsapp_jid")

            if not owner_jid:
                logger.warning(f"⚠️ Cannot send direct owner notification: No OWNER_WHATSAPP_JID found for tenant {tenant_id}")
                return False

            logger.info(f"📲 Sending direct owner notification to {owner_jid}")

            # Send message via bridge
            payload = {
                "jid": owner_jid,
                "content": message,
                "device_id": self.whatsapp_device_id
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.bridge_url}/api/message/send",
                    json=payload,
                    headers={"X-API-Key": self.bridge_api_key}
                )
                resp.raise_for_status()
                return True

        except Exception as e:
            logger.error(f"❌ Failed to send direct owner notification: {e}")
            return False

    async def _notify_bijou_owner(
        self, owner_wa: str, message: str, tenant_id: str = ""
    ) -> bool:
        """
        Send a direct WhatsApp message to the Bijou platform owner's personal number.
        Used for critical-priority escalations that need immediate human attention.

        Reads BIJOU_OWNER_WA env var (phone digits only, no +).
        Sends via SUPPORT_WA_DEVICE_ID or falls back to self.whatsapp_device_id.
        """
        try:
            if not owner_wa:
                return False
            device_id = os.getenv("SUPPORT_WA_DEVICE_ID", "") or getattr(self, "whatsapp_device_id", "")
            if not device_id:
                logger.warning("⚠️ _notify_bijou_owner: no device_id available")
                return False
            jid = f"{owner_wa}@s.whatsapp.net"
            self.send_message(jid, message, tenant_id=tenant_id)
            logger.info(f"✅ Bijou owner pinged at {owner_wa} (tenant={tenant_id[:8]})")
            return True
        except Exception as e:
            logger.error(f"❌ _notify_bijou_owner failed: {e}")
            return False

    def _format_phone(self, jid: str) -> str:
        """
        Format JID to phone number for display in notifications.

        Examples:
            60142673197@s.whatsapp.net -> +60142673197
            84950644740196@lid -> +84950644740196 (LID - device identifier)

        Args:
            jid: WhatsApp JID (e.g., "60142673197@s.whatsapp.net")

        Returns:
            Formatted phone number with + prefix
        """
        if not jid:
            return "Unknown"

        # Extract phone number part before @
        phone = jid.split("@")[0] if "@" in jid else jid

        # Add + prefix if not already present
        if not phone.startswith("+"):
            phone = f"+{phone}"

        return phone

    async def _save_message(
        self,
        chat_jid: str,
        tenant_id: Optional[str],
        role: str,
        content: str,
        device_jid: Optional[str] = None,
        chat_type: str = "individual",
        is_system_event: bool = False,
        media_url: Optional[str] = None,
        media_type: Optional[str] = None,
        media_mime: Optional[str] = None,
    ):
        """
        Save a message to the messages table (Supabase).

        New columns written (added in migration 019):
          - device_jid       Normalized business device JID (no :N suffix)
          - phone_jid        Resolved phone JID for @lid contacts (None for normal JIDs)
          - chat_type        "individual" | "group"
          - is_system_event  True for internal/system messages, False for real chat
          - conversation_key Tenant-scoped composite key computed internally

        media_url/media_type/media_mime (added in add_message_media_columns.sql,
        2026-08-23): the customer's raw WhatsApp attachment, so a human agent
        taking over a chat can see the actual photo/voice note/file instead of
        only the AI's text summary of it. Callers pass these only for the
        inbound customer message when media is present; left None otherwise.

        Note: conversation_key is computed here — callers must NOT pass it.
        Note: phone_jid is resolved here only when chat_jid ends with @lid
              (avoids an extra DB round-trip for every normal message).
        """
        try:
            if self.db_type == "supabase" and self.db_conn:
                # ── Existing fields ──────────────────────────────────────────
                customer_phone = self._extract_phone_number(chat_jid)
                customer_name = self._extract_customer_name(chat_jid)
                safe_tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID")
                if not safe_tenant_id:
                    logger.error(
                        f"❌ _save_message: no tenant_id for chat_jid={chat_jid} — message will NOT be saved. "
                        "Set DEFAULT_TENANT_ID in .env if demo/fallback mode is required."
                    )
                    return

                # ── New: conditional phone_jid resolution ────────────────────
                # Only hit the DB when chat_jid is a LID (@lid) JID.
                # For normal phone JIDs this is always None — no extra query.
                if chat_jid and chat_jid.endswith("@lid"):
                    phone_jid = await resolve_phone_jid(
                        self.db_conn, chat_jid, safe_tenant_id
                    )
                else:
                    phone_jid = None

                # ── New: conversation_key computed internally ─────────────────
                # Caller must NOT pass this — it is always derived here so it
                # stays consistent regardless of which call site invokes us.
                conv_key = (
                    build_conversation_key(safe_tenant_id, device_jid, chat_jid)
                    if device_jid
                    else None
                )

                self.db_conn.table("messages").insert(
                    {
                        "tenant_id": safe_tenant_id,
                        "chat_jid": chat_jid,
                        "role": role,
                        "content": content,
                        "customer_phone": customer_phone,
                        "customer_name": customer_name,
                        "created_at": datetime.now().isoformat(),
                        # ── New columns (migration 019) ──────────────────────
                        "device_jid": device_jid,
                        "phone_jid": phone_jid,
                        "chat_type": chat_type,
                        "is_system_event": is_system_event,
                        "conversation_key": conv_key,
                        # ── New columns (add_message_media_columns.sql) ──────
                        "media_url": media_url,
                        "media_type": media_type,
                        "media_mime": media_mime,
                    }
                ).execute()

            elif self.db_type == "sqlite" and self.db_conn:
                # SQLite fallback — new columns not supported, keep existing behaviour
                pass

        except Exception as e:
            logger.error(f"⚠️ Failed to save message: {e}")

    def _extract_phone_number(self, chat_jid: str) -> str:
        """
        Extract real phone number from WhatsApp JID.

        Examples:
            60142673197@s.whatsapp.net → +60142673197
            88304745713870@lid → DEVICE_88304745713870
        """
        if not chat_jid:
            return "UNKNOWN"

        # Remove domain part (@s.whatsapp.net or @lid)
        phone = chat_jid.split('@')[0]

        # Check if it's a device ID (@lid format)
        if '@lid' in chat_jid:
            return f"DEVICE_{phone}"

        # Add + prefix for international format
        if not phone.startswith('+'):
            phone = f"+{phone}"

        return phone

    def _extract_customer_name(self, chat_jid: str) -> Optional[str]:
        """
        Extract customer name from WhatsApp contact if available.
        For now returns None, can be enhanced later with contact lookup.
        """
        # TODO: Query WhatsApp bridge for contact name
        return None

    def _save_conversation(
        self, message: Dict, lang_context: Optional[LanguageContext], response: str
    ):
        """Legacy: Save conversation to conversations table (deprecated, use _save_message)"""
        try:
            if self.db_type == "sqlite" and self.db_conn:
                cursor = self.db_conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO conversations
                    (chat_jid, message_id, message_content, detected_language, response)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        message["chat_jid"],
                        message.get("message_id"),
                        message["content"],
                        lang_context.primary_language.value
                        if lang_context
                        else "unknown",
                        response,
                    ),
                )
                self.db_conn.commit()

            elif self.db_type == "supabase" and self.db_conn:
                # Extract contact name from sender field (WhatsApp bridge provides this)
                sender = message.get("sender", "")
                contact_name = sender if sender and "@" not in sender else None
                if not contact_name and message["chat_jid"]:
                    # Fallback: extract from JID
                    contact_name = message["chat_jid"].split("@")[0]

                self.db_conn.table("conversations").insert(
                    {
                        "tenant_id": message.get("tenant_id") or os.getenv("DEFAULT_TENANT_ID"),
                        "chat_jid": message["chat_jid"],
                        "message_id": message.get("message_id"),
                        "message_content": message["content"],
                        "detected_language": lang_context.primary_language.value
                        if lang_context
                        else "unknown",
                        "ai_response": response,
                        "timestamp": datetime.now().isoformat(),
                        "contact_name": contact_name,
                    }
                ).execute()

        except Exception as e:
            logger.error(f"⚠️ Failed to save conversation: {e}")

    def is_escalated(self, chat_jid: str) -> bool:
        """Check if chat is currently escalated to human"""
        return (
            chat_jid in self.escalated_chats
            and self.escalated_chats[chat_jid].get("status") == "pending"
        )

    def get_health_status(self) -> Dict:
        """
        Get comprehensive health status (programmatic API).
        Returns bridge connectivity and service status.
        """
        try:
            r = requests.get(f"{self.bridge_url}/health", timeout=5)
            return {
                "status": "healthy" if r.status_code == 200 else "degraded",
                "bridge_url": self.bridge_url,
                "bridge_status_code": r.status_code,
                "database": self.db_type,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "bridge_url": self.bridge_url,
                "error": str(e),
                "database": self.db_type,
            }

    def get_metrics(self) -> Dict:
        """
        Get minimal metrics (programmatic API).
        Extended metrics can be added when HealthMonitor/metrics are wired in.
        """
        return {
            "poll_count": getattr(self, "poll_count", 0),
            "bridge_url": self.bridge_url,
            "database": self.db_type,
        }

    async def run_polling_loop(self):
        """Main polling loop - DISABLED in webhook mode"""
        if self.webhook_mode:
            logger.info("🔔 WEBHOOK MODE - Polling loop disabled")
            logger.info("✅ Bijou AI is ready! Waiting for webhook messages...")
            logger.info("Press Ctrl+C to stop")

            # Track last report check
            last_report_check = datetime.now()

            # Keep the process alive but don't poll
            while self.running:
                try:
                    await asyncio.sleep(60)  # Sleep for 1 minute

                    # Check for daily reports every hour
                    now = datetime.now()
                    if (now - last_report_check).total_seconds() >= 3600:  # 1 hour
                        last_report_check = now
                        self._check_and_send_reports()

                    # Process scheduled reminders every minute
                    if self.reminder_system:
                        try:
                            processed_count = await self.reminder_system.process_scheduled_reminders()
                            if processed_count > 0:
                                logger.debug(f"📬 Processed {processed_count} scheduled reminders")
                        except Exception as e:
                            logger.error(f"❌ Error processing scheduled reminders: {e}")

                except KeyboardInterrupt:
                    logger.info("🛑 Keyboard interrupt received")
                    break
            logger.info("👋 Bijou AI stopped")
            return

        logger.info(
            f"🔄 Starting message polling (interval: {self.config['polling_interval']}s)"
        )
        logger.info("✅ Bijou AI is ready! Waiting for messages...")
        logger.info("Press Ctrl+C to stop")

        consecutive_errors = 0
        max_consecutive_errors = 10

        # ✅ CLEAR OLD PROCESSED IDs on startup to allow new messages through
        # Keep only the last 100 to prevent memory bloat
        if len(self.processed_message_ids) > 100:
            logger.info(
                f"🧹 Clearing {len(self.processed_message_ids)} old processed message IDs"
            )
            self.processed_message_ids.clear()

        while self.running:
            try:
                # Poll for new messages
                messages = self.poll_new_messages()

                # ✅ CRITICAL FIX: Update last_poll_time BEFORE processing
                # This prevents re-fetching the same messages if processing fails
                if messages:
                    self.last_poll_time = datetime.now()
                    logger.debug(
                        f"[POLL] Updated last_poll_time to {self.last_poll_time.isoformat()}"
                    )

                # Process each message
                for message in messages:
                    await self.process_message(message)

                # Reset error counter on success
                if messages or consecutive_errors > 0:
                    consecutive_errors = 0

                # Sleep before next poll
                await asyncio.sleep(self.config["polling_interval"])

            except KeyboardInterrupt:
                logger.info("🛑 Keyboard interrupt received")
                break

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    f"❌ Polling loop error ({consecutive_errors}/{max_consecutive_errors}): {e}"
                )

                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(
                        f"🚨 Too many consecutive errors ({consecutive_errors}). Stopping."
                    )
                    break

                # Exponential backoff
                backoff = min(30, 2**consecutive_errors)
                logger.info(f"⏳ Backing off for {backoff}s before retry...")
                await asyncio.sleep(backoff)

            # Check for daily reports periodically
            if hasattr(self, "_last_report_check"):
                now = datetime.now()
                if (now - self._last_report_check).total_seconds() >= 3600:  # 1 hour
                    self._last_report_check = now
                    self._check_and_send_reports()
            else:
                self._last_report_check = datetime.now()

            # Process scheduled reminders periodically (every minute)
            if self.reminder_system and hasattr(self, "_last_reminder_check"):
                now = datetime.now()
                if (now - self._last_reminder_check).total_seconds() >= 60:  # 1 minute
                    self._last_reminder_check = now
                    try:
                        processed_count = await self.reminder_system.process_scheduled_reminders()
                        if processed_count > 0:
                            logger.debug(f"📬 Processed {processed_count} scheduled reminders")
                    except Exception as e:
                        logger.error(f"❌ Error processing scheduled reminders: {e}")
            elif self.reminder_system:
                self._last_reminder_check = datetime.now()

        logger.info("👋 Bijou AI polling loop stopped")

    def _check_and_send_reports(self):
        """Check if it's time to send daily/weekly reports and send them"""
        if not self.reporting_engine:
            return

        try:
            # Check if it's time for daily report
            if self.reporting_engine.should_send_daily():
                logger.info("📊 Sending daily report to owner...")
                tenant_id = os.getenv("DEFAULT_TENANT_ID", "default")
                report = self.reporting_engine.generate_daily_report(tenant_id)

                # Send to owner
                self.send_message(self.owner_jid, report, tenant_id=tenant_id)
                logger.info("✅ Daily report sent to owner")

            # Check if it's time for weekly report
            if self.reporting_engine.should_send_weekly():
                logger.info("📊 Sending weekly report to owner...")
                tenant_id = os.getenv("DEFAULT_TENANT_ID", "default")
                report = self.reporting_engine.generate_weekly_report(tenant_id)

                # Send to owner
                self.send_message(self.owner_jid, report, tenant_id=tenant_id)
                logger.info("✅ Weekly report sent to owner")

        except Exception as e:
            logger.error(f"❌ Failed to send reports: {e}")


# FastAPI routes for health checks and status


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    tenant_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    """
    Serve tenant-specific dashboard with authentication
    - If tenant_id and token provided: Validate and serve tenant dashboard
    - If no params: Redirect to onboarding for new clients
    """
    if tenant_id and token:
        # Validate token before serving dashboard
        try:
            from src.core.dashboard_api_simple import verify_session
            # This will raise HTTPException if token is invalid
            await verify_session(tenant_id=tenant_id, token=token)

            # Serve tenant-specific dashboard
            dashboard_path = Path(__file__).parent.parent.parent / "static" / "dashboard.html"
            if dashboard_path.exists():
                return dashboard_path.read_text(encoding="utf-8")
            else:
                return HTMLResponse("Dashboard not found", status_code=404)
        except HTTPException as e:
            # Invalid credentials - show user-friendly error
            error_html = f"""
            <!DOCTYPE html>
            <html><head><title>Authentication Required</title>
            <style>body{{font-family:Arial;padding:40px;text-align:center;background:#f5f5f5}}
            .error-box{{background:white;padding:40px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);max-width:500px;margin:0 auto}}
            h1{{color:#ef4444;margin-bottom:16px}}p{{color:#666;line-height:1.6}}
            a{{color:#3b82f6;text-decoration:none}}
            </style></head><body>
            <div class="error-box">
                <h1>🔒 Authentication Required</h1>
                <p>{e.detail}</p>
                <p style="margin-top:24px">Please check your email or WhatsApp for the correct dashboard link.</p>
                <p style="margin-top:16px"><a href="/">← Back to Login</a></p>
            </div>
            </body></html>
            """
            return HTMLResponse(error_html, status_code=401)
    else:
        # No magic-link params — serve the dashboard and let the JS handle JWT auth from localStorage
        dashboard_path = Path(__file__).parent.parent.parent / "static" / "dashboard.html"
        if dashboard_path.exists():
            return dashboard_path.read_text(encoding="utf-8")
        return RedirectResponse(url="/")

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the login page - modern login/logout flow"""
    login_path = Path(__file__).parent.parent.parent / "static" / "login.html"
    if login_path.exists():
        return login_path.read_text(encoding="utf-8")
    # Fallback if login page not found
    return HTMLResponse(f"""
    <h1>🤖 Bijou AI Login Portal</h1>
    <p>Status: <strong style="color: green;">Running</strong></p>
    <p><a href="/signup">New Customer? Sign Up Here</a></p>
    <p><a href="/health">Health Check</a> | <a href="/status">Status</a></p>
    """)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve the professional login page"""
    login_path = Path(__file__).parent.parent.parent / "static" / "login.html"
    if login_path.exists():
        return login_path.read_text(encoding="utf-8")
    return RedirectResponse(url="/")

@app.get("/help", response_class=HTMLResponse)
async def help_page():
    """Serve the help & support page"""
    help_path = Path(__file__).parent.parent.parent / "static" / "help.html"
    if help_path.exists():
        return help_path.read_text(encoding="utf-8")
    return RedirectResponse(url="/")

@app.get("/outreach", response_class=HTMLResponse)
async def outreach_page():
    """Serve the outreach campaigns dashboard"""
    p = Path(__file__).parent.parent.parent / "static" / "outreach.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return RedirectResponse(url="/dashboard")

@app.get("/kb-wizard", response_class=HTMLResponse)
async def kb_wizard_page():
    """Serve the industry KB template wizard (fill-in-the-blank AI setup)"""
    p = Path(__file__).parent.parent.parent / "static" / "kb-wizard.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return RedirectResponse(url="/dashboard")

@app.get("/callback", response_class=HTMLResponse)
async def oauth_callback_page():
    """Serve the cal.com OAuth PKCE callback page"""
    p = Path(__file__).parent.parent.parent / "static" / "callback.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return RedirectResponse(url="/dashboard")


@app.get("/onboard/{token}", response_class=HTMLResponse)
async def onboard_qr_page(token: str):
    """
    Serve the WhatsApp QR onboarding page (replaces v0-cliste Vercel app).

    Both email signup and Google OAuth redirect here after creating a tenant.
    The page polls /api/onboarding/status/{token} every 3s and shows the QR
    code from /api/onboarding/qr/{token}. When WhatsApp connects, the page
    calls /api/onboarding/complete/{token} and redirects to /dashboard.
    """
    p = Path(__file__).parent.parent.parent / "static" / "onboard-qr.html"
    if p.exists():
        # Inject PUBLIC_URL so the page can use it for absolute URLs in success redirects
        html = p.read_text(encoding="utf-8")
        return HTMLResponse(content=html)
    return HTMLResponse("Onboarding page not found", status_code=404)


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page():
    """Serve the Supabase password reset page (handles #access_token=... fragment)"""
    p = Path(__file__).parent.parent.parent / "static" / "reset-password.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return RedirectResponse(url="/login")

@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page():
    """Serve the plans & pricing page"""
    p = Path(__file__).parent.parent.parent / "static" / "pricing.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return RedirectResponse(url="/dashboard")

@app.get("/signup", response_class=HTMLResponse)
async def signup_page():
    """Serve the professional signup page"""
    signup_path = Path(__file__).parent.parent.parent / "static" / "signup.html"
    if signup_path.exists():
        return signup_path.read_text(encoding="utf-8")
    # Fallback to old onboarding page
    onboarding_path = Path(__file__).parent.parent.parent / "static" / "onboarding.html"
    if onboarding_path.exists():
        return onboarding_path.read_text(encoding="utf-8")
    # Fallback if onboarding page not found
    return HTMLResponse(f"""
    <h1>🤖 Bijou AI WhatsApp Enterprise v2.2.0</h1>
    <p>Status: <strong style="color: green;">Running</strong></p>
    <p>Platform: {os.getenv("ENVIRONMENT", "production")}</p>
    <p>Database: {os.getenv("DB_TYPE", "sqlite").upper()}</p>
    <h3>Features:</h3>
    <ul>
        <li>✅ Multi-Language Detection (Malay, Mandarin, Tamil, English, Manglish)</li>
        <li>✅ Cultural Context Adaptation</li>
        <li>✅ Human Escalation System</li>
        <li>✅ AI-Powered Responses (Gemini 2.0 Flash)</li>
        <li>✅ Multi-Tenant Support</li>
        <li>✅ Supabase PostgreSQL</li>
    </ul>
    <p><a href="/health">Health Check</a> | <a href="/status">Status</a></p>
    """)

@app.get("/onboarding", response_class=HTMLResponse)
async def onboarding_alias():
    """Alias for /signup for backward compatibility"""
    return await signup_page()


def _serve_static_html(filename: str):
    """Return the contents of `static/<filename>` or a 404 HTMLResponse."""
    file_path = Path(__file__).parent.parent.parent / "static" / filename
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    return HTMLResponse(
        f"<h1>Page Not Found</h1><p>{filename} is missing from the static directory.</p>",
        status_code=404,
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Tenant admin panel (linked from the dashboard help menu)."""
    return _serve_static_html("admin.html")


@app.get("/integrations", response_class=HTMLResponse)
async def integrations_page():
    """Integrations marketplace / OAuth landing."""
    return _serve_static_html("integrations.html")


@app.get("/system-check", response_class=HTMLResponse)
async def system_check_page():
    """Self-serve diagnostic page that the dashboard links to."""
    return _serve_static_html("system-check.html")


@app.get("/user-guide", response_class=HTMLResponse)
async def user_guide_page():
    """End-user onboarding guide."""
    return _serve_static_html("user-guide.html")


@app.get("/sales-presentation", response_class=HTMLResponse)
async def sales_presentation_page():
    """Sales / share-this-deck page (linked from pricing & outreach)."""
    return _serve_static_html("sales-presentation.html")


@app.get("/api-docs", response_class=HTMLResponse)
async def api_documentation():
    """Serve interactive API documentation"""
    docs_path = Path(__file__).parent.parent.parent / "docs" / "api-docs.html"
    if docs_path.exists():
        return docs_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>API Documentation Not Found</h1>", status_code=404)


@app.get("/changelog", response_class=HTMLResponse)
async def changelog():
    """Serve API changelog with version history"""
    changelog_path = Path(__file__).parent.parent.parent / "docs" / "CHANGELOG.md"
    if not changelog_path.exists():
        return HTMLResponse("<h1>Changelog Not Found</h1>", status_code=404)

    # Read markdown content
    md_content = changelog_path.read_text(encoding='utf-8')

    # Simple markdown to HTML conversion (basic formatting)
    # Convert headers
    html_content = md_content
    html_content = html_content.replace('# ', '<h1>').replace('\n\n', '</h1>\n\n')
    html_content = html_content.replace('## ', '<h2>').replace('\n\n', '</h2>\n\n')
    html_content = html_content.replace('### ', '<h3>').replace('\n\n', '</h3>\n\n')

    # Wrap in HTML template with styling
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Bijou AI - API Changelog</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                max-width: 900px;
                margin: 40px auto;
                padding: 20px;
                line-height: 1.6;
                background-color: #0a0e27;
                color: #e0e0e0;
            }}
            h1 {{
                color: #60a5fa;
                border-bottom: 3px solid #3b82f6;
                padding-bottom: 10px;
            }}
            h2 {{
                color: #34d399;
                margin-top: 30px;
                border-bottom: 2px solid #10b981;
                padding-bottom: 8px;
            }}
            h3 {{
                color: #fbbf24;
                margin-top: 20px;
            }}
            ul {{
                margin-left: 20px;
            }}
            li {{
                margin: 8px 0;
            }}
            code {{
                background-color: #1e293b;
                padding: 2px 6px;
                border-radius: 3px;
                color: #fbbf24;
                font-family: 'Courier New', monospace;
            }}
            pre {{
                background-color: #1e293b;
                padding: 15px;
                border-radius: 5px;
                overflow-x: auto;
                border-left: 4px solid #3b82f6;
            }}
            a {{
                color: #60a5fa;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
            .back-link {{
                display: inline-block;
                margin-bottom: 20px;
                padding: 8px 16px;
                background-color: #3b82f6;
                color: white;
                border-radius: 5px;
                text-decoration: none;
            }}
            .back-link:hover {{
                background-color: #2563eb;
            }}
        </style>
    </head>
    <body>
        <a href="/api-docs" class="back-link">← Back to API Documentation</a>
        <pre>{md_content}</pre>
        <hr style="margin-top: 40px; border-color: #334155;">
        <p style="text-align: center; color: #94a3b8;">
            <a href="/health">Health Check</a> |
            <a href="/status">Status</a> |
            <a href="/api-docs">API Docs</a>
        </p>
    </body>
    </html>
    """

    return HTMLResponse(html_template)


@app.get("/postman-collection", response_class=JSONResponse)
async def download_postman_collection():
    """
    Download the official Postman Collection for Bijou AI API testing.

    **Usage:**
    1. Download this file
    2. Import into Postman (File > Import)
    3. Create environment with variables:
       - `base_url`: https://bijou-staging.fly.dev
       - `api_key`: Your WhatsApp bridge API key
       - `dashboard_token`: Your dashboard auth token
       - `tenant_id`: Your tenant UUID
    4. Start testing endpoints!

    **What's Included:**
    - 52 API endpoints organized in 7 folders
    - Pre-configured environment variables
    - Request examples with authentication headers
    - Sample request bodies

    **Alternative Access:**
    - Direct download: https://bijou-staging.fly.dev/postman-collection
    - Documentation: https://bijou-staging.fly.dev/api-docs

    Returns:
        JSONResponse: Postman Collection v2.1 JSON file

    Raises:
        HTTPException: 404 if collection file not found
    """
    collection_path = Path(__file__).parent.parent.parent / "docs" / "bijou-api.postman_collection.json"

    if not collection_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Postman collection not found. Please run: python scripts/generate_postman_collection.py"
        )

    # Read collection file
    with open(collection_path, "r", encoding="utf-8") as f:
        collection_data = json.load(f)

    # Return as downloadable JSON
    return JSONResponse(
        content=collection_data,
        headers={
            "Content-Disposition": 'attachment; filename="bijou-api.postman_collection.json"',
            "Content-Type": "application/json"
        }
    )


@app.get("/health")
async def health_check():
    """Health check endpoint for Fly.io"""
    return {
        "status": "healthy",
        "service": "bijou-ai-enterprise",
        "version": "2.2.0",
        "timestamp": datetime.now().isoformat(),
        "database": os.getenv("DB_TYPE", "sqlite"),
    }


@app.get("/health/database")
async def database_health_check():
    """
    Comprehensive database health check including schema validation.

    Checks:
    - Database connectivity
    - Core table existence (tenants, conversations, escalations)
    - Call booking system tables (call_bookings, call_availability, etc.)
    - Row Level Security policies
    - Migration status
    """
    db_type = os.getenv("DB_TYPE", "sqlite")
    health_status = {
        "status": "healthy",
        "database_type": db_type,
        "timestamp": datetime.now().isoformat(),
        "tables": {},
        "migrations": {},
        "connectivity": False,
        "rls_enabled": False,
        "errors": []
    }

    try:
        if db_type == "supabase":
            # Supabase health check
            supabase_client = get_supabase()
            if not supabase_client:
                health_status["status"] = "unhealthy"
                health_status["errors"].append("Supabase client not initialized")
                return JSONResponse(status_code=503, content=health_status)

            # Test basic connectivity
            try:
                result = supabase_client.table("tenants").select("count").limit(1).execute()
                health_status["connectivity"] = True
            except Exception as e:
                health_status["connectivity"] = False
                health_status["errors"].append(f"Database connection failed: {str(e)}")

            # Check core tables exist
            core_tables = [
                "tenants", "conversations", "escalations", "scheduled_messages",
                "campaigns", "silence_rules", "customer_activity", "lead_followups"
            ]

            # Check call booking tables
            call_booking_tables = [
                "call_bookings", "call_availability", "call_types", "call_settings",
                "holiday_exceptions", "availability_overrides"
            ]

            all_tables = core_tables + call_booking_tables

            for table_name in all_tables:
                try:
                    # Test table exists and we can query it
                    result = supabase_client.table(table_name).select("count").limit(1).execute()
                    health_status["tables"][table_name] = {
                        "exists": True,
                        "accessible": True,
                        "is_call_booking": table_name in call_booking_tables
                    }
                except Exception as e:
                    error_msg = str(e).lower()
                    exists = "does not exist" not in error_msg and "relation" not in error_msg
                    health_status["tables"][table_name] = {
                        "exists": exists,
                        "accessible": False,
                        "error": str(e),
                        "is_call_booking": table_name in call_booking_tables
                    }

            # Check if call booking migration is applied
            call_booking_tables_exist = all(
                health_status["tables"].get(t, {}).get("exists", False)
                for t in call_booking_tables
            )

            health_status["migrations"]["call_booking_system"] = {
                "applied": call_booking_tables_exist,
                "tables_count": len([t for t in call_booking_tables if health_status["tables"].get(t, {}).get("exists", False)]),
                "expected_count": len(call_booking_tables)
            }

            # Try to verify migration using the verification function
            try:
                verification_result = supabase_client.rpc('verify_call_booking_migration').execute()
                if verification_result.data:
                    health_status["migrations"]["verification"] = {
                        "function_available": True,
                        "results": verification_result.data
                    }
            except Exception as e:
                health_status["migrations"]["verification"] = {
                    "function_available": False,
                    "error": str(e)
                }

            # Check RLS is enabled (try without tenant context)
            try:
                # This should fail if RLS is properly enabled
                supabase_client.table("call_bookings").select("*").limit(1).execute()  # noaudit - intentional RLS probe: deliberately omits tenant_id to test RLS
                health_status["rls_enabled"] = False  # If this succeeds, RLS might be disabled
            except Exception as e:
                if "row-level security" in str(e).lower() or "policy" in str(e).lower():
                    health_status["rls_enabled"] = True  # RLS is working
                else:
                    health_status["rls_enabled"] = "unknown"

        else:
            # SQLite health check
            if bijou_instance and hasattr(bijou_instance, 'db_conn') and bijou_instance.db_conn:
                health_status["connectivity"] = True

                # Check tables in SQLite
                cursor = bijou_instance.db_conn.cursor()

                # Get all table names
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                existing_tables = [row[0] for row in cursor.fetchall()]

                expected_tables = [
                    "conversations", "escalations", "scheduled_messages", "campaigns",
                    "silence_rules", "customer_activity", "lead_followups",
                    "call_bookings", "call_availability", "call_types", "call_settings",
                    "holiday_exceptions", "availability_overrides"
                ]

                for table_name in expected_tables:
                    health_status["tables"][table_name] = {
                        "exists": table_name in existing_tables,
                        "accessible": table_name in existing_tables,
                        "is_call_booking": table_name.startswith("call_") or table_name in ["holiday_exceptions", "availability_overrides"]
                    }

                call_booking_tables_count = len([
                    t for t in expected_tables
                    if t.startswith("call_") or t in ["holiday_exceptions", "availability_overrides"]
                    if health_status["tables"][t]["exists"]
                ])

                health_status["migrations"]["call_booking_system"] = {
                    "applied": call_booking_tables_count == 6,  # Expected call booking tables
                    "tables_count": call_booking_tables_count,
                    "expected_count": 6
                }

                health_status["rls_enabled"] = False  # SQLite doesn't have RLS
            else:
                health_status["connectivity"] = False
                health_status["errors"].append("SQLite connection not available")

        # Determine overall health
        connectivity_ok = health_status["connectivity"]
        core_tables_ok = all(
            health_status["tables"].get(t, {}).get("exists", False)
            for t in ["tenants", "conversations", "escalations"]
        )

        if not connectivity_ok or not core_tables_ok:
            health_status["status"] = "unhealthy"
        elif not health_status["migrations"]["call_booking_system"]["applied"]:
            health_status["status"] = "degraded"  # App works but call booking not available
            health_status["errors"].append("Call booking system migration not applied")

        # Return appropriate status code
        if health_status["status"] == "unhealthy":
            return JSONResponse(status_code=503, content=health_status)
        elif health_status["status"] == "degraded":
            return JSONResponse(status_code=200, content=health_status)  # Still functional
        else:
            return health_status

    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["errors"].append(f"Health check failed: {str(e)}")
        logger.error(f"❌ Database health check failed: {e}")
        return JSONResponse(status_code=503, content=health_status)


@app.get("/bridge/health")
async def bridge_health_check():
    """Check WhatsApp bridge connectivity and status"""
    import httpx

    bridge_url = os.getenv("BRIDGE_URL", "https://bijou-bridge-staging-v2.fly.dev")
    bridge_user = os.getenv("BRIDGE_USER", "bijou")
    bridge_password = os.getenv("BRIDGE_PASSWORD", "")

    try:
        # Check bridge connectivity using /devices endpoint (works in GOWA v8+)
        # This endpoint doesn't require device_id and returns 200 if bridge is healthy
        async with httpx.AsyncClient(timeout=30.0) as client:
            devices_response = await client.get(
                f"{bridge_url}/devices",
                auth=(bridge_user, bridge_password),
                timeout=5,
            )
        bridge_healthy = devices_response.status_code == 200

        # Parse device status if bridge is healthy
        devices_status = None
        if bridge_healthy:
            try:
                devices_data = devices_response.json()
                devices = devices_data.get("results", [])
                connected_count = sum(1 for d in devices if d.get("is_connected"))
                devices_status = {
                    "total": len(devices),
                    "connected": connected_count,
                    "disconnected": len(devices) - connected_count,
                }
            except Exception as e:
                logger.warning(f"Failed to parse device status: {e}")

        return {
            "status": "healthy" if bridge_healthy else "unhealthy",
            "bridge_url": bridge_url,
            "bridge_responsive": bridge_healthy,
            "devices": devices_status,
            "timestamp": datetime.now().isoformat(),
        }
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "bridge_url": bridge_url,
                "bridge_responsive": False,
                "error": "Bridge timeout",
                "timestamp": datetime.now().isoformat(),
            },
        )
    except Exception as e:
        logger.error(f"Bridge health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "bridge_url": bridge_url,
                "bridge_responsive": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            },
        )


@app.get("/api/tenant/{tenant_id}/device/status")
async def get_tenant_device_status(tenant_id: str):
    """
    Get WhatsApp device status for a specific tenant.

    Resolution order:
    1. Look up real device_id from whatsapp_devices table (most reliable)
    2. Query bridge /devices/{device_id} for live state
    3. Fall back to tenants.whatsapp_connected + whatsapp_jid if bridge is
       unreachable or returns non-200 (bridge may be paused on staging)
    """
    import httpx

    try:
        db = get_supabase()
        bridge_url = os.getenv("BRIDGE_URL", "https://bijou-bridge-staging-v2.fly.dev")

        # --- Step 1: Resolve real device_id and stored JID from DB ---
        stored_jid = None
        stored_device_id = None
        tenant_connected = False

        # Read ground-truth from tenants table
        try:
            tenant_row = db.table("tenants") \
                .select("whatsapp_connected, whatsapp_jid, device_id") \
                .eq("id", tenant_id) \
                .maybe_single() \
                .execute()
            tr_data = getattr(tenant_row, "data", None) if tenant_row else None
            if tr_data:
                tenant_connected = bool(tr_data.get("whatsapp_connected", False))
                stored_jid = tr_data.get("whatsapp_jid")
                stored_device_id = tr_data.get("device_id")
        except Exception as db_err:
            logger.warning(f"⚠️ [DEVICE STATUS] Could not read tenants row: {db_err}")

        # Check whatsapp_devices table for the canonical device_id
        try:
            dev_row = db.table("whatsapp_devices") \
                .select("device_id, whatsapp_jid, device_name") \
                .eq("tenant_id", tenant_id) \
                .execute()
            if dev_row.data:
                stored_device_id = dev_row.data[0].get("device_id") or stored_device_id
                stored_jid = dev_row.data[0].get("whatsapp_jid") or stored_jid
        except Exception as dev_err:
            logger.warning(f"⚠️ [DEVICE STATUS] Could not read whatsapp_devices row: {dev_err}")

        device_id = stored_device_id or f"bijou-{tenant_id}"
        logger.info(f"📋 [DEVICE STATUS] tenant={tenant_id}, device_id={device_id}, stored_jid={stored_jid}, tenant_connected={tenant_connected}")

        # --- Step 2: Query bridge for live state ---
        try:
            async with httpx.AsyncClient() as client:
                device_response = await client.get(
                    f"{bridge_url}/devices/{device_id}",
                    auth=(os.getenv("BRIDGE_USER", "bijou"), os.getenv("BRIDGE_PASSWORD", "")),
                    timeout=8,
                )
            logger.info(f"📡 [DEVICE STATUS] Bridge response: {device_response.status_code}")
        except Exception as bridge_err:
            logger.warning(f"⚠️ [DEVICE STATUS] Bridge unreachable for {device_id}: {bridge_err}")
            # Step 3a: Bridge unreachable — fall back to DB truth
            if tenant_connected and stored_jid:
                phone = stored_jid.split("@")[0] if stored_jid else None
                return {
                    "status": "connected",
                    "connected": True,
                    "device_id": device_id,
                    "tenant_id": tenant_id,
                    "jid": stored_jid,
                    "whatsapp_jid": stored_jid,
                    "phone_number": phone,
                    "source": "tenants_table_fallback",
                }
            return {
                "status": "unknown",
                "connected": False,
                "device_id": device_id,
                "tenant_id": tenant_id,
                "error": str(bridge_err),
            }

        if device_response.status_code == 404:
            logger.info(f"ℹ️ [DEVICE STATUS] Device {device_id} not found on bridge")
            # Step 3b: Device not on bridge — trust DB truth
            if tenant_connected and stored_jid:
                phone = stored_jid.split("@")[0] if stored_jid else None
                return {
                    "status": "connected",
                    "connected": True,
                    "device_id": device_id,
                    "tenant_id": tenant_id,
                    "jid": stored_jid,
                    "whatsapp_jid": stored_jid,
                    "phone_number": phone,
                    "source": "tenants_table_fallback",
                }
            return {
                "status": "not_provisioned",
                "connected": False,
                "device_id": device_id,
                "tenant_id": tenant_id,
                "message": "WhatsApp device not yet provisioned",
            }

        if device_response.status_code != 200:
            logger.warning(f"⚠️ [DEVICE STATUS] Bridge returned {device_response.status_code} for {device_id}")
            # Step 3c: Non-200 bridge — fall back to DB truth
            if tenant_connected and stored_jid:
                phone = stored_jid.split("@")[0] if stored_jid else None
                return {
                    "status": "connected",
                    "connected": True,
                    "device_id": device_id,
                    "tenant_id": tenant_id,
                    "jid": stored_jid,
                    "whatsapp_jid": stored_jid,
                    "phone_number": phone,
                    "source": "tenants_table_fallback",
                }
            return {
                "status": "unknown",
                "connected": False,
                "device_id": device_id,
                "tenant_id": tenant_id,
                "bridge_http_status": device_response.status_code,
            }

        # GOWA v8 format: { "code": "SUCCESS", "results": { "id": "...", "state": "logged_in", "jid": "..." } }
        bridge_data = device_response.json().get("results", {})
        bridge_state = bridge_data.get("state", "")  # "logged_in" | "disconnected" | etc.
        bridge_jid = bridge_data.get("jid") or bridge_data.get("Jid") or ""

        is_connected = bridge_state == "logged_in"
        status = "connected" if is_connected else bridge_state or "disconnected"
        final_jid = bridge_jid or stored_jid or ""
        phone = final_jid.split("@")[0] if final_jid else None

        # Auto-update DB with JID if now connected and JID is available
        if is_connected and bridge_jid:
            try:
                db.table("tenants").update({
                    "whatsapp_jid": bridge_jid,
                    "whatsapp_connected_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                }).eq("id", tenant_id).execute()
                logger.info(f"✅ [DEVICE STATUS] Auto-updated tenant {tenant_id} JID → {bridge_jid}")
            except Exception as db_err:
                logger.warning(f"⚠️ [DEVICE STATUS] Failed to auto-update tenant JID: {db_err}")

        return {
            "status": status,
            "connected": is_connected,
            "device_id": device_id,
            "tenant_id": tenant_id,
            "jid": final_jid or None,
            "whatsapp_jid": final_jid or None,
            "phone_number": phone,
            "display_name": bridge_data.get("display_name", ""),
            "bridge_state": bridge_state,
            "source": "bridge",
        }

    except Exception as e:
        logger.error(f"❌ Failed to get device status for tenant {tenant_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve device status: {str(e)}",
        )


@app.get("/onboard/{token}")
async def serve_onboarding(token: str):
    """Serve onboarding page for property agent signup"""
    from fastapi.responses import FileResponse

    onboarding_html = Path(__file__).parent.parent.parent / "static" / "onboard.html"
    if not onboarding_html.exists():
        raise HTTPException(status_code=404, detail="Onboarding page not found")

    return FileResponse(str(onboarding_html))


@app.get("/status")
async def status():
    """Detailed status endpoint"""
    return {
        "service": "bijou-ai-whatsapp-enterprise",
        "version": "2.2.0",
        "status": "running",
        "environment": os.getenv("ENVIRONMENT", "production"),
        "database": os.getenv("DB_TYPE", "sqlite"),
        "ai_model": os.getenv("AI_MODEL", "gemini-1.5-flash"),
        "languages": os.getenv("PRIMARY_LANGUAGES", "ms,zh,ta,en,en-my").split(","),
        "features": {
            "multi_language": True,
            "cultural_context": True,
            "human_escalation": True,
            "multi_tenant": True,
            "supabase": os.getenv("DB_TYPE") == "supabase",
        },
    }


@app.post("/webhook/message")
async def webhook_message(request: Request, background_tasks: BackgroundTasks):
    """
    Webhook endpoint for receiving new messages from GOWA bridge (v8.x format).
    Expects: {"event": "message", "device_id": "xxx", "payload": {...}}

    PERFORMANCE OPTIMIZATION:
    - Responds to bridge in <100ms (prevents timeouts)
    - Processes message in background task (12-20s processing time)
    - No duplicate processing (idempotency via message_id)
    """
    global bijou_instance

    # ✅ FIX #8: Validate Bijou instance before processing
    if not bijou_instance:
        logger.error("❌ Bijou instance not initialized")
        raise HTTPException(
            status_code=503,
            detail="Service not ready. Please try again in a few seconds."
        )

    try:
        # Validate content-type
        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            logger.warning(f"⚠️ Invalid webhook content-type: {content_type}")
            raise HTTPException(
                status_code=400,
                detail="Content-Type must be application/json"
            )

        # ✅ CRITICAL: Log raw payload BEFORE Pydantic validation to debug 422 errors
        try:
            raw_body = await request.json()
        except Exception as json_error:
            logger.warning(f"⚠️ Malformed webhook JSON (client error): {json_error}")
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON payload"
            )

        logger.info(f"🔍 [WEBHOOK DEBUG] Raw payload received:")
        logger.info(f"   {json.dumps(raw_body, indent=2)}")

        # ✅ FIX: Validate required fields FIRST (before checking event type)
        if not raw_body:
            logger.warning("⚠️ Empty JSON body in webhook")
            raise HTTPException(
                status_code=400,
                detail="Request body cannot be empty"
            )

        # ✅ FIX: Check event type AFTER basic validation
        # Handle connection events for onboarding completion
        event_type = raw_body.get("event", "unknown")

        # ✅ BUG FIX 1: Handle connection/session events to mark WhatsApp step complete
        if event_type in ["connection.update", "session.open", "qr.scanned"]:
            device_id = raw_body.get("device_id")
            logger.info(f"📡 [WEBHOOK] Connection event received: {event_type} for device {device_id}")

            # Find tenant by device_id
            if device_id and bijou_instance.db_type == "supabase" and bijou_instance.db_conn:
                try:
                    db = bijou_instance.db_conn
                    device_result = db.table("whatsapp_devices").select("tenant_id").eq("device_id", device_id).execute()

                    tenant_id = device_result.data[0]["tenant_id"] if device_result.data else None
                    if not tenant_id:
                        # Onboarding keys bridge sessions by tenant_id and writes no
                        # whatsapp_devices row, so connection events can't resolve a tenant
                        # yet. If device_id IS a known tenant id, link it now. Guarded: a
                        # phone-JID device_id matches no tenant -> no-op, exactly as before.
                        t = db.table("tenants").select("id").eq("id", device_id).execute()
                        if t.data:
                            tenant_id = device_id
                            db.table("whatsapp_devices").upsert(
                                {"device_id": device_id, "tenant_id": tenant_id}
                            ).execute()
                            logger.info(f"🔗 [WEBHOOK] Linked device {device_id} -> tenant {tenant_id} (onboarding fallback)")

                    if tenant_id:
                        # Update onboarding_progress to mark WhatsApp step complete
                        db.table("onboarding_progress").update({
                            "step_whatsapp_completed": True,
                            "step_whatsapp_at": datetime.now().isoformat(),
                            "current_step": "knowledge"
                        }).eq("tenant_id", tenant_id).execute()

                        # Update tenant status
                        db.table("tenants").update({
                            "whatsapp_connected": True,
                            "whatsapp_connected_at": datetime.now().isoformat(),
                            "onboarding_step": "completed",
                            "whatsapp_jid": device_id
                        }).eq("id", tenant_id).execute()

                        logger.info(f"✅ [WEBHOOK] Marked WhatsApp step complete for tenant {tenant_id}")
                except Exception as e:
                    logger.error(f"❌ [WEBHOOK] Failed to update onboarding progress: {e}")

            return JSONResponse(
                status_code=200,
                content={"status": "processed", "event": event_type},
            )

        # ── Handle missed-call events from the bridge ────────────────────────────
        # The bridge emits event_type="call" (or "call.missed") when a WhatsApp
        # voice call is received. We synthesise a "📞 MISSED_CALL" message so the
        # existing AI logic in process_message() fires the customer follow-up.
        if event_type in ("call", "call.missed", "call.received", "call.rejected"):
            payload = raw_body.get("payload", {})
            call_status = (
                payload.get("status") or payload.get("outcome") or
                payload.get("type") or event_type
            ).lower()
            caller_jid = (
                payload.get("from") or payload.get("chat_id") or
                payload.get("caller") or ""
            )
            device_id = raw_body.get("device_id", "")

            logger.info(f"📞 [WEBHOOK] Call event: type={event_type} status={call_status} from={caller_jid}")

            is_missed = any(w in call_status for w in ("miss", "unanswer", "reject", "timeout", "no_answer"))
            # Also treat bare "call" event as missed when no answer is indicated
            if event_type in ("call", "call.missed") and call_status in ("call", "call.missed", "missed", ""):
                is_missed = True

            if is_missed and caller_jid and device_id:
                try:
                    db = bijou_instance.db_conn
                    # Resolve tenant from device
                    dev_res = db.table("whatsapp_devices").select("tenant_id").eq("device_id", device_id).execute()
                    if dev_res.data:
                        missed_tenant_id = dev_res.data[0]["tenant_id"]
                        # Queue a synthetic missed-call message for AI processing
                        synthetic_payload = {
                            "chat_id": caller_jid,
                            "from": caller_jid,
                            "message_id": f"CALL_{caller_jid}_{int(datetime.now().timestamp())}",
                            "body": "📞 MISSED_CALL",
                            "message_type": "missed_call",
                            "timestamp": datetime.now().isoformat(),
                        }
                        bijou_instance.message_queue.put_nowait({
                            "tenant_id": missed_tenant_id,
                            "device_id": device_id,
                            "payload": synthetic_payload,
                        })
                        logger.info(f"📞 Missed call queued for AI follow-up: tenant={missed_tenant_id[:8]} caller={caller_jid}")
                    else:
                        logger.warning(f"⚠️ [MISSED CALL] No tenant found for device {device_id}")
                except Exception as e:
                    logger.error(f"❌ [MISSED CALL] Failed to queue follow-up: {e}")
            else:
                logger.info(f"📞 Call event ignored (status={call_status}, is_missed={is_missed})")

            return JSONResponse(status_code=200, content={"status": "processed", "event": event_type})

        # Skip non-message events (acks, reactions, etc.)
        if event_type != "message":
            logger.info(f"⏭️ [WEBHOOK] Skipping non-message event: {event_type}")
            return JSONResponse(
                status_code=200,
                content={"status": "skipped", "reason": f"event_type_{event_type}"},
            )

        # Validate payload field exists and is non-empty
        if not raw_body.get("payload"):
            logger.warning("⚠️ Missing payload in webhook message")
            raise HTTPException(
                status_code=422,
                detail="Missing required field: payload"
            )

        # Validate payload is not empty
        if not raw_body["payload"] or not isinstance(raw_body["payload"], dict):
            logger.warning("⚠️ Invalid payload structure (must be non-empty dict)")
            raise HTTPException(
                status_code=422,
                detail="Payload must be a non-empty object"
            )

        # Now validate against GOWA webhook model (only for "message" events)
        try:
            gowa_message = GOWAWebhookMessage(**raw_body)
        except ValidationError as validation_error:
            logger.error(f"❌ [WEBHOOK] Pydantic validation failed: {validation_error}")
            logger.error(f"   Raw payload was: {json.dumps(raw_body, indent=2)}")
            raise HTTPException(
                status_code=422,
                detail=f"Invalid message payload structure: {str(validation_error)}"
            )
        except Exception as other_error:
            logger.error(f"❌ [WEBHOOK] Unexpected error during model instantiation: {other_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Internal error during validation: {str(other_error)}"
            )

        payload = gowa_message.payload

        # Convert GOWA format to our internal format
        msg_dict = {
            "id": payload.id,
            "chat_jid": payload.chat_id,  # GOWA uses chat_id, we use chat_jid
            "sender": payload.from_,  # GOWA uses 'from', we use 'sender'
            "from_name": payload.from_name,  # Contact name from WhatsApp
            "content": payload.body,  # GOWA uses 'body', we use 'content'
            "timestamp": payload.timestamp,
            "is_from_me": payload.is_from_me,
            "media_type": None,  # Detect from media fields
            "media_url": None,   # Will be constructed from media_path
            "filename": None,
            "device_id": gowa_message.device_id,  # ✅ FIX: Add device_id for tenant routing
            "business_jid": None,  # GOWA doesn't send this in basic messages
        }

        # ✅ FIX: Detect media type from GOWA payload and extract media_path from dict
        # Media fields come as: {"media_path": "statics/media/xxx.ogg", "mime_type": "audio/ogg"}
        bridge_url = os.getenv("BRIDGE_URL", "https://bijou-bridge-staging-v2.fly.dev")

        def extract_media_url(media_field, msg_id: str, chat_id: str) -> str:
            """Extract media URL from GOWA payload field (dict or string)"""
            if isinstance(media_field, dict):
                media_path = media_field.get("media_path", "")
                if media_path:
                    # Bridge stores files at: {BRIDGE_URL}/{media_path}
                    return f"{bridge_url}/{media_path}"
            elif isinstance(media_field, str) and media_field:
                # Legacy: if it's already a path or URL
                if media_field.startswith("http"):
                    return media_field
                return f"{bridge_url}/{media_field}"
            # Fallback: construct URL from message ID (old method)
            return f"{bridge_url}/api/media/{msg_id}?chat_jid={chat_id}"

        if payload.image:
            msg_dict["media_type"] = "image"
            msg_dict["media_url"] = extract_media_url(payload.image, payload.id, payload.chat_id)
            msg_dict["filename"] = payload.image.get("media_path", "").split("/")[-1] if isinstance(payload.image, dict) else payload.image
            logger.info(f"📷 Image detected - URL: {msg_dict['media_url']}")
        elif payload.video:
            msg_dict["media_type"] = "video"
            msg_dict["media_url"] = extract_media_url(payload.video, payload.id, payload.chat_id)
            msg_dict["filename"] = payload.video.get("media_path", "").split("/")[-1] if isinstance(payload.video, dict) else payload.video
            logger.info(f"🎬 Video detected - URL: {msg_dict['media_url']}")
        elif payload.audio:
            msg_dict["media_type"] = "audio"
            msg_dict["media_url"] = extract_media_url(payload.audio, payload.id, payload.chat_id)
            msg_dict["filename"] = payload.audio.get("media_path", "").split("/")[-1] if isinstance(payload.audio, dict) else payload.audio
            logger.info(f"🎤 Audio detected - URL: {msg_dict['media_url']}")
        elif payload.document:
            msg_dict["media_type"] = "document"
            msg_dict["media_url"] = extract_media_url(payload.document, payload.id, payload.chat_id)
            msg_dict["filename"] = payload.document.get("media_path", "").split("/")[-1] if isinstance(payload.document, dict) else payload.document
            logger.info(f"📄 Document detected - URL: {msg_dict['media_url']}")
        elif payload.sticker:
            msg_dict["media_type"] = "sticker"
            msg_dict["media_url"] = extract_media_url(payload.sticker, payload.id, payload.chat_id)
            msg_dict["filename"] = payload.sticker.get("media_path", "").split("/")[-1] if isinstance(payload.sticker, dict) else payload.sticker
            logger.info(f"😊 Sticker detected - URL: {msg_dict['media_url']}")
        elif payload.location:
            lat = payload.location.get("latitude", "")
            lon = payload.location.get("longitude", "")
            loc_name = payload.location.get("name") or payload.location.get("address") or ""
            msg_dict["body"] = f"📍 Location: {loc_name} ({lat}, {lon})" if loc_name else f"📍 Location: ({lat}, {lon})"
            msg_dict["location"] = payload.location
            logger.info(f"📍 Location message detected - lat={lat}, lon={lon}")
        elif payload.contact:
            vcard = payload.contact if isinstance(payload.contact, dict) else {}
            vname = vcard.get("display_name") or vcard.get("name") or "Contact"
            # Extract phone from vCard phones list or direct field
            vphone = ""
            phones = vcard.get("phones") or vcard.get("phone_numbers") or []
            if phones and isinstance(phones, list):
                vphone = phones[0].get("phone") or phones[0].get("number") or "" if isinstance(phones[0], dict) else str(phones[0])
            elif vcard.get("phone"):
                vphone = vcard.get("phone", "")
            msg_dict["body"] = f"👤 Contact shared: {vname} ({vphone})" if vphone else f"👤 Contact shared: {vname}"
            msg_dict["shared_contact"] = vcard
            logger.info(f"👤 vCard/Contact message detected - name={vname}, phone={vphone}")

        logger.info(
            f"📨 [WEBHOOK] Received message {payload.id} from {payload.chat_id}"
        )
        logger.info(f"   📋 Full message details:")
        logger.info(f"      chat_id: {payload.chat_id}")
        logger.info(f"      from: {payload.from_}")
        logger.info(f"      from_name: {payload.from_name}")
        logger.info(
            f"      body: {payload.body[:100] if payload.body else 'None'}..."
        )
        logger.info(f"      is_from_me: {payload.is_from_me}")

        # ✅ INFINITE LOOP FIX: Skip our own messages at webhook level (before any processing)
        if payload.is_from_me:
            logger.info(f"⏭️ [WEBHOOK] Skipping our own message {payload.id}")
            # Still mark as processed to prevent re-processing on restart
            bijou_instance.processed_message_ids.add(payload.id)
            return JSONResponse(
                status_code=200,
                content={"status": "skipped", "reason": "from_me"},
            )

        # Check if already processed (idempotency)
        if payload.id in bijou_instance.processed_message_ids:
            logger.info(f"⏭️ [WEBHOOK] Message {payload.id} already processed, skipping")
            return JSONResponse(
                status_code=200,
                content={"status": "skipped", "reason": "already_processed"},
            )

        # ✅ BUG FIX 1 + 2: When we receive a message, mark WhatsApp as connected for onboarding tenants
        # This is more reliable than waiting for connection events which may not be sent
        if gowa_message.device_id and bijou_instance.db_type == "supabase" and bijou_instance.db_conn:
            try:
                db = bijou_instance.db_conn

                # Find tenant by device_id
                device_result = db.table("whatsapp_devices").select("tenant_id").eq("device_id", gowa_message.device_id).execute()

                if device_result.data:
                    tenant_id = device_result.data[0]["tenant_id"]

                    # Check if tenant is in onboarding (has onboarding_progress record)
                    progress_check = db.table("onboarding_progress").select("step_whatsapp_completed").eq("tenant_id", tenant_id).execute()

                    if progress_check.data and not progress_check.data[0].get("step_whatsapp_completed"):
                        # Mark WhatsApp step complete
                        db.table("onboarding_progress").update({
                            "step_whatsapp_completed": True,
                            "step_whatsapp_at": datetime.now().isoformat(),
                            "current_step": "knowledge"
                        }).eq("tenant_id", tenant_id).execute()

                        # Update tenant status
                        db.table("tenants").update({
                            "whatsapp_connected": True,
                            "whatsapp_connected_at": datetime.now().isoformat(),
                            "onboarding_step": "completed",
                            "whatsapp_jid": gowa_message.device_id
                        }).eq("id", tenant_id).execute()

                        # ✅ BUG FIX 2: Ensure whatsapp_devices has the correct device_id
                        db.table("whatsapp_devices").update({
                            "whatsapp_jid": gowa_message.device_id,
                            "updated_at": datetime.now().isoformat()
                        }).eq("tenant_id", tenant_id).execute()

                        logger.info(f"✅ [ONBOARDING] WhatsApp connected for tenant {tenant_id} (device: {gowa_message.device_id})")
            except Exception as e:
                logger.error(f"❌ [ONBOARDING] Failed to update progress: {e}")

        # ⚡ PERFORMANCE FIX: Queue message for background processing
        # Returns 200 OK immediately (<100ms) instead of waiting 12-20s
        # Prevents bridge timeout and duplicate webhook deliveries
        background_tasks.add_task(bijou_instance.process_message, msg_dict)

        logger.info(f"✅ [WEBHOOK] Message {payload.id} queued for processing")

        return JSONResponse(
            status_code=200,
            content={
                "status": "accepted",
                "message_id": payload.id,
                "note": "Processing in background"
            }
        )

    except HTTPException:
        # ✅ Let HTTPExceptions propagate with their original status codes
        raise
    except Exception as e:
        logger.error(f"❌ [WEBHOOK] Unexpected error processing message: {e}")
        logger.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/connection")
async def webhook_connection_status(request: Request):
    """
    Webhook for WhatsApp connection status updates from bridge.
    Auto-updates tenant with whatsapp_jid when session connects.

    Expected payload:
    {
        "tenant_id": "uuid",
        "whatsapp_jid": "+60123456789@s.whatsapp.net",
        "status": "connected" | "disconnected",
        "timestamp": "ISO 8601"
    }
    """
    global bijou_instance

    # ✅ FIX #9: Add comprehensive validation
    try:
        # Validate content-type
        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            logger.warning(f"⚠️ Invalid connection webhook content-type: {content_type}")
            raise HTTPException(
                status_code=400,
                detail="Content-Type must be application/json"
            )

        # Parse JSON payload
        try:
            data = await request.json()
        except Exception as json_error:
            logger.error(f"❌ Failed to parse connection webhook JSON: {json_error}")
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON payload"
            )

        # ✅ BUG-2 FIX: Accept BOTH payload formats
        # Format A: {"device_id": "bijou-{uuid}", "payload": {"status": "connected", "jid": "..."}}
        # Format B: {"tenant_id": "uuid", "whatsapp_jid": "...", "status": "connected"}
        device_id_raw = data.get("device_id")
        tenant_id = data.get("tenant_id")
        whatsapp_jid = data.get("whatsapp_jid")
        status = data.get("status")

        # Extract from nested payload if present
        if isinstance(data.get("payload"), dict):
            payload_inner = data["payload"]
            if not whatsapp_jid:
                whatsapp_jid = payload_inner.get("jid") or payload_inner.get("whatsapp_jid")
            if not status:
                status = payload_inner.get("status")

        # ✅ BUG-2 FIX: Strip "bijou-" prefix to extract tenant_id from device_id
        if device_id_raw and not tenant_id:
            if device_id_raw.startswith("bijou-"):
                tenant_id = device_id_raw[len("bijou-"):]
                logger.info(f"📡 [CONNECTION WEBHOOK] Extracted tenant_id={tenant_id} from device_id={device_id_raw}")
            else:
                # 2026-08-22 FIX: on-demand-provisioned devices (see
                # onboarding_api.py) get a bridge-assigned device_id, not the
                # predictable "bijou-{tenant_id}" format, so the branch above
                # never fires for them. Look up the real tenant_id from the
                # whatsapp_devices mapping table instead of treating the raw
                # bridge device_id as a tenant UUID (which always matched
                # zero rows and silently no-op'd the whole webhook — the
                # onboarding page polled "Waiting for scan…" forever even
                # after a real scan).
                tenant_id = device_id_raw
                if bijou_instance and bijou_instance.db_type == "supabase" and bijou_instance.db_conn:
                    try:
                        dev_row = (
                            bijou_instance.db_conn.table("whatsapp_devices")
                            .select("tenant_id")
                            .eq("device_id", device_id_raw)
                            .limit(1)
                            .execute()
                        )
                        if dev_row.data and dev_row.data[0].get("tenant_id"):
                            tenant_id = dev_row.data[0]["tenant_id"]
                            logger.info(f"📡 [CONNECTION WEBHOOK] Resolved tenant_id={tenant_id} from whatsapp_devices for device_id={device_id_raw}")
                    except Exception as _lookup_err:
                        logger.warning(f"⚠️ [CONNECTION WEBHOOK] whatsapp_devices lookup failed for device_id={device_id_raw}: {_lookup_err}")

        logger.info(
            f"📡 [CONNECTION WEBHOOK] tenant={tenant_id}, jid={whatsapp_jid}, status={status}"
        )

        if not tenant_id:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: tenant_id or device_id"
            )

        if not status:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: status"
            )

        # Normalize status: "logged_in" from GOWA bridge → "connected"
        if status == "logged_in":
            status = "connected"

        if status not in ["connected", "disconnected"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid status. Must be 'connected' or 'disconnected'"
            )

        # Normalize JID (remove device suffix like :2)
        if whatsapp_jid and ":" in whatsapp_jid:
            # Extract phone number before device suffix
            base_jid = whatsapp_jid.split(":")[0]
            if "@" in whatsapp_jid:
                suffix = whatsapp_jid.split("@")[1]
                whatsapp_jid = f"{base_jid}@{suffix}"
            logger.info(f"   📞 Normalized JID: {whatsapp_jid}")

        # Get database connection
        if not bijou_instance or bijou_instance.db_type != "supabase" or not bijou_instance.db_conn:
            logger.error("❌ Supabase not configured for connection webhook")
            raise HTTPException(
                status_code=503,
                detail="Database not available"
            )

        db = bijou_instance.db_conn

        if status == "connected":
            # Update tenant with WhatsApp connection info
            update_data = {
                "whatsapp_connected_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }

            if whatsapp_jid:
                update_data["whatsapp_jid"] = whatsapp_jid

            result = (
                db.table("tenants").update(update_data).eq("id", tenant_id).execute()
            )

            # 🔥 BUG-2 FIX: Update onboarding_progress to mark WhatsApp step complete
            try:
                onboarding_upsert = {
                    "tenant_id": tenant_id,
                    "step_whatsapp_completed": True,
                    "step_whatsapp_at": datetime.now().isoformat(),
                    "current_step": "knowledge",
                    "updated_at": datetime.now().isoformat(),
                }
                db.table("onboarding_progress").upsert(onboarding_upsert, on_conflict="tenant_id").execute()
                logger.info(f"✅ [CONNECTION] Updated onboarding_progress: step_whatsapp_completed=True for tenant {tenant_id}")
            except Exception as onboard_err:
                logger.error(f"❌ [CONNECTION] Failed to update onboarding_progress: {onboard_err}")

            # 🔥 CRITICAL: Also update whatsapp_devices table with whatsapp_jid for tenant routing
            if whatsapp_jid:
                try:
                    device_update = db.table("whatsapp_devices").update({
                        "whatsapp_jid": whatsapp_jid,
                        "updated_at": datetime.now().isoformat()
                    }).eq("tenant_id", tenant_id).execute()

                    if device_update.data:
                        logger.info(f"✅ [CONNECTION] Updated whatsapp_devices with JID: {whatsapp_jid}")
                    else:
                        logger.warning(f"⚠️ [CONNECTION] No whatsapp_devices record found for tenant {tenant_id}")
                except Exception as device_error:
                    logger.error(f"❌ [CONNECTION] Failed to update whatsapp_devices: {device_error}")

            logger.info(f"✅ [CONNECTION] Tenant {tenant_id} connected: {whatsapp_jid}")

            # Auto-create client_config if missing
            try:
                config_check = (
                    db.table("client_configs")
                    .select("id")
                    .eq("tenant_id", tenant_id)
                    .execute()
                )

                if not config_check.data:
                    # Get tenant info for defaults
                    tenant_info = (
                        db.table("tenants")
                        .select("name, business_name")
                        .eq("id", tenant_id)
                        .execute()
                    )
                    business_name = (
                        tenant_info.data[0].get("business_name")
                        or tenant_info.data[0].get("name")
                        or "Your Business"
                    ) if tenant_info.data else "Your Business"

                    config_data = {
                        "tenant_id": tenant_id,
                        "client_type": "general",
                        "manglish_level": "medium",
                        "tone": "professional",
                        "enabled_tools": [],
                        "system_prompt_vars": {
                            "business_name": business_name,
                            "business_type": "Business Services",
                        },
                        "is_active": True,
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                    }

                    db.table("client_configs").insert(config_data).execute()
                    logger.info(
                        f"✅ [CONNECTION] Auto-created client_config for {tenant_id}"
                    )
                else:
                    logger.info(
                        f"   ℹ️ client_config already exists for {tenant_id}"
                    )

            except Exception as config_error:
                logger.warning(
                    f"⚠️ [CONNECTION] Could not auto-create client_config: {config_error}"
                )

            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "Tenant connected successfully",
                    "tenant_id": tenant_id,
                    "whatsapp_jid": whatsapp_jid,
                },
            )

        elif status == "disconnected":
            # Mark tenant as disconnected in DB
            db.table("tenants").update(
                {
                    "whatsapp_connected": False,
                    "whatsapp_connected_at": None,
                    "updated_at": datetime.now().isoformat(),
                }
            ).eq("id", tenant_id).execute()

            logger.warning(f"📴 [CONNECTION] Tenant {tenant_id} WhatsApp DISCONNECTED")

            # Notify owner that WhatsApp went offline
            try:
                if bijou_instance and bijou_instance.owner_jid:
                    bijou_instance.send_message(
                        bijou_instance.owner_jid,
                        f"⚠️ *WhatsApp Disconnected*\n\nYour WhatsApp session has gone offline.\n\nTo reconnect: open your dashboard → Settings → WhatsApp and scan the QR code again.",
                        tenant_id=tenant_id,
                    )
            except Exception as _notif_err:
                logger.warning(f"⚠️ Could not send disconnect notification: {_notif_err}")

            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "Tenant disconnected",
                    "tenant_id": tenant_id,
                },
            )

        else:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [CONNECTION WEBHOOK] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/webhook")
async def lead_capture_webhook(request: Request):
    """
    Generic lead capture webhook for external integrations (Forms, Facebook, etc.)
    Routes data to Bijou's ToolOrchestrator.
    """
    global bijou_instance
    if not bijou_instance:
        raise HTTPException(status_code=503, detail="Bijou not ready")

    try:
        data = await request.json()
        logger.info(f"📥 [LEAD WEBHOOK] Received data: {data}")

        # Extract fields
        name = data.get("name", "Unknown Lead")
        phone = data.get("phone", "")
        email = data.get("email")
        message = data.get("message", "New lead from external source")
        tenant_id = data.get("tenant_id")
        business_type = data.get("business_type")

        if not phone and not email:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Phone or email required"},
            )

        # Route to Lead Capture Tool
        if bijou_instance.tool_orchestrator:
            result = await bijou_instance.tool_orchestrator.capture_lead(
                name=name,
                phone=phone,
                message=message,
                email=email,
                tenant_id=tenant_id,
                business_type=business_type,
                metadata={"source": "api_webhook", "raw_data": data},
            )
            return JSONResponse(status_code=200, content=result)
        else:
            return JSONResponse(
                status_code=501,
                content={
                    "status": "error",
                    "message": "Lead capture tool not available",
                },
            )

    except Exception as e:
        logger.error(f"❌ [LEAD WEBHOOK] Error: {e}")
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


# ==================== TELEGRAM WEBHOOK ENDPOINT ====================
@app.post("/webhook/telegram")
async def webhook_telegram(request: Request):
    """
    Webhook endpoint for receiving Telegram updates.
    Converts Telegram Update to UnifiedMessage and processes via BijouAI.
    """
    global bijou_instance

    if not bijou_instance:
        logger.error("❌ Bijou instance not initialized")
        raise HTTPException(status_code=503, detail="Bijou not ready")

    if not bijou_instance.telegram_enabled:
        logger.warning("⚠️ Telegram webhook received but Telegram is not enabled")
        raise HTTPException(status_code=400, detail="Telegram not enabled")

    try:
        # Parse the incoming Telegram update
        update_data = await request.json()
        logger.info(
            f"📨 [TELEGRAM] Received update: {update_data.get('update_id', 'unknown')}"
        )

        # Import Update class for parsing
        if not TELEGRAM_AVAILABLE:
            raise HTTPException(
                status_code=500, detail="Telegram library not available"
            )

        from telegram import Update

        # Convert raw JSON to Telegram Update object
        update = Update.de_json(update_data, bijou_instance.telegram_adapter._bot)

        if not update or not update.message:
            logger.debug(
                "📨 [TELEGRAM] Non-message update (callback, edited, etc.) - skipping"
            )
            return JSONResponse(
                status_code=200, content={"status": "ok", "type": "non-message"}
            )

        # Convert to UnifiedMessage using our telegram_webhook_handler
        unified_msg = telegram_webhook_handler(update, on_message=None)

        if not unified_msg:
            logger.debug("📨 [TELEGRAM] Could not convert update to UnifiedMessage")
            return JSONResponse(
                status_code=200, content={"status": "ok", "type": "unprocessable"}
            )

        # Check if already processed (idempotency)
        if unified_msg.id in bijou_instance.processed_message_ids:
            logger.info(
                f"⏭️ [TELEGRAM] Message {unified_msg.id} already processed, skipping"
            )
            return JSONResponse(
                status_code=200,
                content={"status": "skipped", "reason": "already_processed"},
            )

        logger.info(
            f"📨 [TELEGRAM] Processing message {unified_msg.id} from {unified_msg.chat_jid}"
        )
        logger.info(f"   sender: {unified_msg.sender}")
        logger.info(
            f"   content: {unified_msg.content[:100] if unified_msg.content else 'None'}..."
        )

        # Process using BijouAI.process_message (same as WhatsApp)
        # Convert UnifiedMessage to dict for compatibility
        msg_dict = unified_msg.to_dict()
        await bijou_instance.process_message(msg_dict)

        # Send response via Telegram adapter (not WhatsApp bridge)
        # The process_message uses send_message which goes to WhatsApp
        # We need to intercept and route to Telegram
        # This is handled by overriding send behavior or checking channel in process_message

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message_id": unified_msg.id,
                "channel": "telegram",
            },
        )

    except json.JSONDecodeError as e:
        logger.error(f"❌ [TELEGRAM] Invalid JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"❌ [TELEGRAM] Error processing update: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================================================================


async def run_fastapi():
    """Run FastAPI server in async mode"""
    port = int(
        os.getenv("PORT", os.getenv("API_PORT", 8080))
    )  # Default to 8080 for Fly.io
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,  # Reduce noise
    )
    server = uvicorn.Server(config)
    await server.serve()


def main():
    """Main entry point - runs both polling and web server"""
    global bijou_instance

    logger.info("=" * 60)
    logger.info("🚀 W3J BIJOU AI WHATSAPP ENTERPRISE")
    logger.info("=" * 60)
    logger.info(f"Version: 2.2.0-production")
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'production')}")
    logger.info(f"Database: {os.getenv('DB_TYPE', 'sqlite').upper()}")
    logger.info(f"AI Model: {os.getenv('AI_MODEL', 'gemini-1.5-flash')}")
    logger.info("=" * 60)

    # Validate critical environment variables
    required_vars = {
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"),
        "SUPABASE_URL": os.getenv("SUPABASE_URL"),
        "SUPABASE_KEY": os.getenv("SUPABASE_KEY"),
        "BRIDGE_URL": os.getenv("BRIDGE_URL"),
    }

    missing_vars = [k for k, v in required_vars.items() if not v]
    if missing_vars:
        logger.critical(
            f"🚨 Missing required environment variables: {', '.join(missing_vars)}"
        )
        logger.critical(
            "Please set secrets using: fly secrets set VARIABLE=value --app bijou-staging"
        )
        sys.exit(1)

    # Initialize Bijou AI BEFORE starting FastAPI with error handling
    try:
        logger.info("🔧 Initializing Bijou AI instance...")
        bijou = BijouAI()
        bijou_instance = bijou  # Set global instance for webhook access
        logger.info("✅ Bijou AI instance ready for webhooks")
    except Exception as e:
        logger.critical(f"🚨 Failed to initialize Bijou AI: {e}")
        logger.critical(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)

    # Run both polling and web server concurrently
    async def run_all():
        try:
            # Start stale escalation cleanup task
            async def cleanup_stale_escalations():
                """Auto-close escalations older than 48h with no activity."""
                await asyncio.sleep(60)  # Wait 1 min after startup
                while True:
                    try:
                        if bijou.handover_system:
                            timeout_hours = int(os.getenv("ESCALATION_AUTO_TIMEOUT_HOURS", "48"))
                            closed = await bijou.handover_system.cleanup_stale_escalations(timeout_hours)
                            if closed > 0:
                                logger.info(f"⏰ Auto-closed {closed} stale escalation(s)")
                        await asyncio.sleep(3600)  # Run every hour
                    except Exception as e:
                        logger.error(f"❌ Stale escalation cleanup failed: {e}")
                        await asyncio.sleep(3600)  # Retry in 1 hour

            # Start all tasks concurrently
            await asyncio.gather(
                run_fastapi(),
                bijou.run_polling_loop(),
                cleanup_stale_escalations()
            )
        except Exception as e:
            logger.critical(f"🚨 Runtime error: {e}")
            logger.critical(f"Traceback: {traceback.format_exc()}")
            sys.exit(1)

    # Run
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except Exception as e:
        logger.critical(f"🚨 Fatal error: {e}")
        logger.critical(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)


@app.post("/api/webhook")
async def external_webhook(request: Request, authorization: str = Header(None)):
    """
    Handle external webhooks (e.g., from Forms, Landing Pages).
    Routes data through ToolOrchestrator for lead capture.
    """
    # 1. Simple Auth Check (if needed, or rely on internal network)
    # For now, allow open or check a shared secret if configured

    try:
        data = await request.json()
        logger.info(f"Incoming Webhook: {data}")

        # 2. Extract minimal info
        # Expecting: { "api_key": "...", "phone": "...", "name": "...", "message": "..." }

        # 3. Trigger Lead Capture
        # This is a 'fire and forget' or 'process now' action
        # For simplicity, we just log it as a lead being processed

        return {"status": "received", "data": data}

    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    main()
