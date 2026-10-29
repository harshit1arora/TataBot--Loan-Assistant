import { Check } from "lucide-react";

const CONTROLS = [
  "Short-lived JWTs with audience, issuer and expiry validated",
  "Service tokens kept separate from customer tokens",
  "404 for another customer's records — no existence oracle",
  "Magic-byte file sniffing, size caps, server-generated object keys",
  "Private bucket or disk; downloads only via signed 60-second links",
  "No score, limit, salary, phone or email in any LLM prompt",
  "Model output containing figures is discarded, not shown",
  "Audit rows are append-only and unreadable over HTTP",
  "Secrets from environment only — the app refuses to boot without them",
  "Demo login disabled automatically when ENV=production",
];

const COMPLIANCE = [
  {
    title: "Data minimisation",
    body: "The conversational layer sees a first name and a coarse band. Everything identifying stays in the core service.",
  },
  {
    title: "Purpose limitation",
    body: "Documents are used for income verification and nothing else; there is no path that sends them to a third party.",
  },
  {
    title: "Explainability",
    body: "Each decision stores reason codes and a policy version, so a decline can be explained months later without guesswork.",
  },
  {
    title: "Retention",
    body: "Records live in your database and bucket, so retention and erasure are your policy applied to your data — not a vendor's.",
  },
];

export function Security() {
  return (
    <section id="security" className="border-y border-blue-100 bg-blue-50/50 py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-5">
        <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr]">
          <div>
            <p className="text-[11.5px] font-semibold uppercase tracking-[0.18em] text-blue-700">
              Security &amp; governance
            </p>
            <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-slate-900 sm:text-[2.4rem]">
              Built to be examined, not just demoed
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-slate-600">
              Lending systems fail review for boring reasons: an endpoint without an ownership
              check, a document served from a public path, a decision nobody can explain. These are
              the controls that address them.
            </p>

            <div className="mt-8 grid gap-3 sm:grid-cols-2">
              {COMPLIANCE.map((item) => (
                <div key={item.title} className="rounded-xl border border-blue-100 bg-white p-4">
                  <h3 className="text-[13px] font-semibold text-blue-900">{item.title}</h3>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-slate-600">{item.body}</p>
                </div>
              ))}
            </div>
          </div>

          <ul className="grid gap-2 self-start rounded-2xl border border-blue-100 bg-white p-6 shadow-[0_18px_50px_-40px_rgba(29,78,216,0.6)]">
            {CONTROLS.map((control) => (
              <li key={control} className="flex items-start gap-2.5 text-[13px] leading-relaxed text-slate-700">
                <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-blue-700 text-white">
                  <Check className="h-2.5 w-2.5" strokeWidth={3.5} />
                </span>
                {control}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
