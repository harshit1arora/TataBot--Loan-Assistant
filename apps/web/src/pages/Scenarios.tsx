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
              {summary.verified_income_paise && (
                <p>
                  Verified monthly income {money(summary.verified_income_paise)}
                </p>
              )}
              <strong>{summary.next_action}</strong>
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
