// api/agents.js — Agent fleet dispatch (single Vercel function)
//
// Per GROWTH-TO-50.md plan §3: SCOUT, SCORER, OUTREACH, PILLAR + review-queue.
// Consolidated into ONE Vercel function (Hobby plan: 12 functions max).
// Routes via `?action=<name>` query parameter.
//
// Endpoints (all under /api/agents):
//   GET/POST /api/agents?action=scout              - 8 hard-coded seed prospects (test data)
//   GET/POST /api/agents?action=scout-real         - gateway LLM-suggested prospects
//   GET/POST /api/agents?action=overpass-scout     - real prospects from OpenStreetMap (free, no key)
//   GET/POST /api/agents?action=purge-fake-drafts  - expire drafts linked to manual_seed prospects
//   GET      /api/agents?action=scorer             - list unscored
//   POST     /api/agents?action=scorer             body: { prospect_id?, limit?, concurrency? }
//   POST     /api/agents?action=outreach           body: { prospect_id?, limit?, include_seed? }
//   GET/POST /api/agents?action=outreach-topfit    body: { min_fit?, limit? }   only fit>=min_fit
//   POST     /api/agents?action=pillar             body: { topic, real_evidence? }
//   GET      /api/agents?action=review-queue       ?status=pending
//   POST     /api/agents?action=review-queue       body: { id, action }  (approve|reject)
//   POST     /api/agents?action=review-queue-mark-sent  body: { id }
//   POST     /api/agents?action=review-queue-expire
//
// Hard rules (plan §0 + §3):
//   * No scraping of personal data. Business listings only.
//   * OUTREACH writes to review_queue. A human clicks send. No exceptions.
//   * Never cold WhatsApp. Email + IG DM only.
//
// 2026-07-30: JSON parse retry, parallel scorer, IG channel routing,
//             overpass-scout, outreach-topfit, purge-fake-drafts added.

import { createClient } from "@supabase/supabase-js";

const supabase = (url, key) =>
  createClient(url, key, { auth: { persistSession: false } });

function ok(res, body) { return res.status(200).json({ ok: true, ...body }); }
function err(res, code, message, detail) {
  return res.status(code).json({ ok: false, error: message, detail });
}

async function callGateway(systemPrompt, userPrompt, opts = {}) {
  // Phase 1: route through the new AI Model Router. Keep the same signature
  // (system, user, opts) so call sites don't need to change.
  const { callAI } = await import("../backend/ai-router.cjs");
  const task = opts.task || "chat";
  const maxRetries = opts.maxRetries ?? 2;
  let lastErr = null;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const r = await callAI({
      task,
      payload: {
        system: systemPrompt,
        messages: [{ role: "user", content: userPrompt }],
        max_tokens: opts.max_tokens || 800,
        temperature: opts.temperature ?? 0.7,
      },
    });
    if (!r.ok) {
      lastErr = new Error(r.error || "router call failed");
      if (attempt < maxRetries) continue;
      throw lastErr;
    }
    const cleaned = String(r.text || "").replace(/^```json?\s*/i, "").replace(/```$/i, "").trim();
    if (!cleaned) {
      lastErr = new Error("router returned empty content");
      if (attempt < maxRetries) continue;
      throw lastErr;
    }
    try {
      return JSON.parse(cleaned);
    } catch (parseErr) {
      const repaired = repairJson(cleaned);
      if (repaired) return repaired;
      lastErr = parseErr;
      if (attempt < maxRetries) {
        opts = { ...opts, temperature: Math.max(0, (opts.temperature ?? 0.7) - 0.2) };
        continue;
      }
      throw parseErr;
    }
  }
  throw lastErr || new Error("callGateway failed");
}

// Best-effort JSON repair for the common LLM unterminated-string case.
// Tries to find a balanced object ending, then truncates there.
function repairJson(s) {
  if (!s) return null;
  // Try to find the first balanced JSON object in the string.
  let depth = 0, inStr = false, esc = false, start = -1, end = -1;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (esc) { esc = false; continue; }
    if (c === "\\") { esc = true; continue; }
    if (c === '"') { inStr = !inStr; continue; }
    if (inStr) continue;
    if (c === "{") { if (start < 0) start = i; depth++; }
    else if (c === "}") { depth--; if (depth === 0 && start >= 0) { end = i; break; } }
  }
  if (end > start) {
    try { return JSON.parse(s.slice(start, end + 1)); } catch { return null; }
  }
  return null;
}

function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "https://mybijou.xyz");
  res.setHeader("Vary", "Origin");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Cron-Secret, Authorization");
  res.setHeader("Access-Control-Max-Age", "86400");
}

// ----------------------------------------------------------------------------
// SCOUT
// ----------------------------------------------------------------------------

const SCOUT_SEED = [
  { id: "klcc-aes-001", business_name: "Dr. ABC Aesthetics KLCC", vertical: "aesthetic_clinic", area: "KLCC" },
  { id: "klcc-aes-002", business_name: "[seed: aesthetic clinic 2]", vertical: "aesthetic_clinic", area: "KLCC" },
  { id: "mk-aes-001", business_name: "Mont Kiara Skin Clinic", vertical: "aesthetic_clinic", area: "Mont Kiara" },
  { id: "bsr-aes-001", business_name: "Bangsar Aesthetic Co.", vertical: "aesthetic_clinic", area: "Bangsar" },
  { id: "pj-den-001", business_name: "PJ Dental Specialist", vertical: "dental_clinic", area: "Petaling Jaya" },
  { id: "pj-den-002", business_name: "[seed: dental clinic 2]", vertical: "dental_clinic", area: "Petaling Jaya" },
  { id: "sub-den-001", business_name: "Subang Jaya Dental Care", vertical: "dental_clinic", area: "Subang Jaya" },
  { id: "dam-den-001", business_name: "Damansara Heights Dental", vertical: "dental_clinic", area: "Damansara Heights" },
];

async function handleScout(req, res, db) {
  const expected = process.env.SCOUT_CRON_SECRET;
  if (expected && req.headers["x-cron-secret"] !== expected) {
    return err(res, 401, "Unauthorized");
  }
  const { data: runRow, error: runErr } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "scout",
      trigger_kind: req.method === "POST" ? "cron" : "manual",
      status: "running",
      model: "manual_seed_v1",
      prompt_version: "2026-07-30",
    })
    .select("id").single();
  if (runErr) return err(res, 500, "Failed to start run", runErr.message);
  const runId = runRow.id;
  let inserted = 0;
  const errors = [];
  for (const s of SCOUT_SEED) {
    const { error } = await db
      .from("bjx_prospects")
      .upsert({
        source: "manual_seed",
        source_id: s.id,
        source_url: `https://mybijou.xyz/#/admin/outreach-queue?p=${s.id}`,
        business_name: s.business_name,
        vertical: s.vertical,
        area: s.area,
        city: "Kuala Lumpur",
        country: "Malaysia",
      }, { onConflict: "source,source_id", ignoreDuplicates: true });
    if (error) errors.push({ id: s.id, error: error.message });
    else inserted += 1;
  }
  await db.from("bjx_agent_runs").update({
    finished_at: new Date().toISOString(),
    status: errors.length === 0 ? "ok" : "error",
    items_in: SCOUT_SEED.length,
    items_out: inserted,
    error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
  }).eq("id", runId);
  return ok(res, {
    run_id: runId,
    seeds_total: SCOUT_SEED.length,
    inserted,
    skipped: SCOUT_SEED.length - inserted - errors.length,
    errors: errors.length,
  });
}

// ----------------------------------------------------------------------------
// SCORER
// ----------------------------------------------------------------------------

const SCORER_SYSTEM = `You are Bijou AI's prospect scoring agent. Evaluate Malaysian
SME businesses (aesthetic & dental clinics, Klang Valley) for fit with Bijou's
RM299/mo Manglish-first chatbot for appointment-driven businesses.

Score 5 binary signals, each true/false, with a one-sentence reasoning:
- appointment_driven
- active_whatsapp
- owner_reachable
- evidence_missed_enquiries
- active_online_presence

Output JSON only:
{ "appointment_driven": bool, "active_whatsapp": bool, "owner_reachable": bool, "evidence_missed_enquiries": bool, "active_online_presence": bool, "reasoning": str }`;

function scoreUserPrompt(p) {
  return `Business to score:
- Name: ${p.business_name}
- Vertical: ${p.vertical || "unknown"}
- Area: ${p.area || "Klang Valley"}, ${p.city || "Kuala Lumpur"}
- Instagram: ${p.instagram_handle || "not on file"}
- Facebook: ${p.facebook_page_url || "not on file"}
- Website: ${p.website || "not on file"}
- Has WhatsApp Business: ${p.has_whatsapp_business}
- Has online booking: ${p.has_booking_link}
- Public evidence notes: ${p.evidence_notes || "none captured"}

Score the 5 signals. JSON only.`;
}

