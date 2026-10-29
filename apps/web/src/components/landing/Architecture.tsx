const LAYERS = [
  {
    tag: "Client",
    title: "React SPA",
    items: ["Typed API client", "15s timeout per call", "Signed-link downloads", "Single origin"],
  },
  {
    tag: "Conversation",
    title: "Conversation service",
    items: [
      "State machine + wording",
      "Amount / tenure parsing",
      "LLM: language only",
      "No customer data, no decisions",
    ],
  },
  {
    tag: "Core",
    title: "Core lending service",
    items: [
      "Credit policy (versioned)",
      "Underwriting + EMI in paise",
      "Documents, extraction, sanction",
      "Audit trail",
    ],
  },
];

export function Architecture() {
  return (
    <section id="architecture" className="relative overflow-hidden bg-blue-950 py-20 sm:py-24">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 grid-blue-dark opacity-70" />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-0 h-72 w-[40rem] -translate-x-1/2 rounded-full bg-blue-500/25 blur-[120px]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 right-0 h-64 w-64 rounded-full bg-amber-400/15 blur-[100px]"
      />

      <div className="relative mx-auto max-w-6xl px-5">
        <div className="max-w-2xl">
          <p className="text-[11.5px] font-semibold uppercase tracking-[0.18em] text-amber-300">
            Architecture
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-white sm:text-[2.4rem]">
            Two services, one boundary that matters
          </h2>
          <p className="mt-4 text-[15px] leading-relaxed text-blue-100/75">
            The conversational layer can talk. It cannot read a customer record, price a loan or
            approve one. That single rule is what makes the rest of the system defensible.
          </p>
        </div>

        <div className="mt-12 grid gap-4 lg:grid-cols-3">
          {LAYERS.map((layer, index) => (
            <div key={layer.tag} className="relative">
              <div className="h-full rounded-2xl border border-white/12 bg-white/[0.06] p-5 backdrop-blur-sm">
                <span className="text-[10.5px] font-semibold uppercase tracking-[0.2em] text-amber-300">
                  {layer.tag}
                </span>
                <h3 className="mt-2 text-[16px] font-semibold text-white">{layer.title}</h3>
                <ul className="mt-4 space-y-2">
                  {layer.items.map((item) => (
                    <li key={item} className="flex gap-2 text-[12.5px] leading-relaxed text-blue-100/80">
                      <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-amber-300/70" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              {index < LAYERS.length - 1 && (
                <div
                  aria-hidden="true"
                  className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-amber-300/60 lg:block"
                >
                  →
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="mt-6 grid gap-4 rounded-2xl border border-white/12 bg-white/[0.04] p-5 sm:grid-cols-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300/80">
              Data plane
            </p>
            <p className="mt-1.5 text-[13px] text-blue-100/80">
              Postgres for records, private object storage for documents, signed URLs for access.
            </p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300/80">
              Deployable two ways
            </p>
            <p className="mt-1.5 text-[13px] text-blue-100/80">
              Containers behind one gateway, or both services as serverless functions with a
              managed database and bucket.
            </p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300/80">
              Failure behaviour
            </p>
            <p className="mt-1.5 text-[13px] text-blue-100/80">
              If the model is unavailable the assistant keeps working. If the core service is
              unavailable it says so rather than inventing an answer.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
