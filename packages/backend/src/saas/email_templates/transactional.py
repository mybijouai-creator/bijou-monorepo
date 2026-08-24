"""
Bijou AI — Email Templates: Transactional Builders (Python port)
=================================================================

Python mirror of `bijou_templates/email-templates/0[1-9]-*.js` and `10-*.js`.
The 10 transactional builders from the JS source of truth, ported line-for-line
so the rendered HTML is byte-equivalent (modulo whitespace) to the JS output.

Builders exposed (each accepts a dict of named args matching the JS JSDoc):
  - build_email_verification
  - build_welcome_trial_start
  - build_trial_expiry_warning
  - build_trial_expired
  - build_payment_confirmation
  - build_dashboard_access
  - build_internal_signup_notify
  - build_magic_link_login
  - build_escalation_agent_notification
  - build_settings_test_email

Brand tokens come from `BRAND` in this package's `base.py`. The brand shell
(header/footer/wrap/CTA) is also delegated to `base.py` so all 10 builders
inherit the Signal Gem chrome without duplication.

If the JS source changes, port the change here too. The 1:1 mapping is the
only way to keep the customer-facing brand consistent across Vercel
(landing's preview.mjs) and Fly.io (email_service.py).
"""
from __future__ import annotations

from typing import List, Optional

from .base import (
    BRAND,
    cta_button,
    email_footer,
    email_header,
    email_wrap,
    divider as _divider,
    support_row as _support_row,
)


