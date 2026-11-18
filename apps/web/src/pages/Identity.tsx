import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { oidc, providerToken } from "@/lib/identity";
import { setToken } from "@/lib/api";

export default function Identity() {
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const [enroll, setEnroll] = useState(false);
  const [phone, setPhone] = useState("");
  const started = useRef(false);
  async function exchange(payload?: object) {
    const response = await fetch("/auth/verified", {
      method: "POST",
      headers: {
        Authorization: "Bearer " + (await providerToken()),
        "Content-Type": "application/json",
      },
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const data = await response.json();
    if (response.status === 422 && !payload) {
      setEnroll(true);
      return;
    }
    if (!response.ok)
      throw new Error(
        data.detail || data.error?.message || "Identity exchange failed.",
      );
    setToken(data.access_token, data.expires_in);
    navigate("/chat", { replace: true });
  }
  useEffect(() => {
    if (started.current || !oidc) return;
    started.current = true;
    const manager = oidc;
    void (async () => {
      if (!new URLSearchParams(location.search).has("code")) {
        await manager.signinRedirect({
          state: {
            destination: location.hash === "#review" ? "review" : "chat",
          },
        });
        return;
      }
      const user = await manager.signinRedirectCallback();
      history.replaceState({}, "", "/identity");
      if ((user.state as { destination?: string })?.destination === "review") {
        navigate("/review");
        return;
      }
      setPhone(String(user.profile.phone_number || "").replace(/^\+91/, ""));
      await exchange();
    })().catch((e) => setMessage(String(e.message)));
    // The callback can only be redeemed once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const values = Object.fromEntries(new FormData(e.currentTarget));
    await exchange({
      consent_version: "income-assessment-v1",
      profile: {
        name: values.name,
        email: values.email,
        phone,
        age: Number(values.age),
        city: values.city,
        declared_monthly_income_rupees: Number(values.income),
        declared_credit_score: Number(values.score),
      },
    }).catch((err) => setMessage(err.message));
  }
  return (
    <main className="mx-auto max-w-lg p-8 space-y-4">
      <h1 className="text-2xl font-semibold">Verified customer enrollment</h1>
      {!oidc && (
        <p>The identity provider is not configured for this deployment.</p>
      )}
      {message && <p role="alert">{message}</p>}
      {enroll && (
        <form onSubmit={submit} className="grid gap-4">
          <p>Verified mobile number · {phone}</p>
          {(
            [
              ["name", "Full name", "text"],
              ["email", "Email", "email"],
              ["age", "Age", "number"],
              ["city", "City", "text"],
              ["income", "Declared monthly income (₹)", "number"],
              ["score", "Self-declared credit score", "number"],
            ] as const
          ).map(([key, label, type]) => (
            <label key={key}>
              {label}
              <input
                required
                name={key}
                type={type}
                className="block w-full border rounded p-2"
              />
            </label>
          ))}
          <label>
            <input type="checkbox" required /> I consent to TataBot using my
            declared details and uploaded income documents to assess this
            application.
          </label>
          <button className="bg-blue-900 text-white p-3 rounded">
            Create verified account
          </button>
        </form>
      )}
    </main>
  );
}
