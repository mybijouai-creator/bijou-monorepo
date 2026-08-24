"""
Bijou AI - Email Service
========================

Handles all transactional emails with automatic multi-domain key rotation.

Sending domains (tried in order, rotates on HTTP 429 quota exhaustion):
  1. app.app.mybijou.xyz    — RESEND_API_KEY          (primary)
  2. getbijou.xyz   — RESEND_API_KEY_GETBIJOU
  3. mybijouai.xyz  — RESEND_API_KEY_MYBIJOUAI
  4. bijouboleh.xyz — RESEND_API_KEY_BIJOUBOLEH

On 429, the exhausted key is cooled down for 1 hour and the next key is
tried immediately — transparent to all callers.

Other environment variables:
  EMAIL_FROM     - Override primary sender address (optional)
  EMAIL_DOMAIN   - Primary sender domain fallback (default: app.app.mybijou.xyz)
  EMAIL_NOTIFY   - Internal notification recipient (optional)

Author: W3J Bijou AI
Version: 3.0.0 — multi-domain rotation
"""

import logging
import os
import time
from typing import Optional, Dict, Any, List

import httpx

from .email_templates import (
    BRAND as _BRAND,
    email_header as _email_header,
    email_footer as _email_footer,
    email_wrap as _email_wrap,
    cta_button as _cta_button,
    divider as _divider,
    support_row as _support_row,
    # Transactional builders (Signal Gem 2026 edition) — the real source of
    # truth for email content. These mirror the JS builders in
    # `bijou_templates/email-templates/0[1-9]-*.js` + `10-*.js` line-for-line.
    build_email_verification as _build_email_verification,
    build_welcome_trial_start as _build_welcome_trial_start,
    build_trial_expiry_warning as _build_trial_expiry_warning,
    build_trial_expired as _build_trial_expired,
    build_payment_confirmation as _build_payment_confirmation,
    build_dashboard_access as _build_dashboard_access,
    build_internal_signup_notify as _build_internal_signup_notify,
    build_magic_link_login as _build_magic_link_login,
    build_escalation_agent_notification as _build_escalation_agent_notification,
    build_settings_test_email as _build_settings_test_email,
)

logger = logging.getLogger(__name__)

# Resend API endpoint
RESEND_API_URL = "https://api.resend.com/emails"

# How long (seconds) to cool down a key after a 429 quota hit
_QUOTA_COOLDOWN_SECONDS = 3600  # 1 hour


