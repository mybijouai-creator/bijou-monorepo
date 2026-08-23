import { motion } from "framer-motion";
import { Check, Crown, Lock, Zap } from "lucide-react";
import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { track as trackPostHog } from "../services/posthog";

function getUrgencyMessage(remaining: number): string {
  if (remaining >= 10) return "🎉 All 10 Early Adopter Spots Available";
  if (remaining >= 8)
    return `⏰ Price increases to RM399/mo after spot #${10 - remaining + 1} fills`;
  if (remaining >= 5) return `🔥 Only ${remaining} spots left at RM299/mo`;
  if (remaining >= 3) return `🚨 LAST ${remaining} SPOTS — Lock Your Rate Now!`;
  if (remaining === 2)
    return "⚡ 2 SPOTS LEFT — Price Jumps to RM399 After This!";
  if (remaining === 1) return "🔴 FINAL SPOT — RM299 Rate Expires Tonight!";
  return "✅ All Early Adopter Spots Claimed — New Price: RM399/mo";
}

interface PricingProps {
  onOpenModal: () => void;
}

const addOns = [
  { name: "Extra WhatsApp number", when: "Q2 2026", price: "+RM80/mo" },
  { name: "Extra Telegram bot", when: "Q2 2026", price: "+RM60/mo" },
  { name: "Multi-user seats", when: "Q2 2026", price: "+RM80/seat" },
  {
    name: "Appointment reminders (WhatsApp push)",
    when: "Q2 2026",
    price: "+RM60/mo",
  },
  { name: "Facebook Messenger", when: "Q3 2026", price: "+RM60/mo" },
  { name: "Advanced PDF parsing", when: "Q3 2026", price: "+RM100/mo" },
  { name: "Larger context window (128K)", when: "Q3 2026", price: "+RM80/mo" },
  { name: "Loan calculator", when: "Q4 2026", price: "+RM150/mo" },
];

