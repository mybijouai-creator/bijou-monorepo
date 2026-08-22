-- ============================================================================
-- Add media columns to messages table — 2026-08-23
-- ============================================================================
--
-- Problem: The `messages` table has NO media columns at all. When a customer
-- sends a photo/voice note/document over WhatsApp, `bijou.py` downloads it,
-- runs it through Gemini/Deepgram, and stores only the AI's text summary
-- (e.g. "📸 Image: a receipt for RM45.20...") in `content`. A human agent who
-- takes over the chat in the dashboard can read that summary but can never
-- see the actual attachment — no photo, no audio player, no file link.
--
-- Fix: additive, nullable columns to persist the raw WhatsApp media
-- reference alongside the message. Populated only for inbound customer
-- messages that actually carry media (see bijou.py::_save_message); left
-- NULL for text-only messages and for the AI's own text reply.
--
-- Run this against the Supabase Postgres database (same one `messages`
-- already lives in — service-role key required, RLS blocks anon/authenticated).
-- ============================================================================

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS media_url TEXT;

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS media_type TEXT;

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS media_mime TEXT;

-- ============================================================================
-- Verification Queries (run these after migration)
-- ============================================================================

-- Confirm columns exist:
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'messages' AND column_name IN ('media_url', 'media_type', 'media_mime');

-- Sanity check on real data (should show NULL for text-only rows):
-- SELECT id, role, media_type, media_url FROM messages ORDER BY created_at DESC LIMIT 20;

-- ============================================================================
-- How to Run This Migration
-- ============================================================================
--
-- Via Supabase SQL Editor:
--   1. Copy the SQL above
--   2. Go to Supabase SQL Editor (project lrwzlujomukzjykafmic)
--   3. Paste and run
--
-- Via local psql (if you have the DB URL):
--   psql "postgres://..." -f migrations-py/add_message_media_columns.sql
-- ============================================================================