function computeScore(s) {
  return (
    (s.appointment_driven ? 30 : 0) +
    (s.active_whatsapp ? 20 : 0) +
    (s.owner_reachable ? 20 : 0) +
    (s.evidence_missed_enquiries ? 20 : 0) +
    (s.active_online_presence ? 10 : 0)
  );
}

async function handleScorerList(res, db) {
  const { data, error } = await db
    .from("bjx_prospects")
    .select("id, business_name, vertical, area, status")
    .eq("status", "new")
    .order("created_at", { ascending: true })
    .limit(50);
  if (error) return err(res, 500, error.message);
  return ok(res, { unscored: data, count: data.length });
}

async function handleScorerRun(req, res, db) {
  const prospectId = req.body?.prospect_id;
  const limit = parseInt(req.body?.limit || (prospectId ? 1 : 25), 10);
  const concurrency = parseInt(req.body?.concurrency || "4", 10);
  let query = db
    .from("bjx_prospects")
    .select("*").eq("status", "new").limit(limit);
  if (prospectId) query = query.eq("id", prospectId);
  const { data: prospects, error: qErr } = await query;
  if (qErr) return err(res, 500, qErr.message);
  if (!prospects?.length) return ok(res, { scored: 0 });

  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "scorer", trigger_kind: "manual", status: "running",
      model: "auto/best-fast", prompt_version: "2026-07-30", items_in: prospects.length,
    })
    .select("id").single();

  let scored = 0;
  const errors = [];
  // Process in parallel (capped at `concurrency` to be polite to the gateway).
  for (let i = 0; i < prospects.length; i += concurrency) {
    const batch = prospects.slice(i, i + concurrency);
    await Promise.all(batch.map(async (p) => {
      try {
        const s = await callGateway(SCORER_SYSTEM, scoreUserPrompt(p), { temperature: 0.2, max_tokens: 400, task: 'scorer' });
        const fit = computeScore(s);
        const { error: insErr } = await db
          .from("bjx_prospect_scores")
          .insert({
            prospect_id: p.id, fit_score: fit,
            appointment_driven: !!s.appointment_driven,
            active_whatsapp: !!s.active_whatsapp,
            owner_reachable: !!s.owner_reachable,
            evidence_missed_enquiries: !!s.evidence_missed_enquiries,
            active_online_presence: !!s.active_online_presence,
            model: "auto/best-fast", prompt_version: "2026-07-30",
            reasoning: s.reasoning || null,
          });
        if (insErr) { errors.push({ prospect_id: p.id, error: insErr.message }); return; }
        const newStatus = fit < 30 ? "rejected" : "scored";
        await db.from("bjx_prospects").update({
          status: newStatus,
          rejection_reason: newStatus === "rejected" ? `fit_score ${fit} < 30` : null,
          updated_at: new Date().toISOString(),
        }).eq("id", p.id);
        scored += 1;
      } catch (e) {
        errors.push({ prospect_id: p.id, error: String(e?.message || e) });
      }
    }));
  }
  if (runRow?.id) {
    await db.from("bjx_agent_runs").update({
      finished_at: new Date().toISOString(),
      status: errors.length === 0 ? "ok" : "error",
      items_out: scored,
      error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
    }).eq("id", runRow.id);
  }
  return ok(res, { scored, errors: errors.length, error_detail: errors });
}

// ----------------------------------------------------------------------------
// OUTREACH
// ----------------------------------------------------------------------------

const OUTREACH_SYSTEM = `You are Bijou AI's outreach agent for the Malaysian SME market.
Write a personalised first-touch DM/email in Manglish for a single prospect.
Target vertical: aesthetic or dental clinic in Klang Valley.
Voice: warm, professional, never spammy. Reference one specific thing you noticed.

Output JSON: { subject, body, channel, reasoning }
- subject: <60 chars, no emojis (only when channel='email')
- body: <300 words, max 2 emoji, max 1 'lah', no "boleh tahu" or "no hal"
- channel: 'email' | 'instagram_dm' (pick the one the user prompt hints at)
- reasoning: 1-sentence why this opener fits

Do NOT include marketing claims that aren't true. Do NOT offer discounts.
For Instagram DM: no subject line, opener should be casual, max 2-3 short paragraphs.
For email: include subject, full body with sign-off.`;

function outreachUserPrompt(p) {
  const channelHint = p.instagram_handle
    ? "Instagram DM (the prospect is active on Instagram, so reach them there)"
    : "Email (no Instagram on file, so reach them via email)";
  return `Prospect:
- Business: ${p.business_name}
- Vertical: ${p.vertical || "unknown"}
- Area: ${p.area || "Klang Valley"}, ${p.city || "Kuala Lumpur"}
- Instagram: ${p.instagram_handle || "not on file"}
- Facebook: ${p.facebook_page_url || "not on file"}
- Website: ${p.website || "not on file"}
- Has WhatsApp Business: ${p.has_whatsapp_business}
- Has online booking: ${p.has_booking_link}
- Evidence: ${p.evidence_notes || "no specific evidence captured"}

CHANNEL HINT: ${channelHint}

Write the first-touch draft. JSON only, no markdown fences.`;
}

async function handleOutreach(req, res, db) {
  const prospectId = req.body?.prospect_id;
  const includeSeed = req.body?.include_seed === true;
  const limit = parseInt(req.body?.limit || (prospectId ? 1 : 10), 10);
  let query = db
    .from("bjx_prospects")
    .select("*")
    .in("status", ["new", "scored", "queued"])
    .limit(prospectId ? 1 : limit);
  if (prospectId) query = query.eq("id", prospectId);
  // Default: skip manual_seed prospects (test data, not real businesses)
  if (!includeSeed) query = query.neq("source", "manual_seed");
  const { data: prospects, error: qErr } = await query;
  if (qErr) return err(res, 500, qErr.message);
  if (!prospects?.length) return ok(res, { generated: 0, message: "No prospects to process" });

  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "outreach", trigger_kind: "manual", status: "running",
      model: "auto/best-fast", prompt_version: "2026-07-30", items_in: prospects.length,
    })
    .select("id").single();

  let generated = 0;
  const errors = [];
  // Run in parallel (capped at 4 concurrent to be polite to the gateway)
  const CONCURRENCY = 4;
  for (let i = 0; i < prospects.length; i += CONCURRENCY) {
    const batch = prospects.slice(i, i + CONCURRENCY);
    await Promise.all(batch.map(async (p) => {
      try {
        const draft = await callGateway(OUTREACH_SYSTEM, outreachUserPrompt(p), { max_tokens: 600, task: 'outreach' });
        const payload = {
          prospect: {
            id: p.id, business_name: p.business_name, area: p.area,
            vertical: p.vertical, instagram_handle: p.instagram_handle,
            facebook_page_url: p.facebook_page_url,
          },
          channel: draft.channel || (p.instagram_handle ? "instagram_dm" : "email"),
          subject: draft.subject || null,
          body: draft.body || "",
          reasoning: draft.reasoning || null,
        };
        const { error: insErr } = await db
          .from("bjx_review_queue")
          .insert({
            item_type: "outreach_dm", payload,
            source_agent: "outreach", source_prospect_id: p.id,
            source_model: "auto/best-fast", priority: 60,
          });
        if (insErr) { errors.push({ prospect_id: p.id, error: insErr.message }); return; }
        await db.from("bjx_prospects")
          .update({ status: "queued", updated_at: new Date().toISOString() })
          .eq("id", p.id);
        generated += 1;
      } catch (e) {
        errors.push({ prospect_id: p.id, error: String(e?.message || e) });
      }
    }));
  }
  if (runRow?.id) {
    await db.from("bjx_agent_runs").update({
      finished_at: new Date().toISOString(),
      status: errors.length === 0 ? "ok" : "error",
      items_out: generated,
      error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
    }).eq("id", runRow.id);
  }
  return ok(res, { generated, errors: errors.length, error_detail: errors });
}

// ----------------------------------------------------------------------------
// PILLAR
// ----------------------------------------------------------------------------

const PILLAR_DEFAULT_TOPICS = [
  "Why Malaysian aesthetic clinics lose 30% of bookings to missed WhatsApp messages",
  "The 3am enquiry: a clinic owner's most expensive missed call",
  "From reception to revenue: how an AI Manglish agent doubles a clinic's after-hours bookings",
  "Hot, warm, cold: a clinic owner's lead-temperature cheat sheet",
  "Why we built Bijou in Manglish (and why your chatbot should too)",
];

