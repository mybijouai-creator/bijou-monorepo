// services/posthog.ts
// Frontend PostHog wrapper. Single init, lazy-loaded SDK, typed event helpers.
// The project key is exposed via Vite's import.meta.env (VITE_POSTHOG_PROJECT_KEY).
// Host is exposed via VITE_POSTHOG_HOST (defaults to US Cloud).

import posthog from "posthog-js";
import type { PostHog } from "posthog-js";

const PROJECT_KEY = import.meta.env.VITE_POSTHOG_PROJECT_KEY as string | undefined;
const HOST = (import.meta.env.VITE_POSTHOG_HOST as string | undefined) || "https://us.i.posthog.com";

let initialized = false;

/**
 * Initialise PostHog on the client. Safe to call multiple times.
 * - No-op when VITE_POSTHOG_PROJECT_KEY is missing (e.g. local dev without the env var).
 * - Captures pageviews + pageleaves automatically.
 * - Survives SPA route changes.
 */
export function initPostHog(): void {
  if (initialized) return;
  if (!PROJECT_KEY) {
    if (import.meta.env.DEV) {
      console.info("[posthog] VITE_POSTHOG_PROJECT_KEY not set — analytics disabled.");
    }
    initialized = true; // mark as init'd to avoid retry spam
    return;
  }

  posthog.init(PROJECT_KEY, {
    api_host: HOST,
    // Capture pageview + pageleave on init
    capture_pageview: true,
    capture_pageleave: true,
    // Use a single shared session across page loads
    persistence: "localStorage+cookie",
    // Respect Do-Not-Track
    respect_dnt: true,
    // Bootstrap with safe defaults; identify() upgrades once we know who the user is.
    person_profiles: "identified_only",
    // We don't ship session recording UI yet — flip when we want.
    disable_session_recording: false,
    // Keep the SDK lean
    autocapture: true,
    // Named page events become the canonical funnel
    loaded: (ph) => {
      ph.register({
        app: "bijou-landing",
        env: import.meta.env.MODE,
      });
    },
  });

  initialized = true;
}

/**
 * Identify a user once we have an email or customer id.
 * Idempotent — safe to call on every render.
 */
export function identifyUser(
  userId: string,
  traits?: Record<string, unknown>,
): void {
  if (!initialized || !PROJECT_KEY) return;
  posthog.identify(userId, traits);
}

export function resetUser(): void {
  if (!initialized || !PROJECT_KEY) return;
  posthog.reset();
}

/**
 * Track a typed event. Use the EventName type to keep funnels in sync.
 */
export type EventName =
  // Top-of-funnel — landing
  | "landing_pageview"
  | "language_change"
  | "hero_cta_clicked"
  | "nav_signup_clicked"
  | "nav_menu_opened"
  // Modals
  | "signup_modal_opened"
  | "signup_modal_submitted"
  | "signup_modal_completed"
  | "signup_modal_failed"
  | "demo_modal_opened"
  | "demo_chat_message_sent"
  | "demo_chat_response_received"
  | "demo_booked"
  | "waitlist_modal_opened"
  | "waitlist_modal_submitted"
  | "lead_capture_form_submitted"
  | "lead_capture_form_failed"
  | "lead_capture_duplicate"
  | "lead_captured"
  // Conversion
  | "pricing_plan_clicked"
  | "checkout_started"
  | "checkout_completed"
  // Engagement
  | "cal_booking_opened"
  | "cal_booking_completed"
  | "whatsapp_cta_clicked"
  | "whatsapp_relay_sent"
  | "slide_deck_opened"
  | "slide_deck_downloaded"
  | "voice_waitlist_joined"
  | "spot_count_fetched"
  // Errors
  | "api_error"
  | "chat_error"
  // 2026-08-23: Changelog (issue #8)
  | "changelog_github_click"
  | "changelog_github_footer_click";

export function track(event: EventName, properties?: Record<string, unknown>): void {
  if (!initialized || !PROJECT_KEY) return;
  posthog.capture(event, properties);
}

export function isPostHogEnabled(): boolean {
  return initialized && Boolean(PROJECT_KEY);
}

/** Escape hatch for advanced usage (super-properties, feature flags, etc.). */
export function getPostHog(): PostHog | null {
  if (!initialized || !PROJECT_KEY) return null;
  return posthog;
}
