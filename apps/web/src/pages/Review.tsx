import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { providerToken } from "@/lib/identity";

type Item = {
  document_id: string;
  application_id: string;
  filename: string;
  confidence: number | null;
  fields: Record<string, unknown> | null;
  referral: string;
  owner: string | null;
  waiting_since: string;
  overdue: boolean;
};

async function staff(path: string, init: RequestInit = {}) {
  const response = await fetch("/v1/reviews" + path, {
    ...init,
    headers: {
      Authorization: "Bearer " + (await providerToken()),
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || "Review request failed.");
  }
  return response;
}
export default function Review() {
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Item | null>(null);
  const [action, setAction] = useState("confirm"),
    [income, setIncome] = useState(""),
    [reason, setReason] = useState("");
  const [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  async function load() {
    setItems(await (await staff("")).json());
  }
  useEffect(() => {
    void load().catch((e) => setMessage(e.message));
  }, []);
  async function download(item: Item) {
    try {
      const blob = await (await staff("/" + item.document_id + "/file")).blob();
      const url = URL.createObjectURL(blob),
        a = document.createElement("a");
      a.href = url;
      a.download = item.filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setMessage((e as Error).message);
    }
  }
  return (
    <main className="mx-auto max-w-4xl p-6 space-y-5">
      <h1 className="text-3xl font-semibold">Underwriter queue</h1>
      <Link to="/operations">Operations and support</Link>
      <Link to="/identity#review" className="text-blue-800">
        Sign in as an underwriter
      </Link>
      <button
        className="ml-4"
        onClick={() => void load().catch((e) => setMessage(e.message))}
      >
        Refresh queue
      </button>
      {items.length === 0 && !message && <p>No documents awaiting review.</p>}
      {items.map((item) => (
        <button
          className="block w-full rounded-lg border p-4 text-left"
          key={item.document_id}
          onClick={() => {
            setSelected(item);
            setReason("");
            setIncome("");
            setAction(
              item.fields?.monthly_income_paise ? "confirm" : "correct",
            );
          }}
        >
          {item.filename} · Application {item.application_id} · {item.owner || "Unassigned"} · Waiting since {new Date(item.waiting_since).toLocaleString()} {item.overdue && "· Overdue"}
        </button>
      ))}
      {selected && (
        <form
          className="grid gap-3 rounded-lg border p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              const res = await (
                await staff("/" + selected.document_id, {
                  method: "POST",
                  body: JSON.stringify({
                    action,
                    reason,
                    income_rupees: action === "correct" ? Number(income) : null,
                  }),
                })
              ).json();
              setMessage(
                `Review recorded. Application ${res.application.application_id} is ${res.application.status}.`,
              );
              setSelected(null);
              await load();
            } catch (err) {
              setMessage((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <h2 className="font-semibold">{selected.referral}</h2>
          <button type="button" onClick={() => void staff("/" + selected.document_id + "/claim", {method:"POST"}).then(load).catch((e) => setMessage(e.message))}>Claim review</button>
          <p>
            Extraction confidence ·{" "}
            {selected.confidence === null
              ? "Unavailable"
              : Math.round(selected.confidence * 100) + "%"}
          </p>
          <dl>
            {Object.entries(selected.fields || {}).map(([k, v]) => (
              <div key={k}>
                <dt className="font-medium">{k}</dt>
                <dd>{String(v)}</dd>
              </div>
            ))}
          </dl>
          <button
            type="button"
            className="text-left text-blue-800"
            onClick={() => void download(selected)}
          >
            Download evidence
          </button>
          <label>
            Resolution{" "}
            <select value={action} onChange={(e) => setAction(e.target.value)}>
              <option value="confirm">Confirm extracted income</option>
              <option value="correct">Correct income</option>
              <option value="replace">Request replacement</option>
            </select>
          </label>
          {action === "correct" && (
            <label>
              Verified monthly income (₹){" "}
              <input
                type="number"
                required
                min="1"
                value={income}
                onChange={(e) => setIncome(e.target.value)}
                className="border p-2"
              />
            </label>
          )}
          <label>
            Reason{" "}
            <textarea
              className="block w-full border p-2"
              required
              minLength={3}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button
            className="rounded bg-blue-900 p-2 text-white"
            disabled={busy}
          >
            Record review
          </button>
        </form>
      )}
      {message && <p role="status">{message}</p>}
    </main>
  );
}
