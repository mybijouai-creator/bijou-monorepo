// BIJOU AI - Lead Capture API Endpoint
// Saves lead to Supabase + sends confirmation email via Resend
// Fires server-side PostHog events on success/failure.

import { createClient } from "@supabase/supabase-js";
import { Resend } from "resend";
import { checkRateLimit } from "../lib/rateLimit.js";
import { logTypoWarning } from "../lib/env.js";
import { captureServer, identifyServer, distinctIdFromReq } from "../lib/posthog-server.js";

logTypoWarning();

// Map any incoming source to a valid DB source value
const VALID_SOURCES = [
  "hero_form",
  "cal_booking",
  "waitlist",
  "whatsapp_cta",
  "website",
  "referral",
];
function normaliseSource(raw) {
  if (!raw) return "website";
  const s = raw.toLowerCase();
  if (VALID_SOURCES.includes(s)) return s;
  if (s.includes("hero")) return "hero_form";
  if (s.includes("wait")) return "waitlist";
  if (s.includes("whats")) return "whatsapp_cta";
  if (s.includes("cal")) return "cal_booking";
  if (s.includes("referral")) return "referral";
  return "website";
}

const LOGO_URL = "https://mybijou.xyz/brand/logo.png";
const QR_URL = "https://mybijou.xyz/brand/qr.png";