class EmailService:
    """
    Service for sending transactional emails via Resend API.

    Supports automatic key rotation across up to 4 sending domains:
      1. app.app.mybijou.xyz    → RESEND_API_KEY          (primary)
      2. getbijou.xyz   → RESEND_API_KEY_GETBIJOU
      3. mybijouai.xyz  → RESEND_API_KEY_MYBIJOUAI
      4. bijouboleh.xyz → RESEND_API_KEY_BIJOUBOLEH

    On HTTP 429 (quota exhausted), the current key is marked as cooled-down
    for 1 hour and the next available key is tried automatically.
    """

    def __init__(self):
        self.notify_address: str = os.getenv("EMAIL_NOTIFY", "")

        # ------- Build ordered key pool -------
        # Each entry: {"key": str, "from": str, "domain": str}
        _raw_from = os.getenv("EMAIL_FROM", "")
        _primary_domain = os.getenv("EMAIL_DOMAIN", "app.app.mybijou.xyz")
        _primary_from = _raw_from if _raw_from else f"Bijou AI <hello@{_primary_domain}>"

        _pool_spec: List[Dict[str, str]] = [
            {
                "key": os.getenv("RESEND_API_KEY", ""),
                "from": _primary_from,
                "domain": _primary_domain,
            },
            {
                "key": os.getenv("RESEND_API_KEY_GETBIJOU", ""),
                "from": "Bijou AI <hello@getbijou.xyz>",
                "domain": "getbijou.xyz",
            },
            {
                "key": os.getenv("RESEND_API_KEY_MYBIJOUAI", ""),
                "from": "Bijou AI <hello@mybijouai.xyz>",
                "domain": "mybijouai.xyz",
            },
            {
                "key": os.getenv("RESEND_API_KEY_BIJOUBOLEH", ""),
                "from": "Bijou AI <hello@bijouboleh.xyz>",
                "domain": "bijouboleh.xyz",
            },
        ]

        # Only keep entries where a key is actually set
        self._key_pool: List[Dict[str, str]] = [
            e for e in _pool_spec if e["key"]
        ]

        # Primary api_key / from_address (for code that reads them directly)
        self.api_key: Optional[str] = self._key_pool[0]["key"] if self._key_pool else None
        self.from_address: str = self._key_pool[0]["from"] if self._key_pool else _primary_from

        # Quota cooldown tracker: key → unix timestamp when cooldown expires
        self._quota_exhausted_until: Dict[str, float] = {}

        if self._key_pool:
            domains = [e["domain"] for e in self._key_pool]
            logger.info(
                f"✅ EmailService initialised — {len(self._key_pool)} key(s) ready | "
                f"domains: {', '.join(domains)}"
            )
        else:
            logger.warning(
                "⚠️  No RESEND_API_KEY configured — email sending disabled"
            )

    # ------------------------------------------------------------------
    # Internal: key rotation
    # ------------------------------------------------------------------

    def _get_active_entry(self) -> Optional[Dict[str, str]]:
        """
        Return the first non-rate-limited key pool entry.
        Falls back to primary even if cooled-down (with a warning) if all are exhausted.
        """
        now = time.time()
        for entry in self._key_pool:
            exhausted_until = self._quota_exhausted_until.get(entry["key"], 0)
            if now >= exhausted_until:
                return entry

        # All keys are in cooldown — log and fall back to primary
        if self._key_pool:
            primary = self._key_pool[0]
            cooldown_remaining = int(
                self._quota_exhausted_until.get(primary["key"], 0) - now
            )
            logger.error(
                f"🚨 ALL Resend keys are quota-exhausted! Attempting primary key anyway. "
                f"Primary cooldown expires in ~{cooldown_remaining}s. "
                f"Consider upgrading Resend plans or spacing sends."
            )
            return primary
        return None

    def _mark_key_exhausted(self, key: str) -> None:
        """Mark a key as quota-exhausted for the cooldown period."""
        self._quota_exhausted_until[key] = time.time() + _QUOTA_COOLDOWN_SECONDS

    # ------------------------------------------------------------------
    # Core send helper
    # ------------------------------------------------------------------

    def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
    ) -> bool:
        """
        Send an email via the Resend REST API with automatic key rotation.

        On HTTP 429 from any key, that key is suspended for 1 hour and the
        next available domain key is tried immediately, up to all 4 keys.

        Args:
            to:        Recipient email address.
            subject:   Email subject line.
            html_body: HTML body content.
            text_body: Plain-text fallback (optional).

        Returns:
            True if the email was accepted by Resend (2xx response).
        """
        if not self._key_pool:
            logger.error("❌ Cannot send email — no RESEND_API_KEY configured")
            return False

        # Try each key in pool order, rotating on 429
        tried_keys: set = set()

        while True:
            entry = self._get_active_entry()
            if entry is None:
                logger.error(f"❌ No usable Resend key found for {to}")
                return False

            # Avoid infinite loop if somehow active entry keeps being the same exhausted one
            if entry["key"] in tried_keys:
                logger.error(
                    f"❌ All {len(self._key_pool)} Resend key(s) failed or exhausted "
                    f"for {to} | subject='{subject}'"
                )
                return False

            tried_keys.add(entry["key"])

            payload: Dict[str, Any] = {
                "from": entry["from"],
                "to": [to],
                "subject": subject,
                "html": html_body,
            }
            if text_body:
                payload["text"] = text_body

            try:
                response = httpx.post(
                    RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {entry['key']}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=15.0,
                )

                if response.status_code in (200, 201):
                    data = response.json()
                    logger.info(
                        f"✅ Email sent to {to} | subject='{subject}' | "
                        f"domain={entry['domain']} | id={data.get('id')}"
                    )
                    return True

                elif response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "~3600")
                    logger.warning(
                        f"🚫 Resend 429 quota hit on {entry['domain']} | "
                        f"to={to} | subject='{subject}' | Retry-After={retry_after}s | "
                        f"Rotating to next key..."
                    )
                    self._mark_key_exhausted(entry["key"])
                    # Loop: try next non-exhausted key

                else:
                    logger.error(
                        f"❌ Resend API error {response.status_code} on {entry['domain']} "
                        f"sending to {to} | subject='{subject}' | {response.text}"
                    )
                    return False

            except httpx.TimeoutException:
                logger.error(
                    f"❌ Resend API timeout on {entry['domain']} sending to {to}"
                )
                return False
            except Exception as exc:
                logger.error(
                    f"❌ Unexpected error sending email to {to} via {entry['domain']}: {exc}",
                    exc_info=True,
                )
                return False

    # ------------------------------------------------------------------
    # Brand shell helper  (private)
    # ------------------------------------------------------------------

    def _wrap(self, title: str, body: str, footer_note: str = "") -> str:
        """
        Wrap email body HTML in the Bijou AI dark brand shell.

        Now delegates to the shared Python helpers in `email_templates.base`,
        which mirror `bijou_templates/email-templates/shared/base.js` (the JS
        source of truth). Brand tokens are kept in lockstep — see rebrand-progress.md
        "Task 2: Brand palette consolidation" for the canonical values.
        """
        fn = footer_note or "You received this as a Bijou AI account holder."
        return _email_wrap(_email_header(title), body, _email_footer(fn))

    def _cta(self, href: str, text: str, color: str = None) -> str:
        """Render a Signal Gem gold CTA button block.

        `color` overrides the default Signal Gem gold; pass a CSS gradient or
        hex value. Defaults to BRAND.PRIMARY (Signal Gem gold).
        """
        return _cta_button(href, text, color=color or _BRAND["PRIMARY"])

    def _card(self, content: str, border_color: str = None, bg: str = None) -> str:
        """Render a dark info card block.

        Defaults to Signal Gem green-tinted card surface (matches the JS template).
        """
        bc = border_color or _BRAND["BORDER"]
        bg_ = bg or _BRAND["CARD_BG"]
        return f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:{bg_};border:1px solid {bc};border-radius:12px;margin-bottom:20px;overflow:hidden;">
  <tr><td style="padding:18px 22px;">{content}</td></tr>
