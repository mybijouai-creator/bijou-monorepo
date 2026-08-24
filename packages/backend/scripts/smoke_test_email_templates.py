"""Smoke test for the 10 ported email template builders."""
import sys
from pathlib import Path
# Allow running from anywhere — add src/ to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from saas.email_templates import (
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


def check(label, html, must_contain):
    missing = [s for s in must_contain if s not in html]
    status = "PASS" if not missing else "FAIL"
    print(f"[{status}] {label}: len={len(html)}" + (f" | missing={missing}" if missing else ""))
    return not missing


def main():
    all_pass = True

    all_pass &= check(
        "01 email_verification",
        build_email_verification("Test User", "https://app.mybijou.xyz/verify?token=abc123", 30),
        ["DOCTYPE", "Confirm your email address", "30 minutes", "#E3B457", "Bijou", "AI"],
    )
    all_pass &= check(
        "02 welcome_trial_start",
        build_welcome_trial_start("Boss", "Acme Sdn Bhd", "March 12, 2026"),
        ["DOCTYPE", "Fuyoh, welcome aboard", "Acme Sdn Bhd", "March 12, 2026", "#E3B457"],
    )
    all_pass &= check(
        "03 trial_expiry_warning (1d)",
        build_trial_expiry_warning("Boss", 1, "Tomorrow", "https://app.mybijou.xyz/upgrade"),
        ["DOCTYPE", "day remaining on your free trial", "Last Day", "#ef4444", "Upgrade Now"],
    )
    all_pass &= check(
        "03 trial_expiry_warning (3d)",
        build_trial_expiry_warning("Boss", 3, "Friday"),
        ["days remaining on your free trial", "3 Days Left", "47+", "120+", "380%"],
    )
    all_pass &= check(
        "04 trial_expired",
        build_trial_expired("Boss", grace_days=7),
        ["DOCTYPE", "Your digital employee just went offline", "7 more days", "Reactivate"],
    )
    all_pass &= check(
        "05 payment_confirmation",
        build_payment_confirmation("Boss", "Pro Plan", "RM 299.00", "INV-2026-00142", "26 February 2026", "26 March 2026", "https://app.mybijou.xyz/invoice/123"),
        ["DOCTYPE", "Payment received", "INV-2026-00142", "RM 299.00", "Total Charged"],
    )
    all_pass &= check(
        "06 dashboard_access",
        build_dashboard_access("Boss", "Acme Sdn Bhd", "Growth Plan", "https://app.mybijou.xyz/dashboard?token=x"),
        ["DOCTYPE", "Command Centre is Live", "Acme Sdn Bhd", "Growth Plan", "WhatsApp Console", "Analytics"],
    )
    all_pass &= check(
        "07 internal_signup_notify",
        build_internal_signup_notify(
            "John Doe", "john@example.com", "60174106981",
            company="Acme", industry="F&B", source="pricing_page", plan="Free Trial",
        ),
        ["DOCTYPE", "John Doe", "john@example.com", "Internal Alert", "View in Supabase"],
    )
    all_pass &= check(
        "08 magic_link_login",
        build_magic_link_login("Boss", "https://app.mybijou.xyz/auth/magic?token=xyz", expiry_mins=15, ip_hint="KL, MY", device_hint="Chrome on macOS"),
        ["DOCTYPE", "Your sign-in link is ready", "15 minutes", "KL, MY", "Chrome on macOS"],
    )
    all_pass &= check(
        "09 escalation_agent",
        build_escalation_agent_notification(
            "Agent Smith", "Customer X", "60174106981",
            issue="Refund request denied",
            escalation_id="ESC-123",
            chat_snippet=["User: I want refund", "Bijou AI: Let me check", "User: Please hurry"],
            priority="high",
        ),
        ["DOCTYPE", "Refund request denied", "ESC-123", "HIGH PRIORITY", "Customer", "Bijou AI"],
    )
    all_pass &= check(
        "10 settings_test",
        build_settings_test_email("Boss", smtp_host="smtp.resend.com", email_from="hello@mybijou.xyz"),
        ["DOCTYPE", "Your email notifications are working", "SMTP Auth", "TLS Secure", "Deliverable"],
    )

    print()
    if all_pass:
        print("ALL 11 CASES PASS")
    else:
        print("SOME CASES FAILED")
    raise SystemExit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
