import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, CheckCircle, Circle, Download, Loader2, Search } from "lucide-react";
import {
  ApiError,
  downloadDocument,
  hasToken,
  myApplications,
  sessionStatus,
  sessionTrace,
} from "@/lib/api";
import type { ApplicationView, SessionTrace, SessionView } from "@/lib/types";
import { formatINR, reasonLabel } from "@/lib/format";
import { LogoMark } from "@/components/Logo";

const STAGES = [
  { key: "submitted", label: "Application received" },
  { key: "document_required", label: "Income document" },
  { key: "approved", label: "Credit decision" },
  { key: "sanctioned", label: "Sanction letter" },
];

function stageIndex(status: string | undefined): number {
  switch (status) {
    case "submitted":
      return 0;
    case "document_required":
      return 1;
    case "approved":
      return 2;
    case "sanctioned":
      return 3;
    case "rejected":
      return 2;
    default:
      return 0;
  }
}

export default function StatusTracker() {
  const [sessionId, setSessionId] = useState(sessionStorage.getItem("tatabot.sessionId") ?? "");
  const [session, setSession] = useState<SessionView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mine, setMine] = useState<ApplicationView[]>([]);
  const [trace, setTrace] = useState<SessionTrace | null>(null);
  const [showTrace, setShowTrace] = useState(false);

  const load = useCallback(async (id: string) => {
    if (!id) {
      setError("Enter the reference shown in your chat.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setSession(await sessionStatus(id));
      sessionTrace(id)
        .then(setTrace)
        .catch(() => setTrace(null));
    } catch (err) {
      setSession(null);
      setError(
        err instanceof ApiError && err.status === 404
          ? "No application found for that reference."
          : "Could not load the application status.",
      );
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const stored = sessionStorage.getItem("tatabot.sessionId");
    if (stored) load(stored);
  }, [load]);

  // The customer's own applications, straight from the database.
  useEffect(() => {
    if (!hasToken()) return;
    myApplications()
      .then(setMine)
      .catch(() => setMine([]));
  }, [session]);

  const application = session?.application ?? null;
  const index = stageIndex(application?.status);
  const rejected = application?.status === "rejected";

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="bg-blue-900 text-white">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to="/chat"
            aria-label="Back to chat"
            className="p-2 rounded-lg bg-white/10 hover:bg-white/20"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="flex items-center gap-2.5">
            <LogoMark size={30} tone="light" />
            <div>
              <h1 className="text-[15px] font-semibold leading-tight">Application status</h1>
              <p className="text-[11px] text-blue-100/60">Track every stage of your application</p>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
        {!hasToken() && (
          <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            You are signed out. <Link to="/login" className="underline">Sign in</Link> to view an
            application.
          </p>
        )}

        <form
          onSubmit={(event) => {
            event.preventDefault();
            load(sessionId.trim());
          }}
          className="bg-white rounded-2xl border border-slate-200 p-4 flex gap-2"
        >
          <label htmlFor="sessionId" className="sr-only">
            Application reference
          </label>
          <input
            id="sessionId"
            value={sessionId}
            onChange={(event) => setSessionId(event.target.value)}
            placeholder="Application reference (from your chat)"
            className="flex-1 rounded-xl border border-slate-300 px-3 py-2.5 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600/20"
          />
          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-60"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Look up
          </button>
        </form>

        {mine.length > 0 && (
          <section className="rounded-2xl border border-blue-100 bg-white p-4">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Your applications
            </h2>
            <ul className="mt-2 divide-y divide-blue-50">
              {mine.map((application) => (
                <li key={application.application_id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSessionId(application.application_id);
                      void load(application.application_id);
                    }}
                    className="flex w-full items-center justify-between gap-3 py-2.5 text-left hover:bg-blue-50/50"
                  >
                    <span className="text-[13px] font-medium text-slate-800">
                      {formatINR(application.requested_amount_paise)} · {application.tenure_months}m
                    </span>
                    <span className="text-[12px] text-slate-500">
                      {application.status.replace(/_/g, " ")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {error && (
          <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </p>
        )}

        {session && application && (
          <section className="bg-white rounded-2xl border border-slate-200 p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold text-blue-900">
                  {formatINR(application.requested_amount_paise)}
                </h2>
                <p className="text-xs text-slate-500">
                  {application.tenure_months} months · ref {application.application_id.slice(0, 8)}
                </p>
              </div>
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  rejected
                    ? "bg-rose-100 text-rose-800"
                    : application.status === "sanctioned"
                      ? "bg-blue-700 text-white"
                      : "bg-amber-200 text-amber-950"
                }`}
              >
                {application.status.replace(/_/g, " ")}
              </span>
            </div>

            <ol className="mt-5 space-y-3">
              {STAGES.map((stage, i) => {
                const done = i < index || application.status === "sanctioned";
                const current = i === index && application.status !== "sanctioned";
                return (
                  <li key={stage.key} className="flex items-center gap-3 text-sm">
                    {done ? (
                      <CheckCircle className="w-5 h-5 text-blue-600" />
                    ) : current ? (
                      <Circle className="w-5 h-5 text-amber-500" />
                    ) : (
                      <Circle className="w-5 h-5 text-slate-300" />
                    )}
                    <span className={done || current ? "text-blue-900" : "text-slate-400"}>
                      {stage.label}
                    </span>
                  </li>
                );
              })}
            </ol>

            {application.decision && (
              <div className="mt-5 rounded-xl border border-blue-200 bg-blue-50/70 p-3 text-sm">
                <p className="font-medium text-blue-900">
                  Decision: {application.decision.outcome.replace(/_/g, " ")}
                  {application.decision.emi_paise !== null &&
                    ` · EMI ${formatINR(application.decision.emi_paise)}`}
                </p>
                <ul className="mt-1 text-slate-700">
                  {application.decision.reason_codes.map((code) => (
                    <li key={code}>· {reasonLabel(code)}</li>
                  ))}
                </ul>
                <p className="mt-1 text-[11px] text-slate-400">
                  policy {application.decision.policy_version}
                </p>
              </div>
            )}

            {trace && trace.steps.length > 0 && (
              <div className="mt-5 border-t border-blue-100 pt-4">
                <button
                  type="button"
                  onClick={() => setShowTrace((value) => !value)}
                  aria-expanded={showTrace}
                  className="flex w-full items-center justify-between text-left"
                >
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    How this application moved
                  </span>
                  <span className="text-[12px] font-medium text-blue-700">
                    {showTrace ? "Hide" : `Show ${trace.steps.length} steps`}
                  </span>
                </button>

                {showTrace && (
                  <ol className="mt-3 space-y-2">
                    {trace.steps.map((step, index) => (
                      <li key={`${step.at}-${index}`} className="flex gap-2.5 text-[12px]">
                        <span className="mt-[3px] grid h-4 w-4 shrink-0 place-items-center rounded-full bg-blue-700 text-[9px] font-bold text-white">
                          {index + 1}
                        </span>
                        <span className="min-w-0">
                          <span className="font-medium text-slate-800">
                            {step.from_state.replace(/_/g, " ")} → {step.to_state.replace(/_/g, " ")}
                          </span>
                          <span className="block text-[11px] text-slate-500">{step.handled_by}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}

            {application.sanction_document_id && (
              <button
                type="button"
                onClick={() => downloadDocument(application.sanction_document_id!)}
                className="mt-4 inline-flex items-center gap-2 rounded-xl bg-blue-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800"
              >
                <Download className="w-4 h-4" />
                Download sanction letter
              </button>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
