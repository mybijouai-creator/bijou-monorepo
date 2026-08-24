"""
Bijou AI — Email Templates (Python port)
========================================

Python mirror of `bijou_templates/email-templates/` (the JS source of truth).

This package provides:
  1. The **shared shell** (BRAND constants + header/footer/wrap helpers)
  2. The **10 transactional builders** ported line-for-line from JS

Both share the Signal Gem 2026 brand tokens so any Python caller can produce
an email that matches the JS-rendered output (modulo whitespace).

Brand tokens (canonical — mirror of `--bj-*` in CSS):
  BJ_GREEN = #0B3B2E
  BJ_GOLD  = #E3B457
  BJ_CREAM = #F7F4EC
  BJ_INK   = #0A0A0A

Public API:
  BRAND              — dict of brand constants
  email_header(...)  — render the Signal Gem header row
  email_footer(...)  — render the Signal Gem footer row
  email_wrap(...)    — render the full <html> document
  cta_button(...)    — render a Signal Gem gold CTA
  divider            — horizontal divider row (str)
  support_row(...)   — "Need help?" contact block

  # Transactional builders (the 10 specific email types)
  build_email_verification(name, verify_url, expiry_mins=30)
  build_welcome_trial_start(name, business_name, trial_ends=None)
  build_trial_expiry_warning(name, days_left, trial_ends, upgrade_url=None)
  build_trial_expired(name, upgrade_url=None, grace_days=3)
  build_payment_confirmation(name, plan, amount, invoice_id, billing_date, next_billing, invoice_url=None)
  build_dashboard_access(name, business_name, plan, login_url=None)
  build_internal_signup_notify(name, email, phone=None, company=None, industry=None, source=None, plan=None, time=None, supabase_url=None)
  build_magic_link_login(name, magic_url, expiry_mins=15, ip_hint=None, device_hint=None)
  build_escalation_agent_notification(agent_name, customer_name, customer_phone, issue, escalation_id, chat_snippet=None, priority="high", response_url=None, time=None)
  build_settings_test_email(name, smtp_host=None, email_from=None, time=None)

If the JS source changes, port the change to `transactional.py` too. The 1:1
mapping is the only way to keep the customer-facing brand consistent across
Vercel (landing's preview.mjs) and Fly.io (email_service.py).
"""

from .base import (
    BRAND,
    email_header,
    email_footer,
    email_wrap,
    cta_button,
    divider,
    support_row,
)

from .transactional import (
    build_email_verification,
    build_welcome_trial_start,
    build_trial_expiry_warning,
    build_trial_expired,
    build_payment_confirmation,
    build_dashboard_access,
    build_internal_signup_notify,
    build_magic_link_login,
    build_escalation_agent_notification,
    build_settings_test_email,
)

__all__ = [
    "BRAND",
    "email_header",
    "email_footer",
    "email_wrap",
    "cta_button",
    "divider",
    "support_row",
    "build_email_verification",
    "build_welcome_trial_start",
    "build_trial_expiry_warning",
    "build_trial_expired",
    "build_payment_confirmation",
    "build_dashboard_access",
    "build_internal_signup_notify",
    "build_magic_link_login",
    "build_escalation_agent_notification",
    "build_settings_test_email",
]
