"""
Bijou AI - Function Calling System
====================================

AI-driven automatic tool orchestration using Gemini 2.0 native function calling.

Automatically detects user intent and calls appropriate tools:
- Email: Send, search, draft emails via Gmail
- Calendar: Create, update, view events via Google Calendar
- Search: Query knowledge base
- Reminders: Set reminders for follow-ups

Author: W3J Consulting - Muhammad Nurunnabi (Jewel)
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class FunctionCaller:
    """
    Manages AI-driven function calling for automatic tool orchestration.

    Integrates with Gemini 2.0 function calling API to automatically
    detect intent and execute appropriate tools.
    """

    def __init__(
        self,
        tool_orchestrator=None,
        gemini_api_key: Optional[str] = None,
        enable_confirmations: bool = True,
        connector_router=None,
        connector_registry=None,
    ):
        """
        Initialize function caller.

        Args:
            tool_orchestrator: ToolOrchestrator instance
            gemini_api_key: Gemini API key
            enable_confirmations: Require confirmation for destructive actions
        """
        self.tool_orchestrator = tool_orchestrator
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        self.enable_confirmations = enable_confirmations

        # Feature flag
        self.enabled = os.getenv("ENABLE_FUNCTION_CALLING", "false").lower() == "true"

        # Track pending confirmations
        self.pending_confirmations: Dict[str, Dict[str, Any]] = {}

        # Multi-backend connector layer (native + Composio). Feature-flagged;
        # when ENABLE_COMPOSIO is off, none of the connector code paths run and
        # behavior is identical to before.
        self.composio_enabled = os.getenv("ENABLE_COMPOSIO", "false").lower() == "true"
        self._router = connector_router
        self._registry = connector_registry
        self._connector_fn_map: Dict[str, str] = {}
        if self._registry is not None:
            self._connector_fn_map = {a.replace(".", "_"): a for a in self._registry}

        # Initialize Gemini client
        if self.enabled and self.gemini_api_key:
            try:
                from google import genai

                self.genai_client = genai.Client(api_key=self.gemini_api_key)
                logger.info("✅ FunctionCaller initialized (enabled=true)")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                self.enabled = False
        else:
            logger.info("✅ FunctionCaller initialized (enabled=false)")

    def _ensure_connectors(self) -> None:
        """Lazily build the connector router + registry (idempotent)."""
        if self._router is not None and self._registry is not None:
            return
        from src.connectors.registry import build_registry
        from src.connectors.router import ConnectorRouter
        from src.connectors.native_connector import NativeConnector
        from src.connectors.composio_connector import ComposioConnector
        if self._registry is None:
            self._registry = build_registry(self.tool_orchestrator)
        if self._router is None:
            self._router = ConnectorRouter({
                "native": NativeConnector(self.tool_orchestrator),
                "composio": ComposioConnector(),  # api_key from COMPOSIO_API_KEY env
            })
        self._connector_fn_map = {a.replace(".", "_"): a for a in self._registry}

    def get_function_declarations(self, enabled_tools: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Get function declarations for Gemini function calling.

        Returns:
            List of function declaration dicts
        """
        functions = []

        # Email functions (if Gmail tool available)
        # 2026-08-22 FIX: hasattr() alone is always True here — ToolOrchestrator's
        # __init__ sets self.gmail_tool = None unconditionally, so this
        # advertised send_email/search_email to the model even when Gmail
        # never initialized (which it currently never does — see gmail_tool.py's
        # desktop-OAuth flow incompatible with the service-account credential
        # path.production sets). Match the truthiness check the Calendar
        # branch below already uses.
        if self.tool_orchestrator and getattr(self.tool_orchestrator, "gmail_tool", None):
            functions.extend(
                [
                    {
                        "name": "send_email",
                        "description": "Send an email via Gmail",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "to": {
                                    "type": "string",
                                    "description": "Recipient email address",
                                },
                                "subject": {
                                    "type": "string",
                                    "description": "Email subject",
                                },
                                "body": {"type": "string", "description": "Email body"},
                            },
                            "required": ["to", "subject", "body"],
                        },
                    },
                    {
                        "name": "search_email",
                        "description": "Search emails in Gmail",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query (e.g., 'from:john@example.com')",
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Maximum number of results (default 10)",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                ]
            )

        # Calendar functions (Multi-tenant calendar service)
        if self.tool_orchestrator and hasattr(self.tool_orchestrator, "tenant_calendar_service") and self.tool_orchestrator.tenant_calendar_service:
            functions.extend(
                [
                    {
                        "name": "check_availability",
                        "description": "Check available appointment slots on the calendar for a specific date. ALWAYS call this FIRST before booking.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "date_from": {
                                    "type": "string",
                                    "description": "Start date in ISO format (e.g., '2026-03-06')",
                                },
                                "date_to": {
                                    "type": "string",
                                    "description": "End date in ISO format (e.g., '2026-03-07'). Defaults to date_from + 1 day",
                                },
                            },
                            "required": ["date_from"],
                        },
                    },
                    {
                        "name": "book_appointment",
                        "description": "Book an appointment/viewing for customer using their Cal.com calendar. Only call this AFTER you have collected customer name, email, phone AND checked availability.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "customer_name": {
                                    "type": "string",
                                    "description": "Customer's full name",
                                },
                                "customer_email": {
                                    "type": "string",
                                    "description": "Customer's email address",
                                },
                                "customer_phone": {
                                    "type": "string",
                                    "description": "Customer's phone number (with country code)",
                                },
                                "start_time": {
                                    "type": "string",
                                    "description": "Appointment time in ISO format (e.g., '2026-03-05T14:00:00+08:00')",
                                },
                                "property_name": {
                                    "type": "string",
                                    "description": "Property name or description (optional)",
                                },
                                "notes": {
                                    "type": "string",
                                    "description": "Additional notes about the appointment (optional)",
                                },
                                "duration_minutes": {
                                    "type": "integer",
                                    "description": "Duration in minutes (default 30)",
                                },
                            },
                            "required": ["start_time"],
                        },
                    },
                ]
            )

        # Escalation/Handover functions
        functions.append(
            {
                "name": "escalate_to_human",
                "description": "Transfer conversation to human agent when customer needs personal assistance, has complex questions, or requests to speak with sales/support team",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Reason for escalation (e.g., 'Customer wants pricing negotiation', 'Complex technical question')",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "urgent"],
                            "description": "Escalation priority (default: medium)",
                        },
                        "customer_context": {
                            "type": "string",
                            "description": "Summary of conversation and customer's needs (optional)",
                        },
                    },
                    "required": ["reason"],
                },
            }
        )

        # Knowledge base search
        functions.append(
            {
                "name": "search_knowledge",
                "description": "Search the business knowledge base for information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (default 5)",
                        },
                    },
                    "required": ["query"],
                },
            }
        )

        # Calculator function
        functions.append(
            {
                "name": "calculate",
                "description": "Evaluate a mathematical expression (e.g., '150 * 1.06')",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "The math expression to calculate",
                        }
                    },
                    "required": ["expression"],
                },
            }
        )

        # CRM functions
        functions.extend([
            {
                "name": "search_customer",
                "description": "Search for a customer or lead by name or phone",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Name or phone number to search"}
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "add_crm_lead",
                "description": "Add a new lead to the CRM",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Customer name"},
                        "phone": {"type": "string", "description": "Customer phone number"},
                        "details": {"type": "string", "description": "Additional details about the lead"}
                    },
                    "required": ["name", "phone"],
                },
            },
            {
                # Web access tool — works regardless of LLM provider.
                # Uses httpx to GET a URL and returns the text content
                # (HTML stripped to plain text). Useful for "what's on this
                # page?" / "check this link" requests.
                "name": "fetch_url",
                "description": (
                    "Fetch the content of a public URL and return it as plain "
                    "text. Use this when the customer shares a link and asks "
                    "what it is, or when you need to look up information from a "
                    "web page. Supports http and https. Max response size is "
                    "limited to keep payloads small. Will not follow redirects "
                    "to private (auth-required) URLs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The full URL to fetch (must start with http:// or https://)",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum number of characters to return (default 8000, max 32000)",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                # Web search tool — uses DuckDuckGo HTML (no API key needed).
                # Returns the top search results as title + URL + snippet.
                "name": "web_search",
                "description": (
                    "Search the public web using DuckDuckGo. Returns up to 5 "
                    "results with title, URL, and a short snippet. Use this when "
                    "the customer asks a question that requires current or general "
                    "knowledge (news, prices, businesses, facts)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query (e.g., 'best ramen KL 2026')",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 5, max 10)",
                        },
                    },
                    "required": ["query"],
                },
            },
        ])

        # Long-tail actions served via the connector layer (Composio-backed).
        # Native/critical actions are already declared above; we only surface the
        # COMPOSIO_ONLY breadth here, using Gemini-safe names (dots -> underscores).
        if self.composio_enabled:
            self._ensure_connectors()
            from src.connectors.base import Policy
            existing = {f["name"] for f in functions}
            for gemini_name, canonical in self._connector_fn_map.items():
                action = self._registry[canonical]
                if action.policy is not Policy.COMPOSIO_ONLY:
                    continue
                if gemini_name in existing:
                    continue
                functions.append({
                    "name": gemini_name,
                    "description": action.description,
                    "parameters": action.input_schema,
                })

        # 2026-08-22/23 FEATURE: per-tenant tool gating. `enabled_tools` is
        # written into client_configs on every signup (auth_api.py) but was
        # NEVER read anywhere — every tenant got the identical global tool
        # set, gated only by process-wide env flags. CORRECTNESS CONSTRAINT:
        # every existing tenant has enabled_tools=[] (empty) — empty/None
        # MUST mean "all tools enabled" (today's behavior unchanged), never
        # "no tools." Only a genuinely non-empty list restricts the set.
        if enabled_tools:
            functions = [f for f in functions if f["name"] in enabled_tools]

        return functions

    def get_openai_tools(self, enabled_tools: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Return function declarations in OpenAI tools format.

        OpenAI's tools schema wraps each Gemini declaration in
        {"type": "function", "function": {...}}. The inner shape is
        otherwise identical (name, description, parameters with type/object
        + properties + required), so this is a near-mechanical conversion.
        OpenAI-compatible providers (MiniMax, OpenAI, Groq, Together, etc.)
        all accept this format.
        """
        out: List[Dict[str, Any]] = []
        for fn in self.get_function_declarations(enabled_tools=enabled_tools):
            out.append({
                "type": "function",
                "function": {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                },
            })
        return out

    async def call_with_openai_tools(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.minimax.io/v1",
        max_iterations: int = 5,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        user_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Drive an OpenAI-compatible chat completion with function calling.

        Sends the conversation; if the model returns tool_calls, dispatches
        each via _call_function, sends the results back, and loops. Stops
        when the model returns a plain text response (no tool_calls) or
        after max_iterations tool rounds (defensive cap so a runaway model
        can't loop forever).

        The returned string is the final assistant content (stripped of
        any <think>...</think> leaks from MiniMax M2.7).

        Compatibility: works with any OpenAI-compatible endpoint that
        supports the `tools` parameter — MiniMax M3, OpenAI gpt-4o-mini,
        Groq, Together, etc. Tested against MiniMax.
        """
        from openai import OpenAI
        import re as _re

        if not api_key:
            raise ValueError("call_with_openai_tools: api_key is required")
        if user_context is None:
            user_context = {}

        client = OpenAI(base_url=base_url, api_key=api_key)
        # Per-tenant tool gating (see get_function_declarations) — caller
        # threads the tenant's client_config.enabled_tools through user_context.
        tools = self.get_openai_tools(enabled_tools=user_context.get("enabled_tools")) or None

        for _round in range(max_iterations):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                logger.error(f"❌ OpenAI-compat call failed for {model}: {e}")
                # Re-raise so the caller can decide whether to fall through
                # to another provider.
                raise

            if not resp.choices:
                logger.warning(f"⚠️ {model} returned no choices")
                return ""
            msg = resp.choices[0].message

            # If no tool_calls, we have the final answer.
            if not getattr(msg, "tool_calls", None):
                content = (msg.content or "").strip()
                # Strip MiniMax M2.7 <think>...</think> leaks (M3 doesn't emit them).
                content = _re.sub(r"<think>.*?</think>\s*", "", content, flags=_re.DOTALL).strip()
                if content:
                    logger.info(
                        f"✅ Response via {model} (round {_round + 1}) "
                        f"[{len(content)} chars]"
                    )
                return content

            # Otherwise: append the assistant message (with tool_calls),
            # execute each tool, and feed the results back.
            tool_calls = msg.tool_calls
            messages.append(msg)  # OpenAI SDK serializes this for the next call
            logger.info(
                f"🔧 {model} requested {len(tool_calls)} tool call(s): "
                + ", ".join(tc.function.name for tc in tool_calls)
            )

            for tc in tool_calls:
                name = tc.function.name
                raw_args = tc.function.arguments or "{}"
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except Exception as parse_err:
                    logger.warning(
                        f"⚠️ {model} sent unparseable args for {name}: {raw_args!r} ({parse_err})"
                    )
                    args = {}

                # 2026-08-22 FIX: this loop is the MiniMax/OpenAI-compatible
                # tool-call path — currently the PRIMARY provider (Gemini is
                # suspended, see the "PRIMARY" note in bijou.py's model
                # routing). It called _call_function directly, skipping the
                # is_destructive_action()/pending_confirmations gate that
                # _execute_function (the Gemini-native path) already has —
                # so every send_email/delete_email/create_calendar_event/etc.
                # tool call went straight through with no confirmation step
                # on the path actually in use. Mirror the same gate here.
                if self.enable_confirmations and self.is_destructive_action(name):
                    confirmation_id = f"{user_context.get('chat_jid', 'unknown')}_{datetime.now().timestamp()}"
                    self.pending_confirmations[confirmation_id] = {
                        "function_name": name,
                        "args": args,
                        "chat_jid": user_context.get("chat_jid"),
                        "timestamp": datetime.now().isoformat(),
                    }
                    result = {
                        "status": "pending_confirmation",
                        "confirmation_id": confirmation_id,
                        "message": self._get_confirmation_message(name, args),
                    }
                else:
                    try:
                        result = await self._call_function(name, args, user_context)
                    except Exception as tool_err:
                        logger.error(f"❌ Tool {name} raised: {tool_err}")
                        result = {"success": False, "error": str(tool_err)}

                # OpenAI requires the tool message to echo the tool_call_id
                # and to have a string content (not a dict).
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(result, default=str)[:32000],
                })

        logger.warning(f"⚠️ {model} hit max_iterations={max_iterations} without a final text reply")
        # Try to extract the last assistant content if present, else give up.
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("content"):
                return (m["content"] or "").strip()
        return "[tool-calling loop reached the iteration limit without a final answer]"

    # =========================================================================
    # WEB TOOLS (provider-agnostic, no API key required)
    # =========================================================================
    # The agent had no way to open URLs or search the public web — those
    # capabilities were missing entirely. fetch_url and web_search are the
    # minimum needed for "what's on this page?" and "look this up for me"
    # requests. They are declared as Gemini function declarations and will
    # be added to MiniMax tool-calling when that is implemented.

    async def _web_fetch_url(self, url: str, max_chars: int = 8000) -> Dict[str, Any]:
        """
        Fetch a public URL and return its text content.

        Strips HTML to plain text using a simple regex-based approach (no
        external deps). Keeps payload small by capping at max_chars (default
        8000, max 32000). Refuses non-http(s) schemes and private IPs to
        prevent SSRF.
        """
        import re
        import socket
        from urllib.parse import urlparse

        # 1. Validate URL shape
        try:
            parsed = urlparse(url)
        except Exception:
            return {"success": False, "error": f"Invalid URL: {url}"}
        if parsed.scheme not in ("http", "https"):
            return {"success": False, "error": f"Unsupported scheme: {parsed.scheme}"}
        if not parsed.netloc:
            return {"success": False, "error": "URL is missing a host"}

        # 2. SSRF guard: refuse to fetch private/loopback IPs
        try:
            host = parsed.hostname or ""
            # Resolve to IP and check
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                ip = info[4][0]
                if (ip.startswith("127.") or ip.startswith("10.") or
                    ip.startswith("192.168.") or ip.startswith("169.254.") or
                    ip.startswith("0.") or ip == "::1" or
                    ip.startswith("fc") or ip.startswith("fd")):
                    return {"success": False, "error": "Refusing to fetch private/internal IP"}
        except socket.gaierror:
            return {"success": False, "error": f"Could not resolve host: {host}"}

        # 3. Fetch with timeout + size cap
        max_chars = max(500, min(int(max_chars or 8000), 32000))
        try:
            import httpx
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                max_redirects=3,
                headers={"User-Agent": "BijouAgent/1.0 (+https://mybijou.xyz)"},
            ) as client:
                r = await client.get(url)
                ct = (r.headers.get("content-type") or "").lower()
                if r.status_code != 200:
                    return {"success": False, "error": f"HTTP {r.status_code}", "url": url}
                # Cap raw bytes at 2MB to avoid huge responses
                body = r.text[: 2 * 1024 * 1024]

                # If HTML, strip to plain text
                if "html" in ct or body.lstrip().startswith(("<!DOCTYPE", "<html", "<HTML")):
                    # Drop script + style blocks
                    body = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.DOTALL | re.IGNORECASE)
                    body = re.sub(r"<style\b[^>]*>.*?</style>", " ", body, flags=re.DOTALL | re.IGNORECASE)
                    # Strip tags
                    body = re.sub(r"<[^>]+>", " ", body)
                    # Decode common entities
                    body = (body
                        .replace("&nbsp;", " ")
                        .replace("&amp;", "&")
                        .replace("&lt;", "<")
                        .replace("&gt;", ">")
                        .replace("&quot;", '"')
                        .replace("&#39;", "'"))
                    # Collapse whitespace
                    body = re.sub(r"\s+", " ", body).strip()
                text = body[:max_chars]
                return {
                    "success": True,
                    "url": url,
                    "final_url": str(r.url),
                    "content_type": ct,
                    "status": r.status_code,
                    "length": len(text),
                    "truncated": len(body) > max_chars,
                    "text": text,
                }
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    async def _web_search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Search the public web via DuckDuckGo HTML (no API key required).

        Returns the top max_results with title, URL, and snippet. Use this
        when the LLM needs fresh public information (news, prices, business
        listings, etc.). Fallback chain: DDG HTML -> empty result.
        """
        import re
        import urllib.parse

        max_results = max(1, min(int(max_results or 5), 10))
        try:
            import httpx
            # DuckDuckGo HTML endpoint (no key required, returns HTML)
            url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 BijouAgent/1.0"},
            ) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    return {"success": False, "error": f"DDG HTTP {r.status_code}", "results": []}
                html = r.text

                # Parse result blocks. DDG HTML uses result__a for title+href
                # and result__snippet for the text snippet. We extract the
                # first max_results blocks.
                # Find <a class="result__a" href="...">TITLE</a>
                link_re = re.compile(
                    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                    re.DOTALL | re.IGNORECASE,
                )
                # Find <a class="result__snippet" ...>SNIPPET</a> or <td class="result__snippet">SNIPPET</td>
                snip_re = re.compile(
                    r'class="result__snippet"[^>]*>(.*?)</(?:a|td)>',
                    re.DOTALL | re.IGNORECASE,
                )
                links = link_re.findall(html)
                snippets = snip_re.findall(html)
                results = []
                for i, (href, title_html) in enumerate(links[:max_results]):
                    title = re.sub(r"<[^>]+>", "", title_html).strip()
                    # DDG wraps real URLs in /l/?uddg=<base64> — un-wrap
                    if "uddg=" in href:
                        m = re.search(r"uddg=([^&]+)", href)
                        if m:
                            href = urllib.parse.unquote(m.group(1))
                    snippet = ""
                    if i < len(snippets):
                        snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
                    results.append({"title": title, "url": href, "snippet": snippet})
                return {"success": True, "query": query, "count": len(results), "results": results}
        except Exception as e:
            return {"success": False, "error": str(e), "query": query, "results": []}

    def is_destructive_action(self, function_name: str) -> bool:
        """
        Check if a function is destructive (requires confirmation).

        Args:
            function_name: Name of the function

        Returns:
            True if destructive
        """
        destructive_functions = [
            "send_email",
            "delete_email",
            "create_calendar_event",
            "delete_calendar_event",
            "update_calendar_event",
        ]
        return function_name in destructive_functions

    async def detect_and_execute(
        self, message: str, chat_jid: str, user_context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if message requires function calling and execute.

        Args:
            message: User message
            chat_jid: Chat JID
            user_context: Optional user context

        Returns:
            Execution result dict or None if no function detected
        """
        if not self.enabled:
            return None

        try:
            from google.genai import types

            # Get function declarations
            functions = self.get_function_declarations()

            if not functions:
                logger.debug("No functions available for calling")
                return None

            # Create tools config
            tools = [types.Tool(function_declarations=functions)]

            # Call Gemini with function calling
            response = self.genai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=message,
                config=types.GenerateContentConfig(
                    tools=tools,
                    temperature=0.3,  # Lower temperature for function calling
                ),
            )

            # Check if function was called
            if not response.candidates:
                return None

            candidate = response.candidates[0]
            if not hasattr(candidate, "function_calls") or not candidate.function_calls:
                return None

            # Execute function calls
            results = []
            for function_call in candidate.function_calls:
                result = await self._execute_function(
                    function_call, chat_jid, user_context
                )
                results.append(result)

            return {"function_calls": results, "requires_confirmation": False}

        except Exception as e:
            logger.error(f"Error in function calling: {e}")
            return None

    async def _execute_function(
        self,
        function_call: Any,
        chat_jid: str,
        user_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a single function call.

        Args:
            function_call: Function call from Gemini
            chat_jid: Chat JID
            user_context: User context

        Returns:
            Execution result
        """
        function_name = function_call.name
        args = dict(function_call.args)

        logger.info(f"🔧 Executing function: {function_name} with args: {args}")

        # Check if destructive and needs confirmation
        if self.enable_confirmations and self.is_destructive_action(function_name):
            # Store pending confirmation
            confirmation_id = f"{chat_jid}_{datetime.now().timestamp()}"
            self.pending_confirmations[confirmation_id] = {
                "function_name": function_name,
                "args": args,
                "chat_jid": chat_jid,
                "timestamp": datetime.now().isoformat(),
            }

            return {
                "function": function_name,
                "args": args,
                "status": "pending_confirmation",
                "confirmation_id": confirmation_id,
                "message": self._get_confirmation_message(function_name, args),
            }

        # Execute function
        try:
            result = await self._call_function(function_name, args, user_context)
            return {
                "function": function_name,
                "args": args,
                "status": "success",
                "result": result,
            }
        except Exception as e:
            logger.error(f"Error executing {function_name}: {e}")
            return {
                "function": function_name,
                "args": args,
                "status": "error",
                "error": str(e),
            }

    async def _call_function(
        self, function_name: str, args: Dict[str, Any], user_context: Optional[Dict]
    ) -> Any:
        """
        Actually call the function.

        Args:
            function_name: Name of function
            args: Function arguments
            user_context: User context

        Returns:
            Function result
        """
        # Connector-routed actions (multi-backend: native + Composio). Checked
        # first so new long-tail tools never collide with the native branches
        # below, and so a Composio outage degrades gracefully instead of raising.
        if self.composio_enabled:
            self._ensure_connectors()
            canonical = self._connector_fn_map.get(function_name)
            if canonical is not None:
                tenant_id = (user_context or {}).get("tenant_id")
                result = await self._router.execute(tenant_id, canonical, args, self._registry)
                return {
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                    "backend": result.backend,
                    "user_message": result.user_message,
                }

        # Email functions
        if function_name == "send_email":
            if not self.tool_orchestrator.gmail_tool:
                raise ValueError("Gmail tool not available")
            return self.tool_orchestrator.gmail_tool.send_email(
                to=args["to"], subject=args["subject"], body=args["body"]
            )

        elif function_name == "search_email":
            if not self.tool_orchestrator.gmail_tool:
                raise ValueError("Gmail tool not available")
            return self.tool_orchestrator.gmail_tool.search_emails(
                query=args["query"], max_results=args.get("max_results", 10)
            )

        # Calendar availability check (multi-tenant)
        elif function_name == "check_availability":
            if not self.tool_orchestrator.tenant_calendar_service:
                raise ValueError("Calendar service not available")

            tenant_id = user_context.get("tenant_id") if user_context else None
            if not tenant_id:
                raise ValueError("Tenant ID required for calendar check")

            # 2026-08-22 FIX: this used to hand-roll a fresh CalendarTool with
            # only cal_api_key/cal_username (never checking OAuth), and then
            # treated get_availability()'s return dict ({"success", "slots":
            # {<date>: [...]}, "busy": [...]}) as if IT were the slots list —
            # `bool(slots)` was always True and `len(slots)` always counted
            # the dict's fixed top-level keys, not real slot counts, so the
            # AI always told customers "Found 3 available slot(s)" regardless
            # of actual availability. TenantCalendarService.check_availability()
            # already does this correctly (OAuth-or-API-key, real result) —
            # delegate to it instead of duplicating (and getting wrong) the
            # same logic here.
            try:
                date_from = args["date_from"]
                date_to = args.get("date_to", date_from)
                result = self.tool_orchestrator.tenant_calendar_service.check_availability(
                    tenant_id=tenant_id, date_from=date_from, date_to=date_to
                )
                if not result.get("success"):
                    return {
                        "available": False,
                        "error": result.get("error"),
                        "message": "Could not check calendar availability. Please ask the customer to contact the office directly."
                    }
                slots_by_date = result.get("slots") or {}
                flat_slots = [s for day_slots in slots_by_date.values() for s in (day_slots or [])]
                return {
                    "available": bool(flat_slots),
                    "slots": slots_by_date,
                    "message": f"Found {len(flat_slots)} available slot(s)" if flat_slots else "No available slots for this date"
                }
            except Exception as e:
                logger.error(f"Calendar availability check failed: {e}")
                return {
                    "available": False,
                    "error": str(e),
                    "message": "Could not check calendar availability. Please ask the customer to contact the office directly."
                }

        # Calendar booking (multi-tenant)
        elif function_name == "book_appointment":
            if not self.tool_orchestrator.tenant_calendar_service:
                raise ValueError("Calendar service not available")

            # Get tenant_id from user_context
            tenant_id = user_context.get("tenant_id") if user_context else None
            if not tenant_id:
                raise ValueError("Tenant ID required for calendar booking")

            return self.tool_orchestrator.tenant_calendar_service.create_booking(
                tenant_id=tenant_id,
                customer_name=args["customer_name"],
                customer_email=args["customer_email"],
                customer_phone=args["customer_phone"],
                start_time=args["start_time"],
                property_name=args.get("property_name"),
                notes=args.get("notes"),
                duration_minutes=args.get("duration_minutes", 30),
            )

        # Escalation/Handover
        elif function_name == "escalate_to_human":
            # Get user context
            chat_jid = user_context.get("chat_jid") if user_context else None
            tenant_id = user_context.get("tenant_id") if user_context else None

            if not chat_jid or not tenant_id:
                raise ValueError("Chat JID and Tenant ID required for escalation")

            # Create escalation via HandoverSystem
            try:
                # 2026-08-22 FIX: ToolOrchestrator never actually sets a
                # `handover_system` attribute (confirmed: grep across
                # tool_orchestrator.py has no such assignment), so the
                # hasattr() check was always False and this always fell
                # into `HandoverSystem()` with no supabase_client — which
                # makes create_escalation() unconditionally return None
                # (handover_system.py: `if not self.enabled or not
                # self.supabase: return None`). Pass the orchestrator's own
                # supabase_client through so a real client actually gets
                # written when ENABLE_HANDOVER_QUEUE is on.
                if self.tool_orchestrator and getattr(self.tool_orchestrator, 'handover_system', None):
                    handover = self.tool_orchestrator.handover_system
                else:
                    from src.saas.handover_system import HandoverSystem
                    handover = HandoverSystem(
                        supabase_client=getattr(self.tool_orchestrator, 'supabase_client', None)
                    )

                escalation_id = await handover.create_escalation(
                    tenant_id=tenant_id,
                    chat_jid=chat_jid,
                    reason=args["reason"],
                    priority=args.get("priority", "medium"),
                    metadata={"customer_context": args.get("customer_context", "")},
                )

                # 2026-08-22 FIX: this used to unconditionally claim success
                # even when create_escalation() returned None (handover
                # disabled via ENABLE_HANDOVER_QUEUE, or no supabase client)
                # — the AI would tell a real customer "escalated to a human"
                # when nothing was created and nobody was notified. Only
                # claim success if a row actually got created.
                if not escalation_id:
                    logger.error(
                        f"Escalation returned no id for tenant {tenant_id} "
                        f"(handover disabled or misconfigured) — not claiming success"
                    )
                    return {
                        "success": False,
                        "error": "Escalation is not available right now. Please leave your contact details and the team will reach out.",
                    }

                return {
                    "success": True,
                    "escalation_id": escalation_id,
                    "message": "Escalated to human agent successfully",
                }
            except Exception as e:
                logger.error(f"Escalation failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                }

        # Knowledge base search
        elif function_name == "search_knowledge":
            # 2026-08-22 FIX: this used to return a fake positive-looking
            # result ("Search functionality coming soon" dressed up as a
            # real search hit). Now does a real (simple ILIKE, not semantic)
            # search against knowledge_documents — the table the rest of the
            # chat pipeline's context-builder actually reads
            # (KnowledgeUploader.get_combined_knowledge, knowledge_upload.py)
            # and the wizard now writes to (kb_templates_api.py). Not vector
            # search — knowledge_chunks/vector_search.py exists for that but
            # nothing populates it; this is the honest minimum that returns
            # real content instead of nothing or a fake stub.
            tenant_id = user_context.get("tenant_id") if user_context else None
            if not tenant_id or not self.tool_orchestrator or not getattr(self.tool_orchestrator, "supabase_client", None):
                return {
                    "success": False,
                    "results": [],
                    "message": "Knowledge base search is not available (no tenant context).",
                }
            try:
                query = args["query"]
                max_results = min(int(args.get("max_results") or 5), 20)
                rows = (
                    self.tool_orchestrator.supabase_client.table("knowledge_documents")
                    .select("filename, content_extracted")
                    .eq("tenant_id", tenant_id)
                    .ilike("content_extracted", f"%{query}%")
                    .limit(max_results)
                    .execute()
                )
                results = [
                    {"title": r.get("filename") or "Untitled", "content": (r.get("content_extracted") or "")[:2000]}
                    for r in (rows.data or [])
                ]
                return {
                    "success": True,
                    "results": results,
                    "message": f"Found {len(results)} result(s)" if results else "No matching knowledge found",
                }
            except Exception as e:
                logger.error(f"search_knowledge failed: {e}")
                return {"success": False, "results": [], "error": str(e)}

        # Calculator
        elif function_name == "calculate":
            if not self.tool_orchestrator.calculator_tool:
                raise ValueError("Calculator tool not available")
            return self.tool_orchestrator.calculator_tool.calculate(args["expression"])

        # CRM
        elif function_name == "search_customer":
            if not self.tool_orchestrator.crm_tool:
                raise ValueError("CRM tool not available")
            return self.tool_orchestrator.crm_tool.search_customer(args["query"])

        elif function_name == "add_crm_lead":
            if not self.tool_orchestrator.crm_tool:
                raise ValueError("CRM tool not available")
            return self.tool_orchestrator.crm_tool.add_lead(
                name=args["name"],
                phone=args["phone"],
                details=args.get("details")
            )

        # Web: fetch a URL and return its text content. Provider-agnostic.
        elif function_name == "fetch_url":
            return await self._web_fetch_url(
                url=args["url"],
                max_chars=int(args.get("max_chars") or 8000),
            )

        # Web: search the public web via DuckDuckGo HTML (no API key).
        elif function_name == "web_search":
            return await self._web_search(
                query=args["query"],
                max_results=int(args.get("max_results") or 5),
            )

        # Reminder
        elif function_name == "set_reminder":
            # Placeholder - integrate with reminder system
            return {
                "status": "scheduled",
                "message": args["message"],
                "time": args["time"],
            }

        else:
            raise ValueError(f"Unknown function: {function_name}")

    def _get_confirmation_message(
        self, function_name: str, args: Dict[str, Any]
    ) -> str:
        """
        Generate confirmation message for destructive action.

        Args:
            function_name: Function name
            args: Function arguments

        Returns:
            Confirmation message
        """
        if function_name == "send_email":
            return (
                f"📧 **Confirm Email**\n\n"
                f"To: {args['to']}\n"
                f"Subject: {args['subject']}\n"
                f"Body: {args['body'][:100]}...\n\n"
                f"Reply 'yes' to send or 'no' to cancel."
            )

        elif function_name == "create_calendar_event":
            return (
                f"📅 **Confirm Calendar Event**\n\n"
                f"Title: {args['title']}\n"
                f"Start: {args['start_time']}\n"
                f"End: {args.get('end_time', 'Not specified')}\n\n"
                f"Reply 'yes' to create or 'no' to cancel."
            )

        else:
            return (
                f"⚠️ **Confirm Action**\n\n"
                f"Function: {function_name}\n"
                f"Arguments: {json.dumps(args, indent=2)}\n\n"
                f"Reply 'yes' to proceed or 'no' to cancel."
            )

    async def confirm_action(
        self, confirmation_id: str, confirmed: bool
    ) -> Dict[str, Any]:
        """
        Confirm or deny a pending action.

        Args:
            confirmation_id: Confirmation ID
            confirmed: True to confirm, False to cancel

        Returns:
            Execution result
        """
        if confirmation_id not in self.pending_confirmations:
            return {"status": "error", "error": "Confirmation not found or expired"}

        pending = self.pending_confirmations.pop(confirmation_id)

        if not confirmed:
            return {
                "status": "cancelled",
                "function": pending["function_name"],
                "message": "Action cancelled by user",
            }

        # Execute the function
        try:
            result = await self._call_function(
                pending["function_name"], pending["args"], None
            )
            return {
                "status": "success",
                "function": pending["function_name"],
                "result": result,
            }
        except Exception as e:
            return {
                "status": "error",
                "function": pending["function_name"],
                "error": str(e),
            }

    def get_stats(self) -> Dict[str, Any]:
        """Get function caller statistics"""
        return {
            "enabled": self.enabled,
            "confirmations_enabled": self.enable_confirmations,
            "pending_confirmations": len(self.pending_confirmations),
            "available_functions": len(self.get_function_declarations()),
        }
