"""Tenant config — read tenant + KB from Bijou Supabase.

Voice concierge needs to know:
- Is this phone number a known Bijou tenant? (resolve to tenant_id)
- What's the tenant's business name, KB docs, escalation rules?

This is the "where am I" lookup the voice orchestrator does at call
pickup. We read from the same Bijou Supabase backend that the
WhatsApp agent uses, so a tenant's config stays in one place.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from supabase import Client, create_client
import asyncio
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def _async(fn: Callable[[], T]) -> T:
    return await asyncio.to_thread(fn)


class TenantConfig(BaseModel):
    """Snapshot of a tenant's voice-relevant config."""
    id: str
    business_name: str
    whatsapp_jid: Optional[str] = None
    whatsapp_connected_at: Optional[str] = None
    plan: Optional[str] = None
    # Computed: the Telnyx phone number this tenant wants voice calls to land on
    # (from the bij_voice_numbers table, set by the admin)
    voice_number: Optional[str] = None


class TenantConfigClient:
    """Read tenant + voice config from Bijou Supabase.

    The voice service should NEVER write to the tenants table — that's
    the WhatsApp agent's job. This client is read-only on tenants, with
    one optional write to bij_voice_numbers when an admin assigns a Telnyx
    number to a tenant.
    """

    def __init__(self, supabase_url: str, supabase_service_key: str):
        if not supabase_url or not supabase_service_key:
            raise ValueError("TenantConfigClient requires SUPABASE_URL and SUPABASE_SERVICE_KEY")
        self._sb: Client = create_client(supabase_url, supabase_service_key)

    async def resolve_tenant_by_phone(self, phone_e164: str) -> Optional[TenantConfig]:
        """Look up a tenant by the Telnyx number the caller dialed.

        Returns None if no tenant owns that number (caller hit a dead line).
        The voice service plays a polite "we don't recognize this number"
        in that case (see AGENT.md "Failure modes" table).
        """
        def _query():
            return (
                self._sb.table("bij_voice_numbers")
                .select("tenant_id, tenants(id, business_name, whatsapp_jid, plan)")
                .eq("phone_e164", phone_e164)
                .eq("enabled", True)
                .limit(1)
                .execute()
            )
        result = await _async(_query)
        rows = result.data or []
        if not rows:
            return None
        row = rows[0]
        t = row.get("tenants") or {}
        if not t:
            return None
        return TenantConfig(
            id=t["id"],
            business_name=t.get("business_name", ""),
            whatsapp_jid=t.get("whatsapp_jid"),
            plan=t.get("plan"),
            voice_number=phone_e164,
        )

    async def get_kb_documents(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Return the tenant's KB documents (titles + storage_path) for the LLM.

        The voice orchestrator streams these to the LLM's context window.
        We don't load the full text here — the LLM gateway streams it on
        demand. We just return the manifest.
        """
        def _query():
            return (
                self._sb.table("kb_documents")
                .select("id, title, storage_path, created_at")
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=True)
                .execute()
            )
        result = await _async(_query)
        return list(result.data or [])


_client: Optional[TenantConfigClient] = None


def get_tenant_config_client() -> TenantConfigClient:
    import os
    global _client
    if _client is None:
        _client = TenantConfigClient(
            supabase_url=os.environ["SUPABASE_URL"],
            supabase_service_key=os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client