export const Pricing: React.FC<PricingProps> = ({ onOpenModal }) => {
  const { t } = useTranslation();
  const [spots, setSpots] = useState<{
    remaining: number;
    total: number;
    spotsTotal: number;
  } | null>(null);

  useEffect(() => {
    fetch("/api/spots")
      .then((r) => r.json())
      .then((data) => setSpots(data))
      .catch(() => setSpots({ remaining: 7, total: 3, spotsTotal: 10 }));
  }, []);

  const remaining = spots?.remaining ?? 7;
  const spotsTotal = spots?.spotsTotal ?? 10;
  const filledPct = Math.round(((spotsTotal - remaining) / spotsTotal) * 100);

  const liveFeatures = [
    t("pricing.pro.features.0"),
    t("pricing.pro.features.1"),
    t("pricing.pro.features.2"),
    t("pricing.pro.features.3"),
    t("pricing.pro.features.4"),
    t("pricing.pro.features.5"),
    t("pricing.pro.features.6"),
    t("pricing.pro.features.7"),
    t("pricing.pro.features.8"),
    t("pricing.pro.features.9"),
  ];

  return (
    <section
      id="pricing"
      className="py-24 relative bg-gradient-to-b from-dark-900 to-black overflow-hidden"
    >
      {/* Background glows */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/4 left-1/3 w-[600px] h-[600px] bg-gold-500/8 rounded-full blur-[140px]" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-emerald-500/8 rounded-full blur-[120px]" />
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
          className="text-center mb-14"
        >
          <div className="inline-block px-4 py-1.5 mb-6 rounded-full glass-panel-3d border border-gold-400/20 text-gold-400 text-xs font-bold uppercase tracking-wider">
            {t("pricing.badge")}
          </div>
          <h2 className="text-4xl md:text-5xl font-display font-extrabold mb-5 tracking-tight text-white">
            {t("pricing.title")}
          </h2>
          <p className="text-lg text-gray-300 max-w-2xl mx-auto">
            {t("pricing.subtitle.part1")}{" "}
            <span className="text-gold-400 font-bold">
              {t("pricing.subtitle.trial")}
            </span>
            {t("pricing.subtitle.part2")}
          </p>
        </motion.div>

        {/* PRO Plan Card */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
          className="glass-panel-3d rounded-3xl p-8 md:p-12 border-2 border-gold-400/50 shadow-[0_0_80px_rgba(212,175,55,0.18)] relative mb-6"
        >
          {/* Badge */}
          <div className="absolute -top-4 left-1/2 transform -translate-x-1/2 px-5 py-1.5 rounded-full bg-gradient-to-r from-gold-500 to-gold-300 text-black text-xs font-black uppercase tracking-widest whitespace-nowrap">
            {t("pricing.pro.badge")}
          </div>

          <div className="flex flex-col md:flex-row md:items-start gap-10">
            {/* Left: Pricing */}
            <div className="md:w-72 flex-shrink-0">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-12 h-12 rounded-2xl bg-gold-500/20 flex items-center justify-center">
                  <Crown className="w-6 h-6 text-gold-400" />
                </div>
                <div>
                  <h3 className="text-2xl font-black text-white">
                    {t("pricing.pro.name")}
                  </h3>
                  <p className="text-gray-400 text-xs">
                    {t("pricing.pro.description")}
                  </p>
                </div>
              </div>

              {/* Price */}
              <div className="mt-6 mb-4">
                <div className="flex items-baseline gap-1">
                  <span className="text-sm text-gray-400 font-medium">RM</span>
                  <span className="text-6xl font-black text-gradient-gold leading-none">
                    {t("pricing.pro.price")}
                  </span>
                  <span className="text-gray-400 text-sm">/month</span>
                </div>
              </div>

              {/* Annual option */}
              <div className="bg-emerald-900/20 border border-emerald-500/20 rounded-xl px-4 py-3 mb-6">
                <div className="flex items-center gap-2 mb-1">
                  <Zap className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                  <span className="text-emerald-400 text-xs font-bold uppercase tracking-wide">
                    Annual Plan
                  </span>
                </div>
                <div className="flex items-baseline gap-1">
                  <span className="text-xs text-gray-400">RM</span>
                  <span className="text-2xl font-black text-white">
                    {t("pricing.pro.yearlyPrice")}
                  </span>
                  <span className="text-gray-400 text-xs">/year</span>
                </div>
                <p className="text-emerald-400 text-xs font-semibold mt-1">
                  {t("pricing.pro.yearlySaving")}
                </p>
              </div>

              {/* CTA */}
              <button
                onClick={() => { trackPostHog("pricing_plan_clicked", { plan_name: "pro", source: "pricing" }); onOpenModal?.(); }}
                className="w-full py-4 px-6 rounded-xl font-bold text-black bg-gradient-to-r from-gold-500 to-gold-300 shadow-[0_0_30px_rgba(212,175,55,0.4)] hover:shadow-[0_0_50px_rgba(212,175,55,0.6)] transition-all transform hover:scale-[1.02] text-sm"
              >
                {t("pricing.cta.trial")}
              </button>
              {/* Direct contact row */}
              <div className="flex gap-2 mt-3">
                <a
                  href="https://api.whatsapp.com/send/?phone=60174106981"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 py-2.5 px-3 rounded-xl text-xs font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 transition-all text-center"
                >
                  💬 WhatsApp Us
                </a>
                <a
                  href="mailto:jewel@mybijou.xyz"
                  className="flex-1 py-2.5 px-3 rounded-xl text-xs font-bold text-gold-400 bg-gold-500/10 border border-gold-400/20 hover:bg-gold-500/20 transition-all text-center"
                >
                  ✉️ Email Founder
                </a>
              </div>

              {/* Zero Hidden Fees */}
              <div className="mt-4 border border-emerald-500/15 bg-emerald-950/20 rounded-xl px-4 py-3">
                <p className="text-emerald-400 text-[10px] font-bold uppercase tracking-wider mb-2">
                  Zero hidden fees. Ever.
                </p>
                <div className="grid grid-cols-1 gap-y-1">
                  {[
                    "WhatsApp conversation markup",
                    "Per-message charges",
                    "WABA application fee",
                    "Annual lock-in",
                    "Bot-wall for support",
                  ].map((item, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-red-400 text-xs leading-none">
                        ✕
                      </span>
                      <span className="text-gray-400 text-xs">{item}</span>
                    </div>
                  ))}
                </div>
              </div>

              <p className="text-xs text-center text-gold-400/70 mt-3 font-medium">
                {t("pricing.guarantee.title")}
              </p>
            </div>

            {/* Right: Features */}
            <div className="flex-1">
              <p className="text-xs font-bold text-emerald-400 uppercase tracking-wider mb-3">
                ✅ What&apos;s Live Today
              </p>
              <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 mb-5">
                {liveFeatures.map((feature, i) => (
                  <li key={i} className="flex items-start gap-2.5">
                    <Check className="w-4 h-4 text-gold-400 flex-shrink-0 mt-0.5" />
                    <span className="text-gray-300 text-sm leading-snug">
                      {feature}
                    </span>
                  </li>
                ))}
              </ul>

              {/* Early Adopter Counter — live from /api/spots */}
              {/* Early Adopter Price Lock — enhanced */}
              <div className="border-t border-white/5 pt-5 mt-3">
                <div className="relative rounded-2xl overflow-hidden border border-gold-400/40 bg-gradient-to-br from-gold-500/10 via-black/20 to-amber-500/5 p-5 shadow-[0_0_40px_rgba(212,175,55,0.12)]">
                  {/* Animated shimmer edge */}
                  <div className="absolute inset-0 bg-gradient-to-r from-transparent via-gold-400/5 to-transparent animate-shine bg-[length:200%_100%] pointer-events-none" />

                  {/* Header row */}
                  <div className="flex items-start gap-3 mb-4">
                    <motion.div
                      animate={{ scale: [1, 1.18, 1], rotate: [0, -5, 5, 0] }}
                      transition={{
                        repeat: Infinity,
                        duration: 3,
                        ease: "easeInOut",
                      }}
                      className="flex-shrink-0 w-9 h-9 rounded-xl bg-gold-500/20 flex items-center justify-center"
                    >
                      <Lock className="w-4 h-4 text-gold-400" />
                    </motion.div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-0.5">
                        <span className="text-gold-300 text-[10px] font-black uppercase tracking-widest">
                          {t("pricing.ea.label")}
                        </span>
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-500/20 border border-red-500/30 text-red-400 text-[10px] font-black animate-pulse">
                          {t("pricing.ea.badge")}
                        </span>
                      </div>
                      <p className="text-white text-sm font-bold leading-snug">
                        {getUrgencyMessage(remaining)}
                      </p>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-gold-400/70 text-[10px] font-semibold">
                        {t("pricing.ea.claimed", { total: spotsTotal })}
                      </span>
                      <span className="text-gold-300 text-[10px] font-black">
                        {remaining} {t("pricing.ea.left")}
                      </span>
                    </div>
                    <div className="w-full bg-black/40 rounded-full h-2.5 overflow-hidden">
                      <motion.div
                        className="bg-gradient-to-r from-gold-500 to-amber-300 h-2.5 rounded-full relative"
                        initial={{ width: 0 }}
                        animate={{ width: `${filledPct}%` }}
                        transition={{ duration: 1.4, ease: "easeOut" }}
                      >
                        <div className="absolute right-0 top-0 bottom-0 w-3 bg-white/30 rounded-full blur-sm" />
                      </motion.div>
                    </div>
                  </div>

                  {/* What the lock means */}
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { icon: "🔒", text: t("pricing.ea.b1") },
                      { icon: "📈", text: t("pricing.ea.b2") },
                      { icon: "✅", text: t("pricing.ea.b3") },
                      { icon: "🎁", text: t("pricing.ea.b4") },
                    ].map((item, i) => (
                      <div key={i} className="flex items-center gap-1.5">
                        <span className="text-sm">{item.icon}</span>
                        <span className="text-gray-300 text-[10px] leading-tight">
                          {item.text}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <p className="text-gray-500 text-[10px] leading-relaxed mt-2 pl-1">
                  💡 {t("pricing.pro.earlyAccessNote")}
                </p>
              </div>
            </div>
          </div>
        </motion.div>

        {/* Fix 5: ENTERPRISE tier card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="mb-8 max-w-2xl mx-auto"
        >
          <div className="glass-panel-3d rounded-3xl border border-[#D4AF37]/30 p-8 relative overflow-hidden">
            {/* Coming soon overlay badge */}
            <div className="absolute top-4 right-4">
              <span className="px-3 py-1 rounded-full bg-[#D4AF37]/10 border border-[#D4AF37]/30 text-[#D4AF37] text-xs font-bold uppercase tracking-wider">
                Coming Q3 2026 · Waitlist
              </span>
            </div>

            <div className="flex items-start gap-4 mb-6">
              <div className="flex-shrink-0 w-12 h-12 rounded-xl bg-[#D4AF37]/10 border border-[#D4AF37]/20 flex items-center justify-center">
                <span className="text-[#D4AF37] text-xl font-black">E</span>
              </div>
              <div>
                <h3 className="text-white text-2xl font-black">ENTERPRISE</h3>
                <div className="flex items-baseline gap-1 mt-1">
                  <span className="text-[#D4AF37] text-3xl font-black">RM999</span>
                  <span className="text-gray-400 text-sm">/month</span>
                </div>
              </div>
            </div>

            <div className="grid sm:grid-cols-2 gap-3 mb-6">
              {[
                "Official WABA (WhatsApp Business API)",
                "Unlimited messages — no 3,000/mo cap",
                "Multi-location support",
                "Team accounts + role management",
                "Priority support with dedicated onboarding",
                "Custom Manglish persona per brand",
              ].map((feat, i) => (
                <div key={i} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#D4AF37] flex-shrink-0" />
                  {feat}
                </div>
              ))}
            </div>

            {/* Cap upgrade note */}
            <div className="p-3 rounded-xl bg-amber-500/5 border border-amber-500/10 mb-4">
              <p className="text-amber-300 text-xs font-semibold">
                Hit the 3,000/mo cap? Tell us — we'll upgrade you to ENTERPRISE early.
              </p>
              <p className="text-gray-500 text-[10px] mt-0.5 italic">
                Dah guna 3,000 perbulan? Beritahu kami — kami akan upgrade ke ENTERPRISE awal.
              </p>
            </div>

            <button
              onClick={() => { trackPostHog("pricing_plan_clicked", { plan_name: "enterprise", source: "pricing" }); onOpenModal?.(); }}
              className="w-full py-3 rounded-xl border border-[#D4AF37]/40 text-[#D4AF37] font-bold text-sm hover:bg-[#D4AF37]/10 transition-all"
            >
              Join Enterprise Waitlist →
            </button>
          </div>
        </motion.div>

        {/* Enterprise footnote */}
        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="text-center mb-12"
        >
          <p className="text-gray-500 text-sm">
            {t("pricing.cta.enterprisePrompt")}{" "}
            <button
              onClick={() => { trackPostHog("pricing_plan_clicked", { plan_name: "enterprise_contact", source: "pricing_footer" }); onOpenModal?.(); }}
              className="text-gold-400 hover:text-gold-300 font-semibold underline underline-offset-2 transition-colors"
            >
              {t("pricing.cta.enterprise")}
            </button>
          </p>
        </motion.div>

        {/* 2026-08-23: Competitor comparison table.
            Anchors Bijou's price + feature set against the four closest
            alternatives a Malaysian SME is most likely evaluating. Designed
            for the "should I just use WATI?" objection. Numbers are the
            verified 2026 entry-tier public prices (USD, billed annually):
              - WATI: $49/mo, 5 agents, 2,500 MAU
              - Respond.io: $79/mo Starter, $159/mo Growth
              - SleekFlow: ~$153/mo (3-seat min, Pro AI)
              - Tidio: $24.17 Starter + $32.50 Lyro AI add-on
            The "vs WATI" / "vs Respond.io" etc. links go to per-competitor
            battle-card pages (todo, see issue #6 follow-up). */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6, delay: 0.15 }}
          className="glass-panel-3d rounded-3xl p-6 md:p-8 border border-white/10 mb-12"
        >
          <div className="text-center mb-6">
            <div className="inline-block px-3 py-1 mb-3 rounded-full bg-emerald-500/10 border border-emerald-400/20 text-emerald-400 text-xs font-bold uppercase tracking-wider">
              {t("pricing.compare.badge")}
            </div>
            <h3 className="text-2xl md:text-3xl font-bold text-white mb-2">
              {t("pricing.compare.title")}
            </h3>
            <p className="text-gray-400 text-sm max-w-2xl mx-auto">
              {t("pricing.compare.subtitle")}
            </p>
          </div>

          <div className="overflow-x-auto -mx-2 px-2">
            <table className="w-full text-left text-sm min-w-[640px]">
              <thead>
                <tr className="text-gray-400 text-[10px] uppercase tracking-wider border-b border-white/10">
                  <th className="py-3 pr-3 font-semibold w-1/4"></th>
                  <th className="py-3 px-2 font-semibold w-1/6">
                    <div className="text-gold-400 text-xs font-black">Bijou PRO</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">Manglish AI agent</div>
                  </th>
                  <th className="py-3 px-2 font-semibold w-1/6">
                    <div className="text-white text-xs font-bold">WATI</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">Hong Kong</div>
                  </th>
                  <th className="py-3 px-2 font-semibold w-1/6">
                    <div className="text-white text-xs font-bold">Respond.io</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">Kuala Lumpur</div>
                  </th>
                  <th className="py-3 px-2 font-semibold w-1/6">
                    <div className="text-white text-xs font-bold">SleekFlow</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">Hong Kong</div>
                  </th>
                  <th className="py-3 px-2 font-semibold w-1/6">
                    <div className="text-white text-xs font-bold">Tidio</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">US/PL</div>
                  </th>
                </tr>
              </thead>
              <tbody className="text-gray-300">
                {[
                  { row: "price", bij: "RM 299/mo", wati: "$49/mo", rio: "$79/mo", sleek: "~$153/mo", tidi: "$24 + $33" },
                  { row: "biji_label", bij: "Bijou", wati: "WATI", rio: "Respond", sleek: "SleekFlow", tidi: "Tidio", isLabel: true },
                  { row: "lang", bij: "Manglish + EN + BM + 中文 + தமிழ்", wati: "EN only", rio: "EN + ZH", sleek: "EN + ZH", tidi: "EN only" },
                  { row: "ai_reasoning", bij: true, wati: false, rio: "partial", sleek: false, tidi: false },
                  { row: "ai_setup_time", bij: "5 min", wati: "30 min", rio: "30 min", sleek: "1 hour", tidi: "1 hour" },
                  { row: "telegram", bij: true, wati: false, rio: true, sleek: true, tidi: false },
                  { row: "voice_calls", bij: "Q4 2026 (Telnyx)", wati: true, rio: "Advanced+", sleek: false, tidi: false },
                  { row: "cal_booking", bij: true, wati: false, rio: false, sleek: false, tidi: "Shopify only" },
                  { row: "lead_score", bij: "Q3 2026", wati: false, rio: true, sleek: true, tidi: true },
                  { row: "eu_ai_act", bij: "Q3 2026 (in progress)", wati: false, rio: false, sleek: false, tidi: false },
                  { row: "pdpa_export", bij: "Q3 2026 (in progress)", wati: false, rio: false, sleek: false, tidi: false },
                  { row: "msg_markup", bij: "None", wati: "Markup", rio: "None (Advanced+)", sleek: "Small", tidi: "Pass-through" },
                  { row: "annual_lock_in", bij: "No", wati: "No", rio: "No", sleek: "No", tidi: "No" },
                ].map((r, i) => {
                  if (r.isLabel) return null;
                  const labels: Record<string, string> = {
                    price: "Entry price",
                    lang: "Languages",
                    ai_reasoning: "Visible AI reasoning (why it said what it said)",
                    ai_setup_time: "Time to first AI reply",
                    telegram: "Telegram channel",
                    voice_calls: "Voice calls",
                    cal_booking: "Cal.com booking + reminders",
                    lead_score: "AI lead scoring",
                    eu_ai_act: "EU AI Act 2024 traceability",
                    pdpa_export: "Self-serve PDPA/GDPR export",
                    msg_markup: "Per-message markup",
                    annual_lock_in: "Annual lock-in",
                  };
                  const cell = (v: boolean | string) => {
                    if (v === true) return <span className="text-emerald-400 font-bold">✓</span>;
                    if (v === false) return <span className="text-red-400/70">✗</span>;
                    return <span className="text-gray-300 text-xs">{v}</span>;
                  };
                  return (
                    <tr key={i} className="border-b border-white/5">
                      <td className="py-2.5 pr-3 text-[11px] text-gray-400 font-medium">
                        {labels[r.row] ?? r.row}
                      </td>
                      <td className="py-2.5 px-2 text-center bg-gold-500/5 rounded-l-lg">
                        {cell(r.bij)}
                      </td>
                      <td className="py-2.5 px-2 text-center">{cell(r.wati)}</td>
                      <td className="py-2.5 px-2 text-center">{cell(r.rio)}</td>
                      <td className="py-2.5 px-2 text-center">{cell(r.sleek)}</td>
                      <td className="py-2.5 px-2 text-center bg-transparent rounded-r-lg">
                        {cell(r.tidi)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded-xl p-4 bg-gold-500/5 border border-gold-400/20">
              <p className="text-gold-400 text-xs font-bold uppercase tracking-wider mb-1">
                Why Bijou costs more than WATI
              </p>
              <p className="text-gray-300 text-xs leading-relaxed">
                WATI is great for English-only WhatsApp marketing. Bijou is built for
                Malaysia: Manglish native, BM + 中文 + தமிழ் out of the box, Cal.com
                booking, AI reasoning trace, and a roadmap toward EU AI Act 2026
                compliance. For a non-technical Malaysian SME owner, the value is in
                what you don&apos;t have to configure.
              </p>
            </div>
            <div className="rounded-xl p-4 bg-emerald-500/5 border border-emerald-400/20">
              <p className="text-emerald-400 text-xs font-bold uppercase tracking-wider mb-1">
                Why Bijou costs less than Respond.io / SleekFlow
              </p>
              <p className="text-gray-300 text-xs leading-relaxed">
                Both are multi-channel platforms priced for teams of 5+ agents.
                Bijou is WhatsApp-first, AI-first, and tuned for the 1-2 person
                shop. No agent-seat fees. No per-message markup on Advanced-tier
                plans. You get the same AI, the same booking, the same compliance
                posture &mdash; without paying for seats you don&apos;t need.
              </p>
            </div>
          </div>

          <p className="text-gray-500 text-[10px] mt-4 text-center italic">
            Competitor prices verified 2026-08 against public pricing pages. Sources
            linked in our <a className="underline hover:text-gold-300" href="/vs/wati">vs WATI</a>,
            {" "}<a className="underline hover:text-gold-300" href="/vs/respond-io">vs Respond.io</a>,
            {" "}<a className="underline hover:text-gold-300" href="/vs/sleekflow">vs SleekFlow</a>,
            {" "}<a className="underline hover:text-gold-300" href="/vs/tidio">vs Tidio</a> detailed comparisons.
          </p>
        </motion.div>

        {/* Roadmap & Add-ons */}
        <div id="roadmap" />
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="glass-panel-3d rounded-3xl p-8 border border-white/10 mb-12"
        >
          <div className="text-center mb-8">
            <div className="inline-block px-3 py-1 mb-3 rounded-full bg-purple-500/10 border border-purple-400/20 text-purple-400 text-xs font-bold uppercase tracking-wider">
              Product Roadmap
            </div>
            <h3 className="text-2xl md:text-3xl font-bold text-white mb-2">
              {t("pricing.addons.title")}
            </h3>
            <p className="text-gray-400 text-sm max-w-lg mx-auto">
              {t("pricing.addons.subtitle")}
            </p>
          </div>

          {/* Phase timeline */}
          <div className="flex items-center gap-0 mb-8 overflow-x-auto pb-2">
            {[
              {
                phase: "Now",
                label: "Live",
                color: "bg-emerald-400",
                text: "text-emerald-400",
                border: "border-emerald-400/40",
              },
              {
                phase: "Q2 2026",
                label: "Phase 5",
                color: "bg-blue-400",
                text: "text-blue-400",
                border: "border-blue-400/40",
              },
              {
                phase: "Q3 2026",
                label: "Phase 6",
                color: "bg-purple-400",
                text: "text-purple-400",
                border: "border-purple-400/40",
              },
              {
                phase: "Q4 2026",
                label: "Phase 7",
                color: "bg-orange-400",
                text: "text-orange-400",
                border: "border-orange-400/40",
              },
            ].map((p, i) => (
              <React.Fragment key={i}>
                <div
                  className={`flex-shrink-0 flex flex-col items-center gap-1 px-4 py-2 rounded-xl border ${p.border} bg-white/5`}
                >
                  <span
                    className={`text-[10px] font-black uppercase tracking-widest ${p.text}`}
                  >
                    {p.label}
                  </span>
                  <span className="text-white text-xs font-bold">
                    {p.phase}
                  </span>
                </div>
                {i < 3 && (
                  <div className="flex-1 h-px bg-white/10 min-w-[20px]" />
                )}
              </React.Fragment>
            ))}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {addOns.map((addon, i) => {
              const phaseColors: Record<string, string> = {
                "Q2 2026": "border-blue-400/20 hover:border-blue-400/40",
                "Q3 2026": "border-purple-400/20 hover:border-purple-400/40",
                "Q4 2026": "border-orange-400/20 hover:border-orange-400/40",
              };
              const timeBadge: Record<string, string> = {
                "Q2 2026": "text-blue-400",
                "Q3 2026": "text-purple-400",
                "Q4 2026": "text-orange-400",
              };
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 10 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: i * 0.05 }}
                  className={`bg-white/5 border rounded-xl p-4 transition-colors ${phaseColors[addon.when] ?? "border-white/10"}`}
                >
                  <p className="text-white text-sm font-semibold leading-snug mb-3">
                    {addon.name}
                  </p>
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider ${timeBadge[addon.when] ?? "text-gray-500"}`}
                    >
                      {addon.when}
                    </span>
                    <span className="text-gold-400 text-xs font-bold">
                      {addon.price}
                    </span>
                  </div>
                </motion.div>
              );
            })}
          </div>

          <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-3 pt-5 border-t border-white/5">
            <p className="text-emerald-400 text-xs font-semibold">
              ✅ Pro customers get first access — free during trial period when
              each feature ships
            </p>
            <p className="text-gray-500 text-xs">
              Roadmap subject to change. No delivery dates guaranteed.
            </p>
          </div>
        </motion.div>

        {/* Money-Back Guarantee */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="text-center"
        >
          <div className="inline-flex items-center gap-3 px-6 py-4 rounded-2xl glass-panel-3d border border-emerald-500/20 bg-emerald-900/10">
            <div className="w-10 h-10 rounded-full bg-emerald-500/20 flex items-center justify-center flex-shrink-0">
              <Check className="w-6 h-6 text-emerald-400" />
            </div>
            <div className="text-left">
              <div className="font-bold text-white">
                {t("pricing.guarantee.title")}
              </div>
              <div className="text-sm text-gray-400">
                {t("pricing.guarantee.subtitle")}
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

// NOTE: pricing.starter.*, pricing.professional.*, pricing.enterprise.* keys in i18n.ts are
// kept for reference/rollback but no longer rendered in this component.
// Only pricing.pro.* keys are active now. To rollback: restore the old Pricing.tsx from git history.
