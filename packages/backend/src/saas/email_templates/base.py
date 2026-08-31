"""
Bijou AI — Email Templates: Shared Base (Python port)
======================================================

Port of `bijou_templates/email-templates/shared/base.js`. Keep in sync when the
JS source changes. The 10 specific template bodies (verification, welcome,
trial-expiry, etc.) are NOT ported here — they live in JS only.

Brand Guide: 2026 Signal Gem edition.
Brand tokens (BJ_*) are the canonical palette — mirror of `--bj-*` CSS vars in
landing index.html and dashboard.html.
"""


# ---------------------------------------------------------------------------
# BRAND constants
# ---------------------------------------------------------------------------
BRAND = {
    # Asset URLs
    "LOGO": "https://mybijou.xyz/brand/logo.png",
    "QR":   "https://mybijou.xyz/brand/qr.png",

    # Signal Gem brand tokens — canonical. Do not rename or revalue.
    "BJ_GREEN": "#0B3B2E",
    "BJ_GOLD":  "#E3B457",
    "BJ_CREAM": "#F7F4EC",
    "BJ_INK":   "#0A0A0A",

    # Functional aliases — used inside the email templates. BJ_GOLD is the
    # primary brand action color (replaces the old indigo PRIMARY for CTAs).
    "PRIMARY":   "#E3B457",  # Signal Gem gold — CTAs, buttons, highlights
    "EMERALD":   "#10b981",  # Success, links, status
    "AMBER":     "#f59e0b",  # Urgency, warnings
    "GOLD":      "#E3B457",  # Brand wordmark accent
    "DARK_BG":   "#0A0A0A",  # Page background — Signal Gem ink
    "BODY_BG":   "#0B3B2E",  # Email body — Signal Gem green
    "CARD_BG":   "#0a1f19",  # Cards / boxes — derived darker green
    "FOOTER_BG": "#072A1F",  # Footer — deeper green
    "BORDER":    "#1e3a2f",  # Card borders — green-tinted
    "TEXT_MUTED": "#9aa7a4",
    "TEXT_DIM":   "#6b7370",
    "TEXT_LIGHT": "#F7F4EC",

    "APP_URL":  "https://app.mybijou.xyz",
    "SITE_URL": "https://mybijou.xyz",
    "SIGNUP":   "https://app.mybijou.xyz/signup",
    "DASHBOARD": "https://app.mybijou.xyz/dashboard",
    "GUIDE":    "https://app.mybijou.xyz/static/user-guide.html",
    "DECK":     "https://app.mybijou.xyz/static/sales-presentation.html",
    "SUPPORT":  "support@mybijou.xyz",
    "WHATSAPP": "https://wa.me/60174106981",
    "WA_NUM":   "+60 17-410 6981",
    "LINKEDIN": "https://linkedin.com/company/mybijou",
    "INSTAGRAM": "https://instagram.com/mybijouai",
    "TWITTER":  "https://x.com/meetbijou",
}


# ---------------------------------------------------------------------------
# Currency formatter
# ---------------------------------------------------------------------------
# Canonical currency symbol map. Brand canon is RM (Malaysian Ringgit). USD
# and EUR are here for defence-in-depth — if Stripe is ever mis-configured
# for a non-MYR currency, the rendered amount still matches the customer's
# actual charge instead of silently displaying the wrong symbol. Any code
# path that hard-codes a "$" prefix instead of going through this helper
# should be treated as a brand-canon bug.
_CURRENCY_SYMBOLS = {
    "myr": "RM",
    "usd": "$",
    "eur": "€",
    "gbp": "£",
    "sgd": "S$",
    "aud": "A$",
    "idr": "Rp",
}


