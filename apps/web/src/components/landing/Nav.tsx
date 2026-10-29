import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { Wordmark } from "@/components/Logo";

const LINKS = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#capabilities", label: "Capabilities" },
  { href: "#architecture", label: "Architecture" },
  { href: "#impact", label: "Impact" },
  { href: "#security", label: "Security" },
];

export { Wordmark };

export function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-300 ${
        scrolled
          ? "border-b border-blue-100 bg-white/90 shadow-[0_1px_0_rgba(29,78,216,0.06)] backdrop-blur-xl"
          : "bg-transparent"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <Link to="/" aria-label="TataBot home">
          <Wordmark />
        </Link>

        <nav aria-label="Sections" className="hidden items-center gap-7 md:flex">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="text-[13px] font-medium text-slate-600 transition-colors hover:text-blue-700"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <Link
            to="/login"
            className="rounded-lg bg-blue-700 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-blue-800"
          >
            Open the app
          </Link>
          <button
            type="button"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="grid h-9 w-9 place-items-center rounded-lg text-slate-600 hover:bg-blue-50 md:hidden"
          >
            {open ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {open && (
        <div className="border-t border-blue-100 bg-white px-5 py-4 shadow-lg md:hidden">
          <nav aria-label="Sections" className="flex flex-col gap-1">
            {LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="rounded-lg px-2 py-2.5 text-sm font-medium text-slate-700 hover:bg-blue-50 hover:text-blue-700"
              >
                {link.label}
              </a>
            ))}
          </nav>
        </div>
      )}
    </header>
  );
}
