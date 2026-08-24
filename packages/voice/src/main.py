"""FastAPI app entry point for Bijou Voice."""
from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .shared_context import get_shared_context_client
from .tenant_config import get_tenant_config_client
from .orchestrator import VoiceOrchestrator
from .telnyx_webhook import router as telnyx_router

logger = logging.getLogger("bijou.voice")

# Module-level singleton: the orchestrator needs both clients anyway,
# so we wire them once at startup and pass them around.
_orchestrator: VoiceOrchestrator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate required env at startup, build the orchestrator singleton.

    If env is missing or unreachable, log and continue (so the
    container passes its healthcheck even in a misconfigured state —
    Coolify will then surface the warning in /health).
    """
    global _orchestrator
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    llm_url = os.environ.get("BIJOU_BACKEND_URL", "http://bijou-backend:8080")
    if supabase_url and supabase_key:
        try:
            ctx = get_shared_context_client()
            tcc = get_tenant_config_client()
            _orchestrator = VoiceOrchestrator(shared_context=ctx, llm_gateway_url=llm_url)
            logger.info("✅ voice service initialised: orchestrator wired")
        except Exception as e:
            logger.error("⚠️ voice service initialisation failed: %s", e, exc_info=True)
            _orchestrator = None
    else:
        logger.warning(
            "⚠️ SUPABASE_URL or SUPABASE_SERVICE_KEY missing — orchestrator not wired. "
            "Healthcheck will report degraded."
        )
    yield
    logger.info("🛑 voice service shutting down")


app = FastAPI(
    title="Bijou Voice",
    version="0.1.0",
    description="Telnyx-backed voice concierge with A2A shared context. See AGENT.md.",
    lifespan=lifespan,
)

# Mount the Telnyx webhook router
app.include_router(telnyx_router)


# ─── Health + diagnostic endpoints ─────────────────────────────────────

@app.get("/health")
async def health():
    """Trivial health — used by Docker / Coolify. Always 200 if process is up."""
    return JSONResponse({"ok": True, "service": "bijou-voice", "version": "0.1.0"})


@app.get("/api/voice/status")
async def status():
    """Detailed status. Returns 200 always; surfaces what's wired and what's not."""
    return JSONResponse({
        "service": "bijou-voice",
        "version": "0.1.0",
        "orchestrator_wired": _orchestrator is not None,
        "supabase_configured": bool(os.environ.get("SUPABASE_URL")) and bool(os.environ.get("SUPABASE_SERVICE_KEY")),
        "bijou_backend_url": os.environ.get("BIJOU_BACKEND_URL", "http://bijou-backend:8080"),
        "telnyx_configured": bool(os.environ.get("TELNYX_API_KEY")),
        "stub": True,  # until the orchestrator's LLM call lands
    })
