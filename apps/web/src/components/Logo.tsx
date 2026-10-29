/**
 * Brand mark.
 *
 * A "T" whose stem bends into a tick, with the final upstroke in the accent yellow —
 * a T that becomes an approval. Three strokes, so it still reads at 16 px.
 */
export function LogoMark({
  size = 36,
  tone = "brand",
  className = "",
}: {
  size?: number;
  /** "brand" = blue tile with white strokes; "light" = white tile, for dark surfaces. */
  tone?: "brand" | "light";
  className?: string;
}) {
  const light = tone === "light";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="TataBot"
      className={className}
    >
      <defs>
        <linearGradient id="tb-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={light ? "#FFFFFF" : "#2C6BF0"} />
          <stop offset="1" stopColor={light ? "#E8EFFC" : "#1B3A8F"} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="17" fill="url(#tb-mark)" />
      <rect
        x="2.75"
        y="2.75"
        width="58.5"
        height="58.5"
        rx="16.25"
        fill="none"
        stroke={light ? "#1B3A8F" : "#FFFFFF"}
        strokeOpacity={light ? 0.12 : 0.18}
        strokeWidth="1.5"
      />
      <g
        fill="none"
        strokeWidth="6.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        stroke={light ? "#1B3A8F" : "#FFFFFF"}
      >
        <path d="M17 20.5h30" />
        <path d="M32 20.5v11.5" />
        <path d="M32 32l8.4 8.6" />
      </g>
      <path
        d="M40.4 40.6L48.5 29"
        fill="none"
        stroke="#FBBF24"
        strokeWidth="6.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Wordmark({
  tone = "dark",
  showTagline = true,
}: {
  tone?: "dark" | "light";
  showTagline?: boolean;
}) {
  const onDark = tone === "light";
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark size={34} tone={onDark ? "light" : "brand"} />
      <span className="flex flex-col leading-none">
        <span
          className={`text-[15.5px] font-semibold tracking-tight ${
            onDark ? "text-white" : "text-slate-900"
          }`}
        >
          TataBot
        </span>
        {showTagline && (
          <span
            className={`mt-0.5 text-[9.5px] font-semibold uppercase tracking-[0.17em] ${
              onDark ? "text-amber-300" : "text-blue-700/70"
            }`}
          >
            Loan origination
          </span>
        )}
      </span>
    </span>
  );
}
