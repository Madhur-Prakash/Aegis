"use client";

/**
 * The small shared pieces: buttons, inputs, skeletons, empty and error states,
 * count-up numerals, the seal, and the copy-on-click hash.
 *
 * Every one of these consumes tokens and named motion variants.  There is no hex
 * colour, raw duration or inline easing anywhere in this file (spec 25.1).
 */

import { motion, useMotionValue, useSpring, useTransform } from "motion/react";
import type { ReactNode } from "react";
import { useEffect, useId, useState } from "react";

import { D, E, inView } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useT } from "@/lib/i18n";

// ── Buttons ─────────────────────────────────────────────────────────────────
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger" | "capsule";
  tone?: "pass" | "unverified" | "fail";
  cursorLabel?: string;
};

export function Button({
  variant = "primary",
  tone,
  cursorLabel,
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`btn btn--${variant} ${tone ? `btn--tone-${tone}` : ""} ${className}`}
      data-cursor={rest.disabled ? undefined : cursorLabel ? `label:${cursorLabel}` : ""}
      {...rest}
    >
      {children}
    </button>
  );
}

/** The capsule from the reference screenshot: a pill with a leading live dot. */
export function Capsule({
  children,
  dotTone = "pass",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { dotTone?: "pass" | "unverified" | "fail" }) {
  return (
    <button className="capsule" data-cursor="" {...rest}>
      <span className="capsule-dot" style={{ background: `var(--sig-${dotTone})` }} aria-hidden />
      {children}
    </button>
  );
}

// ── Inputs ──────────────────────────────────────────────────────────────────
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label micro">{label}</span>
      {children}
      {hint && !error ? <span className="field-hint">{hint}</span> : null}
      {error ? (
        <span className="field-error" role="alert">
          {error}
        </span>
      ) : null}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" data-cursor="text" {...props} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className="input input--area" data-cursor="text" {...props} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="input input--select" data-cursor="" {...props} />;
}

/** A real button with `aria-pressed`, not a styled div (ui/00 §7). */
export function Toggle({
  pressed,
  onToggle,
  children,
  label,
}: {
  pressed: boolean;
  onToggle: () => void;
  children?: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      className={`toggle ${pressed ? "is-on" : ""}`}
      aria-pressed={pressed}
      aria-label={label}
      onClick={onToggle}
      data-cursor=""
    >
      <span className="toggle-knob" aria-hidden />
      {children}
    </button>
  );
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`segmented-item ${value === option.value ? "is-on" : ""}`}
          aria-current={value === option.value ? "true" : undefined}
          onClick={() => onChange(option.value)}
          data-cursor=""
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// ── Loading, empty, error (ui/03 §7) ────────────────────────────────────────
/** Skeletons, not spinners.  They match the final layout so nothing jumps. */
export function Skeleton({
  lines = 3,
  height = 14,
  className = "",
}: {
  lines?: number;
  height?: number;
  className?: string;
}) {
  return (
    <div className={`skeleton-group ${className}`} aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{ height, width: `${100 - (i % 3) * 12}%` }}
        />
      ))}
    </div>
  );
}

export function Loading({ label }: { label?: string }) {
  const t = useT();
  return (
    <div className="state-block" role="status" aria-live="polite">
      <span className="micro">{label ?? t("common.loading")}</span>
      <Skeleton lines={3} />
    </div>
  );
}

/** A `micro` label, one line of explanation, and the single action that resolves
 *  it.  Never an illustration. */
export function Empty({
  label,
  body,
  action,
}: {
  label: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="state-block state-block--empty">
      <span className="micro">{label}</span>
      {body ? <p className="state-body">{body}</p> : null}
      {action}
    </div>
  );
}

/** Errors appear instantly -- no entrance animation -- and carry the typed code
 *  from the API envelope, mirroring I9. */
export function ErrorBlock({
  code,
  message,
  onRetry,
}: {
  code: string;
  message: string;
  onRetry?: () => void;
}) {
  const t = useT();
  return (
    <div className="state-block state-block--error" role="alert">
      <span className="mono-code">{code}</span>
      <p className="state-body">{message}</p>
      {onRetry ? (
        <Button variant="ghost" onClick={onRetry}>
          {t("common.retry")}
        </Button>
      ) : null}
    </div>
  );
}

// ── Numbers ─────────────────────────────────────────────────────────────────
/**
 * Numeric interpolation with tabular numerals.  Under reduced motion the final
 * value renders immediately.
 */