def format_currency(amount: str, currency: str = "myr") -> str:
    """Format a numeric amount with the correct currency symbol/prefix.

    Args:
        amount:   Numeric string, e.g. "299.00" or "99". Non-numeric input
                  is returned unchanged (defensive — the caller may have
                  already pre-formatted it).
        currency: Lowercase ISO 4217 currency code. Unknown codes are
                  uppercased and used as a prefix (e.g. "JPY 1500").

    Returns:
        Formatted amount string, e.g. "RM 299.00" for myr/299.00,
        "$99.00" for usd/99.00, "MYR 299.00" if currency is "myr" but
        the symbol map ever needs to be bypassed.

    The space between symbol and number is intentional — it matches the
    canonical brand usage ("RM 299/mo", "RM299/mo" both appear in
    marketing; the email receipt uses spaced form for legibility).

    Idempotency: if `amount` already starts with a known currency prefix
    (from `_CURRENCY_SYMBOLS` values or any 3-letter alpha code), the
    function returns the input unchanged. This lets callers safely
    pre-format and pass through without risk of double-prefixing.
    """
    s = (amount or "").strip()
    if not s:
        return s
    # Idempotency check: if the first whitespace-separated token is a
    # known currency prefix (symbol like "RM"/"$"/"€" or 3-letter alpha
    # code like "MYR"/"USD"), return as-is. Prevents double-prefixing
    # when the caller already pre-formatted the amount.
    first_token = s.split(maxsplit=1)[0]
    if first_token in _CURRENCY_SYMBOLS.values() or (
        len(first_token) == 3 and first_token.isalpha()
    ):
        return s
    code = (currency or "myr").lower()
    symbol = _CURRENCY_SYMBOLS.get(code, code.upper())
    return f"{symbol} {s}"


# Backwards-compatible alias — internal callers and tests that imported the
# private name before it became public keep working.
_format_currency = format_currency


# ---------------------------------------------------------------------------
# Shared header
# ---------------------------------------------------------------------------
def email_header(badge_text: str = "") -> str:
    """Return the Signal Gem email header <tr>…</tr> row."""
    badge_html = ""
    if badge_text:
        badge_html = (
            f'<p style="margin:14px 0 0;display:inline-block;'
            f'background:rgba(227,180,87,0.18);border:1px solid rgba(227,180,87,0.4);'
            f'border-radius:20px;padding:5px 16px;font-size:12px;'
            f'color:{BRAND["GOLD"]};font-weight:600;">{badge_text}</p>'
        )
    return (
        '<tr><td style="background:linear-gradient(160deg,#072A1F 0%,#0B3B2E 55%,#0E4938 100%);'
        'border-radius:16px 16px 0 0;padding:36px 40px 28px;text-align:center;">'
        '<img src="' + BRAND["LOGO"] + '" alt="Bijou AI" width="56" height="56" '
        'style="display:block;margin:0 auto 14px;border-radius:12px;'
        'box-shadow:0 4px 24px rgba(0,0,0,0.4);" />'
        '<div>'
        f'<span style="font-size:26px;font-weight:900;color:{BRAND["GOLD"]};letter-spacing:-0.5px;">Bijou</span>'
        '<span style="font-size:26px;font-weight:900;color:#fff;">AI</span>'
        '</div>'
        '<p style="margin:5px 0 0;font-size:10px;color:#9aa7a4;font-weight:700;'
        'letter-spacing:2.5px;text-transform:uppercase;">Your Digital Employee &middot; by W3J</p>'
        f'{badge_html}'
        '</td></tr>'
    )


# ---------------------------------------------------------------------------
# Shared footer
# ---------------------------------------------------------------------------
def email_footer(
    unsubscribe_note: str = "You received this as part of your Bijou AI account activity.",
) -> str:
    """Return the Signal Gem email footer <tr>…</tr> row."""
    return (
        f'<tr><td style="background:{BRAND["FOOTER_BG"]};border-radius:0 0 16px 16px;'
        f'padding:24px 40px;text-align:center;border-top:1px solid #072A1F;">'
        '<p style="margin:0 0 10px;font-size:13px;">'
        f'<a href="{BRAND["LINKEDIN"]}" style="color:{BRAND["PRIMARY"]};text-decoration:none;font-weight:600;margin:0 8px;">LinkedIn</a>'
        '<span style="color:#1a3a2c;">·</span>'
        f'<a href="{BRAND["INSTAGRAM"]}" style="color:{BRAND["PRIMARY"]};text-decoration:none;font-weight:600;margin:0 8px;">Instagram</a>'
        '<span style="color:#1a3a2c;">·</span>'
        f'<a href="{BRAND["TWITTER"]}" style="color:{BRAND["PRIMARY"]};text-decoration:none;font-weight:600;margin:0 8px;">X (Twitter)</a>'
        '</p>'
        '<p style="margin:0 0 6px;font-size:11px;color:#6b7370;">'
        '<strong style="color:#9aa7a4;">Bijou AI</strong> is a product of '
        '<strong style="color:#9aa7a4;">W3J Sdn Bhd</strong> &nbsp;&middot;&nbsp; Kuala Lumpur, Malaysia'
        '</p>'
        '<p style="margin:0 0 6px;font-size:11px;color:#6b7370;">'
        f'<a href="{BRAND["SITE_URL"]}" style="color:{BRAND["EMERALD"]};text-decoration:none;">mybijou.xyz</a>'
        '&nbsp;&middot;&nbsp;'
        '<a href="https://w3j.my" style="color:' + BRAND["EMERALD"] + ';text-decoration:none;">w3j.my</a>'
        '&nbsp;&middot;&nbsp;'
        f'<a href="mailto:{BRAND["SUPPORT"]}" style="color:{BRAND["EMERALD"]};text-decoration:none;">{BRAND["SUPPORT"]}</a>'
        '</p>'
        f'<p style="margin:0;font-size:10px;color:#3a4a44;">{unsubscribe_note}</p>'
        '</td></tr>'
    )


