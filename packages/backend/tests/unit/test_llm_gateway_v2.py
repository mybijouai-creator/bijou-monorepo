"""
Tests for the LLM Gateway v2 — aliases, fallback chain, budget, privacy, and
observability.

The gateway is a pure orchestration layer: it owns the alias→provider policy
file, the fallback order, the budget counter, and the structured log. The
provider calls themselves are faked via a per-test dispatch override, so these
tests run with zero network and zero external API keys.

Coverage:
  - 4 aliases resolve to their declared primary
  - Fallback chain fires on 429 / 5xx and stops on first success
  - Privacy: ai://private never falls back to openrouter even if declared
  - Budget: spending cap returns BudgetExceeded and 429s the caller
  - Observability: every successful call writes a structured row with
    provider / model / alias / latency_ms / tokens / cost / fallback_reason
  - Unknown alias and NoProviderAvailable paths
  - _UsageTracker / drain_buffer / spent_today
  - The migration file exists and has the expected table name

Total: 25 tests.
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Make src.* importable when pytest is run from any cwd.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import llm_gateway_v2 as g  # noqa: E402
from src.core.llm_gateway_v2 import (  # noqa: E402
    BudgetExceeded,
    LLMGateway,
    NoProviderAvailable,
    ProviderError,
    _call_gemini,
    _call_openai_compatible,
    _read_env_keys,
    _UsageTracker,
)


# -----------------------------------------------------------------------------
# Helpers — fake provider dispatch.
# -----------------------------------------------------------------------------


def _ok(text="hello", pt=10, ct=5, model="m1"):
    """Build a fake adapter callable that returns a successful result tuple."""
    payload = (text, {"fake": True}, pt, ct, model)

    def fake(model, messages, opts):
        return payload

    return fake


def _err(status_code=429, message="rate limit"):
    """Build a fake adapter that raises ProviderError."""

    def fake(model, messages, opts):
        raise ProviderError(message, status_code=status_code)

    return fake


@pytest.fixture
def fresh_gateway():
    """Build a gateway whose dispatch is fully faked — zero network."""
    gw = LLMGateway.__new__(LLMGateway)  # skip __init__ to avoid file IO
    gw._config_path = g._CONFIG_PATH
    gw._lock = __import__("threading").Lock()
    # Reload from the real YAML — same file the runtime uses.
    gw.reload()
    gw._usage = _UsageTracker()
    gw._dispatch_override = {}
    return gw


def _set_dispatch(gw, **per_provider):
    """Inject fake adapters by provider name."""
    gw._dispatch_override = per_provider


# -----------------------------------------------------------------------------
# 1. Each alias resolves to its primary
# -----------------------------------------------------------------------------


def test_fast_alias_routes_to_gemini_primary(fresh_gateway):
    _set_dispatch(fresh_gateway, gemini=_ok("fast reply", model="gemini-2.5-flash"))
    r = asyncio.run(
        fresh_gateway.complete("ai://fast", [{"role": "user", "content": "hi"}])
    )
    assert r.provider == "gemini"
    assert r.text == "fast reply"
    assert r.alias == "ai://fast"
    assert r.fallback_reason is None  # primary answered


def test_reasoning_alias_routes_to_gemini_primary(fresh_gateway):
    _set_dispatch(fresh_gateway, gemini=_ok("reasoning reply"))
    r = asyncio.run(
        fresh_gateway.complete("ai://reasoning", [{"role": "user", "content": "x"}])
    )
    assert r.provider == "gemini"
    assert r.alias == "ai://reasoning"


def test_extract_alias_routes_to_gemini_primary(fresh_gateway):
    _set_dispatch(fresh_gateway, gemini=_ok('{"intent":"buy"}'))
    r = asyncio.run(
        fresh_gateway.complete("ai://extract", [{"role": "user", "content": "x"}])
    )
    assert r.provider == "gemini"
    assert r.alias == "ai://extract"


def test_private_alias_routes_to_gemini_primary(fresh_gateway):
    _set_dispatch(fresh_gateway, gemini=_ok("private reply"))
    r = asyncio.run(
        fresh_gateway.complete("ai://private", [{"role": "user", "content": "x"}])
    )
    assert r.provider == "gemini"
    assert r.alias == "ai://private"


# -----------------------------------------------------------------------------
# 2. Fallback chain — primary 429 -> next provider
# -----------------------------------------------------------------------------


def test_fallback_on_429_uses_next_provider(fresh_gateway):
    _set_dispatch(
        fresh_gateway,
        gemini=_err(429, "quota"),
        openrouter=_ok("from openrouter", model="google/gemini-2.5-flash"),
    )
    r = asyncio.run(
        fresh_gateway.complete("ai://fast", [{"role": "user", "content": "hi"}])
    )
    assert r.provider == "openrouter"
    assert r.fallback_reason == "http_429"
    assert r.text == "from openrouter"


def test_fallback_on_503_uses_next_provider(fresh_gateway):
    _set_dispatch(
        fresh_gateway,
        gemini=_err(503, "down"),
        openrouter=_ok("ok"),
    )
    r = asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    assert r.provider == "openrouter"
    assert r.fallback_reason == "http_503"


def test_fallback_chain_walks_through_all_entries(fresh_gateway):
    _set_dispatch(
        fresh_gateway,
        gemini=_err(429),
        openrouter=_err(502),
        openai_compatible=_ok("final", model="gpt-4o-mini"),
    )
    r = asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    assert r.provider == "openai_compatible"
    assert r.fallback_reason == "http_502"  # last failure that triggered the move


def test_fallback_does_not_retry_400_class_errors(fresh_gateway):
    """400/401/403/404 are config bugs — falling back is wrong (just hits the same wall)."""
    _set_dispatch(
        fresh_gateway,
        gemini=_err(401, "bad key"),
        openrouter=_ok("should not reach"),
    )
    with pytest.raises(ProviderError) as exc:
        asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    assert exc.value.status_code == 401


def test_all_providers_failing_raises_last_error(fresh_gateway):
    _set_dispatch(
        fresh_gateway,
        gemini=_err(500),
        openrouter=_err(503),
        openai_compatible=_err(429),
    )
    with pytest.raises(ProviderError) as exc:
        asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    assert exc.value.status_code == 429


# -----------------------------------------------------------------------------
# 3. Privacy — ai://private must NEVER fall back to OpenRouter
# -----------------------------------------------------------------------------


def test_private_alias_skips_openrouter_even_if_listed(fresh_gateway):
    """Even if someone (incorrectly) added openrouter to private's fallbacks,
    the strict-privacy gate must filter it out before it ever gets called."""
    # Hand-craft a config with openrouter sneaking in.
    fresh_gateway._config["aliases"]["ai://private"]["fallbacks"].insert(
        0, {"provider": "openrouter", "model": "x", "max_output_tokens": 100, "temperature": 0.3}
    )
    _set_dispatch(
        fresh_gateway,
        gemini=_err(429),
        openrouter=_ok("leak"),  # must NOT be called
        openai_compatible=_ok("safe", model="gpt-4o-mini"),
    )
    r = asyncio.run(
        fresh_gateway.complete("ai://private", [{"role": "user", "content": "ssn: 123"}])
    )
    assert r.provider == "openai_compatible"
    assert "leak" not in r.text


def test_private_alias_with_no_strict_fallback_raises(fresh_gateway):
    """If only OpenRouter is in the chain and privacy=strict, the alias has
    zero usable providers and must raise NoProviderAvailable — better to
    refuse than to leak to a multi-tenant aggregator."""
    # Replace BOTH primary and fallbacks with only-strict-incompatible providers,
    # AND mock the strict providers' dispatch to error, so the loop walks the
    # whole chain and the privacy filter blocks every entry.
    fresh_gateway._config["aliases"]["ai://private"]["primary"] = {
        "provider": "openrouter", "model": "x", "max_output_tokens": 100, "temperature": 0.3
    }
    fresh_gateway._config["aliases"]["ai://private"]["fallbacks"] = [
        {"provider": "openrouter", "model": "y", "max_output_tokens": 100, "temperature": 0.3}
    ]
    _set_dispatch(fresh_gateway, openrouter=_ok("leak"))  # must never be called
    with pytest.raises(NoProviderAvailable):
        asyncio.run(
            fresh_gateway.complete("ai://private", [{"role": "user", "content": "x"}])
        )


# -----------------------------------------------------------------------------
# 4. Budget enforcement
# -----------------------------------------------------------------------------


def test_budget_exceeded_raises_after_spending_cap(fresh_gateway):
    """If the alias's daily_budget_usd is $0.0001 and we record $0.0001, the next
    call must raise BudgetExceeded without hitting any provider."""
    # Force a tiny budget.
    fresh_gateway._config["aliases"]["ai://fast"]["daily_budget_usd"] = 0.0001
    _set_dispatch(fresh_gateway, gemini=_ok("first", pt=1000, ct=1000, model="gemini-2.5-flash"))
    # First call: 1000 * 0.000075 + 1000 * 0.0003 = $0.000375 — well over budget.
    asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    # Now the next call must be blocked.
    with pytest.raises(BudgetExceeded) as exc:
        asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    assert exc.value.alias == "ai://fast"


def test_budget_zero_means_unlimited(fresh_gateway):
    """A daily_budget_usd of 0 (or missing) means 'no cap'."""
    fresh_gateway._config["aliases"]["ai://fast"]["daily_budget_usd"] = 0
    _set_dispatch(fresh_gateway, gemini=_ok("ok", pt=1_000_000, ct=1_000_000))
    # Should not raise even with huge cost.
    r = asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    assert r.text == "ok"


def test_spent_today_isolated_per_alias(fresh_gateway):
    """Spending on ai://fast must NOT consume ai://reasoning's budget."""
    fresh_gateway._config["aliases"]["ai://fast"]["daily_budget_usd"] = 0.01
    _set_dispatch(fresh_gateway, gemini=_ok("ok", pt=1000, ct=1000, model="gemini-2.5-flash"))
    asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    # reasoning budget untouched
    assert fresh_gateway.spent_today("ai://reasoning") == 0.0


