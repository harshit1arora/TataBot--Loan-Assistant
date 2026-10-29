import {
  Bot,
  Braces,
  Database,
  FileCheck2,
  GitBranch,
  KeyRound,
  LineChart,
  ScrollText,
} from "lucide-react";

const FEATURES = [
  {
    icon: Bot,
    title: "Conversational intake",
    body: "Natural language for amount, tenure and questions. Amount parsing handles lakh, crore, ₹ and plain figures — and refuses to guess when the sentence is ambiguous.",
  },
  {
    icon: GitBranch,
    title: "Server-side state machine",
    body: "Six explicit states with an allowed-transition table. Jumping from a fresh session to a decision is not expressible, so KYC cannot be skipped.",
  },
  {
    icon: Braces,
    title: "One versioned credit policy",
    body: "Score floor, pre-approved multiple, FOIR ceiling and tenure bounds in a single module. Every decision stores the policy version that produced it.",
  },
  {
    icon: FileCheck2,
    title: "Document-gated limits",
    body: "Declared income and verified income are separate fields. Only a processed salary slip above the confidence threshold can unlock an above-limit request.",
  },
  {
    icon: KeyRound,
    title: "Ownership on every read",
    body: "Customer-scoped JWTs, service tokens for service-to-service calls, and 404 — not 403 — for someone else's resource, so the API never confirms what exists.",
  },
  {
    icon: ScrollText,
    title: "Append-only audit trail",
    body: "Applications, decisions, documents and state transitions are recorded with redacted metadata. No HTTP route can read the trail back.",
  },
  {
    icon: Database,
    title: "Durable by default",
    body: "Sessions, messages and decisions live in Postgres, so a restart or a second replica does not lose an in-flight application.",
  },
  {
    icon: LineChart,
    title: "Operable",
    body: "JSON logs with a request id, Prometheus metrics, liveness and readiness split, and a circuit breaker around the LLM and the core service.",
  },
];

export function Features() {
  return (
    <section id="capabilities" className="border-y border-blue-100 bg-white py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-5">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-2xl">
            <p className="text-[11.5px] font-semibold uppercase tracking-[0.18em] text-blue-700">
              Capabilities
            </p>
            <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-slate-900 sm:text-[2.4rem]">
              Everything a lending flow needs to survive review
            </h2>
          </div>
          <p className="max-w-sm text-[13.5px] leading-relaxed text-slate-600">
            Not a chatbot with a database bolted on — a control plane for origination, where the
            model is one replaceable component among several.
          </p>
        </div>

        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <article
              key={title}
              className="group rounded-2xl border border-blue-100 bg-white p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-[0_18px_40px_-24px_rgba(29,78,216,0.45)]"
            >
              <span className="grid h-9 w-9 place-items-center rounded-lg bg-blue-700 text-white transition-colors group-hover:bg-blue-800">
                <Icon className="h-4 w-4" />
              </span>
              <h3 className="mt-4 text-[14px] font-semibold text-slate-900">{title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">{body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
