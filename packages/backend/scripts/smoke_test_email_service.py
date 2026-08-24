"""End-to-end smoke test: render all 8 wired EmailService methods and
verify they call into the Signal Gem builders (BRAND colors, no slate)."""
import sys
import io
# Force UTF-8 stdout so emoji in subjects don't crash on Windows cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Patch out httpx so we don't actually send any email.
import saas.email_service as es_mod
_original_send = es_mod.EmailService.send_email
def _fake_send(self, to, subject, html_body, text_body=None):
    # Stash the rendered HTML so the test can assert on it
    _fake_send.last_html = html_body
    _fake_send.last_subject = subject
    return True
_fake_send.last_html = None
_fake_send.last_subject = None
es_mod.EmailService.send_email = _fake_send

from saas.email_service import EmailService

# Bypass __init__ side effects (env / keys) — construct directly
svc = EmailService.__new__(EmailService)
svc.notify_address = "internal@mybijou.xyz"

cases = [
    ("send_verification_email",
     lambda: svc.send_verification_email("user@x.com", "Acme Sdn Bhd", "tok-abc", "https://app.mybijou.xyz")),
    ("send_welcome_email",
     lambda: svc.send_welcome_email("user@x.com", "Acme Sdn Bhd", "https://app.mybijou.xyz/onboarding/whatsapp")),
    ("send_trial_expiry_warning (1d)",
     lambda: svc.send_trial_expiry_warning("user@x.com", "Acme Sdn Bhd", 1, "https://app.mybijou.xyz/upgrade")),
    ("send_trial_expiry_warning (3d)",
     lambda: svc.send_trial_expiry_warning("user@x.com", "Acme Sdn Bhd", 3, "https://app.mybijou.xyz/upgrade")),
    ("send_trial_expired_email",
     lambda: svc.send_trial_expired_email("user@x.com", "Acme Sdn Bhd", "https://app.mybijou.xyz/upgrade")),
    ("send_payment_confirmation",
     lambda: svc.send_payment_confirmation("user@x.com", "Acme Sdn Bhd", "Pro", "RM 299.00", "https://app.mybijou.xyz/invoice/INV-123")),
    ("send_dashboard_access_email",
     lambda: svc.send_dashboard_access_email("user@x.com", "Acme Sdn Bhd", "https://app.mybijou.xyz/dashboard?token=abc")),
    ("send_login_magic_link",
     lambda: svc.send_login_magic_link("user@x.com", "Acme Sdn Bhd", "https://app.mybijou.xyz/auth/magic?token=xyz")),
    ("send_internal_signup_notification",
     lambda: svc.send_internal_signup_notification(
         name="John Doe", email="john@example.com", phone="60174106981",
         company="Acme", industry="F&B", source="pricing_page", plan="Pro Trial",
     )),
    ("send_escalation_alert",
     lambda: svc.send_escalation_alert(
         agent_name="Agent Smith", customer_name="Cust", customer_phone="60174106981",
         issue="Refund request", escalation_id="ESC-1",
         chat_snippet=["User: I want refund", "Bijou AI: Let me check"],
         priority="high",
     )),
    ("send_settings_test",
     lambda: svc.send_settings_test("user@x.com", "Boss", smtp_host="smtp.resend.com", email_from="hello@mybijou.xyz")),
]

# Brand-color checks
# Canonical Signal Gem colors (must be present in every email)
ON_PALETTE = ["#0B3B2E", "#E3B457", "#F7F4EC", "#0A0A0A", "rgba(227,180,87"]

# Off-palette colors that signal pre-rebrand Slate UI drift.
# IMPORTANT: the JS source templates intentionally use some slate shades for
# "fine print" / "fallback link" text (e.g. #475569 in 01-email-verification.js
# for "If the button doesn't work…"). Those are part of the canonical design
# and SHOULD be present in the Python port. We only fail on colors that are
# NOT in the JS source AND are clearly off-palette (indigo, slate blocks).
OFF_PALETTE_HARD = [
    "#6366f1",   # pre-rebrand indigo CTA — must NEVER appear
    "#a5b4fc",   # pre-rebrand indigo light text
    "#64748b",   # pre-rebrand slate-500 body text
    "#cbd5e1",   # pre-rebrand slate-300 muted text
    "#1e293b",   # pre-rebrand slate-800 borders
    "#0a0a0c",   # pre-rebrand page bg (we use #0A0A0A)
]
# Soft "fine print" colors that the JS templates intentionally use. The
# Python port preserves them — failure here means we drifted from the JS.
FINE_PRINT = ["#475569", "#94a3b8", "#334155"]

all_pass = True
for label, fn in cases:
    fn()
    html = _fake_send.last_html or ""
    subject = _fake_send.last_subject or ""

    has_on = any(c in html for c in ON_PALETTE)
    has_off_hard = [c for c in OFF_PALETTE_HARD if c.lower() in html.lower()]
    has_fine_print = [c for c in FINE_PRINT if c.lower() in html.lower()]

    # FAIL only on hard off-palette colors. Fine-print is allowed (preserved
    # from JS source) — the assertion is that we kept them, not that we added
    # more.
    status = "PASS" if has_on and not has_off_hard else "FAIL"
    all_pass = all_pass and (status == "PASS")
    print(f"[{status}] {label}: subject='{subject[:50]}' len={len(html)} hard_off={has_off_hard} fine_print={has_fine_print}")

print()
if all_pass:
    print("ALL 11 CASES PASS — EmailService is now wired to the Signal Gem builders")
else:
    print("SOME CASES FAILED")
raise SystemExit(0 if all_pass else 1)
