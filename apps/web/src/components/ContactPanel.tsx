import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Clock, Loader2, Mail, Phone, Send, X } from "lucide-react";
import { ApiError, mySupportMessages, sendSupportMessage } from "@/lib/api";
import type { SupportMessageView, SupportTopic } from "@/lib/types";

const CHANNELS = [
  { icon: Phone, label: "Helpline", value: "1800-000-0000", note: "Mon–Sat, 9am–7pm IST" },
  { icon: Mail, label: "Email", value: "support@example.com", note: "Replies within a working day" },
  { icon: Clock, label: "Grievance", value: "grievance@example.com", note: "Formal complaints, RBI Fair Practices" },
];

const TOPICS: { value: SupportTopic; label: string }[] = [
  { value: "general", label: "General question" },
  { value: "application", label: "My application" },
  { value: "document", label: "Document upload" },
  { value: "repayment", label: "EMI or repayment" },
  { value: "grievance", label: "Complaint / grievance" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  customerName: string;
  defaultContact?: string;
}

/**
 * Contact panel.
 *
 * Messages are POSTed and stored — the reference shown back is a real row a support team
 * could read. The channels are placeholders and say so.
 */
export function ContactPanel({ open, onClose, customerName, defaultContact = "" }: Props) {
  const [topic, setTopic] = useState<SupportTopic>("general");
  const [message, setMessage] = useState("");
  const [contact, setContact] = useState(defaultContact);
  const [name, setName] = useState(customerName);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ reference: string; expected: string } | null>(null);
  const [history, setHistory] = useState<SupportMessageView[]>([]);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await mySupportMessages());
    } catch {
      setHistory([]); // not signed in, or nothing yet
    }
  }, []);

  useEffect(() => {
    if (open) {
      void loadHistory();
      setError(null);
    }
  }, [open, loadHistory]);

  useEffect(() => {
    setName(customerName);
  }, [customerName]);

  if (!open) return null;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const result = await sendSupportMessage({
        name: name.trim(),
        contact: contact.trim(),
        topic,
        message: message.trim(),
      });
      setCreated({ reference: result.reference, expected: result.expected_response });
      setMessage("");
      void loadHistory();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not send the message. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = name.trim().length >= 2 && contact.trim().length >= 5 && message.trim().length >= 10;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close contact panel"
        onClick={onClose}
        className="absolute inset-0 bg-blue-950/40 backdrop-blur-sm"
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="contact-title"
        className="relative flex h-full w-full max-w-md flex-col overflow-y-auto bg-white shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-blue-100 bg-blue-900 px-5 py-4 text-white">
          <div>
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-amber-300">
              Support
            </p>
            <h2 id="contact-title" className="text-base font-semibold">
              Contact us
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg bg-white/10 p-2 hover:bg-white/20"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-5 px-5 py-5">
          <ul className="space-y-2">
            {CHANNELS.map(({ icon: Icon, label, value, note }) => (
              <li key={label} className="flex items-start gap-3 rounded-xl border border-blue-100 p-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-700">
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    {label}
                  </p>
                  <p className="truncate text-[13.5px] font-medium text-slate-900">{value}</p>
                  <p className="text-[11.5px] text-slate-500">{note}</p>
                </div>
              </li>
            ))}
          </ul>
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11.5px] leading-relaxed text-amber-950">
            These channels are placeholders in this demonstration. Messages sent here are stored
            and referenceable, but nobody is paged.
          </p>

          {created ? (
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
              <p className="flex items-center gap-2 text-[13px] font-semibold text-blue-900">
                <CheckCircle2 className="h-4 w-4" />
                Message logged
              </p>
              <p className="mt-1.5 text-[13px] text-slate-700">
                Reference{" "}
                <span className="rounded bg-white px-1.5 py-0.5 font-mono text-[12.5px] font-semibold text-blue-900">
                  {created.reference}
                </span>
              </p>
              <p className="mt-1 text-[11.5px] text-slate-600">
                Expected response: {created.expected}.
              </p>
              <button
                type="button"
                onClick={() => setCreated(null)}
                className="mt-3 rounded-lg bg-blue-700 px-3 py-1.5 text-[12.5px] font-semibold text-white hover:bg-blue-800"
              >
                Send another message
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <label htmlFor="support-topic" className="mb-1 block text-[12.5px] font-medium text-slate-700">
                  What is this about?
                </label>
                <select
                  id="support-topic"
                  value={topic}
                  onChange={(event) => setTopic(event.target.value as SupportTopic)}
                  className="w-full appearance-none rounded-xl border border-blue-200 bg-white px-3 py-2.5 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600/20"
                >
                  {TOPICS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="support-name" className="mb-1 block text-[12.5px] font-medium text-slate-700">
                    Your name
                  </label>
                  <input
                    id="support-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    className="w-full rounded-xl border border-blue-200 px-3 py-2.5 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600/20"
                  />
                </div>
                <div>
                  <label htmlFor="support-contact" className="mb-1 block text-[12.5px] font-medium text-slate-700">
                    Phone or email
                  </label>
                  <input
                    id="support-contact"
                    value={contact}
                    onChange={(event) => setContact(event.target.value)}
                    placeholder="98XXXXXXXX"
                    className="w-full rounded-xl border border-blue-200 px-3 py-2.5 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600/20"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="support-message" className="mb-1 block text-[12.5px] font-medium text-slate-700">
                  Message
                </label>
                <textarea
                  id="support-message"
                  rows={4}
                  maxLength={2000}
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="Tell us what went wrong, and which application it relates to."
                  className="w-full resize-none rounded-xl border border-blue-200 px-3 py-2.5 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600/20"
                />
                <p className="mt-1 text-right text-[11px] text-slate-400">{message.length}/2000</p>
              </div>

              {error && (
                <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
                  {error}
                </p>
              )}

              <button
                type="button"
                onClick={submit}
                disabled={!canSubmit || busy}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-700 py-2.5 text-[13.5px] font-semibold text-white transition hover:bg-blue-800 disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {busy ? "Sending…" : "Send message"}
              </button>
            </div>
          )}

          {history.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Your messages
              </p>
              <ul className="mt-2 space-y-1.5">
                {history.map((row) => (
                  <li
                    key={row.reference}
                    className="flex items-center justify-between rounded-lg border border-blue-100 px-3 py-2 text-[12.5px]"
                  >
                    <span className="font-mono text-blue-900">{row.reference}</span>
                    <span className="text-slate-500">
                      {row.topic} · {row.status}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