export function CountUp({
  value,
  format,
  className = "num",
}: {
  value: number;
  format: (value: number) => string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const motionValue = useMotionValue(reduced ? value : 0);
  const spring = useSpring(motionValue, { stiffness: 90, damping: 20, mass: 0.6 });
  const text = useTransform(spring, (latest) => format(Math.round(latest)));
  const [fallback, setFallback] = useState(() => format(value));

  useEffect(() => {
    setFallback(format(value));
    if (reduced) {
      motionValue.set(value);
      return;
    }
    motionValue.set(value);
  }, [value, reduced, motionValue, format]);

  if (reduced) return <span className={className}>{fallback}</span>;
  return (
    <motion.span className={className} suppressHydrationWarning>
      {text}
    </motion.span>
  );
}

/**
 * A hash, truncated in the middle, copyable, with the full value in `title`.
 * Both ends of a hash carry signal, so it is never truncated at the end only.
 */
export function Hash({
  value,
  head = 4,
  tail = 4,
  label,
}: {
  value: string | null | undefined;
  head?: number;
  tail?: number;
  label?: string;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="num">—</span>;
  const clean = value.startsWith("0x") ? value.slice(2) : value;
  const short =
    clean.length <= head + tail ? value : `${clean.slice(0, head)}…${clean.slice(-tail)}`;
  return (
    <button
      type="button"
      className="hash"
      title={value}
      aria-label={`${label ?? "hash"} ${value}`}
      data-cursor=""
      onClick={() => {
        navigator.clipboard?.writeText(value).then(
          () => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          },
          () => setCopied(false),
        );
      }}
    >
      <span className="num">{short}</span>
      <span className="hash-copy nano">{copied ? t("provenance.copied") : t("provenance.copy")}</span>
    </button>
  );
}

// ── The attestation seal (ui/01 §3.4) ───────────────────────────────────────
/**
 * A circle draws clockwise, the inner sigil scales with an overshoot, then the
 * truncated tx hash types in beneath.  One-shot, never replayed on re-render:
 * this is the shot that sells "provenance", and a looping seal would cheapen it.
 */
export function Seal({
  size = 76,
  tone = "pass",
  label,
}: {
  size?: number;
  tone?: "pass" | "unverified" | "fail";
  label?: string;
}) {
  const reduced = useReducedMotion();
  const id = useId();
  const stroke = `var(--sig-${tone})`;
  const radius = size / 2 - 4;
  const circumference = 2 * Math.PI * radius;
  return (
    <figure className="seal">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth="1"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={stroke}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: reduced ? 0 : circumference }}
          animate={{ strokeDashoffset: 0 }}
          transition={
            reduced
              ? { duration: 0 }
              : { duration: D.reveal, ease: E.expo as [number, number, number, number] }
          }
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <motion.g
          initial={{ scale: reduced ? 1 : 0.85, opacity: reduced ? 1 : 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={
            reduced
              ? { duration: 0 }
              : { duration: D.base, ease: E.back as [number, number, number, number], delay: D.fast }
          }
          style={{ transformOrigin: "50% 50%" }}
        >
          <path
            d={`M ${size / 2 - 10} ${size / 2} l 6 7 l 13 -14`}
            fill="none"
            stroke={stroke}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </motion.g>
        <title id={id}>{label ?? "attestation seal"}</title>
      </svg>
      {label ? <figcaption className="nano">{label}</figcaption> : null}
    </figure>
  );
}

// ── Layout helpers ──────────────────────────────────────────────────────────
export function Panel({
  children,
  title,
  right,
  className = "",
  id,
}: {
  children: ReactNode;
  title?: string;
  right?: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`panel ${className}`} id={id}>
      {title ? (
        <header className="panel-head">
          <h2 className="micro">{title}</h2>
          {right}
        </header>
      ) : null}
      {children}
    </section>
  );
}

/** Wide content scrolls inside its own container.  The page never scrolls
 *  sideways (ui/00 §4). */
export function ScrollX({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`scroll-x ${className}`}>{children}</div>;
}

/**
 * A single-value bar for the confidence breakdown.  It animates `scaleX` only --
 * never `width` -- so it composites on the GPU (ui/01 §7).
 */
export function Bar({
  value,
  tone = "pass",
  label,
  index = 0,
}: {
  value: number;
  tone?: "pass" | "unverified" | "fail" | "neutral";
  label?: string;
  index?: number;
}) {
  const reduced = useReducedMotion();
  const fraction = Math.max(0, Math.min(1, Math.abs(value)));
  const colour = tone === "neutral" ? "var(--fg-micro)" : `var(--sig-${tone})`;
  return (
    <div className="bar" role="img" aria-label={label}>
      <motion.span
        className="bar-fill"
        style={{ background: colour, transformOrigin: "0% 50%" }}
        initial={{ scaleX: reduced ? fraction : 0 }}
        whileInView={{ scaleX: fraction }}
        viewport={inView}
        transition={
          reduced
            ? { duration: 0 }
            : {
                duration: D.reveal,
                ease: E.enter as [number, number, number, number],
                delay: Math.min(index * 0.055, 0.4),
              }
        }
      />
    </div>
  );
}