const PILLAR_SYSTEM = `You are Bijou AI's content agent for the Malaysian SME market.
Voice: Manglish, warm, never cringe. Real numbers, real stories, real advice.
Banned phrases: "game-changer", "unlock potential", "revolutionary", "delve into",
"navigate the landscape", "in today's fast-paced world", "leverage", "synergy".
Manglish rules: max 2 'lah' per post, no "boleh tahu", no "no hal",
never start a sentence with "So,".

Output JSON only. No markdown fences. Shape:
{
  "pillar": { "title": str, "body_markdown": str, "word_count": int },
  "atoms": {
    "facebook": { "text": str, "hashtags": [str] },
    "instagram": { "text": str, "hashtags": [str] },
    "linkedin":  { "text": str },
    "tiktok_caption": { "text": str, "hashtags": [str] },
    "threads":  { "text": str },
    "reel_script": { "hook_3s": str, "beats": [str], "caption": str },
    "email":    { "subject": str, "body_markdown": str }
  }
}`;

function pillarUserPrompt(topic, realEvidence) {
  return `Topic: ${topic}

REAL EVIDENCE (must be referenced or the pillar is rejected):
${realEvidence || "(none provided — write a 'frame' pillar that the founder can fill in with a real story later)"}

Audience: Malaysian aesthetic & dental clinic owners. Klang Valley first.
Length: pillar body 800-1200 words. Atoms: 60-150 words each.
Include: one Manglish-voice line, one specific MY detail (RM, location, time), one CTA.`;
}

async function handlePillar(req, res, db) {
  const body = req.body || {};
  const topic = body.topic || PILLAR_DEFAULT_TOPICS[Math.floor(Math.random() * PILLAR_DEFAULT_TOPICS.length)];
  const realEvidence = body.real_evidence || null;
  const language = body.language || "manglish";

  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "pillar", trigger_kind: "manual", status: "running",
      model: "auto/best-fast", prompt_version: "2026-07-30",
    })
    .select("id").single();

  try {
    const out = await callGateway(
      PILLAR_SYSTEM, pillarUserPrompt(topic, realEvidence),
      { temperature: 0.8, max_tokens: 4000, task: 'pillar' }
    );
    if (!out?.pillar?.title || !out?.pillar?.body_markdown) {
      throw new Error("Pillar output missing required fields");
    }
    const { data: pillarRow, error: pErr } = await db
      .from("bjx_content_drafts")
      .insert({
        kind: "pillar_longform", language, platform: "blog",
        title: out.pillar.title, body: out.pillar.body_markdown,
        word_count: out.pillar.word_count || out.pillar.body_markdown.split(/\s+/).length,
        status: "draft", model: "auto/best-fast", prompt_version: "2026-07-30",
      })
      .select("id").single();
    if (pErr) throw new Error(`pillar insert: ${pErr.message}`);

    const atoms = out.atoms || {};
    const platformMap = {
      facebook: "facebook", instagram: "instagram", linkedin: "linkedin",
      tiktok_caption: "tiktok", threads: "threads", reel_script: "tiktok", email: "email",
    };
    const atomRows = [];
    for (const [k, v] of Object.entries(atoms)) {
      if (!v) continue;
      const platform = platformMap[k] || "facebook";
      const isEmail = k === "email";
      atomRows.push({
        kind: isEmail ? "email" : k.startsWith("reel") ? "reel_script" : "social_post",
        language, platform,
        title: isEmail ? v.subject : null,
        body: isEmail ? v.body_markdown : (v.text || v.caption || ""),
        hashtags: v.hashtags || null,
        pillar_id: pillarRow.id, status: "draft",
        model: "auto/best-fast", prompt_version: "2026-07-30",
      });
    }
    if (atomRows.length > 0) {
      const { error: aErr } = await db
        .from("bjx_content_drafts")
        .insert(atomRows);
      if (aErr) throw new Error(`atoms insert: ${aErr.message}`);
    }
    if (runRow?.id) {
      await db.from("bjx_agent_runs").update({
        finished_at: new Date().toISOString(), status: "ok",
        items_out: 1 + atomRows.length,
      }).eq("id", runRow.id);
    }
    return ok(res, { pillar_id: pillarRow.id, atom_count: atomRows.length, topic, language });
  } catch (e) {
    if (runRow?.id) {
      await db.from("bjx_agent_runs").update({
        finished_at: new Date().toISOString(), status: "error",
        error: String(e?.message || e).slice(0, 1000),
      }).eq("id", runRow.id);
    }
    return err(res, 500, String(e?.message || e));
  }
}

// ----------------------------------------------------------------------------
// REVIEW QUEUE
// ----------------------------------------------------------------------------

async function handleReviewQueueList(req, res, db) {
  const status = String(req.query.status || "pending");
  const limit = Math.min(parseInt(req.query.limit || "100", 10), 500);
  const { data, error } = await db
    .from("bjx_review_queue")
    .select("id, created_at, item_type, payload, source_agent, source_prospect_id, source_model, priority, status, expires_at")
    .eq("status", status)
    .order("priority", { ascending: false })
    .order("created_at", { ascending: true })
    .limit(limit);
  if (error) return err(res, 500, error.message);
  return ok(res, { items: data, count: data.length });
}

async function handleReviewQueueAct(req, res, db) {
  const { id, action, reason } = req.body || {};
  if (!id || !action) return err(res, 400, "id and action required");
  if (action === "approve") {
    const { data, error } = await db
      .from("bjx_review_queue")
      .update({ status: "approved", approved_at: new Date().toISOString(), approved_by: "founder" })
      .eq("id", id).select("id, status, approved_at").single();
    if (error) return err(res, 500, error.message);
    return ok(res, { item: data });
  }
  if (action === "reject") {
    const { data, error } = await db
      .from("bjx_review_queue")
      .update({ status: "rejected", rejection_reason: reason || "no reason given" })
      .eq("id", id).select("id, status, rejection_reason").single();
    if (error) return err(res, 500, error.message);
    return ok(res, { item: data });
  }
  return err(res, 400, "action must be 'approve' or 'reject'");
}

async function handleMarkSent(req, res, db) {
  const { id } = req.body || {};
  if (!id) return err(res, 400, "id required");
  const { data, error } = await db
    .from("bjx_review_queue")
    .update({ status: "sent", sent_at: new Date().toISOString() })
    .eq("id", id).select("id, status, sent_at").single();
  if (error) return err(res, 500, error.message);
  const item = await db
    .from("bjx_review_queue")
    .select("source_prospect_id, payload").eq("id", id).single();
  if (item?.data?.source_prospect_id) {
    const p = item.data.payload || {};
    await db.from("bjx_touches").insert({
      prospect_id: item.data.source_prospect_id,
      channel: p.channel || "email", direction: "outbound", message_kind: "first_touch",
      subject: p.subject || null, body_excerpt: (p.body || "").slice(0, 500),
      sent_by: "founder", sent_at: new Date().toISOString(),
    });
    await db.from("bjx_prospects")
      .update({ status: "touched", updated_at: new Date().toISOString() })
      .eq("id", item.data.source_prospect_id);
  }
  return ok(res, { item: data });
}

async function handleExpire(res, db) {
  const { data, error } = await db
    .from("bjx_review_queue")
    .update({ status: "expired" })
    .eq("status", "pending")
    .lt("expires_at", new Date().toISOString())
    .select("id");
  if (error) return err(res, 500, error.message);
  return ok(res, { expired: data?.length || 0 });
}

// ----------------------------------------------------------------------------
// PIPELINE SUMMARY — single-call dashboard for the founder
// Returns counts per stage + recent runs + next cron fires
// ----------------------------------------------------------------------------

