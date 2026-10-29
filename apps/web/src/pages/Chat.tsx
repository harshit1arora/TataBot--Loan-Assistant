import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  Download,
  FileUp,
  History,
  LifeBuoy,
  LogOut,
  Paperclip,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  ApiError,
  clearToken,
  downloadDocument,
  hasToken,
  profile,
  sendMessage,
  sessionMessages,
  sessionStatus,
  uploadDocument,
} from "@/lib/api";
import type { ChatResponse, CustomerProfile, DecisionView } from "@/lib/types";
import {
  STATE_LABELS,
  dayKey,
  formatINR,
  messageDate,
  messageTime,
  reasonLabel,
} from "@/lib/format";
import TypingIndicator from "@/components/TypingIndicator";
import { ContactPanel } from "@/components/ContactPanel";
import { HistoryPanel } from "@/components/HistoryPanel";
import { LogoMark } from "@/components/Logo";

interface Bubble {
  id: string;
  role: "customer" | "assistant" | "system";
  text: string;
  /** ISO timestamp, shown under every message and used for day separators. */
  at: string;
  attachment?: boolean;
  /** Set when the reply came from the agent graph. */
  agents?: string[];
  citations?: string[];
}

function newId(): string {
  return crypto.randomUUID();
}

function DecisionCard({ decision }: { decision: DecisionView }) {
  const tone =
    decision.outcome === "approve"
      ? "border-blue-300 bg-blue-50"
      : decision.outcome === "reject"
        ? "border-rose-200 bg-rose-50"
        : "border-amber-300 bg-amber-50";
  return (
    <div className={`mt-3 rounded-xl border p-3 text-sm ${tone}`}>
      <p className="font-semibold text-blue-900">
        {decision.outcome === "approve"
          ? "Approved"
          : decision.outcome === "reject"
            ? "Not approved"
            : "Document needed"}
      </p>
      {decision.emi_paise !== null && (
        <p className="text-slate-700">
          EMI {formatINR(decision.emi_paise)} · {decision.tenure_months} months ·{" "}
          {decision.interest_rate_percent.toFixed(2)}% p.a.
        </p>
      )}
      <ul className="mt-1 space-y-0.5 text-slate-600">
        {decision.reason_codes.map((code) => (
          <li key={code}>· {reasonLabel(code)}</li>
        ))}
      </ul>
      <p className="mt-1 text-[11px] text-slate-400">policy {decision.policy_version}</p>
    </div>
  );
}

