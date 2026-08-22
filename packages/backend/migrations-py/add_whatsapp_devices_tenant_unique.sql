-- Migration: unique constraint on whatsapp_devices.tenant_id
-- Date: 2026-08-22
--
-- Root cause: three call sites (onboarding_api.py provision-on-demand,
-- bijou.py send-message auto-discovery cache, dashboard_api_simple.py
-- auto-discovery cache) all upsert into whatsapp_devices with
-- on_conflict="tenant_id", assuming "one device row per tenant". But the
-- only constraint ever added on this table (add_whatsapp_device_mapping.sql)
-- is UNIQUE on device_id, not tenant_id. Postgres requires ON CONFLICT to
-- target a column backed by a real unique/exclusion constraint (error
-- 42P10) — every one of those upserts has been silently failing (caught by
-- a bare except and logged as a warning), so the device_id -> tenant_id
-- mapping this table exists to hold has never actually been persisted.
-- Downstream effect: the WhatsApp-connected webhook can't resolve tenant_id
-- for on-demand-provisioned devices (whose device_id isn't the predictable
-- bijou-{tenant_id} format), so onboarding never flips to "connected" even
-- after a real scan.
--
-- Step 1: collapse any pre-existing duplicate tenant_id rows (defensive —
-- given the upserts always errored, there should be at most one row per
-- tenant already, but don't assume it). Keep the newest row per tenant.
DELETE FROM whatsapp_devices a
USING whatsapp_devices b
WHERE a.tenant_id = b.tenant_id
  AND a.id <> b.id
  AND (a.updated_at, a.id) < (b.updated_at, b.id);

-- Step 2: add the constraint the three call sites already assume exists.
ALTER TABLE whatsapp_devices
  ADD CONSTRAINT uq_whatsapp_devices_tenant UNIQUE (tenant_id);
