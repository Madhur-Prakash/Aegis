/**
 * Money, dates and hashes.
 *
 * Every rupee figure in the product goes through `inr()`. `en-IN` is not a
 * preference: the grouping is different, and a judge from Bangalore reading
 * "₹420,000" instead of "₹4,20,000" would be right to notice.
 */

export const inr = (paise: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(paise / 100);

/** With paise, for a figure that must reconcile to the last unit. */
export const inrExact = (paise: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(paise / 100);

export const paiseToRupees = (paise: number) => paise / 100;
export const rupeesToPaise = (rupees: number) => Math.round(rupees * 100);

export const num = (value: number, digits = 0) =>
  new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);

export const pct = (value: number, digits = 0) =>
  new Intl.NumberFormat("en-IN", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);

/** Confidence is always three decimals: 0.510 and 0.51 must not look different. */
export const confidence = (value: number) => value.toFixed(3);

export const dateTime = (iso: string | Date, locale = "en-IN") =>
  new Intl.DateTimeFormat(locale === "hi" ? "hi-IN" : "en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(typeof iso === "string" ? new Date(iso) : iso);

export const dateOnly = (iso: string | Date, locale = "en-IN") =>
  new Intl.DateTimeFormat(locale === "hi" ? "hi-IN" : "en-IN", {
    dateStyle: "medium",
    timeZone: "Asia/Kolkata",
  }).format(typeof iso === "string" ? new Date(iso) : iso);

export const timeOnly = (iso: string | Date) =>
  new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "Asia/Kolkata",
  }).format(typeof iso === "string" ? new Date(iso) : iso);

/** Truncated in the middle, never at the end: both ends of a hash carry signal. */
export const shortHash = (hash: string | null | undefined, head = 4, tail = 4) => {
  if (!hash) return "-";
  const clean = hash.startsWith("0x") ? hash.slice(2) : hash;
  if (clean.length <= head + tail) return hash;
  return `${clean.slice(0, head)}…${clean.slice(-tail)}`;
};

export const relative = (iso: string | Date) => {
  const then = typeof iso === "string" ? new Date(iso).getTime() : iso.getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const table: [Intl.RelativeTimeFormatUnit, number][] = [
    ["second", 60],
    ["minute", 60],
    ["hour", 24],
    ["day", 7],
    ["week", 4.35],
    ["month", 12],
    ["year", Number.POSITIVE_INFINITY],
  ];
  let value = seconds;
  for (const [unit, size] of table) {
    if (Math.abs(value) < size) return formatter.format(-Math.round(value), unit);
    value /= size;
  }
  return formatter.format(-Math.round(value), "year");
};

/** State -> semantic tone. The ONLY place a state becomes a hue (spec: hue is data). */
export type Tone = "pass" | "unverified" | "fail" | "neutral";

export const milestoneTone = (state: string): Tone => {
  switch (state) {
    case "SETTLED":
    case "RELEASE_APPROVED":
      return "pass";
    case "UNDER_HUMAN_REVIEW":
    case "VERIFYING":
    case "DISPUTED":
      return "unverified";
    case "REJECTED":
      return "fail";
    default:
      return "neutral";
  }
};

export const verdictTone = (verdict: string): Tone =>
  verdict === "PASS"
    ? "pass"
    : verdict === "FAIL"
      ? "fail"
      : verdict === "UNVERIFIABLE"
        ? "unverified"
        : "neutral";

export const decisionTone = (decision: string): Tone =>
  decision === "RELEASE"
    ? "pass"
    : decision === "REJECT"
      ? "fail"
      : decision === "ESCALATE"
        ? "unverified"
        : "neutral";

export const dealTone = (state: string): Tone => {
  switch (state) {
    case "COMPLETED":
      return "pass";
    case "DISPUTED":
    case "IN_PROGRESS":
    case "FUNDED":
      return "unverified";
    case "CANCELLED":
    case "EXPIRED":
    case "REFUNDED":
      return "fail";
    default:
      return "neutral";
  }
};

export const riskTone = (score: number | null | undefined): Tone => {
  if (score === null || score === undefined) return "neutral";
  if (score < 0.25) return "pass";
  if (score < 0.5) return "unverified";
  return "fail";
};

export const seq = (n: number, total?: number) =>
  total === undefined
    ? String(n).padStart(2, "0")
    : `${String(n).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