# ---------------------------------------------------------------------------
# EMAIL 01 — Email Verification
# ---------------------------------------------------------------------------
def build_email_verification(
    name: str,
    verify_url: str,
    expiry_mins: int = 30,
) -> str:
    """Email 01 — Email Verification (Signal Gem 2026 edition)."""
    first_name = (name or "there").split(" ")[0]
    header = email_header("Verify Your Email")

    body = f"""
    <!-- Security Icon -->
    <div style="text-align:center;margin-bottom:28px;">
      <div style="display:inline-block;width:72px;height:72px;background:linear-gradient(135deg,#0E4938,#0E4938);border-radius:20px;text-align:center;line-height:72px;font-size:36px;box-shadow:0 8px 32px rgba(227,180,87,0.3);">🔐</div>
    </div>

    <h2 style="margin:0 0 8px;font-size:24px;font-weight:900;color:#fff;text-align:center;">
      Confirm your email address
    </h2>
    <p style="margin:0 0 32px;font-size:15px;color:{BRAND['TEXT_MUTED']};line-height:1.7;text-align:center;">
      Hi <strong style="color:{BRAND['TEXT_LIGHT']};">{first_name}</strong>,<br/>
      Click the button below to verify your email and activate your Bijou AI account.
    </p>

    {cta_button(verify_url, "✓ Verify My Email Address", f"linear-gradient(135deg,#E3B457,{BRAND['PRIMARY']})")}

    <!-- Security Notice -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a1f19;border:1px solid #1e3a2f;border-radius:12px;margin-bottom:24px;">
      <tr><td style="padding:18px 22px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td width="32" style="vertical-align:top;padding-top:1px;padding-right:12px;font-size:18px;">🛡️</td>
            <td>
              <p style="margin:0 0 4px;font-size:13px;font-weight:700;color:#F5DC9E;">Security Notice</p>
              <p style="margin:0;font-size:12px;color:{BRAND['TEXT_DIM']};line-height:1.6;">
                This link expires in <strong style="color:#f59e0b;">{expiry_mins} minutes</strong>.
                If you didn't create a Bijou AI account, you can safely ignore this email.
                We will never ask for your password via email.
              </p>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>

    <!-- Manual link fallback -->
    <p style="margin:0 0 6px;font-size:12px;color:{BRAND['TEXT_DIM']};text-align:center;">If the button doesn't work, copy and paste this link:</p>
    <p style="margin:0;font-size:11px;color:#475569;text-align:center;word-break:break-all;">
      <a href="{verify_url}" style="color:{BRAND['PRIMARY']};text-decoration:none;">{verify_url}</a>
    </p>
  """

    footer = email_footer(
        "You received this because someone signed up for Bijou AI using this email.",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 02 — Welcome / Trial Start
# ---------------------------------------------------------------------------
def build_welcome_trial_start(
    name: str,
    business_name: str,
    trial_ends: Optional[str] = None,
) -> str:
    """Email 02 — Welcome / Trial Start (Signal Gem 2026 edition)."""
    first_name = (name or "Boss").split(" ")[0]
    biz = business_name or "your business"
    header = email_header("14-Day Free Trial Started ✓")

    features = [
        ("💬", "WhatsApp AI Agent",
         "Handles customer enquiries 24/7, qualifies leads, books appointments — automatically."),
        ("📊", "Live Analytics",
         "See every chat, lead, and conversion tracked in real-time on your dashboard."),
        ("🔗", "Seamless Integrations",
         "Connects to your CRM, calendar, and payment tools in under 5 minutes."),
    ]
    feature_rows = "".join(
        f"""<tr><td style="padding-bottom:14px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;overflow:hidden;">
          <tr><td style="padding:18px 22px;">
            <table cellpadding="0" cellspacing="0"><tr>
              <td width="40" style="font-size:24px;padding-right:14px;vertical-align:middle;">{icon}</td>
              <td>
                <p style="margin:0 0 3px;font-size:14px;font-weight:800;color:#fff;">{title}</p>
                <p style="margin:0;font-size:13px;color:{BRAND['TEXT_DIM']};line-height:1.5;">{desc}</p>
              </td>
            </tr></table>
          </td></tr>
        </table>
      </td></tr>"""
        for icon, title, desc in features
    )

    steps = [
        ("Connect your WhatsApp number in Settings", f"{BRAND['DASHBOARD']}/settings/whatsapp"),
        ("Train Bijou on your products & FAQs", f"{BRAND['DASHBOARD']}/training"),
        ("Set your business hours & auto-reply rules", f"{BRAND['DASHBOARD']}/settings"),
    ]
    step_rows = "".join(
        f"""<tr>
            <td width="30" style="vertical-align:top;padding-top:2px;">
              <span style="display:inline-block;background:linear-gradient(135deg,#E3B457,{BRAND['PRIMARY']});color:#fff;border-radius:50%;width:22px;height:22px;text-align:center;line-height:22px;font-size:11px;font-weight:800;">{i + 1}</span>
            </td>
            <td style="padding-bottom:12px;">
              <a href="{link}" style="font-size:13px;color:{BRAND['TEXT_LIGHT']};text-decoration:none;line-height:1.5;">{step}</a>
            </td>
          </tr>"""
        for i, (step, link) in enumerate(steps)
    )

    trial_end_html = (
        f""" — until <strong style="color:#fff;">{trial_ends}</strong>"""
        if trial_ends else ""
    )

    body = f"""
    <h2 style="margin:0 0 6px;font-size:26px;font-weight:900;color:#fff;">
      Fuyoh, welcome aboard! 🎉
    </h2>
    <p style="margin:0 0 28px;font-size:15px;color:{BRAND['TEXT_MUTED']};line-height:1.8;">
      Hi <strong style="color:{BRAND['TEXT_LIGHT']};">{first_name}</strong>, your digital employee has just reported for duty at <strong style="color:{BRAND['EMERALD']};">{biz}</strong>.
      Your free trial is <strong style="color:{BRAND['EMERALD']};">active now</strong>{trial_end_html}.
    </p>

    <!-- Feature Grid -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
      {feature_rows}
    </table>

    <!-- Quick Start Steps -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a1f19;border:1px solid rgba(227,180,87,0.3);border-radius:14px;margin-bottom:28px;overflow:hidden;">
      <tr><td style="padding:18px 22px;border-bottom:1px solid rgba(227,180,87,0.15);">
        <p style="margin:0;font-size:12px;font-weight:700;color:#F5DC9E;text-transform:uppercase;letter-spacing:1.5px;">⚡ 3 Steps to Go Live Today</p>
      </td></tr>
      <tr><td style="padding:20px 22px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          {step_rows}
        </table>
      </td></tr>
    </table>

    {cta_button(BRAND['DASHBOARD'], "Open My Dashboard →")}
    <p style="margin:-16px 0 28px;font-size:11px;color:#475569;text-align:center;">First time? <a href="{BRAND['GUIDE']}" style="color:{BRAND['PRIMARY']};">Read the setup guide →</a></p>

    {_support_row("Your success is our business. We're here whenever you need us:")}
  """

    footer = email_footer(
        "You received this because you verified your Bijou AI account.",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 03 — Trial Expiry Warning
# ---------------------------------------------------------------------------
def build_trial_expiry_warning(
    name: str,
    days_left: int,
    trial_ends: str,
    upgrade_url: Optional[str] = None,
) -> str:
    """Email 03 — Trial Expiry Warning (Signal Gem 2026 edition)."""
    first_name = (name or "Boss").split(" ")[0]
    upgrade = upgrade_url or f"{BRAND['APP_URL']}/billing/upgrade"

    if days_left == 1:
        urgency = {"label": "⚠️ Last Day", "accent": "#ef4444", "dim": "#7f1d1d"}
    elif days_left <= 3:
        urgency = {"label": f"⏳ {days_left} Days Left", "accent": BRAND["AMBER"], "dim": "#78350f"}
    else:
        urgency = {"label": f"📅 {days_left} Days Left", "accent": "#f59e0b", "dim": "#451a03"}

    header = email_header(urgency["label"])
    day_word = "day" if days_left == 1 else "days"

    stats = [
        ("Avg. leads saved per month", "47+"),
        ("Hours of manual work saved", "120+"),
        ("ROI in your first 30 days", "380%"),
    ]
    stat_cells = "".join(
        f"""<td width="33%" style="text-align:center;padding:0 6px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;padding:16px 8px;">
            <tr><td style="padding:16px 8px;text-align:center;">
              <p style="margin:0 0 4px;font-size:26px;font-weight:900;color:{BRAND['EMERALD']};">{val}</p>
              <p style="margin:0;font-size:11px;color:{BRAND['TEXT_DIM']};line-height:1.4;">{label}</p>
            </td></tr>
          </table>
        </td>"""
        for label, val in stats
    )

    keeps = [
        "24/7 WhatsApp AI replies continue uninterrupted",
        "All your training data & conversation history preserved",
        "Priority support + onboarding call with our team",
    ]
    keep_items = "".join(
        f'<p style="margin:0 0 7px;font-size:13px;color:{BRAND["TEXT_MUTED"]};">✓ &nbsp;{item}</p>'
        for item in keeps
    )

    body = f"""
    <!-- Countdown Banner -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,{urgency['dim']},{urgency['accent']}22);border:1px solid {urgency['accent']}55;border-radius:14px;margin-bottom:28px;overflow:hidden;">
      <tr><td style="padding:22px 28px;text-align:center;">
        <p style="margin:0 0 4px;font-size:42px;font-weight:900;color:{urgency['accent']};letter-spacing:-2px;">{days_left}</p>
        <p style="margin:0;font-size:14px;font-weight:700;color:#fff;">{day_word} remaining on your free trial</p>
        <p style="margin:6px 0 0;font-size:12px;color:{urgency['accent']}aa;">Trial ends: <strong style="color:{urgency['accent']};">{trial_ends}</strong></p>
      </td></tr>
    </table>

    <h2 style="margin:0 0 8px;font-size:22px;font-weight:900;color:#fff;">
      {first_name}, don't lose your digital employee
    </h2>
    <p style="margin:0 0 24px;font-size:15px;color:{BRAND['TEXT_MUTED']};line-height:1.8;">
      Your Bijou AI agent is still working hard right now. The moment your trial ends, all automations will pause — including your WhatsApp replies, lead captures, and booking flows.
    </p>

    <!-- ROI Stats -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
      <tr>
        {stat_cells}
      </tr>
    </table>

    {cta_button(upgrade, f"Upgrade Now — Keep Bijou Running →", f"linear-gradient(135deg,{urgency['dim']},{urgency['accent']})")}
    <p style="margin:-16px 0 28px;font-size:11px;color:#475569;text-align:center;">Plans start at RM 299/mo · No contracts · Cancel anytime</p>

    <!-- Plan reminder -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;margin-bottom:8px;">
      <tr><td style="padding:18px 22px;">
        <p style="margin:0 0 10px;font-size:13px;font-weight:700;color:{BRAND['PRIMARY']};text-transform:uppercase;letter-spacing:1px;">💎 What you keep when you upgrade</p>
        {keep_items}
      </td></tr>
    </table>

    {_support_row("Questions about pricing? Let's talk:")}
  """

    footer = email_footer(
        "You received this because you have an active Bijou AI trial.",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 04 — Trial Expired Notice
# ---------------------------------------------------------------------------
def build_trial_expired(
    name: str,
    upgrade_url: Optional[str] = None,
    grace_days: int = 3,
) -> str:
    """Email 04 — Trial Expired Notice (Signal Gem 2026 edition)."""
    first_name = (name or "Boss").split(" ")[0]
    upgrade = upgrade_url or f"{BRAND['APP_URL']}/billing/upgrade"

    header = email_header("Trial Ended")

    paused = [
        "WhatsApp AI auto-replies",
        "Lead capture & qualification flows",
        "Appointment booking automations",
        "Analytics tracking & reporting",
    ]
    paused_items = "".join(
        f'<p style="margin:0 0 8px;font-size:13px;color:#f87171;">✗ &nbsp;{item}</p>'
        for item in paused
    )

    body = f"""
    <!-- Status Banner -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#1c0a0a,#450a0a);border:1px solid #7f1d1d;border-radius:14px;margin-bottom:28px;overflow:hidden;">
      <tr><td style="padding:24px 28px;text-align:center;">
        <div style="font-size:48px;margin-bottom:8px;">😴</div>
        <p style="margin:0 0 4px;font-size:18px;font-weight:800;color:#fca5a5;">Your digital employee just went offline</p>
        <p style="margin:0;font-size:13px;color:#f87171;">All automations have paused as of today.</p>
      </td></tr>
    </table>

    <h2 style="margin:0 0 8px;font-size:22px;font-weight:900;color:#fff;">
      {first_name}, your account is on hold
    </h2>
    <p style="margin:0 0 24px;font-size:15px;color:{BRAND['TEXT_MUTED']};line-height:1.8;">
      Your Bijou AI trial has ended. Your configurations, training data, and conversation history are all saved — but your WhatsApp automations, lead flows, and booking integrations are currently paused.
    </p>

    <!-- What's paused -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid #7f1d1d55;border-radius:12px;margin-bottom:24px;">
      <tr><td style="padding:18px 22px;border-bottom:1px solid #7f1d1d33;">
        <p style="margin:0;font-size:12px;font-weight:700;color:#fca5a5;text-transform:uppercase;letter-spacing:1.5px;">🔴 Currently Paused</p>
      </td></tr>
      <tr><td style="padding:16px 22px;">
        {paused_items}
      </td></tr>
    </table>

    <!-- Grace period warning -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#1c1400;border:1px solid {BRAND['AMBER']}44;border-radius:12px;margin-bottom:28px;">
      <tr><td style="padding:16px 22px;">
        <table cellpadding="0" cellspacing="0"><tr>
          <td width="30" style="font-size:20px;padding-right:12px;vertical-align:top;padding-top:2px;">⚠️</td>
          <td><p style="margin:0;font-size:13px;color:{BRAND['AMBER']};line-height:1.6;">
            <strong>Your data is safe for {grace_days} more days.</strong> After that, your account configuration will be permanently deleted. Upgrade now to keep everything intact.
          </p></td>
        </tr></table>
      </td></tr>
    </table>

    {cta_button(upgrade, "Reactivate Bijou AI Now →", f"linear-gradient(135deg,#E3B457,{BRAND['PRIMARY']})")}
    <p style="margin:-16px 0 28px;font-size:11px;color:#475569;text-align:center;">Reactivate in 60 seconds · All your data restored instantly</p>

    {_divider}
    <p style="margin:0;font-size:14px;color:{BRAND['TEXT_MUTED']};text-align:center;line-height:1.7;">
      Not ready to upgrade? <a href="mailto:{BRAND['SUPPORT']}?subject=Trial Extension Request" style="color:{BRAND['PRIMARY']};">Reply here</a> and we'll see what we can do, boss. 🙏
    </p>

    {_support_row()}
  """

    footer = email_footer(
        "You received this because your Bijou AI trial has ended.",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 05 — Payment Confirmation
# ---------------------------------------------------------------------------
def build_payment_confirmation(
    name: str,
    plan: str,
    amount: str,
    invoice_id: str,
    billing_date: str,
    next_billing: str,
    invoice_url: Optional[str] = None,
) -> str:
    """Email 05 — Payment Confirmation (Signal Gem 2026 edition)."""
    first_name = (name or "Boss").split(" ")[0]
    invoice = invoice_url or f"{BRAND['APP_URL']}/billing/invoices"

    header = email_header("Payment Successful ✓")

    rows = [
        ("Plan", plan),
        ("Amount Paid", amount),
        ("Payment Date", billing_date),
        ("Next Billing", next_billing),
        ("Status", f'<span style="color:{BRAND["EMERALD"]};font-weight:700;">✓ Paid</span>'),
    ]
    receipt_rows = "".join(
        f"""<table width="100%" cellpadding="0" cellspacing="0"
               style="{'border-bottom:1px solid #1a3a2c;' if i < len(rows) - 1 else ''}">
          <tr>
            <td style="padding:14px 0;font-size:13px;color:{BRAND['TEXT_DIM']};font-weight:600;width:140px;">{label}</td>
            <td style="padding:14px 0;font-size:14px;color:#fff;text-align:right;">{val}</td>
          </tr>
        </table>"""
        for i, (label, val) in enumerate(rows)
    )

    body = f"""
    <!-- Success Icon -->
    <div style="text-align:center;margin-bottom:28px;">
      <div style="display:inline-block;width:72px;height:72px;background:linear-gradient(135deg,#052e16,#065f46);border-radius:50%;text-align:center;line-height:72px;font-size:36px;box-shadow:0 8px 32px rgba(16,185,129,0.3);">✓</div>
    </div>

    <h2 style="margin:0 0 6px;font-size:24px;font-weight:900;color:#fff;text-align:center;">
      Payment received, thank you!
    </h2>
    <p style="margin:0 0 32px;font-size:15px;color:{BRAND['TEXT_MUTED']};line-height:1.7;text-align:center;">
      Hi <strong style="color:{BRAND['TEXT_LIGHT']};">{first_name}</strong>, your payment has been processed successfully. Your digital employee is active and ready to work.
    </p>

    <!-- Receipt Card -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:16px;margin-bottom:24px;overflow:hidden;">
      <tr><td style="background:linear-gradient(135deg,#052e16,#064e3b);padding:18px 28px;">
        <p style="margin:0;font-size:11px;font-weight:700;color:#6ee7b7;text-transform:uppercase;letter-spacing:2px;">Official Receipt</p>
        <p style="margin:4px 0 0;font-size:20px;font-weight:900;color:#fff;">{invoice_id}</p>
      </td></tr>
      <tr><td style="padding:0 28px;">
        {receipt_rows}
      </td></tr>
    </table>

    <!-- Amount highlight -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#052e16,#064e3b);border-radius:12px;margin-bottom:28px;">
      <tr><td style="padding:22px;text-align:center;">
        <p style="margin:0 0 4px;font-size:13px;color:#6ee7b7;font-weight:600;">Total Charged</p>
        <p style="margin:0;font-size:36px;font-weight:900;color:#fff;">{amount}</p>
      </td></tr>
    </table>

    {cta_button(invoice, "View Full Invoice →", f"linear-gradient(135deg,#E3B457,{BRAND['PRIMARY']})")}

    {_divider}

    <!-- Support -->
    <table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
      <p style="margin:0 0 8px;font-size:13px;color:{BRAND['TEXT_DIM']};">Billing questions? We're here:</p>
      <p style="margin:0;font-size:13px;color:{BRAND['TEXT_MUTED']};">
        📧 <a href="mailto:{BRAND['SUPPORT']}" style="color:{BRAND['EMERALD']};text-decoration:none;">{BRAND['SUPPORT']}</a>
        &nbsp;&nbsp;|&nbsp;&nbsp;
        💬 <a href="{BRAND['WHATSAPP']}" style="color:{BRAND['EMERALD']};text-decoration:none;">{BRAND['WA_NUM']}</a>
      </p>
    </td></tr></table>
  """

    footer = email_footer(
        "You received this because a payment was processed on your Bijou AI account.",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 06 — Dashboard Access
# ---------------------------------------------------------------------------
def build_dashboard_access(
    name: str,
    business_name: str,
    plan: str,
    login_url: Optional[str] = None,
) -> str:
    """Email 06 — Dashboard Access (Signal Gem 2026 edition)."""
    first_name = (name or "Boss").split(" ")[0]
    biz = business_name or "your business"
    login = login_url or BRAND["DASHBOARD"]
    header = email_header("Dashboard Access Granted ✓")

    body = f"""
    <!-- Hero Banner -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#0a1f19,#0E4938);border:1px solid rgba(227,180,87,0.4);border-radius:16px;margin-bottom:28px;overflow:hidden;">
      <tr><td style="padding:28px;text-align:center;">
        <div style="font-size:48px;margin-bottom:12px;">🖥️</div>
        <p style="margin:0 0 6px;font-size:20px;font-weight:900;color:#fff;">Your Command Centre is Live</p>
        <p style="margin:0;font-size:13px;color:#F5DC9E;">{biz} &nbsp;·&nbsp; <strong style="color:#fff;">{plan or 'Active Plan'}</strong></p>
      </td></tr>
    </table>

    <h2 style="margin:0 0 8px;font-size:22px;font-weight:900;color:#fff;">
      Welcome to the team, {first_name}! 💎
    </h2>
    <p style="margin:0 0 28px;font-size:15px;color:{BRAND['TEXT_MUTED']};line-height:1.8;">
      Your Bijou AI dashboard is fully activated. Here's everything waiting for you inside:
    </p>

    <!-- Dashboard Modules -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
      <tr>
        <td width="50%" style="padding:0 6px 12px 0;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;">
            <tr><td style="padding:18px;">
              <p style="margin:0 0 6px;font-size:22px;">📱</p>
              <p style="margin:0 0 4px;font-size:13px;font-weight:800;color:#fff;">WhatsApp Console</p>
              <p style="margin:0;font-size:11px;color:{BRAND['TEXT_DIM']};line-height:1.5;">Connect, monitor & manage your AI agent</p>
            </td></tr>
          </table>
        </td>
        <td width="50%" style="padding:0 0 12px 6px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;">
            <tr><td style="padding:18px;">
              <p style="margin:0 0 6px;font-size:22px;">📊</p>
              <p style="margin:0 0 4px;font-size:13px;font-weight:800;color:#fff;">Analytics</p>
              <p style="margin:0;font-size:11px;color:{BRAND['TEXT_DIM']};line-height:1.5;">Conversations · Leads · Conversions</p>
            </td></tr>
          </table>
        </td>
      </tr>
      <tr>
        <td width="50%" style="padding:0 6px 0 0;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;">
            <tr><td style="padding:18px;">
              <p style="margin:0 0 6px;font-size:22px;">🧠</p>
              <p style="margin:0 0 4px;font-size:13px;font-weight:800;color:#fff;">AI Training</p>
              <p style="margin:0;font-size:11px;color:{BRAND['TEXT_DIM']};line-height:1.5;">Upload FAQs, products & playbooks</p>
            </td></tr>
          </table>
        </td>
        <td width="50%" style="padding:0 0 0 6px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;">
            <tr><td style="padding:18px;">
              <p style="margin:0 0 6px;font-size:22px;">🔗</p>
              <p style="margin:0 0 4px;font-size:13px;font-weight:800;color:#fff;">Integrations</p>
              <p style="margin:0;font-size:11px;color:{BRAND['TEXT_DIM']};line-height:1.5;">CRM · Calendar · Payment links</p>
            </td></tr>
          </table>
        </td>
      </tr>
    </table>

    {cta_button(login, "Go to My Dashboard →")}

    <!-- Bilingual note -->
    <p style="margin:-16px 0 28px;font-size:11px;color:#475569;text-align:center;">
      Dashboard tersedia dalam Bahasa Melayu &amp; English · <a href="{BRAND['GUIDE']}" style="color:{BRAND['PRIMARY']};">Baca panduan persediaan →</a>
    </p>

    {_support_row("Need a hand getting set up?")}
  """

    footer = email_footer(
        "You received this because your Bijou AI subscription is now active.",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 07 — Internal Signup Notification
# ---------------------------------------------------------------------------
def _now_myt() -> str:
    """Current time in MYT, e.g. '24/8/2026 19:00:26 MYT'.

    Uses strftime without platform-specific %- tokens (Windows strftime
    does not support %-d / %-m — those are GNU/BSD extensions).
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        now = datetime.now(ZoneInfo("Asia/Kuala_Lumpur"))
    except Exception:
        # Fallback: assume +08:00
        from datetime import timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%d/%m/%Y %H:%M:%S MYT")


def build_internal_signup_notify(
    name: str,
    email: str,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    industry: Optional[str] = None,
    source: Optional[str] = None,
    plan: Optional[str] = None,
    time: Optional[str] = None,
    supabase_url: Optional[str] = None,
) -> str:
    """Email 07 — Internal Signup Notification (Signal Gem 2026 edition)."""
    display_time = time or _now_myt()
    supabase = supabase_url or "https://supabase.com/dashboard/project"

    header = f"""
    <tr><td style="background:linear-gradient(160deg,#0a1f19 0%,#0E4938 100%);border-radius:16px 16px 0 0;padding:28px 36px;border-bottom:1px solid rgba(227,180,87,0.3);">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td>
          <img src="{BRAND['LOGO']}" alt="Bijou AI" width="36" height="36" style="display:inline-block;vertical-align:middle;border-radius:8px;margin-right:10px;" />
          <span style="font-size:18px;font-weight:900;color:{BRAND['GOLD']};vertical-align:middle;">Bijou</span><span style="font-size:18px;font-weight:900;color:#fff;vertical-align:middle;">AI</span>
          <span style="margin-left:12px;font-size:11px;color:#F5DC9E;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;">Internal Alert</span>
        </td>
        <td align="right">
          <span style="background:rgba(16,185,129,0.15);border:1px solid {BRAND['EMERALD']}44;border-radius:20px;padding:4px 14px;font-size:11px;color:{BRAND['EMERALD']};font-weight:700;">🔴 LIVE</span>
        </td>
      </tr></table>
    </td></tr>"""

    lead_rows = [
        ("Name", name or "—"),
        ("Email", email),
        ("Phone", phone or "—"),
        ("Company", company or "—"),
        ("Industry", industry or "—"),
        ("Source", source or "organic"),
        ("Plan", plan or "Free Trial"),
    ]
    lead_html = "".join(
        f"""<table width="100%" cellpadding="0" cellspacing="0" style="{'border-bottom:1px solid #0a1f19;' if i < len(lead_rows) - 1 else ''}">
          <tr>
            <td width="110" style="padding:10px 0;font-size:12px;color:{BRAND['TEXT_DIM']};font-weight:700;">{label}</td>
            <td style="padding:10px 0;font-size:13px;color:{BRAND['TEXT_LIGHT']};">{val}</td>
          </tr>
        </table>"""
        for i, (label, val) in enumerate(lead_rows)
    )

    body = f"""
    <!-- Alert headline -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#0E4938,#0E4938);border-radius:14px;margin-bottom:24px;">
      <tr><td style="padding:22px 28px;">
        <p style="margin:0 0 4px;font-size:12px;color:#F5DC9E;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;">🎯 New Signup</p>
        <p style="margin:0 0 2px;font-size:22px;font-weight:900;color:#fff;">{name or 'Unknown'}</p>
        <p style="margin:0;font-size:13px;color:#F5DC9E;">{email} &nbsp;·&nbsp; {display_time}</p>
      </td></tr>
    </table>

    <!-- Lead Details -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:14px;margin-bottom:20px;overflow:hidden;">
      <tr><td style="padding:16px 22px;border-bottom:1px solid #1a3a2c;">
        <p style="margin:0;font-size:11px;font-weight:700;color:{BRAND['PRIMARY']};text-transform:uppercase;letter-spacing:1.5px;">📋 Lead Details</p>
      </td></tr>
      <tr><td style="padding:8px 22px 16px;">
        {lead_html}
      </td></tr>
    </table>

    <!-- Quick Actions -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:8px;">
      <tr>
        <td width="50%" style="padding-right:6px;">
          <a href="https://wa.me/{''.join(ch for ch in (phone or '60174106981') if ch.isdigit())}" style="display:block;background:linear-gradient(135deg,#14532d,#16a34a);color:#fff;text-decoration:none;font-weight:700;font-size:13px;padding:12px;border-radius:10px;text-align:center;">
            💬 WhatsApp {(name.split(' ')[0] if name else 'Lead')}
          </a>
        </td>
        <td width="50%" style="padding-left:6px;">
          <a href="{supabase}" style="display:block;background:linear-gradient(135deg,#0E4938,{BRAND['PRIMARY']});color:#fff;text-decoration:none;font-weight:700;font-size:13px;padding:12px;border-radius:10px;text-align:center;">
            🗄️ View in Supabase
          </a>
        </td>
      </tr>
    </table>
  """

    footer = email_footer(
        "Internal notification — Bijou AI Lead System · mybijou.xyz",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 08 — Magic-Link Login
# ---------------------------------------------------------------------------
def build_magic_link_login(
    name: str,
    magic_url: str,
    expiry_mins: int = 15,
    ip_hint: Optional[str] = None,
    device_hint: Optional[str] = None,
) -> str:
    """Email 08 — Magic-Link Login (Signal Gem 2026 edition)."""
    first_name = (name or "there").split(" ")[0]
    header = email_header("Sign-In Link")

    request_details = ""
    if ip_hint or device_hint:
        loc = f'<p style="margin:0 0 6px;font-size:13px;color:{BRAND["TEXT_MUTED"]};">📍 Location: <strong style="color:#fff;">{ip_hint}</strong></p>' if ip_hint else ""
        dev = f'<p style="margin:0;font-size:13px;color:{BRAND["TEXT_MUTED"]};">💻 Device: <strong style="color:#fff;">{device_hint}</strong></p>' if device_hint else ""
        request_details = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;margin-bottom:24px;">
      <tr><td style="padding:16px 22px;">
        <p style="margin:0 0 10px;font-size:12px;font-weight:700;color:{BRAND['TEXT_DIM']};text-transform:uppercase;letter-spacing:1px;">Request Details</p>
        {loc}
        {dev}
      </td></tr>
    </table>"""

    body = f"""
    <!-- Security Shield -->
    <div style="text-align:center;margin-bottom:32px;">
      <div style="display:inline-block;background:linear-gradient(135deg,#0E4938,#0E4938);border-radius:50%;width:80px;height:80px;text-align:center;line-height:80px;font-size:40px;box-shadow:0 8px 40px rgba(227,180,87,0.35);">🔑</div>
    </div>

    <h2 style="margin:0 0 8px;font-size:24px;font-weight:900;color:#fff;text-align:center;">
      Your sign-in link is ready
    </h2>
    <p style="margin:0 0 32px;font-size:15px;color:{BRAND['TEXT_MUTED']};line-height:1.7;text-align:center;">
      Hi <strong style="color:{BRAND['TEXT_LIGHT']};">{first_name}</strong>, click the button below to sign in to your Bijou AI dashboard. No password needed.
    </p>

    <!-- Big CTA -->
    <div style="text-align:center;margin-bottom:28px;">
      <a href="{magic_url}" style="display:inline-block;background:linear-gradient(135deg,#E3B457,#E3B457,#F5DC9E);color:#fff;text-decoration:none;font-weight:800;font-size:16px;padding:18px 48px;border-radius:14px;letter-spacing:0.3px;box-shadow:0 8px 32px rgba(227,180,87,0.4);">
        Sign In to Bijou AI →
      </a>
    </div>

    <!-- Expiry countdown -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#1c1400;border:1px solid {BRAND['AMBER']}55;border-radius:12px;margin-bottom:24px;">
      <tr><td style="padding:16px 22px;text-align:center;">
        <p style="margin:0 0 4px;font-size:13px;font-weight:800;color:{BRAND['AMBER']};">⏰ Link expires in {expiry_mins} minutes</p>
        <p style="margin:0;font-size:12px;color:#92400e;">This is a one-time link — it will expire after use or after {expiry_mins} minutes.</p>
      </td></tr>
    </table>

    <!-- Request details -->
    {request_details}

    <!-- Security warning -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a1f19;border:1px solid {BRAND['BORDER']};border-radius:12px;margin-bottom:8px;">
      <tr><td style="padding:16px 22px;">
        <table cellpadding="0" cellspacing="0"><tr>
          <td width="28" style="font-size:16px;padding-right:10px;vertical-align:top;padding-top:2px;">🛡️</td>
          <td><p style="margin:0;font-size:12px;color:{BRAND['TEXT_DIM']};line-height:1.7;">
            If you didn't request this link, you can safely ignore this email — your account remains secure.
            Never share this link with anyone. <strong style="color:#fff;">Bijou AI will never ask for it.</strong>
          </p></td>
        </tr></table>
      </td></tr>
    </table>

    <!-- Manual fallback -->
    <p style="margin:16px 0 0;font-size:11px;color:#334155;text-align:center;">Button not working? Copy this link into your browser:</p>
    <p style="margin:4px 0 0;font-size:10px;color:#475569;text-align:center;word-break:break-all;">
      <a href="{magic_url}" style="color:{BRAND['PRIMARY']};">{magic_url}</a>
    </p>
  """

    footer = email_footer(
        "You received this because a sign-in was requested for your Bijou AI account.",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 09 — Escalation Agent Notification
# ---------------------------------------------------------------------------
def build_escalation_agent_notification(
    agent_name: str,
    customer_name: str,
    customer_phone: str,
    issue: str,
    escalation_id: str,
    chat_snippet: Optional[List[str]] = None,
    priority: str = "high",
    response_url: Optional[str] = None,
    time: Optional[str] = None,
) -> str:
    """Email 09 — Escalation Agent Notification (Signal Gem 2026 edition)."""
    first_name = (agent_name or "Agent").split(" ")[0]
    display_time = time or _now_myt()
    respond = response_url or BRAND["DASHBOARD"]
    chat_snippet = chat_snippet or []

    priority_lookup = {
        "high": {
            "color": "#ef4444",
            "bg": "#1c0a0a",
            "border": "#7f1d1d",
            "label": "🔴 HIGH PRIORITY",
            "icon": "🔴",
        },
        "medium": {
            "color": BRAND["AMBER"],
            "bg": "#1c1400",
            "border": "#78350f",
            "label": "🟡 MEDIUM PRIORITY",
            "icon": "🟡",
        },
        "low": {
            "color": BRAND["EMERALD"],
            "bg": "#052e16",
            "border": "#064e3b",
            "label": "🟢 LOW PRIORITY",
            "icon": "🟢",
        },
    }
    priority_config = priority_lookup.get(priority) or priority_lookup["high"]

    header = f"""
    <tr><td style="background:linear-gradient(160deg,{priority_config['bg']} 0%,#0a1f19 100%);border:2px solid {priority_config['border']};border-radius:16px 16px 0 0;padding:28px 36px;">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td>
          <img src="{BRAND['LOGO']}" alt="Bijou AI" width="36" height="36" style="display:inline-block;vertical-align:middle;border-radius:8px;margin-right:10px;" />
          <span style="font-size:16px;font-weight:900;color:{BRAND['GOLD']};vertical-align:middle;">Bijou</span><span style="font-size:16px;font-weight:900;color:#fff;vertical-align:middle;">AI</span>
          <span style="margin-left:10px;font-size:11px;color:{priority_config['color']};font-weight:700;text-transform:uppercase;letter-spacing:1.5px;">Escalation Alert</span>
        </td>
        <td align="right">
          <span style="background:{priority_config['bg']};border:1px solid {priority_config['border']};border-radius:20px;padding:5px 14px;font-size:11px;color:{priority_config['color']};font-weight:700;">{priority_config['label']}</span>
        </td>
      </tr></table>
    </td></tr>"""

    customer_rows = [
        ("Name", customer_name or "—"),
        ("Phone / WhatsApp", customer_phone or "—"),
        ("Priority", priority_config["label"]),
    ]
    customer_html = "".join(
        f'<tr><td width="130" style="padding:6px 0;font-size:12px;color:{BRAND["TEXT_DIM"]};font-weight:600;">{l}</td><td style="padding:6px 0;font-size:13px;color:#fff;">{v}</td></tr>'
        for l, v in customer_rows
    )

    chat_html = ""
    if chat_snippet:
        msgs_html = ""
        for msg in chat_snippet:
            low = msg.lower()
            is_user = low.startswith("user:") or low.startswith("customer:")
            label = "Customer" if is_user else "Bijou AI"
            # strip the prefix
            text = msg
            for prefix in ("Customer:", "customer:", "User:", "user:", "Bijou AI:", "bijou ai:", "Bijou:", "bijou:"):
                if text.startswith(prefix):
                    text = text[len(prefix):]
                    break
            text = text.lstrip()
            indent_left = "" if is_user else '<td width="20"></td>'
            indent_right = '<td width="20"></td>' if is_user else ""
            bubble_bg = "#0a1f19" if is_user else "#0E4938"
            bubble_border = "#1a3a2c" if is_user else "rgba(227,180,87,0.3)"
            label_color = BRAND["TEXT_DIM"] if is_user else BRAND["GOLD"]
            msgs_html += f"""
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
            <tr>
              {indent_left}
              <td>
                <div style="background:{bubble_bg};border:1px solid {bubble_border};border-radius:10px;padding:10px 14px;">
                  <p style="margin:0 0 3px;font-size:10px;color:{label_color};font-weight:700;text-transform:uppercase;">{label}</p>
                  <p style="margin:0;font-size:13px;color:#e2e8f0;line-height:1.5;">{text}</p>
                </div>
              </td>
              {indent_right}
            </tr>
          </table>"""
        chat_html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#061a14;border:1px solid {BRAND['BORDER']};border-radius:12px;margin-bottom:20px;overflow:hidden;">
      <tr><td style="padding:14px 20px;border-bottom:1px solid #1a3a2c;">
        <p style="margin:0;font-size:11px;font-weight:700;color:{BRAND['AMBER']};text-transform:uppercase;letter-spacing:1.5px;">💬 Last Messages</p>
      </td></tr>
      <tr><td style="padding:16px 20px;">
        {msgs_html}
      </td></tr>
    </table>"""

    whatsapp_link = ""
    if customer_phone:
        wa_digits = "".join(ch for ch in customer_phone if ch.isdigit())
        whatsapp_link = f"""
    <div style="text-align:center;margin-bottom:8px;">
      <a href="https://wa.me/{wa_digits}" style="display:inline-block;background:#14532d;color:#fff;text-decoration:none;font-weight:600;font-size:13px;padding:10px 28px;border-radius:10px;">
        💬 WhatsApp Customer Directly
      </a>
    </div>"""

    body = f"""
    <!-- Urgency Banner -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{priority_config['bg']};border:1px solid {priority_config['border']};border-radius:12px;margin-bottom:24px;">
      <tr><td style="padding:20px 24px;">
        <p style="margin:0 0 4px;font-size:12px;color:{priority_config['color']};font-weight:700;text-transform:uppercase;letter-spacing:1.5px;">{priority_config['icon']} Human Intervention Required</p>
        <p style="margin:0 0 8px;font-size:20px;font-weight:900;color:#fff;">{issue}</p>
        <p style="margin:0;font-size:12px;color:#94a3b8;">Escalation ID: <strong style="color:#fff;">{escalation_id}</strong> &nbsp;·&nbsp; {display_time}</p>
      </td></tr>
    </table>

    <h3 style="margin:0 0 6px;font-size:16px;font-weight:700;color:#fff;">
      Hi {first_name}, a customer needs your attention
    </h3>
    <p style="margin:0 0 20px;font-size:14px;color:{BRAND['TEXT_MUTED']};line-height:1.7;">
      Bijou AI could not resolve this conversation and has escalated it to you. Please respond ASAP.
    </p>

    <!-- Customer Info -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:12px;margin-bottom:20px;overflow:hidden;">
      <tr><td style="padding:14px 20px;border-bottom:1px solid #1a3a2c;">
        <p style="margin:0;font-size:11px;font-weight:700;color:{BRAND['PRIMARY']};text-transform:uppercase;letter-spacing:1.5px;">👤 Customer</p>
      </td></tr>
      <tr><td style="padding:16px 20px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          {customer_html}
        </table>
      </td></tr>
    </table>

    <!-- Chat Snippet -->
    {chat_html}

    <!-- CTA -->
    <div style="text-align:center;margin:28px 0 8px;">
      <a href="{respond}" style="display:inline-block;background:linear-gradient(135deg,{priority_config['bg']},{priority_config['color']});color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:15px 40px;border-radius:12px;border:1px solid {priority_config['border']};">
        Respond to Customer →
      </a>
    </div>
    {whatsapp_link}
  """

    footer = email_footer(
        "Internal escalation alert — Bijou AI Operations System",
    )
    return email_wrap(header, body, footer)


# ---------------------------------------------------------------------------
# EMAIL 10 — Settings Test Email
# ---------------------------------------------------------------------------
def build_settings_test_email(
    name: str,
    smtp_host: Optional[str] = None,
    email_from: Optional[str] = None,
    time: Optional[str] = None,
) -> str:
    """Email 10 — Settings Test Email (Signal Gem 2026 edition)."""
    first_name = (name or "Boss").split(" ")[0]
    display_time = time or _now_myt()
    header = email_header("Email Test Sent ✓")

    rows = [
        ("Status", f'<span style="color:{BRAND["EMERALD"]};font-weight:700;">✓ Active</span>'),
        ("Transport", "SMTP" if smtp_host else "Resend API"),
        ("Host", smtp_host or "api.resend.com"),
        ("From", email_from or BRAND["SUPPORT"]),
        ("Sent At", display_time),
    ]
    config_rows = "".join(
        f"""<table width="100%" cellpadding="0" cellspacing="0" style="{'border-bottom:1px solid #0a1f19;' if i < len(rows) - 1 else ''}">
          <tr>
            <td width="110" style="padding:10px 0;font-size:12px;color:{BRAND['TEXT_DIM']};font-weight:700;">{label}</td>
            <td style="padding:10px 0;font-size:13px;color:{BRAND['TEXT_LIGHT']};text-align:right;">{val}</td>
          </tr>
        </table>"""
        for i, (label, val) in enumerate(rows)
    )

    system_checks = [
        ("SMTP Auth", BRAND["EMERALD"], "✓"),
        ("TLS Secure", BRAND["EMERALD"], "✓"),
        ("Deliverable", BRAND["EMERALD"], "✓"),
    ]
    check_cells = "".join(
        f"""<td width="33%" style="padding:0 4px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#052e16;border:1px solid {color}33;border-radius:10px;">
            <tr><td style="padding:10px;text-align:center;">
              <p style="margin:0 0 2px;font-size:18px;color:{color};font-weight:900;">{status}</p>
              <p style="margin:0;font-size:10px;color:{BRAND['TEXT_DIM']};">{label}</p>
            </td></tr>
          </table>
        </td>"""
        for label, color, status in system_checks
    )

    body = f"""
    <!-- Success Check -->
    <div style="text-align:center;margin-bottom:28px;">
      <div style="display:inline-block;width:72px;height:72px;background:linear-gradient(135deg,#052e16,#065f46);border-radius:50%;text-align:center;line-height:72px;font-size:36px;box-shadow:0 8px 32px rgba(16,185,129,0.25);">✅</div>
    </div>

    <h2 style="margin:0 0 8px;font-size:22px;font-weight:900;color:#fff;text-align:center;">
      Your email notifications are working!
    </h2>
    <p style="margin:0 0 32px;font-size:15px;color:{BRAND['TEXT_MUTED']};line-height:1.7;text-align:center;">
      Hi <strong style="color:{BRAND['TEXT_LIGHT']};">{first_name}</strong>, this test was sent from your Bijou AI dashboard settings.
      If you can read this, your email configuration is correct.
    </p>

    <!-- Config Summary -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND['CARD_BG']};border:1px solid {BRAND['BORDER']};border-radius:14px;margin-bottom:24px;overflow:hidden;">
      <tr><td style="padding:16px 22px;border-bottom:1px solid #1a3a2c;">
        <p style="margin:0;font-size:11px;font-weight:700;color:{BRAND['EMERALD']};text-transform:uppercase;letter-spacing:1.5px;">⚙️ Configuration Details</p>
      </td></tr>
      <tr><td style="padding:8px 22px 16px;">
        {config_rows}
      </td></tr>
    </table>

    <!-- All systems -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:8px;">
      <tr>
        {check_cells}
      </tr>
    </table>

    {_divider}
    <p style="margin:0;font-size:13px;color:{BRAND['TEXT_DIM']};text-align:center;line-height:1.7;">
      You can configure notification preferences in your <a href="{BRAND['DASHBOARD']}/settings/notifications" style="color:{BRAND['PRIMARY']};">Dashboard Settings</a>.
    </p>
  """

    footer = email_footer(
        "This email was triggered manually from your Bijou AI dashboard settings panel.",
    )
    return email_wrap(header, body, footer)


__all__ = [
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