async function handlePipelineSummary(res, db) {
  // Counts (cheap aggregate)
  const counts = {};
  const tables = [
    "bjx_prospects", "bjx_prospect_scores", "bjx_touches",
    "bjx_content_drafts", "bjx_review_queue", "bjx_listener_opportunities",
    "bjx_agent_runs",
  ];
  for (const t of tables) {
    try {
      const r = await db.from(t).select("id", { count: "exact", head: true });
      counts[t.replace("bjx_", "")] = r.count || 0;
    } catch { counts[t.replace("bjx_", "")] = "?"; }
  }
  // Prospect status breakdown
  const { data: prospects } = await db.from("bjx_prospects").select("status");
  const byStatus = (prospects || []).reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    return acc;
  }, {});
  // Review queue by status
  const { data: queue } = await db.from("bjx_review_queue").select("status, item_type");
  const queueByStatus = (queue || []).reduce((acc, r) => {
    const k = `${r.item_type}:${r.status}`;
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
  // Last 10 agent runs
  const { data: runs } = await db
    .from("bjx_agent_runs")
    .select("agent_name, status, items_in, items_out, created_at, finished_at, error")
    .order("created_at", { ascending: false })
    .limit(10);
  // Last 5 review queue items
  const { data: recentItems } = await db
    .from("bjx_review_queue")
    .select("id, created_at, item_type, payload, source_prospect_id, status")
    .eq("status", "pending")
    .order("created_at", { ascending: false })
    .limit(5);
  return ok(res, {
    counts,
    prospects_by_status: byStatus,
    review_queue_breakdown: queueByStatus,
    recent_runs: runs || [],
    recent_items: (recentItems || []).map((i) => ({
      id: i.id,
      created_at: i.created_at,
      item_type: i.item_type,
      prospect_id: i.source_prospect_id,
      prospect_name: i.payload?.prospect?.business_name,
      channel: i.payload?.channel,
      subject: i.payload?.subject,
    })),
  });
}

// ----------------------------------------------------------------------------
// EXTEND OFFER — mark a prospect as "case_study_offer_extended" with the
// standard plan §5 terms: 3 months free in exchange for case-study + numbers.
// Triggered manually by the founder after a warm reply.
// ----------------------------------------------------------------------------

const CASE_STUDY_OFFER_TERMS = {
  free_months: 3,
  in_exchange_for: [
    "Anonymised booking + reply numbers (monthly, 3 months)",
    "A 30-min case-study interview (recorded, your approval before publish)",
    "A written testimonial (your name + clinic name, or anonymous)",
    "Right to publish: 'Klinik X recovered N after-hours bookings in month 1'",
  ],
  starts_on: "your first day of setup",
  ends_on: "3 months from start",
  upgrade_after: "RM 299/month after the 3 months, or cancel anytime",
};

async function handleRouterStatus(res) {
  const { routerStatus } = await import("../backend/ai-router.cjs");
  const s = await routerStatus();
  return ok(res, s);
}

async function handleDebugRaw(req, res) {
  const { callAI } = await import("../backend/ai-router.cjs");
  const { task = "scorer", message = "Score this business: Klinik Gigi Bangsar. Output JSON: {appointment_driven:true,active_whatsapp:true,owner_reachable:true,evidence_missed_enquiries:true,active_online_presence:true,reasoning:\"dental clinic in KL\"}" } = req.body || {};
  const r = await callAI({
    task,
    payload: {
      system: "You are a JSON scorer. Output valid JSON only. No thinking out loud.",
      messages: [{ role: "user", content: message }],
      max_tokens: 1500,
      temperature: 0.1,
    },
  });
  return ok(res, {
    ok: r.ok,
    provider: r.provider_used,
    model: r.model_used,
    tokens: r.tokens,
    latency_ms: r.latency_ms,
    cost_usd: r.cost_usd,
    text_length: r.text?.length || 0,
    text_preview: (r.text || '').substring(0, 500),
    text_full: r.text || '',
    error: r.error,
    fallback_chain: r.fallback_chain,
  });
}

async function handleChatTest(req, res) {
  // Replicates api/chat.js to debug why the chat endpoint returns the error fallback
  const { callAI } = await import("../backend/ai-router.cjs");
  const fs = await import("fs");
  const path = await import("path");
  const chatPath = path.join(process.cwd(), "api", "chat.js");
  let sys = "You are Bijou.";
  try {
    const src = fs.readFileSync(chatPath, "utf8");
    const m = src.match(/const systemInstruction = `([\s\S]*?)`;/);
    if (m) sys = m[1];
  } catch (e) {
    sys = `(could not read api/chat.js: ${e.message})`;
  }
  const r = await callAI({
    task: "chat",
    payload: {
      system: sys,
      messages: [{ role: "user", content: "hi" }],
      max_tokens: 1500,
      temperature: 0.7,
    },
  });
  return ok(res, {
    ok: r.ok,
    provider: r.provider_used,
    model: r.model_used,
    tokens: r.tokens,
    latency_ms: r.latency_ms,
    cost_usd: r.cost_usd,
    sys_prompt_len: sys.length,
    text_length: r.text?.length || 0,
    text_preview: (r.text || '').substring(0, 800),
    text_full: r.text || '',
    error: r.error,
    fallback_chain: r.fallback_chain,
  });
}

async function handleExtendOffer(req, res, db) {
  const { prospect_id, notes } = req.body || {};
  if (!prospect_id) return err(res, 400, "prospect_id required");
  const { data, error } = await db
    .from("bjx_prospects")
    .update({
      status: "case_study_offer",
      rejection_reason: null,
      updated_at: new Date().toISOString(),
    })
    .eq("id", prospect_id)
    .select("id, business_name, status")
    .single();
  if (error) return err(res, 500, error.message);
  // Note in agent_runs for traceability
  await db.from("bjx_agent_runs").insert({
    agent_name: "founder",
    trigger_kind: "manual",
    status: "ok",
    items_in: 1,
    items_out: 1,
    model: "human",
    prompt_version: "2026-07-30",
    finished_at: new Date().toISOString(),
    error: notes || null,
  });
  return ok(res, { prospect: data, offer_terms: CASE_STUDY_OFFER_TERMS });
}

// ----------------------------------------------------------------------------
// LISTENER — Reddit r/malaysia (no auth, no TOS issues)
// Per plan §3: "LISTENER — Monitors FB groups + Reddit r/malaysia + Lowyat for
// people complaining about missed messages / front desk load. Flags real-time
// reply opportunities."
// MVP (2026-07-30): Reddit public JSON API only.
// ----------------------------------------------------------------------------

const LISTENER_KEYWORDS = [
  "missed call", "missed message", "no reply", "no response",
  "front desk", "receptionist", "booking", "appointment",
  "clinic", "salon", "spa", "restaurant", "agent", "ai",
  "automate", "whatsapp", "customer service", "late reply",
];
const LISTENER_SUBREDDITS = ["malaysia", "klangvalley", "klcc"];
const LISTENER_LIMIT = 25;
const LISTENER_REQUEST_DELAY_MS = 2500;   // pause between subreddits so Reddit doesn't 429
const LISTENER_MAX_RETRIES = 3;
const LISTENER_RETRY_BASE_MS = 5000;     // exponential backoff base

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchSubredditPosts(subreddit) {
  // Reddit JSON API now requires OAuth. Use the public RSS feed instead.
  // The endpoint returns 429 (rate limit) under load; retry with exponential backoff
  // and respect the Retry-After header when Reddit sends one.
  const url = `https://www.reddit.com/r/${subreddit}/new/.rss?limit=${LISTENER_LIMIT}`;
  const headers = {
    "User-Agent": "Mozilla/5.0 (compatible; BijouListener/1.0; +https://mybijou.xyz)",
    Accept: "application/atom+xml, application/xml",
  };
  let lastErr = null;
  for (let attempt = 0; attempt < LISTENER_MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      const backoff = LISTENER_RETRY_BASE_MS * Math.pow(2, attempt - 1);
      console.warn(`[listener] r/${subreddit}: retry ${attempt}/${LISTENER_MAX_RETRIES - 1} in ${backoff}ms`);
      await sleep(backoff);
    }
    let xml;
    try {
      xml = await fetch(url, { headers });
    } catch (e) {
      lastErr = e;
      continue;
    }
    if (xml.ok) {
      const text = await xml.text();
      // Light XML parse — extract <entry> blocks with title, content, link, author
      const entries = [];
      const entryRe = /<entry>([\s\S]*?)<\/entry>/g;
      let m;
      while ((m = entryRe.exec(text))) {
        const e = m[1];
        const title = (e.match(/<title>([\s\S]*?)<\/title>/) || [])[1] || "";
        const content = (e.match(/<content[^>]*>([\s\S]*?)<\/content>/) || [])[1] || "";
        const link = (e.match(/<link[^>]*href="([^"]+)"/) || [])[1] || "";
        const author = (e.match(/<author>\s*<name>([^<]+)<\/name>/) || [])[1] || "";
        entries.push({
          title: title.replace(/<!\[CDATA\[|\]\]>/g, "").trim(),
          selftext: content.replace(/<!\[CDATA\[|\]\]>/g, "").replace(/<[^>]+>/g, "").trim(),
          permalink: link,
          author,
        });
      }
      return entries;
    }
    lastErr = new Error(`Reddit ${subreddit}: ${xml.status}`);
    // Only retry on 429 (rate limit) and 5xx (transient); 4xx other than 429 are permanent
    if (xml.status !== 429 && xml.status < 500) break;
  }
  throw lastErr || new Error(`Reddit ${subreddit}: unknown error`);
}