# ---------------------------------------------------------------------------
# Full email wrapper
# ---------------------------------------------------------------------------
def email_wrap(header_row: str, body_content: str, footer_row: str) -> str:
    """Return the full <!DOCTYPE html>…</html> document."""
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '  <meta charset="UTF-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        '  <meta name="color-scheme" content="dark" />\n'
        '</head>\n'
        f'<body style="margin:0;padding:0;background:{BRAND["DARK_BG"]};'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Inter,Roboto,sans-serif;'
        'color:#e5e7eb;">\n'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND["DARK_BG"]};padding:40px 16px;">\n'
        '  <tr><td align="center">\n'
        '    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">\n'
        f'      {header_row}\n'
        f'      <tr><td style="background:{BRAND["BODY_BG"]};padding:40px;">\n'
        f'        {body_content}\n'
        '      </td></tr>\n'
        f'      {footer_row}\n'
        '    </table>\n'
        '  </td></tr>\n'
        '</table>\n'
        '</body>\n'
        '</html>'
    )


# ---------------------------------------------------------------------------
# CTA button
# ---------------------------------------------------------------------------
def cta_button(
    href: str,
    text: str,
    color: str = None,
    text_color: str = "#fff",
) -> str:
    """Return a centered Signal Gem gold CTA button block."""
    if color is None:
        color = BRAND["PRIMARY"]
    return (
        '<div style="text-align:center;margin:28px 0;">\n'
        f'  <a href="{href}" style="display:inline-block;background:{color};color:{text_color};'
        'text-decoration:none;font-weight:700;font-size:15px;padding:15px 40px;'
        f'border-radius:12px;letter-spacing:0.3px;box-shadow:0 8px 32px rgba(227,180,87,0.35);">{text}</a>\n'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Divider
# ---------------------------------------------------------------------------
divider = (
    '<table width="100%" cellpadding="0" cellspacing="0" style="margin:28px 0;">'
    '<tr><td style="border-top:1px solid #1a3a2c;"></td></tr></table>'
)


# ---------------------------------------------------------------------------
# Support row
# ---------------------------------------------------------------------------
def support_row(msg: str = "Need help? We're always here:") -> str:
    """Return a "Need help?" support contact block (used at bottom of body)."""
    return (
        divider
        + '<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">'
        + f'<p style="margin:0 0 8px;font-size:13px;color:{BRAND["TEXT_DIM"]};font-weight:600;">{msg}</p>'
        + f'<p style="margin:0;font-size:13px;color:{BRAND["TEXT_MUTED"]};">'
        + f'📧 <a href="mailto:{BRAND["SUPPORT"]}" style="color:{BRAND["EMERALD"]};text-decoration:none;">{BRAND["SUPPORT"]}</a>'
        + '&nbsp;&nbsp;|&nbsp;&nbsp;'
        + f'💬 <a href="{BRAND["WHATSAPP"]}" style="color:{BRAND["EMERALD"]};text-decoration:none;">{BRAND["WA_NUM"]}</a>'
        + '</p>'
        + '</td></tr></table>'
    )
