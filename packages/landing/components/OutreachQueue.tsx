import { motion, AnimatePresence } from "framer-motion";
import { Check, Copy, ExternalLink, Inbox, X } from "lucide-react";
import React, { useCallback, useEffect, useState } from "react";

interface ReviewItem {
  id: string;
  created_at: string;
  item_type: string;
  payload: {
    prospect?: {
      id: string;
      business_name: string;
      area?: string;
      vertical?: string;
      instagram_handle?: string;
      facebook_page_url?: string;
    };
    channel?: string;
    subject?: string;
    body?: string;
    reasoning?: string;
  };
  source_agent: string;
  source_prospect_id: string;
  source_model: string;
  priority: number;
  status: string;
  expires_at: string;
}

type ToastKind = "ok" | "err";
function Toast({ msg, kind }: { msg: string; kind: ToastKind }) {
  if (!msg) return null;
  return (
    <div
      className={`fixed bottom-6 right-6 px-4 py-2 rounded-xl text-sm font-semibold shadow-2xl z-50 ${
        kind === "ok"
          ? "bg-emerald-500/20 border border-emerald-400/40 text-emerald-200"
          : "bg-red-500/20 border border-red-400/40 text-red-200"
      }`}
    >
      {msg}
    </div>
  );
}

function CopyButton({ text, label = "Copy body" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-white/5 hover:bg-white/10 border border-white/10 transition-colors"
    >
      {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
      {copied ? "Copied" : label}
    </button>
  );
}

// /api/agents now requires a shared secret on every action (it serves the
// private lead pipeline). This is a founder-only internal screen, so prompt
// once per tab and hold the value in sessionStorage — deliberately NOT
// localStorage, so it dies with the tab. A browser cannot hold a server secret
// safely; the real guarantee is the server-side check, this only carries it.
const AGENT_SECRET_KEY = "bijou_agents_secret";

function agentSecret(): string {
  let s = sessionStorage.getItem(AGENT_SECRET_KEY) || "";
  if (!s) {
    s = window.prompt("Admin secret for /api/agents:") || "";
    if (s) sessionStorage.setItem(AGENT_SECRET_KEY, s);
  }
  return s;
}

// On 401 the stored secret is wrong — drop it so the next call re-prompts
// instead of silently failing for the rest of the session.
function clearAgentSecretOn401(status: number) {
  if (status === 401) sessionStorage.removeItem(AGENT_SECRET_KEY);
}

export const OutreachQueue: React.FC = () => {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: ToastKind } | null>(null);
  const [showRejected, setShowRejected] = useState(false);

  const showToast = useCallback((msg: string, kind: ToastKind) => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 2500);
  }, []);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const status = showRejected ? "approved" : "pending";
      const r = await fetch(`/api/agents?action=review-queue&status=${status}&limit=100`, {
        headers: { "X-Cron-Secret": agentSecret() },
      });
      const data = await r.json();
      if (!r.ok) {
        clearAgentSecretOn401(r.status);
        throw new Error(data.error || `HTTP ${r.status}`);
      }
      setItems(data.items || []);
    } catch (e: any) {
      showToast(`Load failed: ${e?.message || e}`, "err");
    } finally {
      setLoading(false);
    }
  }, [showRejected, showToast]);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  const act = async (id: string, action: "approve" | "reject" | "mark-sent", reason?: string) => {
    setBusy(id);
    try {
      const path = action === "mark-sent"
        ? "/api/agents?action=review-queue-mark-sent"
        : "/api/agents?action=review-queue";
      const r = await fetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Cron-Secret": agentSecret(),
        },
        body: JSON.stringify({ id, action, reason }),
      });
      const data = await r.json();
      if (!r.ok) {
        clearAgentSecretOn401(r.status);
        throw new Error(data.error || `HTTP ${r.status}`);
      }
      showToast(`✓ ${action} ok`, "ok");
      await fetchItems();
    } catch (e: any) {
      showToast(`${action} failed: ${e?.message || e}`, "err");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-6xl mx-auto">
      <Toast msg={toast?.msg || ""} kind={toast?.kind || "ok"} />

      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-display font-extrabold text-white flex items-center gap-3">
            <Inbox className="w-7 h-7 text-gold-400" />
            Outreach Review Queue
          </h1>
          <p className="text-gray-400 text-sm mt-2">
            Agent drafts sit here until you approve. Nothing is sent automatically.
            {items.length > 0 && (
              <span className="ml-2 text-gold-400 font-semibold">{items.length} pending</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowRejected((s) => !s)}
            className="px-3 py-2 rounded-lg text-xs font-bold bg-white/5 hover:bg-white/10 border border-white/10"
          >
            {showRejected ? "Show pending" : "Show approved"}
          </button>
          <button
            onClick={fetchItems}
            className="px-3 py-2 rounded-lg text-xs font-bold bg-gold-500/20 hover:bg-gold-500/30 border border-gold-400/30 text-gold-300"
          >
            Refresh
          </button>
        </div>
      </div>

      {loading && <p className="text-gray-400">Loading…</p>}

      {!loading && items.length === 0 && (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-8 text-center text-gray-400">
          <p className="mb-2">Queue is empty. 👌</p>
          <p className="text-xs">
            Run <code className="text-gold-400">POST /api/agents?action=overpass-scout</code> then <code className="text-gold-400">POST /api/agents?action=scorer</code> then <code className="text-gold-400">POST /api/agents?action=outreach</code> to populate it.
          </p>
        </div>
      )}

      <div className="space-y-4">
        <AnimatePresence>
          {items.map((item) => {
            const p = item.payload?.prospect;
            const body = item.payload?.body || "";
            const channel = item.payload?.channel || "email";
            const subject = item.payload?.subject;
            const link =
              channel === "instagram_dm" && p?.instagram_handle
                ? `https://ig.me/${p.instagram_handle.replace(/^@/, "")}`
                : channel === "linkedin" && p?.facebook_page_url
                ? p.facebook_page_url
                : `mailto:${p?.business_name?.toLowerCase().replace(/[^a-z]/g, "")}@example.com`;
            return (
              <motion.div
                key={item.id}
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="rounded-2xl border border-white/10 bg-white/5 p-6"
              >
                <div className="flex items-start justify-between mb-3 gap-4 flex-wrap">
                  <div>
                    <h3 className="text-lg font-bold text-white">
                      {p?.business_name || "Unknown prospect"}
                    </h3>
                    <p className="text-xs text-gray-400">
                      {p?.vertical?.replace(/_/g, " ")} · {p?.area || "Klang Valley"} · channel:{" "}
                      <span className="text-gold-400">{channel}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <a
                      href={link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-white/5 hover:bg-white/10 border border-white/10"
                    >
                      <ExternalLink className="w-3 h-3" />
                      Open {channel}
                    </a>
                    <CopyButton
                      text={`${subject ? `Subject: ${subject}\n\n` : ""}${body}`}
                      label="Copy message"
                    />
                  </div>
                </div>

                {subject && (
                  <p className="text-sm text-gray-300 mb-2">
                    <span className="text-gray-500">Subject:</span>{" "}
                    <span className="font-semibold">{subject}</span>
                  </p>
                )}

                <pre className="whitespace-pre-wrap text-sm text-gray-200 bg-black/30 rounded-xl p-4 mb-3 font-sans">
                  {body}
                </pre>

                {item.payload?.reasoning && (
                  <p className="text-xs text-gray-500 italic mb-3">
                    Agent reasoning: {item.payload.reasoning}
                  </p>
                )}

                {!showRejected ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      disabled={busy === item.id}
                      onClick={() => act(item.id, "approve")}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-400/40 text-emerald-200 disabled:opacity-50"
                    >
                      <Check className="w-3.5 h-3.5" />
                      Approve
                    </button>
                    <button
                      disabled={busy === item.id}
                      onClick={() => {
                        const reason = prompt("Reject reason? (optional)") || undefined;
                        act(item.id, "reject", reason);
                      }}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-red-500/20 hover:bg-red-500/30 border border-red-400/40 text-red-200 disabled:opacity-50"
                    >
                      <X className="w-3.5 h-3.5" />
                      Reject
                    </button>
                    <button
                      disabled={busy === item.id}
                      onClick={() => act(item.id, "mark-sent")}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-gold-500/20 hover:bg-gold-500/30 border border-gold-400/40 text-gold-200 disabled:opacity-50"
                    >
                      Mark as sent
                    </button>
                    <span className="ml-auto text-[10px] text-gray-500">
                      via {item.source_model} · priority {item.priority} · expires{" "}
                      {new Date(item.expires_at).toLocaleDateString()}
                    </span>
                  </div>
                ) : (
                  <p className="text-xs text-emerald-400">✓ approved — copy the message and send it from your own Gmail / IG / LinkedIn</p>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </section>
  );
};

export default OutreachQueue;
