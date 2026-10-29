import { FileSearch, Gauge, ShieldCheck, Upload } from "lucide-react";

const STEPS = [
  {
    icon: FileSearch,
    step: "01",
    title: "Identity first",
    body: "The customer proves the registered mobile number and receives a short-lived token. The token — not the request body — decides whose data is in play.",
  },
  {
    icon: Gauge,
    step: "02",
    title: "Ask, then assess",
    body: "The assistant collects amount and tenure in plain language. The policy engine returns approve, decline or needs-document, with reason codes and the policy version attached.",
  },
  {
    icon: Upload,
    step: "03",
    title: "Documents, not declarations",
    body: "Anything above the pre-approved limit waits for a salary slip. The file is sniffed, stored privately, read, and only then does verified income exist.",
  },
  {
    icon: ShieldCheck,
    step: "04",
    title: "Sanction, once",
    body: "An approved application issues one letter — idempotent by constraint — downloadable through a signed link that expires in a minute.",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="relative bg-blue-50/50 py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-5">
        <div className="max-w-2xl">
          <p className="text-[11.5px] font-semibold uppercase tracking-[0.18em] text-blue-700">
            The flow
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-slate-900 sm:text-[2.4rem]">
            Four steps, in an order the system enforces
          </h2>
          <p className="mt-4 text-[15px] leading-relaxed text-slate-600">
            Most assistants let the model decide what happens next. This one does not: the
            workflow position lives on the server and only advances through transitions that are
            explicitly allowed.
          </p>
        </div>

        <ol className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(({ icon: Icon, step, title, body }) => (
            <li
              key={step}
              className="group relative overflow-hidden rounded-2xl border border-blue-100 bg-white p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-[0_18px_40px_-26px_rgba(29,78,216,0.55)]"
            >
              <span
                aria-hidden="true"
                className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-blue-700 to-amber-400 opacity-0 transition-opacity group-hover:opacity-100"
              />
              <div className="flex items-center justify-between">
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-700 text-white">
                  <Icon className="h-[18px] w-[18px]" />
                </span>
                <span className="text-[11px] font-semibold tracking-[0.2em] text-amber-500">
                  {step}
                </span>
              </div>
              <h3 className="mt-5 text-[15px] font-semibold text-slate-900">{title}</h3>
              <p className="mt-2 text-[13.5px] leading-relaxed text-slate-600">{body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
