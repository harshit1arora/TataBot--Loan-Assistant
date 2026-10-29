import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, FileCheck2, Lock, ScrollText } from "lucide-react";

const PROOF = [
  { icon: ScrollText, label: "Deterministic, versioned credit policy" },
  { icon: Lock, label: "Token-scoped access to every record" },
  { icon: FileCheck2, label: "Income verified from documents, not claims" },
];

/** A static illustration of the product — labelled as such, never passed off as live data. */
function ProductPreview() {
  return (
    <div className="relative">
      <div
        aria-hidden="true"
        className="absolute -inset-5 rounded-[2rem] bg-gradient-to-tr from-blue-200/70 via-amber-100/60 to-transparent blur-2xl"
      />
      <div className="relative overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-[0_30px_70px_-30px_rgba(29,78,216,0.45)]">
        <div className="flex items-center gap-2 border-b border-blue-100 bg-blue-50/70 px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-blue-200" />
          <span className="h-2.5 w-2.5 rounded-full bg-blue-200" />
          <span className="h-2.5 w-2.5 rounded-full bg-blue-200" />
          <span className="ml-2 text-[11px] font-medium text-slate-500">Loan assistant</span>
          <span className="ml-auto rounded-full bg-amber-300 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-950">
            Awaiting document
          </span>
        </div>

        <div className="space-y-3 p-4">
          <div className="ml-auto max-w-[78%] rounded-2xl rounded-br-md bg-blue-700 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-white">
            I need 5 lakh for 36 months
          </div>

          <div className="max-w-[86%] rounded-2xl rounded-bl-md border border-blue-100 bg-blue-50/60 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-slate-700">
            ₹5,00,000 is above your pre-approved limit of ₹3,00,000, so I need your latest
            salary slip before I can decide.
          </div>

          <div className="rounded-xl border border-amber-300 bg-amber-50 p-3">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-800">
              Decision
            </p>
            <p className="mt-1 text-[12.5px] font-medium text-slate-900">Document needed</p>
            <p className="mt-0.5 text-[11.5px] text-slate-600">· Proof of income required</p>
            <p className="mt-1.5 text-[10px] text-slate-400">policy 2026.10-v1</p>
          </div>

          <div className="flex items-center gap-2 rounded-xl border border-blue-100 bg-white px-3 py-2.5">
            <FileCheck2 className="h-4 w-4 shrink-0 text-blue-700" />
            <span className="truncate text-[11.5px] text-slate-600">payslip_march.pdf</span>
            <span className="ml-auto shrink-0 rounded-full bg-blue-700 px-2 py-0.5 text-[10px] font-semibold text-white">
              verified
            </span>
          </div>
        </div>
      </div>
      <p className="mt-3 text-center text-[11px] text-slate-400">
        Illustrative interface. No real customer data is used.
      </p>
    </div>
  );
}

export function Hero() {
  return (
    <section className="relative overflow-hidden bg-white pt-28 pb-20 sm:pt-32">
      {/* depth: faint blue grid, a blue light source, a yellow one */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 grid-blue opacity-70" />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-48 left-1/2 h-[34rem] w-[52rem] -translate-x-1/2 rounded-full bg-blue-200/40 blur-[120px]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-40 right-0 h-[26rem] w-[26rem] rounded-full bg-amber-200/40 blur-[110px]"
      />

      <div className="relative mx-auto grid max-w-6xl items-center gap-14 px-5 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="animate-fade-up">
          <span className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-[11.5px] font-medium text-blue-800">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
            Multi-agent origination · policy-first by design
          </span>

          <h1 className="mt-6 text-[2.05rem] font-semibold leading-[1.1] tracking-tight text-slate-900 sm:text-[3.15rem] sm:leading-[1.06]">
            Loan decisions you
            <br className="hidden sm:inline" />{" "}
            <span className="highlight-yellow text-blue-800 sm:whitespace-nowrap sm:px-1">
              can defend in an audit
            </span>
            .
          </h1>

          <p className="mt-5 max-w-xl text-[15.5px] leading-relaxed text-slate-600">
            A conversational origination stack where the language model writes the words and a
            versioned credit policy makes the decision. Every figure traced, every document
            verified, every state change recorded.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              to="/login"
              className="group inline-flex items-center gap-2 rounded-xl bg-blue-700 px-5 py-3 text-[14px] font-semibold text-white shadow-lg shadow-blue-700/20 transition hover:bg-blue-800"
            >
              Try the assistant
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex items-center gap-2 rounded-xl border border-blue-200 bg-white px-5 py-3 text-[14px] font-semibold text-blue-800 transition hover:border-blue-300 hover:bg-blue-50"
            >
              See how it works
            </a>
          </div>

          <ul className="mt-9 space-y-2.5">
            {PROOF.map(({ icon: Icon, label }) => (
              <li key={label} className="flex items-center gap-2.5 text-[13px] text-slate-600">
                <Icon className="h-4 w-4 shrink-0 text-blue-600" />
                {label}
              </li>
            ))}
          </ul>
        </div>

        <div className="animate-rise lg:pl-4">
          <ProductPreview />
        </div>
      </div>

      <div className="relative mx-auto mt-16 max-w-6xl px-5">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3 border-t border-blue-100 pt-6 text-[11.5px] font-medium uppercase tracking-[0.14em] text-slate-400">
          <span>Built for NBFCs</span>
          <span className="hidden h-1 w-1 rounded-full bg-amber-400 sm:block" />
          <span>Retail banks</span>
          <span className="hidden h-1 w-1 rounded-full bg-amber-400 sm:block" />
          <span>Digital lenders</span>
          <span className="hidden h-1 w-1 rounded-full bg-amber-400 sm:block" />
          <span>Co-lending platforms</span>
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-amber-900">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Works with the LLM switched off
          </span>
        </div>
      </div>
    </section>
  );
}
