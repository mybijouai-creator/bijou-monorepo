"""
Bijou LLM Gateway — Langfuse tracing adapter.

Wraps every LLM gateway call in a Langfuse generation observation so the
dashboard can show traces, costs, latency, token usage, and prompt/completion
content (toggleable for PDPA).

Public surface:
    from src.core.langfuse_tracing import trace_completion, LangfuseConfig

    with trace_completion(alias="ai://fast", model="gpt-4o-mini",
                          provider="openai_compatible", messages=messages,
                          tenant_id=tenant_id) as obs:
        try:
            text, pt, ct = await call_llm(...)
            obs.update(output=text, usage={"prompt_tokens": pt, "completion_tokens": ct})
        except Exception as e:
            obs.fail(str(e))
            raise

Activation:
    LANGFUSE_ENABLED=true                 (default false — fail-closed if missing keys)
    LANGFUSE_PUBLIC_KEY=pk-lf-...         (from Langfuse project settings)
    LANGFUSE_SECRET_KEY=sk-lf-...
    LANGFUSE_HOST=http://langfuse-web:3000   (Coolify internal)
    LANGFUSE_SAMPLE_RATE=1.0                (0.0-1.0, default 1.0 = all)
    LANGFUSE_MASK_PII=true                  (strip phone/email/credit-card from input/output)
    LANGFUSE_ENVIRONMENT=production         (tag for filtering in UI)

The module is import-safe: if Langfuse SDK isn't installed OR env keys are
missing, it returns a no-op context manager. Production code should never
crash because tracing is unavailable.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

# Lazy / safe import — module loads even if langfuse isn't installed
try:
    from langfuse import get_client as _lf_get_client  # type: ignore
    from langfuse import LangfuseGeneration  # type: ignore
    _LANGFUSE_AVAILABLE = True
except ImportError:
    _LANGFUSE_AVAILABLE = False
    _lf_get_client = None
    LangfuseGeneration = None  # type: ignore

# Cached client (per-process, thread-safe)
_client_lock = threading.Lock()
_cached_client = None
_cached_config: Optional["LangfuseConfig"] = None


@dataclass
class LangfuseConfig:
    enabled: bool
    public_key: Optional[str]
    secret_key: Optional[str]
    host: Optional[str]
    environment: str
    sample_rate: float
    mask_pii: bool
    release: Optional[str] = None

    @classmethod
    def from_env(cls) -> "LangfuseConfig":
        enabled = (os.getenv("LANGFUSE_ENABLED", "false").lower() in ("true", "1", "yes"))
        return cls(
            enabled=enabled,
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST"),
            environment=os.getenv("LANGFUSE_ENVIRONMENT", "production"),
            sample_rate=float(os.getenv("LANGFUSE_SAMPLE_RATE", "1.0")),
            mask_pii=(os.getenv("LANGFUSE_MASK_PII", "true").lower() in ("true", "1", "yes")),
            release=os.getenv("LANGFUSE_RELEASE"),
        )

    def is_ready(self) -> bool:
        return (
            self.enabled
            and _LANGFUSE_AVAILABLE
            and bool(self.public_key)
            and bool(self.secret_key)
            and bool(self.host)
        )


def get_config() -> LangfuseConfig:
    """Return the process-wide Langfuse config (cached after first read)."""
    global _cached_config
    if _cached_config is None:
        with _client_lock:
            if _cached_config is None:
                _cached_config = LangfuseConfig.from_env()
    return _cached_config


def _get_client():
    """Return the process-wide Langfuse client (cached). Returns None if not ready."""
    if not _LANGFUSE_AVAILABLE:
        return None
    cfg = get_config()
    if not cfg.is_ready():
        return None
    global _cached_client
    if _cached_client is None:
        with _client_lock:
            if _cached_client is None:
                try:
                    _cached_client = _lf_get_client(public_key=cfg.public_key)  # type: ignore
                except Exception as e:
                    logger.warning("Langfuse client init failed: %s", e)
                    return None
    return _cached_client


# ---------- PII masking ------------------------------------------------------

_PII_PATTERNS = [
    # Malaysian phone numbers
    (re.compile(r"\+?60[\s-]?\d{1,2}[\s-]?\d{3,4}[\s-]?\d{4}"), "+60XXXXXXXXX"),
    # International phone (E.164-ish)
    (re.compile(r"\+\d{8,15}"), "+XXXXXXXXXXX"),
    # Email
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email@redacted"),
    # Credit card (basic)
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "4111-XXXX-XXXX-XXXX"),
    # Malaysian IC (NRIC)
    (re.compile(r"\b\d{6}-?\d{2}-?\d{4}\b"), "XXXXXX-XX-XXXX"),
    # MY plate (basic)
    (re.compile(r"\b[A-Z]{1,3}\s?\d{1,4}\s?[A-Z]?\b"), "PLATE"),
]


def _mask(text: str) -> str:
    if not text:
        return text
    out = text
    for pat, repl in _PII_PATTERNS:
        out = pat.sub(repl, out)
    return out


def _maybe_mask(value: Any) -> Any:
    cfg = get_config()
    if not cfg.mask_pii:
        return value
    if isinstance(value, str):
        return _mask(value)
    if isinstance(value, list):
        return [_maybe_mask(v) for v in value]
    if isinstance(value, dict):
        return {k: _maybe_mask(v) for k, v in value.items()}
    return value


# ---------- Tracing context manager ----------------------------------------


class _NoopObservation:
    """Returned when Langfuse is disabled / unavailable. All methods are safe no-ops."""

    def update(self, **kwargs: Any) -> None:  # noqa: D401
        return None

    def fail(self, message: str, level: str = "ERROR") -> None:  # noqa: D401
        return None

    def score(self, name: str, value: Any, comment: Optional[str] = None) -> None:  # noqa: D401
        return None


@contextmanager
def trace_completion(
    *,
    alias: str,
    model: str,
    provider: str,
    messages: List[Dict[str, Any]],
    tenant_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
) -> Iterator[Any]:
    """Wrap an LLM call in a Langfuse generation observation.

    Yields an observation with `.update(**kwargs)`, `.fail(message)`, and
    `.score(name, value)` methods. If Langfuse is disabled or unavailable,
    the yielded object is a no-op.
    """
    cfg = get_config()
    if not cfg.is_ready():
        yield _NoopObservation()
        return

    client = _get_client()
    if client is None:
        yield _NoopObservation()
        return

    # Apply sampling
    import random
    if cfg.sample_rate < 1.0 and random.random() > cfg.sample_rate:
        yield _NoopObservation()
        return

    # Build input — messages as-is, masked if enabled
    masked_input = _maybe_mask(messages)

    # Build observation metadata
    obs_meta = {
        "alias": alias,
        "tenant_id": tenant_id,
        "provider_chain": provider,  # we don't have the full chain at this point
    }
    if metadata:
        obs_meta.update(_maybe_mask(metadata))

    # Try to start an observation. Langfuse v4 API: client.start_as_current_observation
    obs = None
    try:
        obs = client.start_as_current_observation(
            as_type="generation",
            name=f"{alias}",
            model=model,
            input=masked_input,
            metadata=obs_meta,
            version=cfg.release,
        ) if hasattr(client, "start_as_current_observation") else None
    except Exception as e:
        logger.debug("Langfuse start_as_current_observation failed: %s", e)
        obs = None

    if obs is None:
        yield _NoopObservation()
        return

    # Set trace-level attrs
    try:
        if session_id:
            obs.update_trace(session_id=session_id) if hasattr(obs, "update_trace") else None
        if user_id:
            obs.update_trace(user_id=user_id) if hasattr(obs, "update_trace") else None
        if tags:
            obs.update_trace(tags=tags) if hasattr(obs, "update_trace") else None
    except Exception as e:
        logger.debug("Langfuse update_trace failed: %s", e)

    class _Wrap:
        def update(self, **kwargs: Any) -> None:
            try:
                # Map common kwargs to Langfuse v4 API
                output = kwargs.pop("output", kwargs.pop("text", None))
                usage = kwargs.pop("usage", None)
                cost = kwargs.pop("cost_usd", kwargs.pop("cost", None))
                if output is not None:
                    kwargs["output"] = _maybe_mask(output)
                if usage:
                    kwargs["usage_details"] = {
                        "input": usage.get("prompt_tokens", 0),
                        "output": usage.get("completion_tokens", 0),
                        "total": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
                    }
                if cost is not None:
                    kwargs["cost_details"] = {"total": cost}
                obs.update(**kwargs)
            except Exception as e:
                logger.debug("Langfuse obs.update failed: %s", e)

        def fail(self, message: str, level: str = "ERROR") -> None:
            try:
                obs.update(level=level, status_message=message)
            except Exception as e:
                logger.debug("Langfuse obs.fail failed: %s", e)

        def score(self, name: str, value: Any, comment: Optional[str] = None) -> None:
            try:
                if hasattr(client, "score_current_observation"):
                    client.score_current_observation(name=name, value=value, comment=comment)
                elif hasattr(obs, "score"):
                    obs.score(name=name, value=value, comment=comment)
            except Exception as e:
                logger.debug("Langfuse obs.score failed: %s", e)

    try:
        yield _Wrap()
    except Exception as e:
        try:
            obs.update(level="ERROR", status_message=str(e))
        except Exception:
            pass
        raise
    finally:
        try:
            obs.end()
        except Exception as e:
            logger.debug("Langfuse obs.end failed: %s", e)


def flush() -> None:
    """Flush pending traces. Call on shutdown / after critical paths."""
    cfg = get_config()
    if not cfg.is_ready():
        return
    client = _get_client()
    if client is None:
        return
    try:
        if hasattr(client, "flush"):
            client.flush()
        elif hasattr(client, "flush_events"):
            client.flush_events()
    except Exception as e:
        logger.debug("Langfuse flush failed: %s", e)


def health_summary() -> Dict[str, Any]:
    """For /api/self-test and admin dashboard."""
    cfg = get_config()
    return {
        "enabled": cfg.enabled,
        "sdk_available": _LANGFUSE_AVAILABLE,
        "configured": bool(cfg.public_key and cfg.secret_key and cfg.host),
        "ready": cfg.is_ready(),
        "host": cfg.host,
        "environment": cfg.environment,
        "sample_rate": cfg.sample_rate,
        "mask_pii": cfg.mask_pii,
    }
