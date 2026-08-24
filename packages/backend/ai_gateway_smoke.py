#!/usr/bin/env python3
"""
AI Gateway v2 smoke test — run this after a deploy to confirm the gateway
loaded cleanly, all 4 core aliases are configured, and the refactored
callsites still import.

Usage (from packages/backend/):
    ./.venv/Scripts/python.exe ai_gateway_smoke.py

Exit code 0 = all good. Non-zero = check stdout for which check failed.

This is NOT a unit test (it doesn't mock anything) — it just confirms the
in-process config is well-formed. For real coverage, run
`pytest tests/unit/test_llm_gateway_v2.py`.
"""
import sys

sys.path.insert(0, ".")

from src.core.llm_gateway_v2 import llm  # noqa: E402
from src.core.llm_gateway_v2 import (  # noqa: E402
    LLMGateway,
    CompletionResult,
    BudgetExceeded,
    NoProviderAvailable,
    ProviderError,
)


def main() -> int:
    # 1. Aliases loaded
    aliases = llm.list_aliases()
    print(f"Aliases loaded: {len(aliases)}")
    for a in aliases:
        p = a["primary"]
        print(
            f"  {a['alias']:18s} privacy={a['privacy']:8s} "
            f"budget=${a['daily_budget_usd']:.2f} "
            f"primary={p['provider']}/{p['model']}"
        )

    # 2. Required core aliases
    required = {"ai://fast", "ai://reasoning", "ai://extract", "ai://private"}
    got = {a["alias"] for a in aliases}
    missing = required - got
    print(f"Required core aliases present: {len(missing) == 0}")
    if missing:
        print(f"  MISSING: {missing}")
        return 1

    # 3. Refactored callsites import cleanly
    print("v2 module imports OK")

    try:
        from src.core.bijou import BijouAI  # noqa: F401
        print("BijouAI imports OK (gateway refactor in place)")
    except Exception as e:
        print(f"BijouAI import FAILED: {e}")
        return 1

    try:
        from src.api.help_chat import router  # noqa: F401
        print("help_chat router imports OK")
    except Exception as e:
        print(f"help_chat import FAILED: {e}")
        return 1

    try:
        from src.saas.ai_handover_detector import detect_handover_intent  # noqa: F401
        print("detect_handover_intent imports OK")
    except Exception as e:
        print(f"ai_handover_detector import FAILED: {e}")
        return 1

    print("ALL SMOKE TESTS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