# -----------------------------------------------------------------------------
# 5. Structured log fields
# -----------------------------------------------------------------------------


def test_completion_result_has_all_observability_fields(fresh_gateway):
    _set_dispatch(fresh_gateway, gemini=_ok("hi", pt=12, ct=7, model="gemini-2.5-flash"))
    r = asyncio.run(
        fresh_gateway.complete(
            "ai://fast",
            [{"role": "user", "content": "x"}],
            tenant_id="11111111-1111-1111-1111-111111111111",
        )
    )
    # Every documented field is present and typed correctly.
    assert r.provider == "gemini"
    assert r.model == "gemini-2.5-flash"
    assert r.alias == "ai://fast"
    assert r.fallback_reason is None
    assert r.prompt_tokens == 12
    assert r.completion_tokens == 7
    assert r.cost_usd > 0.0  # we have cost data for gemini-2.5-flash
    assert r.latency_ms >= 0
    assert isinstance(r.text, str)


def test_drain_buffer_returns_one_row_per_successful_call(fresh_gateway):
    _set_dispatch(fresh_gateway, gemini=_ok("ok1"), gemini_b=_ok("ok2"))
    _set_dispatch(fresh_gateway, gemini=_ok("ok1"))
    asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "a"}]))
    asyncio.run(fresh_gateway.complete("ai://reasoning", [{"role": "user", "content": "b"}]))
    rows = fresh_gateway.drain_usage()
    assert len(rows) == 2
    aliases = sorted({r["alias"] for r in rows})
    assert aliases == ["ai://fast", "ai://reasoning"]
    for row in rows:
        assert {"alias", "provider", "model", "latency_ms", "cost_usd"} <= row.keys()