function emailBase(headerContent, bodyContent) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#e5e7eb;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- HEADER -->
        <tr><td style="background:linear-gradient(135deg,#052e16,#064e3b,#065f46);border-radius:16px 16px 0 0;padding:36px 40px 28px;text-align:center;">
          <img src="${LOGO_URL}" alt="Bijou AI" width="52" height="52" style="display:block;margin:0 auto 14px;border-radius:10px;" />
          <div style="display:inline-flex;align-items:center;gap:6px;">
            <span style="font-size:24px;font-weight:900;color:#d4af37;letter-spacing:-0.5px;">Bijou</span><span style="font-size:24px;font-weight:900;color:#ffffff;">AI</span>
          </div>
          <p style="margin:6px 0 0;font-size:11px;color:#6ee7b7;font-weight:700;letter-spacing:2px;text-transform:uppercase;">Your Digital Employee · by W3J</p>
          ${headerContent}
        </td></tr>

        <!-- BODY -->
        <tr><td style="background:#0f172a;padding:40px;">
          ${bodyContent}

          <!-- RESOURCES BOX -->
          <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #1e3a5f;border-radius:14px;overflow:hidden;margin-bottom:32px;">
            <tr><td style="background:#0a1628;padding:20px 24px;border-bottom:1px solid #1e3a5f;">
              <p style="margin:0;font-size:13px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:1px;">📦 Your Bijou Resources</p>
            </td></tr>
            <tr><td style="padding:20px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="40" style="vertical-align:top;padding-top:2px;"><span style="font-size:20px;">🚀</span></td>
                  <td style="padding-bottom:16px;">
                    <p style="margin:0 0 4px;font-size:14px;font-weight:700;color:#fff;">Create Your Account</p>
                    <p style="margin:0 0 6px;font-size:13px;color:#94a3b8;">30-day money-back guarantee, no credit card required</p>
                    <a href="https://app.mybijou.xyz/signup" style="color:#10b981;font-size:13px;font-weight:600;text-decoration:none;">app.mybijou.xyz/signup →</a>
                  </td>
                </tr>
                <tr>
                  <td width="40" style="vertical-align:top;padding-top:2px;"><span style="font-size:20px;">📖</span></td>
                  <td style="padding-bottom:16px;">
                    <p style="margin:0 0 4px;font-size:14px;font-weight:700;color:#fff;">User Guide</p>
                    <p style="margin:0 0 6px;font-size:13px;color:#94a3b8;">Step-by-step onboarding &amp; setup walkthrough</p>
                    <a href="https://app.mybijou.xyz/static/user-guide.html" style="color:#10b981;font-size:13px;font-weight:600;text-decoration:none;">View User Guide →</a>
                  </td>
                </tr>
                <tr>
                  <td width="40" style="vertical-align:top;padding-top:2px;"><span style="font-size:20px;">📊</span></td>
                  <td>
                    <p style="margin:0 0 4px;font-size:14px;font-weight:700;color:#fff;">Sales Presentation</p>
                    <p style="margin:0 0 6px;font-size:13px;color:#94a3b8;">See exactly how Bijou AI works for your business</p>
                    <a href="https://app.mybijou.xyz/static/sales-presentation.html" style="color:#10b981;font-size:13px;font-weight:600;text-decoration:none;">View Slide Deck →</a>
                  </td>
                </tr>
              </table>
            </td></tr>
          </table>

          <!-- SUPPORT -->
          <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #1e293b;padding-top:24px;">
            <tr>
              <td align="center">
                <p style="margin:0 0 10px;font-size:13px;color:#64748b;font-weight:600;">Need help? We're always here:</p>
                <p style="margin:0 0 6px;font-size:13px;color:#94a3b8;">
                  📧 <a href="mailto:support@mybijou.xyz" style="color:#10b981;text-decoration:none;">support@mybijou.xyz</a>
                  &nbsp;&nbsp;|&nbsp;&nbsp;
                  💬 <a href="https://wa.me/60174106981" style="color:#10b981;text-decoration:none;">+60 17-410 6981</a>
                </p>
              </td>
            </tr>
          </table>
        </td></tr>

        <!-- FOOTER -->
        <tr><td style="background:#020617;border-radius:0 0 16px 16px;padding:20px 40px;text-align:center;border-top:1px solid #0f172a;">
          <p style="margin:0 0 6px;font-size:11px;color:#334155;">
            <strong style="color:#475569;">Bijou AI</strong> is a product of <strong style="color:#475569;">W3J Sdn Bhd</strong> &nbsp;·&nbsp; Kuala Lumpur, Malaysia
          </p>
          <p style="margin:0 0 6px;font-size:11px;color:#334155;">
            <a href="https://mybijou.xyz" style="color:#10b981;text-decoration:none;">mybijou.xyz</a>
            &nbsp;·&nbsp;
            <a href="https://w3j.my" style="color:#10b981;text-decoration:none;">w3j.my</a>
          </p>
          <p style="margin:0 0 8px;font-size:11px;color:#334155;">
            <a href="https://linkedin.com/company/mybijou" style="color:#6366f1;text-decoration:none;">LinkedIn</a>
            &nbsp;·&nbsp;
            <a href="https://instagram.com/mybijouai" style="color:#6366f1;text-decoration:none;">Instagram</a>
            &nbsp;·&nbsp;
            <a href="https://x.com/meetbijou" style="color:#6366f1;text-decoration:none;">X (Twitter)</a>
          </p>
          <p style="margin:0;font-size:10px;color:#1e293b;">
            You received this because you submitted your details at mybijou.xyz
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>`;
}

function buildConfirmationEmail(name, company) {
  const firstName = (name || company || "Boss").split(" ")[0];

  const header = `<p style="margin:16px 0 0;font-size:13px;color:#a7f3d0;">Interest confirmed ✓</p>`;

  const body = `
    <h2 style="margin:0 0 6px;font-size:22px;font-weight:800;color:#fff;">
      Fuyoh, we got your details! 🎉
    </h2>
    <p style="margin:0 0 24px;font-size:15px;color:#94a3b8;line-height:1.7;">
      Hi <strong style="color:#e2e8f0;">${firstName}</strong>, thank you for your interest in Bijou AI!<br/>
      Our team will reach out within <strong style="color:#10b981;">24 hours</strong> to discuss how we can automate your business.
    </p>

    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a1628;border:1px solid #1e3a5f;border-radius:14px;padding:0;margin-bottom:28px;overflow:hidden;">
      <tr><td style="padding:20px 24px;border-bottom:1px solid #1e3a5f;">
        <p style="margin:0;font-size:13px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:1px;">⚡ What happens next?</p>
      </td></tr>
      <tr><td style="padding:20px 24px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td width="32" style="vertical-align:top;padding-top:1px;"><span style="display:inline-block;background:#064e3b;color:#10b981;border-radius:50%;width:22px;height:22px;text-align:center;line-height:22px;font-size:11px;font-weight:800;">1</span></td>
              <td style="padding-bottom:14px;font-size:13px;color:#94a3b8;line-height:1.5;">Our team reviews your details and prepares a personalised demo for your industry</td></tr>
          <tr><td width="32" style="vertical-align:top;padding-top:1px;"><span style="display:inline-block;background:#064e3b;color:#10b981;border-radius:50%;width:22px;height:22px;text-align:center;line-height:22px;font-size:11px;font-weight:800;">2</span></td>
              <td style="padding-bottom:14px;font-size:13px;color:#94a3b8;line-height:1.5;">We WhatsApp you to schedule a quick 15-minute walkthrough</td></tr>
          <tr><td width="32" style="vertical-align:top;padding-top:1px;"><span style="display:inline-block;background:#064e3b;color:#10b981;border-radius:50%;width:22px;height:22px;text-align:center;line-height:22px;font-size:11px;font-weight:800;">3</span></td>
              <td style="font-size:13px;color:#94a3b8;line-height:1.5;">You decide if Bijou is right for you — zero pressure, boss!</td></tr>
        </table>
      </td></tr>
    </table>

    <div style="text-align:center;margin-bottom:28px;">
      <a href="https://app.mybijou.xyz/signup" style="display:inline-block;background:linear-gradient(135deg,#4f46e5,#6366f1);color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:14px 36px;border-radius:12px;">
        Start Free Trial →
      </a>
      <p style="margin:10px 0 0;font-size:11px;color:#475569;">30-day money-back · No credit card · Cancel anytime</p>
    </div>

    <!-- QR CODE -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:8px;">
      <tr><td align="center">
        <p style="margin:0 0 10px;font-size:12px;color:#64748b;">Scan to visit mybijou.xyz on your phone:</p>
        <img src="${QR_URL}" alt="mybijou.xyz QR Code" width="110" height="110" style="display:block;margin:0 auto;border-radius:10px;" />
      </td></tr>
    </table>
  `;

  return emailBase(header, body);
}

function buildResourcesEmail(name) {
  const firstName = (name || "Boss").split(" ")[0];

  const header = `<p style="margin:16px 0 0;font-size:13px;color:#a7f3d0;">Resources sent ✓</p>`;

  const body = `
    <h2 style="margin:0 0 6px;font-size:22px;font-weight:800;color:#fff;">
      Here are your Bijou AI resources! 📦
    </h2>
    <p style="margin:0 0 28px;font-size:15px;color:#94a3b8;line-height:1.7;">
      Hi <strong style="color:#e2e8f0;">${firstName}</strong>, everything you need to explore Bijou AI is below — slide deck, user guide, and your onboarding link. Take your time, boss!
    </p>
  `;

  return emailBase(header, body);
}

export default async function handler(req, res) {
  // SECURITY (2026-07-20): CORS tightened from wildcard to known-origin
  // allowlist. See audit-report.md finding #6.
  const requestOrigin = req.headers.origin || "";
  const allowedOrigins = new Set([
    "https://mybijou.xyz",
    "https://app.mybijou.xyz",
    "https://staging.mybijou.xyz",
  ]);
  if (allowedOrigins.has(requestOrigin) || requestOrigin.startsWith("http://localhost:")) {
    res.setHeader("Access-Control-Allow-Origin", requestOrigin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  res.setHeader("Access-Control-Max-Age", "86400");

  if (req.method === "OPTIONS") return res.status(200).json({ ok: true });
  if (req.method !== "POST") {
    res.setHeader("Allow", ["POST", "OPTIONS"]);
    return res.status(405).json({ error: "Method not allowed" });
  }

  // Rate limit BEFORE any I/O so a flood of leads can't burn the
  // Supabase write quota or the Resend free tier. See lib/rateLimit.js
  // for setup (Upstash env vars optional; in-process fallback otherwise).
  const rl = await checkRateLimit(req, { bucket: "leads" });
  if (!rl.ok) {
    res.setHeader("Retry-After", String(rl.retryAfterSeconds));
    return res
      .status(429)
      .json({ error: "Too many requests", code: "RATE_LIMITED" });
  }

  try {
    const {
      name,
      email,
      phone = "",
      company = "",
      industry = "",
      source = "website",
      marketing_consent = false,
    } = req.body;

    // Validation
    if (!email) {
      return res
        .status(400)
        .json({ error: "Email is required", code: "MISSING_EMAIL" });
    }
    // Email regex. Allows `+` in the local part (e.g. john+test@gmail.com),
    // escapes the dash in the middle of a char class, and requires a 2+
    // char TLD. Matches the pattern used in api/onboarding/signup.js.
    const emailRegex = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/;
    if (!emailRegex.test(email)) {
      return res.status(400).json({
        error: "Please provide a valid email address",
        code: "INVALID_EMAIL",
      });
    }
    if (!name && !company) {
      return res
        .status(400)
        .json({ error: "Name or company is required", code: "MISSING_NAME" });
    }

    const leadData = {
      name: (name || company).trim(),
      email: email.toLowerCase().trim(),
      phone: phone.trim() || null,
      company: company.trim() || null,
      industry: industry || null,
      source: normaliseSource(source),
      marketing_consent: Boolean(marketing_consent),
      status: "new",
      lead_score: 30,
    };

    // ── 1. Save to Supabase ──────────────────────────────────────────────────
    let leadId = null;
    let supabaseError = null;
    const supabaseUrl =
      process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL;
    const supabaseKey =
      process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;

    if (supabaseUrl && supabaseKey) {
      try {
        const supabase = createClient(supabaseUrl, supabaseKey);
        const { data, error } = await supabase
          .from("leads")
          .insert(leadData)
          .select("id")
          .single();

        if (error) {
          // Duplicate email - still send email, just don't crash
          if (error.code === "23505") {
            console.warn("Duplicate lead email:", email);
            supabaseError = "duplicate";
          } else {
            console.error("Supabase insert error:", error);
            supabaseError = error.code || "supabase_error";
          }
        } else {
          leadId = data?.id;
          console.log("✅ Lead saved:", leadId);
        }
      } catch (dbErr) {
        console.error("Supabase error (non-fatal):", dbErr);
        supabaseError = "exception";
      }
    } else {
      console.warn(
        "⚠️  SUPABASE_URL / SUPABASE_SERVICE_KEY not set — skipping DB save",
      );
    }

    // ── 2. Send confirmation email via Resend ────────────────────────────────
    const resendKey = process.env.RESEND_API_KEY;
    if (resendKey) {
      try {
        const resend = new Resend(resendKey);
        const emailFrom =
          process.env.EMAIL_FROM || "Bijou AI <hello@mybijou.xyz>";

        // Confirmation to lead
        await resend.emails.send({
          from: emailFrom,
          to: leadData.email,
          subject: `Your Bijou AI details are confirmed! 🤖`,
          html: buildConfirmationEmail(leadData.name, leadData.company),
        });
        console.log("✅ Confirmation email sent to:", leadData.email);

        // Notification to owner
        const notifyEmail = process.env.EMAIL_NOTIFY;
        if (notifyEmail) {
          await resend.emails
            .send({
              from: emailFrom,
              to: notifyEmail,
              subject: `🎯 New Lead: ${leadData.name} (${leadData.company || leadData.source})`,
              html: `<p><strong>Name:</strong> ${leadData.name}</p>