</table>"""

    # ------------------------------------------------------------------
    # Transactional email methods (public interface — do not rename)
    # ------------------------------------------------------------------

    def send_verification_email(
        self,
        to: str,
        business_name: str,
        verification_token: str,
        public_url: str,
    ) -> bool:
        """Send email-verification link to a new sign-up."""

        verify_link = (
            f"{public_url}/api/onboarding/verify-email?token={verification_token}"
        )

        subject = "✅ Verify your email for Bijou AI"

        # Delegate to the new Signal Gem builder — keeps the brand consistent
        # with the JS templates and the rest of the customer-facing surface.
        html_body = _build_email_verification(
            name=business_name,
            verify_url=verify_link,
            expiry_mins=30,
        )

        first = business_name.split()[0] if business_name else "there"
        text_body = (
            f"Welcome to Bijou AI!\n\n"
            f"Hi {first}!\n\n"
            f"Please verify your email by visiting:\n{verify_link}\n\n"
            f"This link expires in 30 minutes.\n\n"
            f"Need help? WhatsApp us at +60 17-410 6981\n\n"
            f"Bijou AI — app.mybijou.xyz"
        )

        return self.send_email(to, subject, html_body, text_body)

    def send_welcome_email(
        self,
        to: str,
        business_name: str,
        onboarding_url: str,
    ) -> bool:
        """Send welcome email after email is verified."""

        subject = f"🚀 Fuyoh, welcome aboard, {business_name}! Your trial starts now"

        # Delegate to the Signal Gem builder. `trial_ends=None` is intentional —
        # the JS template conditionally hides the trial-end line when the
        # parameter is None, which is the right behaviour for a brand-new signup
        # (the dashboard will tell them when their trial ends).
        html_body = _build_welcome_trial_start(
            name=business_name,
            business_name=business_name,
            trial_ends=None,
        )

        text_body = (
            f"Fuyoh, welcome aboard, {business_name}!\n\n"
            f"Your Bijou AI trial is now active (14 days, no credit card).\n\n"
            f"Continue setup at: {onboarding_url}\n\n"
            f"Need help? WhatsApp us at +60 17-410 6981\n\n"
            f"Bijou AI — app.mybijou.xyz"
        )

        return self.send_email(to, subject, html_body, text_body)

    def send_trial_expiry_warning(
        self,
        to: str,
        business_name: str,
        days_remaining: int,
        upgrade_url: str,
    ) -> bool:
        """Send trial expiry warning (7d, 3d, 1d before expiry)."""

        if days_remaining == 1:
            emoji = "🚨"
        elif days_remaining <= 3:
            emoji = "⚠️"
        elif days_remaining <= 7:
            emoji = "⏰"
        else:
            emoji = "📅"

        day_word = "day" if days_remaining == 1 else "days"
        subject = f"{emoji} Your Bijou AI trial expires in {days_remaining} {day_word}!"

        # Delegate to the Signal Gem builder. The urgency tier (1d/3d/7d/30d)
        # is handled inside the builder via `days_left`.
        trial_end_date = (
            f"in {days_remaining} {day_word}"
            if days_remaining > 1
            else "tomorrow"
        )
        html_body = _build_trial_expiry_warning(
            name=business_name,
            days_left=days_remaining,
            trial_ends=trial_end_date,
            upgrade_url=upgrade_url,
        )

        text_body = (
            f"Your Bijou AI trial expires in {days_remaining} {day_word}!\n\n"
            f"Hi {business_name}, upgrade now to keep your AI assistant running:\n{upgrade_url}\n\n"
            f"Need help? WhatsApp us at +60 17-410 6981"
        )

        return self.send_email(to, subject, html_body, text_body)

    def send_trial_expired_email(
        self,
        to: str,
        business_name: str,
        upgrade_url: str,
    ) -> bool:
        """Send email when the trial period has ended."""

        subject = "😢 Your Bijou AI trial has ended — Reactivate now"

        # Delegate to the Signal Gem builder. Default 7-day grace period.
        html_body = _build_trial_expired(
            name=business_name,
            upgrade_url=upgrade_url,
            grace_days=7,
        )

        text_body = (
            f"Your Bijou AI trial has ended.\n\n"
            f"Hi {business_name}, your AI assistant is paused. "
            f"Reactivate at {upgrade_url} to resume.\n\n"
            f"Your conversation data is safe for 30 days. Need help? WhatsApp us at +60 17-410 6981"
        )

        return self.send_email(to, subject, html_body, text_body)

    def send_payment_confirmation(
        self,
        to: str,
        business_name: str,
        plan_name: str,
        amount: str,
        invoice_url: str,
    ) -> bool:
        """Send payment confirmation after a successful Stripe charge."""

        subject = f"✅ Payment confirmed — Welcome to Bijou AI {plan_name}!"

        # Delegate to the Signal Gem builder. invoice_id and date are
        # positional, so we thread invoice_url into both slots for now —
        # the JS template is flexible on these and the customer only ever
        # cares about the download link.
        html_body = _build_payment_confirmation(
            name=business_name,
            plan=plan_name,
            amount=amount,
            invoice_id=invoice_url,
            billing_date="",
            next_billing="",
            invoice_url=invoice_url,
        )

        text_body = (
            f"Payment confirmed — Welcome to Bijou AI {plan_name}!\n\n"
            f"Hi {business_name}, your subscription is now active.\n"
            f"Amount: {amount}\n"
            f"Download invoice: {invoice_url}\n\n"
            f"Open your dashboard: https://app.mybijou.xyz/dashboard"
        )

        return self.send_email(to, subject, html_body, text_body)


    def send_dashboard_access_email(
        self,
        to: str,
        business_name: str,
        dashboard_url: str,
    ) -> bool:
        """
        Send dashboard access link after subscription is activated.

        Args:
            to:            Recipient email address.
            business_name: Tenant's business name.
            dashboard_url: Full URL (with access token) to the tenant's dashboard.

        Returns:
            True if email sent successfully.
        """
        subject = "🚀 Your Bijou AI Dashboard is Ready!"

        # Delegate to the Signal Gem builder. `plan` is optional; pass empty
        # string when the caller doesn't supply it.
        html_body = _build_dashboard_access(
            name=business_name,
            business_name=business_name,
            plan="",
            login_url=dashboard_url,
        )

        text_body = (
            f"Your Bijou AI dashboard is ready!\n\n"
            f"Hi {business_name}, your subscription is now active.\n"
            f"Open your dashboard: {dashboard_url}\n\n"
            f"Need help? WhatsApp us at +60 17-410 6981"
        )

        return self.send_email(to, subject, html_body, text_body)


    def send_login_magic_link(
        self,
        to: str,
        business_name: str,
        magic_link_url: str,
    ) -> bool:
        """
        Send a branded magic-link login email.

        Args:
            to:             Recipient email address.
            business_name:  Tenant's business name (used for personalisation).
            magic_link_url: Full magic-link URL (includes token + tenant_id).

        Returns:
            True if sent successfully.
        """
        subject = "Your Bijou AI Login Link"

        # Delegate to the Signal Gem builder.
        html_body = _build_magic_link_login(
            name=business_name,
            magic_url=magic_link_url,
            expiry_mins=15,
            ip_hint=None,
            device_hint=None,
        )

        text_body = (
            f"Log in to your Bijou AI dashboard\n\n"
            f"Hi {business_name}, click the link below to access your dashboard:\n"
            f"{magic_link_url}\n\n"
            f"This link expires in 15 minutes. If you did not request this, ignore this email."
        )

        return self.send_email(to, subject, html_body, text_body)


    def send_internal_signup_notification(
        self,
        name: str,
        email: str,
        phone: Optional[str] = None,
        company: Optional[str] = None,
        industry: Optional[str] = None,
        source: Optional[str] = None,
        plan: Optional[str] = None,
    ) -> bool:
        """
        Send an internal 'new signup' notification to EMAIL_NOTIFY.

        Wraps the Signal Gem internal-signup template (the one with
        WhatsApp + Supabase quick-actions). Use this instead of
        send_internal_notification() for new signup events specifically.

        Args:
            name:    Sign-up's full name.
            email:   Sign-up's email address.
            phone:   Optional phone (E.164 or local).
            company: Optional company / business name.
            industry:Optional industry / vertical.
            source:  Optional acquisition source (e.g. 'organic', 'meta-ads').
            plan:    Optional plan chosen at signup (e.g. 'Starter', 'Pro').

        Returns:
            True if sent, False if EMAIL_NOTIFY not configured or send fails.
        """
        if not self.notify_address:
            logger.debug("EMAIL_NOTIFY not set — skipping internal signup notification")
            return False

        subject = f"🎯 New Bijou signup: {name} ({email})"
        html_body = _build_internal_signup_notify(
            name=name,
            email=email,
            phone=phone,
            company=company,
            industry=industry,
            source=source,
            plan=plan,
        )
        return self.send_email(self.notify_address, subject, html_body)

    def send_settings_test_email(
        self,
        to: str,
        name: str,
        smtp_host: str = None,
        email_from: str = None,
    ) -> bool:
        """
        Send a "test SMTP configuration" email from the Settings page.

        Delegates to the Signal Gem builder so the test message looks the
        same as a real Bijou AI email (helps the user verify their config
        end-to-end rather than just a generic "OK" message).

        Args:
            to:         Recipient email address.
            name:       User's display name.
            smtp_host:  Optional SMTP host string (e.g. 'smtp.resend.com').
            email_from: Optional From address used in the test send.

        Returns:
            True if sent, False on send failure.
        """
        subject = "\U0001f9ea Test email from Bijou AI settings"
        html_body = _build_settings_test_email(
            name=name,
            smtp_host=smtp_host,
            email_from=email_from,
        )
        text_body = (
            f"Hi {name}, this is a test email from your Bijou AI settings page. "
            f"If you received this, your email configuration is working."
        )
        return self.send_email(to, subject, html_body, text_body)

    def send_escalation_agent_notification(
        self,
        agent_name: str,
        customer_name: str,
        customer_phone: str,
        issue: str,
        escalation_id: str,
        chat_snippet: list = None,
        priority: str = "high",
        response_url: str = None,
    ) -> bool:
        """
        Send an escalation alert to the assigned human agent.

        Delegates to the Signal Gem escalation template so the agent gets
        a consistent, brand-correct alert (priority badge, customer contact,
        chat snippet, one-tap "Open chat" link).

        Args:
            agent_name:     Display name of the on-call agent.
            customer_name:  Customer's display name.
            customer_phone: Customer's phone (E.164).
            issue:          Short one-line issue description.
            escalation_id:  Escalation record id (used in response_url).
            chat_snippet:   Optional list of recent chat lines.
            priority:       'low' | 'normal' | 'high' | 'urgent' (default 'high').
            response_url:   Optional dashboard URL to open the chat directly.

        Returns:
            True if sent, False on send failure.
        """
        subject = f"\U0001f6a8 [{priority.upper()}] Bijou escalation \u2014 {customer_name}"
        html_body = _build_escalation_agent_notification(
            agent_name=agent_name,
            customer_name=customer_name,
            customer_phone=customer_phone,
            issue=issue,
            escalation_id=escalation_id,
            chat_snippet=chat_snippet,
            priority=priority,
            response_url=response_url,
        )
        return self.send_email(self.notify_address, subject, html_body)

    # ------------------------------------------------------------------
    # Backwards-compatible aliases (legacy callers / smoke tests)
    # ------------------------------------------------------------------
    def send_escalation_alert(self, *args, **kwargs):
        """Alias for send_escalation_agent_notification (legacy callers)."""
        return self.send_escalation_agent_notification(*args, **kwargs)

    def send_settings_test(self, to, name, smtp_host=None, email_from=None):
        """Alias for send_settings_test_email (legacy callers)."""
        return self.send_settings_test_email(
            to=to, name=name, smtp_host=smtp_host, email_from=email_from,
        )

    def send_internal_notification(
        self,
        subject: str,
        body: str,
    ) -> bool:
        """
        Send an internal notification email to EMAIL_NOTIFY address.
        Useful for new sign-ups, payment events, escalations etc.

        Args:
            subject: Notification subject.
            body:    Plain-text body.

        Returns:
            True if sent, False if EMAIL_NOTIFY not configured or send fails.
        """
        if not self.notify_address:
            logger.debug("EMAIL_NOTIFY not set — skipping internal notification")
            return False

        card_body = self._card(
            f"<pre style='margin:0;font-family:monospace;font-size:13px;color:#10b981;white-space:pre-wrap;line-height:1.6;'>{body}</pre>",
            border_color="#064e3b", bg="#022c22"
        )
        html_body = self._wrap("Internal Notification", card_body,
                               "Internal Bijou AI system notification — do not forward.")
        return self.send_email(self.notify_address, subject, html_body, body)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Return (or create) the global EmailService singleton."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