function detectPainSignals(text) {
  const lower = String(text || "").toLowerCase();
  return LISTENER_KEYWORDS.filter((kw) => lower.includes(kw));
}

async function handleListener(req, res, db) {
  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "listener", trigger_kind: "cron", status: "running",
      model: "keyword+gateway", prompt_version: "2026-07-30",
    })
    .select("id").single();

  const posts = [];
  const errors = [];
  for (let i = 0; i < LISTENER_SUBREDDITS.length; i++) {
    const sub = LISTENER_SUBREDDITS[i];
    if (i > 0) {
      // Pace requests to stay well under Reddit's rate limit (60 req/min unauth).
      await sleep(LISTENER_REQUEST_DELAY_MS);
    }
    try {
      const list = await fetchSubredditPosts(sub);
      for (const p of list) {
        const text = `${p.title || ""} ${p.selftext || ""}`;
        const signals = detectPainSignals(text);
        if (signals.length === 0) continue;
        posts.push({
          source: "reddit",
          source_url: `https://reddit.com${p.permalink}`,
          source_group: `r/${sub}`,
          post_excerpt: text.slice(0, 800),
          post_author_handle: p.author ? `u/${p.author}` : null,
          pain_signals: signals,
          match_score: Math.min(100, signals.length * 25),
        });
      }
    } catch (e) {
      errors.push({ subreddit: sub, error: String(e?.message || e) });
    }
  }

  let inserted = 0;
  for (const item of posts) {
    const { error } = await db
      .from("bjx_listener_opportunities")
      .upsert(item, { onConflict: "source,source_url", ignoreDuplicates: true });
    if (!error) inserted += 1;
    else errors.push({ url: item.source_url, error: error.message });
  }

  if (runRow?.id) {
    await db.from("bjx_agent_runs").update({
      finished_at: new Date().toISOString(),
      status: errors.length === 0 ? "ok" : "error",
      items_in: posts.length,
      items_out: inserted,
      error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
    }).eq("id", runRow.id);
  }
  return ok(res, {
    posts_scanned: posts.length,
    opportunities_inserted: inserted,
    errors: errors.length,
    error_detail: errors.slice(0, 10),
  });
}

// ----------------------------------------------------------------------------
// ATOMISER — translate a PILLAR draft into the other supported languages
// Per plan §3: "ATOMISER  Splits each pillar into 5 social posts, 1 email, 1 Reel
// script, in EN + MS (+ZH/TA for evergreen). [MiniMax→Claude]"
//
// PILLAR already does the multi-platform split (FB/IG/LinkedIn/TikTok/Threads/Reel/email)
// per run. ATOMISER adds the cross-language variants: take an existing draft and
// produce EN, MS, ZH, TA versions (skips the source language).
// ----------------------------------------------------------------------------

const ATOMISER_SYSTEM = `You are Bijou AI's content translator for the Malaysian SME market.
Translate a piece of Malaysian-SME content into the target language. Keep the
Manglish voice when translating to English (don't sanitise it). For Bahasa Malaysia
(MS), use natural conversational Malay (not formal "Bahasa baku"). For Mandarin (ZH)
and Tamil (TA), keep technical terms (WhatsApp, AI, etc.) in English when there's
no clean local equivalent.

Voice rules (MUST keep):
- max 2 "lah" per post when in Manglish/EN
- never start a sentence with "So,"
- no "boleh tahu" or "no hal"

Output JSON: { "text": str, "hashtags": [str] }
JSON only, no markdown fences.`;

const ATOMISER_LANGS = [
  { code: "en", name: "English" },
  { code: "ms", name: "Bahasa Malaysia" },
  { code: "zh", name: "Mandarin" },
  { code: "ta", name: "Tamil" },
];

async function handleAtomiser(req, res, db) {
  const body = req.body || {};
  const pillarId = body.pillar_id;
  if (!pillarId) return err(res, 400, "pillar_id required (the source content_draft id)");
  // Fetch the source draft
  const { data: source, error: sErr } = await db
    .from("bjx_content_drafts")
    .select("*")
    .eq("id", pillarId)
    .single();
  if (sErr || !source) return err(res, 404, "pillar not found");
  const sourceLang = source.language || "manglish";
  const targetLangs = ATOMISER_LANGS.filter((l) => l.code !== sourceLang);
  if (targetLangs.length === 0) {
    return ok(res, { translated: 0, message: "source already in all 4 languages" });
  }
  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "atomiser", trigger_kind: "manual", status: "running",
      model: "auto/best-fast", prompt_version: "2026-07-30",
      items_in: targetLangs.length,
    })
    .select("id").single();

  let translated = 0;
  const errors = [];
  for (const lang of targetLangs) {
    try {
      const userPrompt = `Source language: ${sourceLang}
Target language: ${lang.name} (code: ${lang.code})

Title: ${source.title || ""}
Body:
${source.body}

Output the translation. Keep Manglish voice rules. JSON only.`;
      const out = await callGateway(ATOMISER_SYSTEM, userPrompt, { temperature: 0.5, max_tokens: 1500, task: 'pillar' });
      const { error: insErr } = await db
        .from("bjx_content_drafts")
        .insert({
          kind: source.kind,
          language: lang.code,
          platform: source.platform,
          title: source.title,
          body: out.text || source.body,
          hashtags: out.hashtags || null,
          pillar_id: source.pillar_id || source.id,
          status: "draft",
          model: "auto/best-fast",
          prompt_version: "2026-07-30",
        });
      if (insErr) { errors.push({ lang: lang.code, error: insErr.message }); continue; }
      translated += 1;
    } catch (e) {
      errors.push({ lang: lang.code, error: String(e?.message || e) });
    }
  }
  if (runRow?.id) {
    await db.from("bjx_agent_runs").update({
      finished_at: new Date().toISOString(),
      status: errors.length === 0 ? "ok" : "error",
      items_out: translated,
      error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
    }).eq("id", runRow.id);
  }
  return ok(res, {
    source_id: pillarId,
    source_lang: sourceLang,
    target_langs: targetLangs.map((l) => l.code),
    translated,
    errors: errors.length,
    error_detail: errors,
  });
}

// ----------------------------------------------------------------------------
// FOLLOWUP — sequence non-responders (5+ days after first touch, no reply)
// ----------------------------------------------------------------------------

const FOLLOWUP_DAYS = 5;
const FOLLOWUP_MAX = 5;

const FOLLOWUP_SYSTEM = `You are Bijou AI's follow-up agent for the Malaysian SME market.
Write a SHORT follow-up email in Manglish for a clinic owner who didn't respond
to the first email 5+ days ago. Voice: warm, never pushy, no guilt trip.

Output JSON: { subject, body, reasoning }
- subject: <50 chars
- body: <120 words, max 1 emoji, max 1 'lah', no "just checking in", no "circling back"
- reasoning: 1-sentence why this follow-up makes sense

DO NOT pretend a relationship. DO NOT mention specific prior messages verbatim.
Re-engage with a different angle: a specific case study, a relevant article, or
a one-line value reminder.`;

function followupUserPrompt(p, firstBody) {
  return `First email sent (DO NOT copy verbatim):
"""${firstBody}"""

Prospect:
- Business: ${p.business_name}
- Area: ${p.area || "Klang Valley"}
- Vertical: ${p.vertical || "clinic"}

Days since first email: ${FOLLOWUP_DAYS}+
No reply received.

Write a follow-up. JSON only.`;
}

