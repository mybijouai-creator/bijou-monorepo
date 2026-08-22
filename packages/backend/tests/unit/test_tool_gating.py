"""
2026-08-22/23: `enabled_tools` was written into client_configs on every
signup (auth_api.py:333, bijou.py:7380) but NEVER read anywhere — every
tenant's AI got the identical global tool set. These tests pin the fix:

  - empty/missing enabled_tools -> full tool list, unchanged from today's
    behavior (CRITICAL: every existing tenant has enabled_tools=[]; treating
    that as "no tools" would be a severe regression for all of them).
  - a non-empty list -> only those tools are returned.
"""

import sys
import types
from unittest.mock import MagicMock

if "supabase" not in sys.modules:
    supabase_stub = types.ModuleType("supabase")
    setattr(supabase_stub, "create_client", lambda *args, **kwargs: None)
    setattr(supabase_stub, "Client", object)
    sys.modules["supabase"] = supabase_stub

import pytest

from src.saas.function_caller import FunctionCaller


@pytest.fixture
def fc():
    # enable_confirmations doesn't matter for declaration-building; disable
    # the Gemini client init path (no real API key in test env).
    return FunctionCaller(tool_orchestrator=None, gemini_api_key=None)


class TestToolGating:
    def test_empty_enabled_tools_returns_full_list(self, fc):
        full = fc.get_function_declarations()
        gated = fc.get_function_declarations(enabled_tools=[])
        assert gated == full
        assert len(gated) > 0

    def test_none_enabled_tools_returns_full_list(self, fc):
        full = fc.get_function_declarations()
        gated = fc.get_function_declarations(enabled_tools=None)
        assert gated == full

    def test_nonempty_list_restricts_to_named_tools(self, fc):
        full = fc.get_function_declarations()
        full_names = [f["name"] for f in full]
        assert "calculate" in full_names, "expected 'calculate' tool in the catalog"

        gated = fc.get_function_declarations(enabled_tools=["calculate"])
        assert [f["name"] for f in gated] == ["calculate"]

    def test_unknown_tool_name_yields_empty_list(self, fc):
        gated = fc.get_function_declarations(enabled_tools=["this_tool_does_not_exist"])
        assert gated == []

    def test_openai_tools_respects_gating_too(self, fc):
        gated = fc.get_openai_tools(enabled_tools=["calculate"])
        assert len(gated) == 1
        assert gated[0]["function"]["name"] == "calculate"

    def test_openai_tools_empty_gate_matches_ungated(self, fc):
        assert fc.get_openai_tools(enabled_tools=[]) == fc.get_openai_tools()
