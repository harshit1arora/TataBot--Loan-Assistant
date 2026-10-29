// Formatting helpers. Money arrives as integer paise and is never re-derived here.

export function formatINR(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return "—";
  const rupees = paise / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(rupees);
}

export function formatINRShort(paise: number): string {
  const rupees = paise / 100;
  if (rupees >= 10000000) return `₹${(rupees / 10000000).toFixed(2)} cr`;
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(2)} lakh`;
  return formatINR(paise);
}

export function reasonLabel(code: string): string {
  const map: Record<string, string> = {
    // Neutral wording: for a self-registered customer the limit is derived, not offered.
    within_pre_approved_limit: "Within your available limit",
    emi_within_foir: "EMI is within 50% of verified income",
    credit_score_below_min: "Credit score below our minimum",
    amount_above_max_multiple_of_pre_approved: "More than 2× your pre-approved limit",
    emi_exceeds_foir_limit: "EMI would exceed 50% of verified income",
    age_out_of_range: "Age outside our lending range",
    amount_above_policy_max: "Amount outside the permitted range",
    verified_income_document_required: "Proof of income required",
    verified_income_unavailable: "Income could not be verified",
  };
  return map[code] ?? code.replace(/_/g, " ");
}

export function stateLabel(state: string): string {
  return STATE_LABELS[state] ?? state.replace(/_/g, " ");
}

export const STATE_LABELS: Record<string, string> = {
  new: "Getting started",
  awaiting_amount: "Collecting details",
  awaiting_document: "Waiting for document",
  assessing: "Assessing document",
  sanctioned: "Sanctioned",
  rejected: "Not approved",
};

/** "12 Oct, 4:32 pm" — short, unambiguous, Indian convention (dd Mon, 12-hour). */
export function messageTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const day = date.getDate().toString().padStart(2, "0");
  const month = date.toLocaleString("en-IN", { month: "short" });
  let hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, "0");
  const meridiem = hours >= 12 ? "pm" : "am";
  hours = hours % 12 || 12;
  return `${day} ${month}, ${hours}:${minutes} ${meridiem}`;
}

/** "12 Oct 2026" — for day separators and history rows. */
export function messageDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getDate().toString().padStart(2, "0")} ${date.toLocaleString("en-IN", {
    month: "short",
  })} ${date.getFullYear()}`;
}

export function dayKey(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

export function relativeDay(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const startOf = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const days = Math.round((startOf(today) - startOf(date)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return messageDate(iso);
}
