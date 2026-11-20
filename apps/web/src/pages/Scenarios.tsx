import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { hasToken, request } from "@/lib/api";
import type { ApplicationView, DocumentView } from "@/lib/types";

type Quote = {
  quote_id: string;
  amount_rupees: number;
  tenure_months: number;
  rate: number;
  emi_paise: number;
  total_interest_paise: number;
  outcome: string;
  reasons: string[];
  expires_at: number;
  product: string;
};
type Summary = {
  reasons: string[];
  counterfactuals: {policy_version:string; annual_rate_percent:number; current_outcome:string; options: {type:string; amount_paise:number; tenure_months:number; income_paise?:number}[]} | null;
  bank_cross_check: { status: string; source: string; signals: string[]; independently_verified: boolean } | null;
  timeline: { at: string; event: string }[];
  verified_income_paise: number | null;
  application: ApplicationView;
  next_action: string;
  income_source: string;
  score_source: string;
  identity_source: string;
  consent_version: string | null;
};
type Acceptance = {
  application?: ApplicationView;
  previous?: Quote;
  replacement?: Quote;
  reason?: string;
};
const money = (paise: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(
    paise / 100,
  );
const field = "border border-slate-300 rounded-lg px-3 py-2 w-full";
const button =
  "rounded-lg bg-blue-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50";
const post = (data?: object) => ({
  method: "POST",
  body: data ? JSON.stringify(data) : undefined,
});

export default function Scenarios() {
  const [rows, setRows] = useState([
    { amount: "500000", months: "36" },
    { amount: "500000", months: "48" },
  ]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [bankFile, setBankFile] = useState<File | null>(null);
  const [bankConsent, setBankConsent] = useState(false);
  const [bankResult, setBankResult] = useState("");
  const [inbox, setInbox] = useState<{id:string; message:string; application_id:string; read_at:string | null}[]>([]);
  useEffect(() => { if (hasToken()) void request<typeof inbox>("/v1/notices").then(setInbox); }, []);
  async function refresh(id: string) {
    setSummary(await request<Summary>(`/v1/applications/${id}/summary`));
  }
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const quote = params.get("quote");
    if (quote && hasToken())
      void request<Quote>(`/v1/quotes/${encodeURIComponent(quote)}`)
        .then((q) => setQuotes([q]))
        .catch((e) => setNotice(e.message));
    const id = params.get("application");
    if (id && hasToken()) void refresh(id).catch((e) => setNotice(e.message));
  }, []);
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function compare() {
    setQuotes(
      await request<Quote[]>(
        "/v1/quotes/compare",
        post({
          scenarios: rows.map((r) => ({
            amount_rupees: Number(r.amount),
            tenure_months: Number(r.months),
          })),
        }),
      ),
    );
  }
  async function accept(q: Quote) {
    const result = await request<Acceptance>(
      `/v1/quotes/${q.quote_id}/accept`,
      post(),
    );
    if (result.replacement && result.previous) {
      setNotice(
        `${result.reason}. Previous EMI ${money(result.previous.emi_paise)}, revised EMI ${money(result.replacement.emi_paise)}. Review and accept again to continue.`,
      );
      setQuotes([result.replacement]);
      return;
    }
    if (result.application) {
      history.replaceState(
        {},
        "",
        "/scenarios?application=" + result.application.application_id,
      );
      await refresh(result.application.application_id);
      setQuotes([]);
    }
  }
  async function upload(file: File) {
    if (!summary) return;
    const id = summary.application.application_id;
    const form = new FormData();
    form.append("file", file);
    form.append("application_id", id);
    form.append("doc_type", "salary_slip");
    const doc = await request<DocumentView>("/v1/documents", {
      method: "POST",
      body: form,
    });
    await request(
      `/v1/applications/${id}/documents/${doc.document_id}/assess`,
      post(),
      55000,
    );
    await refresh(id);
  }
  return (
    <main className="mx-auto max-w-4xl p-6 space-y-6">
      <Link to="/chat" className="text-blue-800">
        ← Chat
      </Link>
      <h1 className="text-3xl font-semibold">Compare loan scenarios</h1>
      {inbox.filter(n => !n.read_at).map(n => <div className="rounded border p-3" key={n.id}>{n.message} <button onClick={() => void request("/v1/notices/" + n.id + "/read", post()).then(() => setInbox(old => old.filter(x => x.id !== n.id)))}>Dismiss</button></div>)}
      {!hasToken() ? (
        <Link to="/login">Sign in to compare your options</Link>
      ) : (
        <>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              void act(compare);
            }}
          >
            {rows.map((r, i) => (
              <div key={i} className="grid grid-cols-2 gap-3">
                <label>
                  Loan amount (₹)
                  <input
                    className={field}
                    type="number"
                    min="10000"
                    max="5000000"
                    required
                    value={r.amount}
                    onChange={(e) =>
                      setRows(
                        rows.map((v, j) =>
                          i === j ? { ...v, amount: e.target.value } : v,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  Tenure (months)
                  <input
                    className={field}
                    type="number"
                    min="6"
                    max="60"
                    required
                    value={r.months}
                    onChange={(e) =>
                      setRows(
                        rows.map((v, j) =>
                          i === j ? { ...v, months: e.target.value } : v,
                        ),
                      )
                    }
                  />
                </label>
              </div>
            ))}
            <button className={button} disabled={busy}>
              Compare
            </button>{" "}
            {rows.length < 3 && (
              <button
                type="button"
                onClick={() =>
                  setRows([...rows, { amount: "300000", months: "24" }])
                }
              >
                Add scenario
              </button>
            )}
          </form>
          <div className="grid gap-4 md:grid-cols-3">
            {quotes.map((q) => (
              <article
                className="rounded-xl border p-4 space-y-2"
                key={q.quote_id}
              >
                <h2 className="font-semibold">
                  {money(q.amount_rupees * 100)} · {q.tenure_months} months
                </h2>
                <p>
                  {q.product} · {q.rate}% p.a.
                </p>
                <p>Monthly EMI {money(q.emi_paise)}</p>
                <p>Total interest {money(q.total_interest_paise)}</p>
                <p>{q.outcome.replace(/_/g, " ")}</p>
                <p className="text-xs">
                  Valid until{" "}
                  {new Date(q.expires_at * 1000).toLocaleTimeString()}
                </p>
                <button
                  className={button}
                  disabled={busy}
                  onClick={() => void act(() => accept(q))}
                >
                  Accept and apply
                </button>
              </article>
            ))}
          </div>
          {summary && (
            <section className="border rounded-xl p-5 space-y-2">
              <h2 className="text-xl font-semibold">Your decision</h2>
              <p>
                Application {summary.application.application_id} ·{" "}
                {summary.application.status.replace(/_/g, " ")}
              </p>
              <p>
                Amount assessed{" "}
                {money(summary.application.requested_amount_paise)} ·{" "}
                {summary.application.tenure_months} months
              </p>
              <p>
                Identity · {summary.identity_source}{" "}
                {summary.consent_version && (
                  <>· Consent {summary.consent_version}</>
                )}
              </p>
              <p>
                Income source · {summary.income_source.replace(/_/g, " ")} ·
                Credit score · {summary.score_source.replace(/_/g, " ")}
              </p>
              <p>{summary.reasons.join(" ")}</p>
              {summary.counterfactuals && <section className="rounded border p-3 space-y-2">
                <h3 className="font-semibold">Possible alternatives under current policy</h3>
                <p>Illustrative checks use current customer details and policy {summary.counterfactuals.policy_version} at {summary.counterfactuals.annual_rate_percent}% p.a. A new application requires a fresh assessment.</p>
                {summary.counterfactuals.current_outcome !== "reject" && <p>The current assessment differs from this recorded decline. Compare a new scenario for current terms.</p>}
                {summary.counterfactuals.current_outcome === "reject" && summary.counterfactuals.options.length === 0 && <p>No single amount, tenure or income change was found that meets current policy.</p>}
                <ul className="list-disc pl-5">
                  {summary.counterfactuals.options.map(option => <li key={option.type}>
                    {option.type === "maximum_amount" && <>A maximum of {money(option.amount_paise)} over {option.tenure_months} months meets the current policy check.</>}
                    {option.type === "minimum_tenure" && <>A tenure of {option.tenure_months} months for {money(option.amount_paise)} meets the current policy check.</>}
                    {option.type === "minimum_verified_income" && <>Verified monthly income of at least {money(option.income_paise ?? 0)} would meet the affordability check for {money(option.amount_paise)} over {option.tenure_months} months. Income must be supported by evidence.</>}
                  </li>)}
                </ul>
              </section>}
              {summary.verified_income_paise && (
                <p>
                  Verified monthly income {money(summary.verified_income_paise)}
                </p>
              )}
              <strong>{summary.next_action}</strong>
              {summary.bank_cross_check && <p>Bank comparison: {summary.bank_cross_check.status} · source {summary.bank_cross_check.source} · independent verification: {summary.bank_cross_check.independently_verified ? "yes" : "no"} · signals: {summary.bank_cross_check.signals.join(", ") || "none"}</p>}
              {summary.application.status === "document_required" && <section className="rounded border p-3 space-y-2">
                <h3 className="font-semibold">Synthetic bank statement</h3>
                <p>Upload a JSON array containing at least three consecutive monthly salary credits before uploading your salary slip. Each entry needs a date, an amount_paise, and category set to salary.</p>
                <input aria-label="Bank statement JSON" type="file" accept=".json,application/json" onChange={e => setBankFile(e.target.files?.[0] ?? null)} />
                <label className="block"><input type="checkbox" checked={bankConsent} onChange={e => setBankConsent(e.target.checked)} /> I consent to use these statement details for this application.</label>
                <button type="button" disabled={!bankFile || !bankConsent || busy} onClick={() => void act(async () => {
                  if (!bankFile) return;
                  const parsed: unknown = JSON.parse(await bankFile.text());
                  if (!Array.isArray(parsed)) throw new Error("The JSON must contain an array of credits.");
                  const checked = await request<{status:string;signals:string[]}>("/v1/applications/" + summary.application.application_id + "/bank-statement", post({consent_version:"bank-assessment-v1",credits:parsed}));
                  setBankResult("Statement recorded. " + checked.status.replace(/_/g, " ") + ". " + checked.signals.join(", "));
                })}>Check statement</button>
                {bankResult && <p role="status">{bankResult}</p>}
              </section>}
              <h3 className="font-semibold">Application timeline</h3>
              <ol className="space-y-1">
                {summary.timeline.map((item, index) => (
                  <li key={index}>{new Date(item.at).toLocaleString()} · {item.event}</li>
                ))}
              </ol>
              {summary.application.status === "document_required" &&
                !summary.next_action.startsWith("Await") && (
                  <label className="block">
                    Salary slip{" "}
                    <input
                      type="file"
                      disabled={busy}
                      accept=".pdf,.png,.jpg,.jpeg"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) void act(() => upload(file));
                      }}
                    />
                  </label>
                )}
              <button
                className="block text-blue-800"
                onClick={() =>
                  void act(() => refresh(summary.application.application_id))
                }
              >
                Refresh decision
              </button>
              {summary.application.status === "approved" && (
                <button
                  className={button}
                  onClick={() =>
                    void act(async () => {
                      await request(
                        `/v1/applications/${summary.application.application_id}/sanction`,
                        post(),
                      );
                      await refresh(summary.application.application_id);
                    })
                  }
                >
                  Issue sanction letter
                </button>
              )}
              {summary.application.sanction_document_id && (
                <button
                  onClick={() =>
                    void act(async () => {
                      const link = await request<{ url: string }>(
                        `/v1/documents/${summary.application.sanction_document_id}/signed-url`,
                      );
                      location.assign(link.url);
                    })
                  }
                >
                  Download sanction letter
                </button>
              )}
            </section>
          )}
        </>
      )}
      {notice && <p role="status">{notice}</p>}
    </main>
  );
}