<p><strong>Email:</strong> ${leadData.email}</p>
<p><strong>Phone:</strong> ${leadData.phone || "N/A"}</p>
<p><strong>Company:</strong> ${leadData.company || "N/A"}</p>
<p><strong>Source:</strong> ${leadData.source}</p>
<p><strong>Time:</strong> ${new Date().toLocaleString("en-MY", { timeZone: "Asia/Kuala_Lumpur" })} MYT</p>`,
            })
            .catch((e) =>
              console.warn("Owner notify email failed:", e.message),
            );
        }

        // Mark email sent in DB
        if (leadId && supabaseUrl && supabaseKey) {
          const supabase = createClient(supabaseUrl, supabaseKey);
          await supabase
            .from("leads")
            .update({ email_sent_at: new Date().toISOString() })
            .eq("id", leadId);
        }
      } catch (emailErr) {
        console.error("Resend error (non-fatal):", emailErr);
      }
    } else {
      console.warn("⚠️  RESEND_API_KEY not set — skipping confirmation email");
    }

    // ── 3. Notify owner via WhatsApp (server-to-server, non-blocking) ───────
    // SECURITY (2026-07-20): Previously this called the public /api/send
    // endpoint, which was an unauthenticated open proxy. We now go directly
    // to the Fly.io backend with the shared `INTERNAL_API_TOKEN` secret.
    // See audit-report.md finding #1.
    const internalToken = process.env.INTERNAL_API_TOKEN;
    if (internalToken) {
      try {
        await fetch("https://bijou-production.fly.dev/api/send", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Internal-Token": internalToken,
          },
          body: JSON.stringify({
            to: "60174106981@s.whatsapp.net",
            message: `🎯 NEW LEAD!\n\nName: ${leadData.name}\nEmail: ${leadData.email}\nPhone: ${leadData.phone || "N/A"}\nCompany: ${leadData.company || "N/A"}\nSource: ${leadData.source}\n\nCheck Supabase dashboard for full details.`,
          }),
        });
      } catch (notifErr) {
        console.warn("WhatsApp notification skipped:", notifErr.message);
      }
    } else {
      console.warn(
        "⚠️  INTERNAL_API_TOKEN not set — skipping WhatsApp owner-notify",
      );
    }

    // Fire PostHog events (server-side, after Supabase + Resend so the
    // `lead_id` is real and the funnel reads correctly).
    await emitLeadEvents({ req, leadData, leadId, supabaseError });

    // 2026-08-22 FIX: this used to hardcode isNewLead: true always, so a
    // returning prospect whose email already exists (supabaseError ===
    // "duplicate") got the identical generic success response as a brand
    // new lead — the frontend's dedicated "Already Part of the Family"
    // duplicate UI (OnboardingModal.tsx createErrorState) could never
    // render because response.ok was always true and no signal said which
    // case this was. isNewLead now reflects the real outcome.
    const isDuplicate = supabaseError === "duplicate";
    return res.status(200).json({
      success: true,
      message: isDuplicate
        ? "Looks like you're already with us! Check your email, or WhatsApp us if you need help."
        : "Thank you! Check your email for confirmation.",
      leadId: leadId || "temp-" + Date.now(),
      isNewLead: !isDuplicate,
      code: isDuplicate ? "DUPLICATE_EMAIL" : undefined,
    });
  } catch (error) {
    console.error("❌ Lead capture error:", error);
    // PostHog: server-side error tracking (no PII)
    await captureServer(distinctIdFromReq(req), "api_error", {
      endpoint: "/api/leads",
      kind: error?.name || "error",
      message: String(error?.message || error).slice(0, 200),
    });
    return res.status(500).json({
      error: "Server error occurred",
      message: "Please try again in a moment",
      code: "INTERNAL_ERROR",
    });
  }
}

// --- PostHog hooks (run AFTER the response is sent) --------------------------
// Vercel serverless: we can keep using `await captureServer` since the call
// is non-blocking and posthog-node flushes in the background.
async function emitLeadEvents({ req, leadData, leadId, supabaseError }) {
  try {
    // Identify the user with PostHog so the lead_captured event attributes
    // to a stable distinctId = the lead's email (hashed for privacy? — we
    // use raw email; PostHog's default is to hash in their UI but the data
    // model stores the email as-is. Flip to hash if you want stricter
    // privacy.)
    const distinctId = `email:${leadData.email}`;
    await identifyServer(distinctId, {
      email: leadData.email,
      name: leadData.name,
      company: leadData.company || undefined,
      industry: leadData.industry || undefined,
      source: leadData.source,
      marketing_consent: leadData.marketing_consent,
      lead_id: leadId || undefined,
      created_at: new Date().toISOString(),
    });
    await captureServer(distinctId, "lead_captured", {
      source: leadData.source,
      industry: leadData.industry || undefined,
      has_phone: Boolean(leadData.phone),
      has_company: Boolean(leadData.company),
      lead_id: leadId || undefined,
      supabase_error: supabaseError || undefined,
      // Mirror the request meta for funnels
      ip_distinct_id: distinctIdFromReq(req),
      ua: req.headers?.["user-agent"]?.slice(0, 100) || undefined,
    });
  } catch (e) {
    console.warn("[posthog:server] lead event emit failed:", e?.message || e);
  }
}