async function handleFollowup(req, res, db) {
  const cutoff = new Date(Date.now() - FOLLOWUP_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const { data: prospects, error: pErr } = await db
    .from("bjx_prospects")
    .select("*, bjx_touches(*)")
    .eq("status", "touched")
    .limit(FOLLOWUP_MAX);
  if (pErr) return err(res, 500, pErr.message);
  if (!prospects?.length) return ok(res, { generated: 0, message: "No non-responders" });

  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "followup", trigger_kind: "manual", status: "running",
      model: "auto/best-fast", prompt_version: "2026-07-30",
      items_in: prospects.length,
    })
    .select("id").single();

  let generated = 0;
  const errors = [];
  const skipped = [];
  for (const p of prospects) {
    const touches = (p.bjx_touches || []).sort((a, b) => new Date(b.sent_at) - new Date(a.sent_at));
    const last = touches[0];
    if (!last || new Date(last.sent_at) > new Date(cutoff)) {
      skipped.push({ prospect_id: p.id, reason: "no touch older than cutoff" });
      continue;
    }
    if (last.replied_at) {
      skipped.push({ prospect_id: p.id, reason: "already replied" });
      continue;
    }
    const { data: existing } = await db
      .from("bjx_review_queue")
      .select("id")
      .eq("source_prospect_id", p.id)
      .eq("item_type", "followup")
      .eq("status", "pending")
      .limit(1);
    if (existing?.length > 0) {
      skipped.push({ prospect_id: p.id, reason: "followup already pending" });
      continue;
    }
    try {
      const draft = await callGateway(
        FOLLOWUP_SYSTEM,
        followupUserPrompt(p, last.body_excerpt || ""),
        { temperature: 0.7, max_tokens: 400, task: 'followup' }
      );
      const payload = {
        prospect: {
          id: p.id, business_name: p.business_name, area: p.area,
          vertical: p.vertical, instagram_handle: p.instagram_handle,
          facebook_page_url: p.facebook_page_url,
        },
        channel: last.channel || "email",
        subject: draft.subject || null,
        body: draft.body || "",
        reasoning: draft.reasoning || null,
        is_followup: true,
        followup_of_touch_id: last.id,
      };
      const { error: insErr } = await db
        .from("bjx_review_queue")
        .insert({
          item_type: "followup", payload,
          source_agent: "followup", source_prospect_id: p.id,
          source_model: "auto/best-fast", priority: 40,
        });
      if (insErr) { errors.push({ prospect_id: p.id, error: insErr.message }); continue; }
      generated += 1;
    } catch (e) {
      errors.push({ prospect_id: p.id, error: String(e?.message || e) });
    }
  }
  if (runRow?.id) {
    await db.from("bjx_agent_runs").update({
      finished_at: new Date().toISOString(),
      status: errors.length === 0 ? "ok" : "error",
      items_out: generated,
      error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
    }).eq("id", runRow.id);
  }
  return ok(res, { generated, errors: errors.length, skipped: skipped.length, skipped_detail: skipped });
}

// ----------------------------------------------------------------------------
// SCOUT-REAL — replace manual_seed with live research via the gateway
// MVP (2026-07-30): uses the gateway's knowledge to suggest real Klang Valley
// businesses, deduped into bjx_prospects. Replace with Google Maps Places API
// once a key is available.
// ----------------------------------------------------------------------------

const REAL_SCOUT_TARGETS = [
  "aesthetic clinic Mont Kiara Kuala Lumpur",
  "dental clinic Bangsar Kuala Lumpur",
  "aesthetic clinic Damansara Heights",
];

const SCOUT_REAL_SYSTEM = `You are Bijou AI's prospect research agent for the Malaysian SME market.
Given a search query, return a JSON list of 2-3 real Klang Valley businesses that
match. Each entry: { name, area, has_whatsapp_business (true|false|null),
has_booking_link (true|false|null), instagram_handle (string|null),
facebook_page_url (string|null), evidence_notes (string|null) }.

Output JSON only, no markdown fences:
{ "results": [ { ... }, { ... } ] }

Use your knowledge of well-known Malaysian businesses in Klang Valley. Prefer
real names over generic placeholders. If unsure, return fewer results, not
made-up ones. Do not invent URLs.`;

async function handleScoutReal(req, res, db) {
  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "scout", trigger_kind: "cron", status: "running",
      model: "auto/best-fast", prompt_version: "2026-07-30-real",
    })
    .select("id").single();

  let inserted = 0;
  const errors = [];
  const found = [];
  for (const query of REAL_SCOUT_TARGETS) {
    try {
      const out = await callGateway(
        SCOUT_REAL_SYSTEM,
        `Search query: ${query}\nReturn 2-3 real Klang Valley businesses.`,
        { temperature: 0.4, max_tokens: 600, task: 'research' }
      );
      const results = out?.results || [];
      for (const r of results) {
        if (!r?.name) continue;
        const sourceId = `gateway_${query.replace(/\W+/g, "_")}_${r.name.replace(/\W+/g, "_")}`.slice(0, 250);
        const row = {
          source: "gateway_research",
          source_id: sourceId,
          source_url: r.facebook_page_url || `https://www.google.com/search?q=${encodeURIComponent(r.name + " " + (r.area || "Klang Valley"))}`,
          business_name: r.name,
          vertical: query.includes("dental") ? "dental_clinic" : "aesthetic_clinic",
          area: r.area || "Klang Valley",
          city: "Kuala Lumpur",
          country: "Malaysia",
          instagram_handle: r.instagram_handle || null,
          facebook_page_url: r.facebook_page_url || null,
          has_whatsapp_business: r.has_whatsapp_business,
          has_booking_link: r.has_booking_link,
          evidence_notes: r.evidence_notes || null,
        };
        const { error } = await db
          .from("bjx_prospects")
          .upsert(row, { onConflict: "source,source_id", ignoreDuplicates: true });
        if (error) errors.push({ query, name: r.name, error: error.message });
        else { inserted += 1; found.push(r.name); }
      }
    } catch (e) {
      errors.push({ query, error: String(e?.message || e) });
    }
  }
  if (runRow?.id) {
    await db.from("bjx_agent_runs").update({
      finished_at: new Date().toISOString(),
      status: errors.length === 0 ? "ok" : "error",
      items_in: REAL_SCOUT_TARGETS.length,
      items_out: inserted,
      error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
    }).eq("id", runRow.id);
  }
  return ok(res, {
    queries_run: REAL_SCOUT_TARGETS.length,
    found: found.length,
    inserted,
    errors: errors.length,
    error_detail: errors,
  });
}

// ----------------------------------------------------------------------------
// OVERPASS SCOUT — real prospect sourcing via OpenStreetMap Overpass API.
// Free, no key, no rate limit (modest usage). Returns REAL businesses with
// name, lat/lon, contact info, opening hours, website, etc.
// Targeted: aesthetic & dental clinics in Klang Valley.
// ----------------------------------------------------------------------------

const KLANG_VALLEY_BBOX = "2.95,101.35,3.30,101.85";
const OVERPASS_ENDPOINTS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass.openstreetmap.fr/api/interpreter",
];
const OVERPASS_QUERIES = [
  { name: "dental_clinics", vertical: "dental_clinic", q: `[out:json][timeout:60];
(node["amenity"="dentist"](${KLANG_VALLEY_BBOX});
 way["amenity"="dentist"](${KLANG_VALLEY_BBOX});
 node["healthcare"="dentist"](${KLANG_VALLEY_BBOX});
 way["healthcare"="dentist"](${KLANG_VALLEY_BBOX}););
out center 300;` },
  { name: "aesthetic_clinics", vertical: "aesthetic_clinic", q: `[out:json][timeout:60];
(node["healthcare"="clinic"]["name"~"aesthetic|skin|beauty|cosmetic|dermatology|slimming|wellness|laser|aesthetics",i](${KLANG_VALLEY_BBOX});
 way["healthcare"="clinic"]["name"~"aesthetic|skin|beauty|cosmetic|dermatology|slimming|wellness|laser|aesthetics",i](${KLANG_VALLEY_BBOX});
 node["amenity"="clinic"]["name"~"aesthetic|skin|beauty|cosmetic|dermatology|slimming|wellness|laser|aesthetics",i](${KLANG_VALLEY_BBOX});
 way["amenity"="clinic"]["name"~"aesthetic|skin|beauty|cosmetic|dermatology|slimming|wellness|laser|aesthetics",i](${KLANG_VALLEY_BBOX});
 node["healthcare"="beauty"](${KLANG_VALLEY_BBOX});
 way["healthcare"="beauty"](${KLANG_VALLEY_BBOX}););
out center 200;` },
];

async function callOverpass(query) {
  let lastErr = null;
  for (const endpoint of OVERPASS_ENDPOINTS) {
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        const body = "data=" + encodeURIComponent(query);
        const url = new URL(endpoint);
        const r = await fetch(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": Buffer.byteLength(body),
            "User-Agent": "BijouAI-Scout/1.0 (contact: w3j.btc@gmail.com)",
          },
        });
        if (!r.ok) {
          const t = await r.text().catch(() => "");
          throw new Error(`Overpass ${r.status}: ${t.slice(0, 100)}`);
        }
        const j = await r.json();
        return j;
      } catch (e) {
        lastErr = e;
        if (String(e.message).match(/4\d\d/)) break;
        await new Promise((r) => setTimeout(r, 1500 * attempt));
      }
    }
  }
  throw lastErr || new Error("All Overpass endpoints failed");
}

function isRealClinic(tags) {
  const name = (tags.name || tags["name:en"] || "").trim();
  if (!name) return false;
  if (tags.disused === "yes" || tags.closed === "yes") return false;
  if (/^hospital/i.test(name)) return false;
  if (/^klinik\s+kesihatan/i.test(name)) return false;
  return true;
}