def test_drain_buffer_is_idempotent(fresh_gateway):
    _set_dispatch(fresh_gateway, gemini=_ok("ok"))
    asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    first = fresh_gateway.drain_usage()
    second = fresh_gateway.drain_usage()
    assert len(first) == 1
    assert len(second) == 0  # already drained


def test_fallback_records_fallback_reason_in_buffer(fresh_gateway):
    _set_dispatch(fresh_gateway, gemini=_err(429), openrouter=_ok("ok"))
    asyncio.run(fresh_gateway.complete("ai://fast", [{"role": "user", "content": "x"}]))
    rows = fresh_gateway.drain_usage()
    assert len(rows) == 1
    assert rows[0]["fallback_reason"] == "http_429"
    assert rows[0]["provider"] == "openrouter"


# -----------------------------------------------------------------------------
# 6. Config / unknown alias / NoProviderAvailable
# -----------------------------------------------------------------------------


def test_unknown_alias_raises_no_provider_available(fresh_gateway):
    with pytest.raises(NoProviderAvailable) as exc:
        asyncio.run(fresh_gateway.complete("ai://nope", [{"role": "user", "content": "x"}]))
    assert "ai://nope" in str(exc.value)


def test_empty_messages_raises_value_error(fresh_gateway):
    with pytest.raises(ValueError):
        asyncio.run(fresh_gateway.complete("ai://fast", []))


