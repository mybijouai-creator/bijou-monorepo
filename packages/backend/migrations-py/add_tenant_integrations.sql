-- Migration: tenant_integrations table for Nango-managed OAuth connections
-- Date: 2026-08-23
--
-- Replaces the never-launched Composio scaffold (src/connectors/oauth_api.py,
-- src/connectors/auth_configs.py — ENABLE_COMPOSIO was never set in
-- production, zero COMPOSIO_AUTH_ID_* secrets configured, router never
-- mounted) with Nango (nango.dev), which handles OAuth + token refresh for
-- each tenant's connected third-party account. Nango itself stores the OAuth
-- tokens; this table only records, per tenant, which integration is
-- connected and under which Nango connection_id, so the backend can look up
-- the right connection_id to call Nango's proxy on the tenant's behalf.
CREATE TABLE IF NOT EXISTS tenant_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    integration_id TEXT NOT NULL,       -- Nango "Provider-Config-Key", e.g. 'google-calendar'
    connection_id TEXT NOT NULL,        -- Nango "Connection-Id"
    status TEXT DEFAULT 'connected',
    connected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, integration_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_integrations_tenant_id ON tenant_integrations (tenant_id);