function osmExtractArea(tags) {
  const sub = (tags["addr:suburb"] || tags["addr:neighbourhood"] || tags["addr:quarter"] || "").toLowerCase();
  const city = (tags["addr:city"] || "").toLowerCase();
  if (sub.includes("bangsar")) return "Bangsar";
  if (sub.includes("mont kiara") || sub.includes("solaris")) return "Mont Kiara";
  if (sub.includes("damansara")) return "Damansara";
  if (sub.includes("petaling jaya") || sub.includes("pj") || city.includes("petaling")) return "Petaling Jaya";
  if (sub.includes("subang")) return "Subang Jaya";
  if (sub.includes("shah alam")) return "Shah Alam";
  if (sub.includes("klang")) return "Klang";
  if (sub.includes("kuala lumpur") || city.includes("kuala") || city.includes("kl")) return "Kuala Lumpur";
  return "Klang Valley";
}

async function handleOverpassScout(req, res, db) {
  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "scout", trigger_kind: "cron", status: "running",
      model: "overpass-osm", prompt_version: "2026-07-30",
    })
    .select("id").single();

  let totalInserted = 0;
  const errors = [];
  for (const { name: qName, vertical, q } of OVERPASS_QUERIES) {
    let data;
    try {
      data = await callOverpass(q);
    } catch (e) {
      errors.push({ q: qName, error: String(e?.message || e) });
      continue;
    }
    const elems = data?.elements || [];
    for (const el of elems) {
      const tags = el.tags || {};
      if (!isRealClinic(tags)) continue;
      const name = (tags.name || tags["name:en"] || "").trim();
      const lat = el.lat || el.center?.lat;
      const lon = el.lon || el.center?.lon;
      if (!lat || !lon) continue;
      const area = osmExtractArea(tags);
      const phone = tags.phone || tags["contact:phone"] || tags["contact:mobile"] || null;
      const website = tags.website || tags["contact:website"] || null;
      const osmId = `${el.type}/${el.id}`;
      const hasWhatsApp = !!(phone && /^\+?60/i.test(phone.replace(/\s/g, "")));
      const row = {
        source: "overpass",
        source_id: osmId,
        source_url: `https://www.openstreetmap.org/${osmId}`,
        business_name: name,
        vertical,
        area,
        city: tags["addr:city"] || "Kuala Lumpur",
        country: "Malaysia",
        address: [tags["addr:street"], tags["addr:housenumber"], tags["addr:suburb"], tags["addr:city"]].filter(Boolean).join(", ") || null,
        website,
        has_whatsapp_business: hasWhatsApp,
        has_booking_link: !!website,
        evidence_notes: [
          tags["opening_hours"] ? `Hours: ${tags["opening_hours"]}` : null,
          phone ? `Phone: ${phone}` : null,
          `OSM: ${osmId}`,
          lat && lon ? `Coords: ${lat.toFixed(4)},${lon.toFixed(4)}` : null,
        ].filter(Boolean).join(" | ") || null,
      };
      const { error } = await db.from("bjx_prospects").upsert(row, { onConflict: "source,source_id", ignoreDuplicates: true });
      if (error) errors.push({ q: qName, name, error: error.message });
      else totalInserted += 1;
    }
  }
  if (runRow?.id) {
    await db.from("bjx_agent_runs").update({
      finished_at: new Date().toISOString(),
      status: errors.length === 0 ? "ok" : "error",
      items_in: OVERPASS_QUERIES.length,
      items_out: totalInserted,
      error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
    }).eq("id", runRow.id);
  }
  return ok(res, {
    queries_run: OVERPASS_QUERIES.length,
    inserted: totalInserted,
    errors: errors.length,
    error_detail: errors,
  });
}

// ----------------------------------------------------------------------------
// PURGE-FAKE-DRAFTS — expire drafts whose source_prospect_id links to a
// manual_seed prospect, and mark those prospects as rejected. Idempotent.
// ----------------------------------------------------------------------------

async function handlePurgeFakeDrafts(req, res, db) {
  // 1. Find manual_seed prospect ids
  const { data: seeds } = await db.from("bjx_prospects").select("id").eq("source", "manual_seed");
  const seedIds = (seeds || []).map((s) => s.id);
  if (!seedIds.length) return ok(res, { expired: 0, rejected: 0 });
  // 2. Expire their drafts
  const { data: expired } = await db
    .from("bjx_review_queue")
    .update({ status: "expired", expires_at: new Date().toISOString() })
    .in("source_prospect_id", seedIds)
    .eq("status", "pending")
    .select("id");
  // 3. Mark the prospects as rejected (so outreach never re-drafts them)
  const { data: rejected } = await db
    .from("bjx_prospects")
    .update({ status: "rejected", rejection_reason: "manual_seed_removed", updated_at: new Date().toISOString() })
    .in("id", seedIds)
    .select("id");
  return ok(res, {
    seed_prospects: seedIds.length,
    drafts_expired: (expired || []).length,
    prospects_rejected: (rejected || []).length,
  });
}

// ----------------------------------------------------------------------------
// OUTREACH-TOPFIT — outreach only for prospects whose bjx_prospect_scores row
// has fit_score >= min_fit. Skips prospects that already have a pending draft.
// ----------------------------------------------------------------------------

async function handleOutreachTopfit(req, res, db) {
  const minFit = parseInt(req.body?.min_fit || req.query?.min_fit || "60", 10);
  const limit = parseInt(req.body?.limit || req.query?.limit || "20", 10);
  const { data: scores, error: sErr } = await db
    .from("bjx_prospect_scores")
    .select("prospect_id, fit_score, reasoning")
    .gte("fit_score", minFit)
    .order("fit_score", { ascending: false })
    .limit(limit);
  if (sErr) return err(res, 500, sErr.message);
  if (!scores?.length) return ok(res, { generated: 0, message: "No scored prospects >= min_fit" });
  // Check which already have pending drafts
  const ids = scores.map((s) => s.prospect_id);
  const { data: existingDrafts } = await db
    .from("bjx_review_queue")
    .select("source_prospect_id")
    .in("source_prospect_id", ids)
    .eq("status", "pending");
  const draftedIds = new Set((existingDrafts || []).map((d) => d.source_prospect_id));
  // Fetch full prospect data
  const { data: prospects, error: pErr } = await db
    .from("bjx_prospects")
    .select("*").in("id", ids);
  if (pErr) return err(res, 500, pErr.message);
  const merged = scores
    .map((s) => ({ ...prospects.find((p) => p.id === s.prospect_id), fit_score: s.fit_score, score_reasoning: s.reasoning }))
    .filter((p) => p.id && !draftedIds.has(p.id));
  if (!merged.length) return ok(res, { generated: 0, message: "All already drafted", skipped: draftedIds.size });

  const { data: runRow } = await db.from("bjx_agent_runs").insert({
    agent_name: "outreach", trigger_kind: "manual", status: "running",
    model: "auto/best-fast", prompt_version: "2026-07-30-topfit", items_in: merged.length,
  }).select("id").single();

  let generated = 0;
  const errors = [];
  const CONCURRENCY = 4;
  for (let i = 0; i < merged.length; i += CONCURRENCY) {
    const batch = merged.slice(i, i + CONCURRENCY);
    await Promise.all(batch.map(async (p) => {
      try {
        const draft = await callGateway(OUTREACH_SYSTEM, outreachUserPrompt(p), { max_tokens: 700, task: 'outreach' });
        const payload = {
          prospect: {
            id: p.id, business_name: p.business_name, area: p.area,
            vertical: p.vertical, instagram_handle: p.instagram_handle,
            facebook_page_url: p.facebook_page_url, fit_score: p.fit_score,
          },
          channel: draft.channel || (p.instagram_handle ? "instagram_dm" : "email"),
          subject: draft.subject || null,
          body: draft.body || "",
          reasoning: draft.reasoning || null,
          fit_score: p.fit_score,
        };
        await db.from("bjx_review_queue").insert({
          item_type: "outreach_dm", payload,
          source_agent: "outreach-topfit", source_prospect_id: p.id,
          source_model: "auto/best-fast", priority: p.fit_score,
        });
        await db.from("bjx_prospects").update({
          status: "queued", updated_at: new Date().toISOString(),
        }).eq("id", p.id);
        generated += 1;
      } catch (e) {
        errors.push({ prospect_id: p.id, business_name: p.business_name, error: String(e?.message || e) });
      }
    }));
  }
  if (runRow?.id) {
    await db.from("bjx_agent_runs").update({
      finished_at: new Date().toISOString(),
      status: errors.length === 0 ? "ok" : "error",
      items_out: generated,
      error: errors.length ? JSON.stringify(errors).slice(0, 1000) : null,
    }).eq("id", runRow.id);
  }
  return ok(res, {
    min_fit: minFit,
    considered: scores.length,
    skipped_already_drafted: draftedIds.size,
    generated,
    errors: errors.length,
    error_detail: errors,
  });
}

