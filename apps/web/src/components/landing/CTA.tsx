import { Link } from "react-router-dom";
import { ArrowRight, Terminal } from "lucide-react";

export function CTA() {
  return (
    <section className="relative overflow-hidden bg-blue-900 py-20">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 grid-blue-dark opacity-60" />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 h-72 w-[44rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-500/30 blur-[120px]"
      />
      <div className="relative mx-auto max-w-3xl px-5 text-center">
        <h2 className="text-balance text-3xl font-semibold tracking-tight text-white sm:text-[2.5rem]">
          Run the flow yourself
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-[15px] leading-relaxed text-blue-100/80">
          Pick a demo customer, ask for more than the pre-approved limit, then upload a payslip to
          watch the decision change. Every step is the real API — no mock layer.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link
            to="/login"
            className="group inline-flex items-center gap-2 rounded-xl bg-amber-400 px-5 py-3 text-[14px] font-semibold text-amber-950 transition hover:bg-amber-300"
          >
            Open the assistant
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
          <Link
            to="/status"
            className="inline-flex items-center gap-2 rounded-xl border border-white/25 px-5 py-3 text-[14px] font-semibold text-white transition hover:border-white/50 hover:bg-white/10"
          >
            <Terminal className="h-4 w-4" />
            Track an application
          </Link>
        </div>
      </div>
    </section>
  );
}
