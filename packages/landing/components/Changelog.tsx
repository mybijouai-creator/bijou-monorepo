import React, { useEffect } from "react";
import { track as trackPostHog } from "../services/posthog";

/**
 * Changelog section for the landing.
 *
 * 2026-08-23: First version. Renders the 5 most recent entries from
 * packages/landing/CHANGELOG.md as a styled, scroll-anchored section.
 * Hardcoded here (not parsed from .md) for speed — the markdown file
 * remains the source of truth and is mirrored to GitHub for the full
 * history view.
 *
 * Anchored at #changelog so anyone can deep-link
 * (e.g. https://mybijou.xyz/#changelog).
 */
const recentEntries: Array<{
  version: string;
  date: string;
  title: string;
  highlights: string[];
}> = [
  {
    version: "5.0.0",
    date: "2026-05-15",
    title: "Honest + Viral Copy Redesign",
    highlights: [
      "Replaced 'RM9,201 savings' with honest baseline: 'Save RM2,700+/mo vs part-time staff'",
      "ROI restated as ~900% at RM299/mo (verifiable against PayScale market rates)",
      "TRACE steps renamed to match real component names: ASI, Humanizer, ERS, Routing",
      "New ENTERPRISE tier (RM999/mo, waitlist) — addresses the 3,000/mo cap objection",
      "Three viral hooks added: 2am Property, Lunch Rush Clinic, Voice Coming Soon",
    ],
  },
  {
    version: "4.x",
    date: "2026-04",
    title: "Performance + accessibility",
    highlights: [
      "Lighthouse Performance 92+ on mobile (was 65)",
      "Lighthouse Accessibility 100 (was 78)",
      "Reduced Tailwind CDN reliance; tokens extracted to brand-tokens.css",
    ],
  },
  {
    version: "3.x",
    date: "2026-03",
    title: "Multilingual + PWA",
    highlights: [
      "Full i18n: en, ms (Bahasa Melayu), zh (中文), ta (தமிழ்)",
      "PWA installable — add to home screen on iOS / Android",
      "Signal Gem audio cues (idle, listening, thinking, speaking)",
    ],
  },
  {
    version: "2.x",
    date: "2026-01",
    title: "Manglish voice + Cal.com booking",
    highlights: [
      "Real Manglish voice — 'boss', 'aiyo', 'leh', 'lor' all native",
      "Cal.com booking integration: create, check, cancel appointments",
      "Telegram channel added alongside WhatsApp",
    ],
  },
  {
    version: "1.0",
    date: "2025-11",
    title: "Initial public launch",
    highlights: [
      "WhatsApp AI agent for Malaysian SMEs",
      "Single PRO plan at RM299/month",
      "30-day money-back guarantee",
    ],
  },
];

export const Changelog: React.FC = () => {
  useEffect(() => {
    // Scroll to the section if the URL hash requests it
    if (typeof window !== "undefined" && window.location.hash === "#changelog") {
      const el = document.getElementById("changelog");
      if (el) {
        setTimeout(() => el.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
      }
    }
  }, []);

  return (
    <section
      id="changelog"
      className="py-20 relative bg-gradient-to-b from-black to-dark-900"
    >
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="text-center mb-12">
          <div className="inline-block px-3 py-1 mb-3 rounded-full bg-emerald-500/10 border border-emerald-400/20 text-emerald-400 text-xs font-bold uppercase tracking-wider">
            What's new
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold text-white mb-3">
            Shipping every week
          </h2>
          <p className="text-gray-400 text-sm max-w-xl mx-auto">
            We push code every week. Here's what changed recently. Full history on{" "}
            <a
              className="text-gold-400 hover:text-gold-300 underline underline-offset-2"
              href="https://github.com/mybijouai-creator/bijou-monorepo/blob/main/packages/landing/CHANGELOG.md"
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => trackPostHog("changelog_github_click", {})}
            >
              GitHub
            </a>
            .
          </p>
        </div>

        {/* Timeline */}
        <ol className="relative border-l border-emerald-500/20 ml-3 space-y-8">
          {recentEntries.map((entry, i) => (
            <li key={i} className="pl-6 relative">
              {/* Dot */}
              <span
                className="absolute -left-1.5 top-1.5 w-3 h-3 rounded-full"
                style={{
                  background: i === 0 ? "var(--accent-hi, #34d399)" : "rgba(16,185,129,0.4)",
                  boxShadow: i === 0 ? "0 0 12px rgba(16,185,129,0.6)" : "none",
                }}
              />
              {/* Card */}
              <div
                className="rounded-xl p-5"
                style={{
                  background: "rgba(18,24,26,0.6)",
                  border: "1px solid rgba(35,48,51,0.8)",
                }}
              >
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
                  <span
                    className="text-xs font-black uppercase tracking-wider"
                    style={{ color: i === 0 ? "#34d399" : "var(--text-mid, #9aa7a4)" }}
                  >
                    v{entry.version}
                  </span>
                  <span className="text-xs text-gray-500">{entry.date}</span>
                  {i === 0 && (
                    <span className="text-[10px] font-black uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                      Latest
                    </span>
                  )}
                </div>
                <h3 className="text-white font-bold text-lg mb-3">{entry.title}</h3>
                <ul className="space-y-1.5">
                  {entry.highlights.map((h, j) => (
                    <li
                      key={j}
                      className="flex items-start gap-2 text-sm text-gray-300"
                    >
                      <span
                        className="flex-shrink-0 w-1 h-1 rounded-full mt-2"
                        style={{ background: "#34d399" }}
                      />
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          ))}
        </ol>

        {/* Footer link */}
        <div className="mt-10 text-center">
          <a
            href="https://github.com/mybijouai-creator/bijou-monorepo/blob/main/packages/landing/CHANGELOG.md"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackPostHog("changelog_github_footer_click", {})}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-gold-400 bg-gold-500/10 border border-gold-400/20 hover:bg-gold-500/20 transition-all"
          >
            View full changelog on GitHub →
          </a>
        </div>
      </div>
    </section>
  );
};
