import { Link } from "react-router-dom";
import { Wordmark } from "@/components/Logo";

const COLUMNS = [
  {
    title: "Product",
    links: [
      { label: "How it works", href: "#how-it-works" },
      { label: "Capabilities", href: "#capabilities" },
      { label: "Impact", href: "#impact" },
    ],
  },
  {
    title: "Engineering",
    links: [
      { label: "Architecture", href: "#architecture" },
      { label: "Security", href: "#security" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="border-t border-blue-950 bg-blue-950 py-12">
      <div className="mx-auto max-w-6xl px-5">
        <div className="flex flex-wrap justify-between gap-10">
          <div className="max-w-sm">
            <Wordmark tone="light" />
            <p className="mt-4 text-[12.5px] leading-relaxed text-blue-100/60">
              A reference implementation of policy-first loan origination: conversational intake,
              deterministic credit decisions and an auditable trail.
            </p>
          </div>

          <div className="flex gap-14">
            {COLUMNS.map((column) => (
              <div key={column.title}>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300/90">
                  {column.title}
                </p>
                <ul className="mt-3 space-y-2">
                  {column.links.map((link) => (
                    <li key={link.label}>
                      <a
                        href={link.href}
                        className="text-[13px] text-blue-100/70 transition-colors hover:text-white"
                      >
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300/90">
                Application
              </p>
              <ul className="mt-3 space-y-2">
                <li>
                  <Link to="/login" className="text-[13px] text-blue-100/70 hover:text-white">
                    Sign in
                  </Link>
                </li>
                <li>
                  <Link to="/status" className="text-[13px] text-blue-100/70 hover:text-white">
                    Track status
                  </Link>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-6">
          <p className="text-[11.5px] text-blue-100/50">
            Independent engineering demonstration. Not affiliated with, endorsed by, or operated by
            any bank or NBFC. No real customer data is processed and no credit is offered.
          </p>
          <p className="text-[11.5px] text-blue-100/40">Simulated environment · {new Date().getFullYear()}</p>
        </div>
      </div>
    </footer>
  );
}