export default function Chat() {
  const navigate = useNavigate();
  const [me, setMe] = useState<CustomerProfile | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(
    sessionStorage.getItem("tatabot.sessionId"),
  );
  const [state, setState] = useState<string>("new");
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<DecisionView | null>(null);
  const [sanctionId, setSanctionId] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [contactOpen, setContactOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!hasToken()) {
      navigate("/login", { replace: true });
    }
  }, [navigate]);

  const rememberSession = (id: string) => {
    setSessionId(id);
    sessionStorage.setItem("tatabot.sessionId", id);
  };

  const applyResponse = useCallback((response: ChatResponse) => {
    rememberSession(response.session_id);
    setState(response.state);
    setDecision(response.application?.decision ?? null);
    setSanctionId(response.sanction_document_id ?? null);
    setSuggestions(response.suggested_actions ?? []);
    if (response.intent === "contact") setContactOpen(true);
    setBubbles((prev) => [
      ...prev,
      {
        id: newId(),
        role: "assistant",
        text: response.reply,
        at: new Date().toISOString(),
        agents: response.agent_route?.length ? response.agent_route : undefined,
        citations: response.citations?.length ? response.citations : undefined,
      },
    ]);
  }, []);

  // One greeting round-trip opens the session on the server.
  useEffect(() => {
    if (started.current || !hasToken()) return;
    started.current = true;

    (async () => {
      setBusy(true);
      try {
        setMe(await profile());
        const response = await sendMessage("hello", sessionStorage.getItem("tatabot.sessionId"));
        applyResponse(response);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          navigate("/login", { replace: true });
          return;
        }
        setError(err instanceof ApiError ? err.message : "Could not start the conversation.");
      } finally {
        setBusy(false);
      }
    })();
  }, [applyResponse, navigate]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bubbles, busy]);

  /** Reopen a past conversation: restore its transcript and continue from its state. */
  async function resumeConversation(targetSessionId: string) {
    setBusy(true);
    setError(null);
    try {
      const [transcript, view] = await Promise.all([
        sessionMessages(targetSessionId),
        sessionStatus(targetSessionId),
      ]);
      setSessionId(targetSessionId);
      setState(view.state);
      setDecision(view.application?.decision ?? null);
      setSanctionId(view.application?.sanction_document_id ?? null);
      setBubbles(
        transcript
          .filter((message) => message.role !== "system")
          .map((message) => ({
            id: newId(),
            role: message.role as "customer" | "assistant",
            text: message.content,
            at: message.created_at,
          })),
      );
      sessionStorage.setItem("tatabot.session", targetSessionId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reopen that conversation.");
    } finally {
      setBusy(false);
    }
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setInput("");
    setError(null);
    setSuggestions([]);
    setBubbles((prev) => [
      ...prev,
      { id: newId(), role: "customer", text: message, at: new Date().toISOString() },
    ]);
    setBusy(true);
    try {
      applyResponse(await sendMessage(message, sessionId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Message could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(file: File) {
    if (!sessionId) return;
    setError(null);
    setBusy(true);
    setBubbles((prev) => [
      ...prev,
      {
        id: newId(),
        role: "customer",
        text: file.name,
        at: new Date().toISOString(),
        attachment: true,
      },
    ]);
    try {
      const response = await uploadDocument(sessionId, file);
      setState(response.state);
      setDecision(response.application?.decision ?? decision);
      setSanctionId(response.sanction_document_id ?? null);
      setBubbles((prev) => [
      ...prev,
      { id: newId(), role: "assistant", text: response.reply, at: new Date().toISOString() },
    ]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const awaitingDocument = state === "awaiting_document";

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <header className="bg-blue-900 text-white">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <LogoMark size={30} tone="light" />
            <div>
              <h1 className="text-[15px] font-semibold leading-tight">
                Loan assistant{me ? ` · ${me.name.split(" ")[0]}` : ""}
              </h1>
              <p className="text-[11px] text-blue-100/60">
                Policy-led decisions · every step recorded
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setContactOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-sm hover:bg-white/20"
            >
              <LifeBuoy className="h-3.5 w-3.5" />
              Contact us
            </button>
            <Link
              to="/status"
              className="text-sm px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20"
            >
              Track status
            </Link>
            <button
              type="button"
              onClick={() => setHistoryOpen(true)}
              aria-label="Chat history"
              className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-2 text-xs font-semibold text-white hover:bg-white/20"
            >
              <History className="w-4 h-4" />
              History
            </button>
            <button
              type="button"
              aria-label="Sign out"
              onClick={() => {
                clearToken();
                navigate("/login", { replace: true });
              }}
              className="p-2 rounded-lg bg-white/10 hover:bg-white/20"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {me && (
        <div className="bg-white border-b border-slate-200">
          <div className="max-w-3xl mx-auto px-4 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-600">
            <span className="inline-flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5 text-blue-600" />
              {me.limit_source === "indicative" ? "Indicative limit" : "Pre-approved"}{" "}
              {formatINR(me.pre_approved_limit_paise)}
            </span>
            {me.score_source === "self_declared" && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10.5px] font-semibold text-amber-950">
                score self-declared
              </span>
            )}
            <span>Profile band: {me.credit_score_band}</span>
            <span
              className={`ml-auto rounded-full px-2.5 py-0.5 font-semibold ${
                awaitingDocument
                  ? "bg-amber-200 text-amber-950"
                  : state === "rejected"
                    ? "bg-rose-100 text-rose-900"
                    : state === "sanctioned"
                      ? "bg-blue-700 text-white"
                      : "bg-blue-50 text-blue-800"
              }`}
            >
              {STATE_LABELS[state] ?? state}
            </span>
          </div>
        </div>
      )}

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-4" aria-live="polite">
          {bubbles.map((bubble, index) => {
            const showDay = index === 0 || dayKey(bubble.at) !== dayKey(bubbles[index - 1].at);
            const isLast = index === bubbles.length - 1;
            return (
              <div key={bubble.id}>
                {showDay && (
                  <div className="my-4 flex items-center gap-3" aria-hidden="true">
                    <span className="h-px flex-1 bg-slate-200" />
                    <span className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">
                      {messageDate(bubble.at)}
                    </span>
                    <span className="h-px flex-1 bg-slate-200" />
                  </div>
                )}

                <div
                  className={`flex ${bubble.role === "customer" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-line shadow-sm ${
                      bubble.role === "customer"
                        ? "bg-blue-700 text-white"
                        : "bg-white text-slate-800 border border-slate-200"
                    }`}
                  >
                    {bubble.attachment && (
                      <Paperclip
                        className="mr-1.5 inline h-3.5 w-3.5 align-[-2px]"
                        aria-hidden="true"
                      />
                    )}
                    {bubble.text}

                    {bubble.agents && (
                      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-blue-100 pt-2">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          Agents
                        </span>
                        {bubble.agents.map((agent) => (
                          <span
                            key={agent}
                            className="rounded-full bg-blue-50 px-2 py-0.5 text-[10.5px] font-semibold text-blue-800 ring-1 ring-blue-100"
                          >
                            {agent}
                          </span>
                        ))}
                        {bubble.citations && (
                          <span className="ml-auto text-[10px] text-slate-400">
                            {bubble.citations.length} source{bubble.citations.length > 1 ? "s" : ""}
                          </span>
                        )}
                      </div>
                    )}

                    {bubble.role === "assistant" && decision && isLast && (
                      <DecisionCard decision={decision} />
                    )}

                    <p
                      className={`mt-1.5 text-[10px] ${
                        bubble.role === "customer" ? "text-blue-100/80" : "text-slate-400"
                      }`}
                    >
                      {messageTime(bubble.at)}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}


          {busy && <TypingIndicator agentName="Assistant" />}

          {sanctionId && (
            <button
              type="button"
              onClick={() => downloadDocument(sanctionId)}
              className="inline-flex items-center gap-2 rounded-xl bg-blue-900 text-white px-4 py-2.5 text-sm font-medium hover:bg-slate-800"
            >
              <Download className="w-4 h-4" />
              Download sanction letter
            </button>
          )}

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-800"
            >
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div ref={endRef} />
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-3xl mx-auto px-4 py-4">
          {suggestions.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() =>
                    suggestion.toLowerCase().includes("contact")
                      ? setContactOpen(true)
                      : send(suggestion)
                  }
                  className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-800 hover:bg-blue-100"
                >
                  <Sparkles className="w-3 h-3" />
                  {suggestion}
                </button>
              ))}
            </div>
          )}

          <form
            onSubmit={(event) => {
              event.preventDefault();
              send(input);
            }}
            className="flex items-center gap-2"
          >
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf,image/jpeg,image/png"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onUpload(file);
              }}
            />
            <button
              type="button"
              aria-label="Upload salary slip"
              title={awaitingDocument ? "Upload salary slip" : "You can upload when a document is requested"}
              disabled={!awaitingDocument || busy}
              onClick={() => fileInput.current?.click()}
              className={`p-3 rounded-xl border transition ${
                awaitingDocument
                  ? "border-amber-300 bg-blue-50 text-blue-800 hover:bg-blue-100"
                  : "border-slate-200 bg-slate-50 text-slate-400 cursor-not-allowed"
              }`}
            >
              <FileUp className="w-5 h-5" />
            </button>

            <label htmlFor="message" className="sr-only">
              Your message
            </label>
            <input
              id="message"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              maxLength={1000}
              placeholder={
                awaitingDocument
                  ? "Upload your salary slip, or ask a question…"
                  : "Ask about a loan, e.g. I need 2 lakh for 36 months"
              }
              className="flex-1 rounded-xl border border-slate-300 px-4 py-3 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600/20"
            />
            <button
              type="submit"
              aria-label="Send message"
              disabled={busy || !input.trim()}
              className="p-3 rounded-xl bg-blue-700 text-white hover:bg-blue-800 disabled:opacity-50"
            >
              <Send className="w-5 h-5" />
            </button>
          </form>

          <p className="mt-2 flex items-center gap-1.5 text-[11px] text-slate-500">
            <ArrowRight className="w-3 h-3" />
            Decisions follow a published credit policy. Nothing here is a credit offer.
          </p>
        </div>
      </footer>

      <ContactPanel
        open={contactOpen}
        onClose={() => setContactOpen(false)}
        customerName={me?.name ?? ""}
      />

      <HistoryPanel
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onResume={(id) => void resumeConversation(id)}
        refreshKey={historyKey}
      />
    </div>
  );
}