def test_list_aliases_returns_all_six(fresh_gateway):
    aliases = {a["alias"] for a in fresh_gateway.list_aliases()}
    # The four core aliases (fast/reasoning/extract/private) plus helpdesk + vision.
    assert aliases == {
        "ai://fast",
        "ai://reasoning",
        "ai://extract",
        "ai://private",
        "ai://helpdesk",
        "ai://vision",
    }


# -----------------------------------------------------------------------------
# 7. env-key reading
# -----------------------------------------------------------------------------


def test_read_env_keys_returns_first_set(monkeypatch):
    monkeypatch.setenv("MY_KEY_A", "value_a")
    monkeypatch.setenv("MY_KEY_B", "value_b")
    monkeypatch.delenv("MY_KEY_C", raising=False)
    out = _read_env_keys("MY_KEY_C|MY_KEY_A|MY_KEY_B")
    assert out == ["value_a", "value_b"]


def test_read_env_keys_handles_comma_separated(monkeypatch):
    monkeypatch.setenv("K1", "v1")
    monkeypatch.setenv("K2", "v2")
    out = _read_env_keys("K1,K2")
    assert out == ["v1", "v2"]


# -----------------------------------------------------------------------------
# 8. Migration file
# -----------------------------------------------------------------------------


def test_llm_usage_migration_exists():
    """The migration file for public.llm_usage must exist in migrations-py/."""
    p = ROOT / "migrations-py" / "add_llm_usage.sql"
    assert p.exists(), f"missing {p}"
    body = p.read_text(encoding="utf-8")
    assert "create table if not exists public.llm_usage" in body
    assert "alias" in body and "provider" in body and "cost_usd" in body


# -----------------------------------------------------------------------------
# 9. Real adapters (smoke test only — fail gracefully on missing key)
# -----------------------------------------------------------------------------


def test_gemini_adapter_raises_without_key(monkeypatch):
    """The real _call_gemini should raise ProviderError if no key is set."""
    for k in ("GEMINI_API_KEY", "GEMINI_API_KEYS", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ProviderError):
        _call_gemini("gemini-2.5-flash", [{"role": "user", "content": "x"}], {})


def test_openai_compatible_adapter_raises_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        _call_openai_compatible("https://api.openai.com/v1", None, "gpt-4o-mini", [{"role": "user", "content": "x"}], {})


# -----------------------------------------------------------------------------
# 10. Cost estimation
# -----------------------------------------------------------------------------


def test_cost_estimation_uses_yaml_table(fresh_gateway):
    """gemini-2.5-flash input $0.000075/1k, output $0.0003/1k."""
    in_rate, out_rate = fresh_gateway._cost_per_1k("gemini-2.5-flash")
    cost = fresh_gateway._estimate_cost("gemini-2.5-flash", prompt_tokens=1000, completion_tokens=500)
    expected = (1000 / 1000.0) * 0.000075 + (500 / 1000.0) * 0.0003
    assert abs(cost - expected) < 1e-9


def test_cost_estimation_returns_zero_for_unknown_model(fresh_gateway):
    cost = fresh_gateway._estimate_cost("no/such-model", 1000, 1000)
    assert cost == 0.0
