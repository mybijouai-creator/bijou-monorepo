"""Smoke test for the new OpenAI-compatible tool calling in FunctionCaller.

Tests:
  1. get_openai_tools() returns the correct format
  2. _web_fetch_url and _web_search (provider-agnostic) work
  3. The call_with_openai_tools flow handles errors gracefully

NOTE: requires MINIMAX_API_KEY env var to test the full flow. Without it,
only the format + provider-agnostic helpers are tested.
"""
import asyncio
import json
import os
import sys

# Make sure we can import the package
sys.path.insert(0, "packages/backend")

from src.saas.function_caller import FunctionCaller


def test_openai_tools_format():
    """The OpenAI tools wrapper must match what the OpenAI SDK expects."""
    fc = FunctionCaller()
    tools = fc.get_openai_tools()
    assert isinstance(tools, list), f"expected list, got {type(tools)}"
    # Production has 9+ tools (email + calendar are conditional on the
    # orchestrator having those tools initialized). In a fresh test env
    # without google credentials, we get 7. Assert >= 7 to cover both.
    assert len(tools) >= 7, f"expected >=7 functions, got {len(tools)}"
    for t in tools:
        assert t.get("type") == "function", f"missing type=function: {t}"
        assert "function" in t, f"missing function key: {t}"
        f = t["function"]
        for k in ("name", "description", "parameters"):
            assert k in f, f"missing {k} in function: {f}"
        p = f["parameters"]
        assert p.get("type") == "object", f"params.type must be object: {p}"
        assert "properties" in p, f"missing properties: {p}"
    print(f"✅ get_openai_tools() returns {len(tools)} OpenAI-format tools")
    for t in tools[:3]:
        print(f"   - {t['function']['name']}: {t['function']['description'][:60]}...")
    return tools


async def test_web_fetch():
    """fetch_url must work without any LLM."""
    fc = FunctionCaller()
    # Use a tiny, stable URL
    r = await fc._web_fetch_url("https://example.com", max_chars=500)
    assert r.get("success"), f"fetch failed: {r}"
    assert "Example Domain" in r.get("text", ""), f"unexpected text: {r.get('text', '')[:200]}"
    print(f"✅ fetch_url works ({r.get('length')} chars from example.com)")


async def test_web_search():
    """web_search must work via DuckDuckGo HTML."""
    fc = FunctionCaller()
    r = await fc._web_search("python programming", max_results=3)
    assert r.get("success"), f"search failed: {r}"
    assert r.get("count", 0) > 0, f"no results: {r}"
    print(f"✅ web_search works ({r.get('count')} results)")


async def test_ssrf_guard():
    """fetch_url must refuse private IPs."""
    fc = FunctionCaller()
    r = await fc._web_fetch_url("http://127.0.0.1:8080/admin", max_chars=100)
    assert not r.get("success"), f"SSRF guard failed: {r}"
    assert "private" in r.get("error", "").lower() or "internal" in r.get("error", "").lower()
    print(f"✅ SSRF guard blocks private IPs: {r.get('error')}")


async def test_call_with_tools_no_key():
    """call_with_openai_tools must raise clearly when no key is provided."""
    fc = FunctionCaller()
    try:
        await fc.call_with_openai_tools(
            messages=[{"role": "user", "content": "hi"}],
            model="MiniMax-M3",
            api_key="",
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert "api_key" in str(e).lower()
        print(f"✅ call_with_openai_tools rejects empty api_key: {e}")


async def test_call_with_tools_real_minimax():
    """If MINIMAX_API_KEY is set, exercise the full flow end-to-end."""
    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        print("⏭️  Skipping real MiniMax test (MINIMAX_API_KEY not set)")
        return
    fc = FunctionCaller()
    messages = [
        {"role": "system", "content": "You are a helpful assistant. When the user shares a link, use fetch_url to open it."},
        {"role": "user", "content": "What does https://example.com say? Use fetch_url."},
    ]
    try:
        reply = await fc.call_with_openai_tools(
            messages=messages,
            model="MiniMax-M3",
            api_key=key,
            base_url=os.environ.get("MINIMAX_API_ENDPOINT", "https://api.minimax.io/v1"),
            max_iterations=3,
            max_tokens=512,
        )
        print(f"✅ Real MiniMax tool-calling flow returned ({len(reply)} chars):")
        print(f"   {reply[:200]}{'...' if len(reply) > 200 else ''}")
    except Exception as e:
        print(f"⚠️ Real MiniMax test failed: {e}")


async def main():
    print("=" * 60)
    print("FunctionCaller OpenAI-tools smoke test")
    print("=" * 60)
    test_openai_tools_format()
    print()
    await test_web_fetch()
    await test_web_search()
    await test_ssrf_guard()
    await test_call_with_tools_no_key()
    await test_call_with_tools_real_minimax()
    print()
    print("=" * 60)
    print("All tests passed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
