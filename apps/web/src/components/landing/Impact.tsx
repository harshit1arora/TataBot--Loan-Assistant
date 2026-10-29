const AUDIENCES = [
  {
    who: "NBFCs & retail lenders",
    before: "Loan officers interpret policy differently, and the audit trail is a folder of PDFs.",
    after:
      "One policy module decides, every decision carries its policy version and reason codes, and the trail is queryable.",
  },
  {
    who: "Digital lending platforms",
    before: "Chat flows that quote numbers the backend never agreed to, and drop-offs when a document is needed.",
    after:
      "The assistant cannot invent a figure; document requests become an explicit, resumable state instead of a dead end.",
  },
  {
    who: "Banks & co-lending partners",
    before: "Integrating a partner means arguing about whose eligibility logic is authoritative.",
    after:
      "Eligibility is an isolated, versioned service with a typed contract — reviewable by risk and testable by engineering.",
  },
  {
    who: "Risk, audit & compliance",
    before: "No way to answer \"why was this loan approved in March?\" without reconstructing it by hand.",
    after:
      "Decision, inputs, policy version and reason codes are stored together; documents are private and access is logged.",
  },
];

const SHIFTS = [
  {
    label: "From prompt-driven to policy-driven",
    detail: "The model's role narrows to language. Eligibility, pricing and limits become code that can be reviewed and regression-tested.",
  },
  {
    label: "From declared to verified",
    detail: "Income that unlocks a higher limit comes from a processed document, not from what the applicant typed.",
  },
  {
    label: "From session memory to durable records",
    detail: "An application survives a restart, a redeploy and a second replica — so support and audit see the same thing the customer saw.",
  },
];

export function Impact() {
  return (
    <section id="impact" className="bg-white py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-5">
        <div className="max-w-2xl">
          <p className="text-[11.5px] font-semibold uppercase tracking-[0.18em] text-blue-700">
            Impact
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-slate-900 sm:text-[2.4rem]">
            What actually changes when the flow is built this way
          </h2>
          <p className="mt-4 text-[15px] leading-relaxed text-slate-600">
            The value is not that a chatbot can discuss loans. It is that a regulated decision
            becomes reproducible, explainable and cheap to change — which is where origination
            cost and audit exposure actually sit.
          </p>
        </div>

        <div className="mt-12 overflow-hidden rounded-2xl border border-blue-100">
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">
              What this architecture changes for different lending organisations
            </caption>
            <thead>
              <tr className="bg-blue-800 text-white">
                <th scope="col" className="px-5 py-3.5 text-[11.5px] font-semibold uppercase tracking-[0.14em]">
                  Who
                </th>
                <th scope="col" className="hidden px-5 py-3.5 text-[11.5px] font-semibold uppercase tracking-[0.14em] sm:table-cell">
                  Today
                </th>
                <th scope="col" className="px-5 py-3.5 text-[11.5px] font-semibold uppercase tracking-[0.14em]">
                  With this
                </th>
              </tr>
            </thead>
            <tbody>
              {AUDIENCES.map((row, i) => (
                <tr key={row.who} className={i % 2 ? "bg-blue-50/60" : "bg-white"}>
                  <th scope="row" className="px-5 py-4 align-top text-[13.5px] font-semibold text-slate-900">
                    {row.who}
                  </th>
                  <td className="hidden px-5 py-4 align-top text-[13px] leading-relaxed text-slate-500 sm:table-cell">
                    {row.before}
                  </td>
                  <td className="px-5 py-4 align-top text-[13px] leading-relaxed text-slate-700">
                    {row.after}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          {SHIFTS.map((shift) => (
            <div key={shift.label} className="rounded-2xl border border-blue-100 bg-blue-50/40 p-5">
              <h3 className="text-[13.5px] font-semibold text-blue-900">{shift.label}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">{shift.detail}</p>
            </div>
          ))}
        </div>

        <p className="mt-6 max-w-3xl text-[12px] leading-relaxed text-slate-500">
          These are qualitative effects of the architecture, not measured business results. This
          build has not processed real applications, so no conversion, cost or turnaround figures
          are claimed.
        </p>
      </div>
    </section>
  );
}
