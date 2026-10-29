import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Loader2 } from "lucide-react";
import { ApiError, login, registerCustomer } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { LogoMark } from "@/components/Logo";

const DEMO_CUSTOMERS = [
  { id: "CUST001", phone: "9810000001", label: "Asha Verma · pre-approved ₹3,00,000" },
  { id: "CUST002", phone: "9810000002", label: "Rahul Sharma · pre-approved ₹2,00,000" },
  { id: "CUST004", phone: "9810000004", label: "Vikram Singh · below credit floor (declined path)" },
  { id: "CUST010", phone: "9810000010", label: "Sourav Ghosh · pre-approved ₹5,00,000" },
];

type Mode = "signin" | "register";

const FIELD =
  "w-full rounded-xl border border-blue-200 bg-white px-3 py-2.5 text-sm text-slate-900 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600/20";
const LABEL = "mb-1 block text-[12.5px] font-medium text-slate-700";

/**
 * Two ways in:
 *
 * * **Sign in** — an existing customer (including the four seeded demo profiles).
 * * **Create account** — a brand-new customer entering their own details. The record is
 *   written to the database, the limit is derived from their declared income, and their
 *   applications are real rows from that moment on.
 *
 * The credit score is *declared* here. A production deployment pulls it from a bureau and
 * the applicant never types it; the record stores which of the two it was.
 */
export default function Login() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("signin");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // sign-in state
  const [customerId, setCustomerId] = useState(DEMO_CUSTOMERS[0].id);
  const [phone, setPhone] = useState(DEMO_CUSTOMERS[0].phone);

  // registration state
  const [form, setForm] = useState({
    name: "",
    phone: "",
    email: "",
    age: 30,
    city: "",
    income: 60000,
    score: 740,
  });

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  async function onSignIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(customerId.trim().toUpperCase(), phone.trim());
      navigate("/chat", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function onRegister(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await registerCustomer({
        name: form.name.trim(),
        phone: form.phone.trim(),
        email: form.email.trim(),
        age: Number(form.age),
        city: form.city.trim(),
        declared_monthly_income_rupees: Number(form.income),
        declared_credit_score: Number(form.score),
      });
      // Sign straight in with the account that was just created.
      await login(created.customer_id, form.phone.trim());
      navigate("/chat", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not create the account. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  function pickDemo(id: string) {
    const found = DEMO_CUSTOMERS.find((c) => c.id === id);
    if (found) {
      setCustomerId(found.id);
      setPhone(found.phone);
    }
  }

  const indicativeLimit = Math.min(Math.floor((Number(form.income) * 6) / 1000) * 1000, 5000000);

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-b from-blue-50 via-white to-amber-50/40 p-6">
      <div className="w-full max-w-md rounded-2xl border border-blue-100 bg-white p-8 shadow-xl shadow-blue-900/5">
        <div className="mb-4 flex items-center gap-2.5">
          <LogoMark size={38} />
          <span className="text-[17px] font-semibold tracking-tight text-slate-900">TataBot</span>
        </div>

        <h1 className="text-2xl font-bold text-slate-900">
          {mode === "signin" ? "Sign in to continue" : "Create your account"}
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          {mode === "signin"
            ? "Use a demo profile, or an account you created earlier."
            : "Your details are stored in the database and used for a real decision."}
        </p>

        <div className="mt-5 grid grid-cols-2 gap-1 rounded-xl bg-blue-50 p-1" role="tablist">
          {(["signin", "register"] as Mode[]).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              onClick={() => {
                setMode(value);
                setError(null);
              }}
              className={`rounded-lg px-3 py-2 text-[13px] font-semibold transition ${
                mode === value
                  ? "bg-white text-blue-800 shadow-sm"
                  : "text-slate-600 hover:text-blue-800"
              }`}
            >
              {value === "signin" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        {mode === "signin" ? (
          <form onSubmit={onSignIn} className="mt-5 space-y-4">
            <div>
              <label htmlFor="customerId" className={LABEL}>
                Customer ID
              </label>
              <select
                id="customerId"
                value={customerId}
                onChange={(e) => pickDemo(e.target.value)}
                className={`${FIELD} appearance-none`}
              >
                {DEMO_CUSTOMERS.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id} — {c.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="phone" className={LABEL}>
                Registered mobile number
              </label>
              <input
                id="phone"
                inputMode="numeric"
                autoComplete="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className={FIELD}
              />
              <p className="mt-1 text-[11.5px] text-slate-500">
                The demo provider matches this against the record instead of sending an OTP.
              </p>
            </div>

            {error && (
              <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-700 py-3 font-semibold text-white transition hover:bg-blue-800 disabled:opacity-60"
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              {busy ? "Signing in…" : "Continue"}
            </button>
          </form>
        ) : (
          <form onSubmit={onRegister} className="mt-5 space-y-3.5">
            <div>
              <label htmlFor="name" className={LABEL}>
                Full name
              </label>
              <input
                id="name"
                required
                minLength={2}
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                className={FIELD}
                placeholder="Your name"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="regPhone" className={LABEL}>
                  Mobile number
                </label>
                <input
                  id="regPhone"
                  required
                  inputMode="numeric"
                  pattern="[6-9][0-9]{9}"
                  title="10 digits, starting 6–9"
                  value={form.phone}
                  onChange={(e) => set("phone", e.target.value)}
                  className={FIELD}
                  placeholder="98XXXXXXXX"
                />
              </div>
              <div>
                <label htmlFor="age" className={LABEL}>
                  Age
                </label>
                <input
                  id="age"
                  required
                  type="number"
                  min={18}
                  max={80}
                  value={form.age}
                  onChange={(e) => set("age", Number(e.target.value))}
                  className={FIELD}
                />
              </div>
            </div>

            <div>
              <label htmlFor="email" className={LABEL}>
                Email
              </label>
              <input
                id="email"
                required
                type="email"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                className={FIELD}
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label htmlFor="city" className={LABEL}>
                City
              </label>
              <input
                id="city"
                required
                minLength={2}
                value={form.city}
                onChange={(e) => set("city", e.target.value)}
                className={FIELD}
                placeholder="Pune"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="income" className={LABEL}>
                  Monthly income (₹)
                </label>
                <input
                  id="income"
                  required
                  type="number"
                  min={5000}
                  step={1000}
                  value={form.income}
                  onChange={(e) => set("income", Number(e.target.value))}
                  className={FIELD}
                />
              </div>
              <div>
                <label htmlFor="score" className={LABEL}>
                  Credit score (300–900)
                </label>
                <input
                  id="score"
                  required
                  type="number"
                  min={300}
                  max={900}
                  value={form.score}
                  onChange={(e) => set("score", Number(e.target.value))}
                  className={FIELD}
                />
              </div>
            </div>

            <div className="rounded-xl border border-blue-100 bg-blue-50/70 p-3 text-[11.5px] leading-relaxed text-slate-600">
              <p>
                <span className="font-semibold text-blue-900">Indicative limit:</span>{" "}
                {formatINR(indicativeLimit * 100)} — six months of the income you enter, capped by
                policy. This is derived, not an offer.
              </p>
              <p className="mt-1.5">
                <span className="font-semibold text-blue-900">Credit score is self-declared.</span>{" "}
                There is no bureau integration in this build, so the decision records that it
                trusted your word. A real deployment pulls it from a bureau.
              </p>
            </div>

            {error && (
              <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-700 py-3 font-semibold text-white transition hover:bg-blue-800 disabled:opacity-60"
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              {busy ? "Creating…" : "Create account and continue"}
              {!busy && <ArrowRight className="h-4 w-4" />}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
