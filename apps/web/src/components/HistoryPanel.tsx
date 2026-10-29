import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Clock, Loader2, MessageSquare, X } from "lucide-react";
import { ApiError, listSessions, sessionMessages } from "@/lib/api";
import type { SessionSummary, TranscriptMessage } from "@/lib/types";
import { formatINR, messageTime, relativeDay, stateLabel } from "@/lib/format";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Resume an existing conversation in the chat view. */
  onResume: (sessionId: string) => void;
  /** Bumped when a new message is sent, so the list refreshes. */
  refreshKey: number;
}

function stateTone(state: string): string {
  if (state === "sanctioned") return "bg-blue-50 text-blue-800 ring-blue-100";
  if (state === "rejected") return "bg-rose-50 text-rose-800 ring-rose-100";
  if (state === "awaiting_document") return "bg-amber-50 text-amber-900 ring-amber-200";
  return "bg-slate-100 text-slate-700 ring-slate-200";
}

export function HistoryPanel({ open, onClose, onResume, refreshKey }: Props) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ session: SessionSummary; messages: TranscriptMessage[] } | null>(
    null,
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listSessions(20);
      setSessions(data.sessions);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your history.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void load();
      setPreview(null);
    }
  }, [open, refreshKey, load]);

  const openTranscript = async (session: SessionSummary) => {
    try {
      const messages = await sessionMessages(session.session_id);
      setPreview({ session, messages });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load that conversation.");
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Chat history">
      <button
        type="button"
        aria-label="Close history"
        onClick={onClose}
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]"
      />
      <aside className="relative flex h-full w-full max-w-md flex-col bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Your conversations
            </p>
            <h2 className="text-lg font-semibold text-slate-900">
              {preview ? "Conversation" : "History"}
            </h2>
          </div>
          <button
            type="button"
            onClick={preview ? () => setPreview(null) : onClose}
            aria-label={preview ? "Back to history" : "Close history"}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <p role="alert" className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </p>
          )}

          {preview ? (
            <div className="space-y-3">
              <div className="rounded-xl border border-blue-100 bg-blue-50/60 px-3 py-2 text-xs text-slate-600">
                {relativeDay(preview.session.updated_at)} · {preview.session.message_count} messages ·{" "}
                {stateLabel(preview.session.state)}
              </div>
              {preview.messages.map((message, index) => (
                <div
                  key={`${message.created_at}-${index}`}
                  className={`rounded-xl px-3 py-2 text-[13px] leading-relaxed ${
                    message.role === "customer"
                      ? "ml-6 bg-blue-700 text-white"
                      : "mr-6 bg-slate-100 text-slate-800"
                  }`}
                >
                  <p className="whitespace-pre-line">{message.content}</p>
                  <p
                    className={`mt-1 text-[10px] ${
                      message.role === "customer" ? "text-blue-100/80" : "text-slate-500"
                    }`}
                  >
                    {messageTime(message.created_at)}
                  </p>
                </div>
              ))}
              <button
                type="button"
                onClick={() => {
                  onResume(preview.session.session_id);
                  onClose();
                }}
                className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800"
              >
                Continue this conversation
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          ) : loading ? (
            <p className="flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading your conversations…
            </p>
          ) : sessions.length === 0 ? (
            <p className="text-sm text-slate-500">
              No conversations yet. Anything you ask from here on will appear in this list, so you
              can pick it up next time.
            </p>
          ) : (
            <ul className="space-y-2">
              {sessions.map((session) => (
                <li key={session.session_id}>
                  <button
                    type="button"
                    onClick={() => void openTranscript(session)}
                    className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-left transition hover:border-blue-200 hover:bg-blue-50/40"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
                        <Clock className="h-3 w-3" />
                        {relativeDay(session.updated_at)} · {messageTime(session.updated_at)}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${stateTone(session.state)}`}
                      >
                        {stateLabel(session.state)}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[13px] text-slate-800">
                      {session.last_message ?? "No messages"}
                    </p>
                    <p className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
                      <MessageSquare className="h-3 w-3" />
                      {session.message_count} messages
                      {session.requested_amount_paise ? ` · ${formatINR(session.requested_amount_paise)}` : ""}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="border-t border-slate-200 px-5 py-3 text-[11px] text-slate-500">
          Stored against your customer id. Only you can read these transcripts.
        </footer>
      </aside>
    </div>
  );
}