// ----------------------------------------------------------------------------
// WEEKLY COST WATCHDOG — Saturdays, via PostHog $ai_generation events
// Per user instruction (2026-07-30): "assign to another agent to use langfuse
// or posthog to do once in a week only, on saturday evening".
// MVP: pulls the last 7 days of $ai_generation events from PostHog, sums
// estimated cost, and writes a digest row to bjx_agent_runs (agent_name='cost').
// Threshold breach: > $5/week → status='error', error=<digest>.
// ----------------------------------------------------------------------------

async function handleCostWeekly(req, res, db) {
  const projectKey = process.env.VITE_POSTHOG_PROJECT_KEY || process.env.POSTHOG_PROJECT_KEY;
  const personalKey = process.env.POSTHOG_PERSONAL_API_KEY;
  const host = process.env.VITE_POSTHOG_HOST || process.env.POSTHOG_HOST || "https://us.i.posthog.com";
  if (!projectKey || !personalKey) {
    return err(res, 503, "PostHog keys not configured");
  }
  const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
  // PostHog HogQL query via /api/projects/:id/query
  const url = `${host.replace(/\/$/, "")}/api/projects/@current/query`;
  const body = {
    query: {
      kind: "HogQLQuery",
      query: `select sum(toFloat64(properties.$ai_total_cost_usd)) as total_cost, count() as events from events where event = '$ai_generation' and timestamp > now() - interval '7 days'`,
    },
  };
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${personalKey}`,
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    return err(res, r.status, `PostHog query failed: ${text.slice(0, 200)}`);
  }
  const data = await r.json();
  const totalCost = parseFloat(data?.results?.[0]?.[0] || "0");
  const events = parseInt(data?.results?.[0]?.[1] || "0", 10);
  const breach = totalCost > 5.0; // RM~25 threshold
  // Record run
  const { data: runRow } = await db
    .from("bjx_agent_runs")
    .insert({
      agent_name: "cost",
      trigger_kind: "cron",
      status: breach ? "error" : "ok",
      model: "posthog-hogql",
      prompt_version: "2026-07-30",
      cost_estimate_usd: totalCost,
      items_in: events,
      items_out: 0,
      error: breach ? `Weekly AI cost $${totalCost.toFixed(2)} exceeds $5 threshold` : null,
      finished_at: new Date().toISOString(),
    })
    .select("id")
    .single();
  return ok(res, {
    window: "7d",
    total_cost_usd: totalCost,
    events,
    breach,
    run_id: runRow?.id,
  });
}

// ----------------------------------------------------------------------------
// Router
// ----------------------------------------------------------------------------

// Every action below reads or mutates the private lead pipeline (prospect
// names, contact channels, drafted outreach). Before 2026-08-10 the only check
// was an *optional* one inside handleScout, so an unauthenticated GET returned
// live prospect rows. Gate the whole router in one place: any new action added
// to the switch is protected by default rather than by remembering to add it.
//
// Fails CLOSED — if no secret is configured the endpoint is disabled rather
// than left open, matching api/onboarding/signup.js's 503 MISCONFIGURED path.
// CORS is not a substitute: it constrains browsers, not curl.
function agentsAuthFailure(req) {
  const expected =
    process.env.AGENTS_API_SECRET || process.env.SCOUT_CRON_SECRET;
  if (!expected) {
    return { status: 503, message: "Agents API not configured" };
  }
  const auth = req.headers.authorization || "";
  const bearer = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  const supplied = req.headers["x-cron-secret"] || bearer;
  if (supplied !== expected) {
    return { status: 401, message: "Unauthorized" };
  }
  return null;
}

export default async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(200).json({ ok: true });

  const authFailure = agentsAuthFailure(req);
  if (authFailure) return err(res, authFailure.status, authFailure.message);

  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) return err(res, 503, "Supabase not configured");

  const db = supabase(url, key);
  const action = String(req.query?.action || "").toLowerCase();

  try {
    switch (action) {
      case "scout":
        if (req.method !== "GET" && req.method !== "POST") { res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed"); }
        return await handleScout(req, res, db);
      case "scout-real":
        if (req.method !== "GET" && req.method !== "POST") { res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed"); }
        return await handleScoutReal(req, res, db);
      case "listener":
        if (req.method !== "GET" && req.method !== "POST") { res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed"); }
        return await handleListener(req, res, db);
      case "followup":
        if (req.method !== "POST") { res.setHeader("Allow", ["POST"]); return err(res, 405, "Method not allowed"); }
        return await handleFollowup(req, res, db);
      case "atomiser":
        if (req.method !== "POST") { res.setHeader("Allow", ["POST"]); return err(res, 405, "Method not allowed"); }
        return await handleAtomiser(req, res, db);
      case "cost-weekly":
        if (req.method !== "GET" && req.method !== "POST") { res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed"); }
        return await handleCostWeekly(req, res, db);
      case "overpass-scout":
        if (req.method !== "GET" && req.method !== "POST") { res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed"); }
        return await handleOverpassScout(req, res, db);
      case "purge-fake-drafts":
        if (req.method !== "GET" && req.method !== "POST") { res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed"); }
        return await handlePurgeFakeDrafts(req, res, db);
      case "outreach-topfit":
        if (req.method !== "GET" && req.method !== "POST") { res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed"); }
        return await handleOutreachTopfit(req, res, db);
      case "scorer":
        if (req.method === "GET") return await handleScorerList(res, db);
        if (req.method === "POST") return await handleScorerRun(req, res, db);
        res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed");
      case "outreach":
        if (req.method !== "POST") { res.setHeader("Allow", ["POST"]); return err(res, 405, "Method not allowed"); }
        return await handleOutreach(req, res, db);
      case "pillar":
        if (req.method !== "POST") { res.setHeader("Allow", ["POST"]); return err(res, 405, "Method not allowed"); }
        return await handlePillar(req, res, db);
      case "review-queue":
        if (req.method === "GET") return await handleReviewQueueList(req, res, db);
        if (req.method === "POST") return await handleReviewQueueAct(req, res, db);
        res.setHeader("Allow", ["GET","POST"]); return err(res, 405, "Method not allowed");
      case "review-queue-mark-sent":
        if (req.method !== "POST") { res.setHeader("Allow", ["POST"]); return err(res, 405, "Method not allowed"); }
        return await handleMarkSent(req, res, db);
      case "review-queue-expire":
        if (req.method !== "POST") { res.setHeader("Allow", ["POST"]); return err(res, 405, "Method not allowed"); }
        return await handleExpire(res, db);
      case "pipeline-summary":
        if (req.method !== "GET") { res.setHeader("Allow", ["GET"]); return err(res, 405, "Method not allowed"); }
        return await handlePipelineSummary(res, db);
      case "extend-offer":
        if (req.method !== "POST") { res.setHeader("Allow", ["POST"]); return err(res, 405, "Method not allowed"); }
        return await handleExtendOffer(req, res, db);
      case "router-status":
        if (req.method !== "GET") { res.setHeader("Allow", ["GET"]); return err(res, 405, "Method not allowed"); }
        return await handleRouterStatus(res);
      case "debug-raw":
        if (req.method !== "POST") { res.setHeader("Allow", ["POST"]); return err(res, 405, "Method not allowed"); }
        return await handleDebugRaw(req, res);
      case "chat-test":
        if (req.method !== "GET") { res.setHeader("Allow", ["GET"]); return err(res, 405, "Method not allowed"); }
        return await handleChatTest(req, res);
      default:
        return ok(res, {
          endpoint: "agents",
          actions: [
            "scout", "scout-real", "overpass-scout", "purge-fake-drafts",
            "scorer", "outreach", "outreach-topfit", "pillar",
            "listener", "followup", "atomiser", "cost-weekly",
            "review-queue", "review-queue-mark-sent", "review-queue-expire",
            "pipeline-summary", "extend-offer",
            "router-status", "debug-raw", "chat-test",
          ],
          usage: "?action=<name>",
        });
    }
  } catch (e) {
    console.error("agents handler error:", e);
    return err(res, 500, String(e?.message || e));
  }
}

// last deploy: 2026-07-30T12:56:28.4054305+08:00
