"use client";

/**
 * The boot sequence (ui/02 §2).
 *
 * A loading screen is usually a vanity tax.  Here it is not, because the app
 * genuinely has four dependencies that must be ready before money can move, and
 * `/health/ready` already reports each one.  Every node is a real subsystem: it
 * fills when the health check says ready, turns amber when a dependency is
 * degraded, and turns red and halts on Postgres -- rather than booting into a
 * broken app and lying about it.
 *
 * Shown on every load. The line reaches the four stations one at a time, and
 * it is presentation of results, not the results: a station the line reaches
 * before health has answered shows as pending and takes its true state the
 * instant health lands, and a halt freezes the line where it is.
 */

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { D, E, STEP_WIPE_STEPS, chipPop, stepWipeClip } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { api, type Health } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const BOOT_KEY = "aegis-booted";
// Long enough to be read as a sequence rather than a flash: the four nodes
// resolve, the counter climbs, the wipe follows. Below about a second it read
// as a glitch. The screen is visible for MIN plus the wipe (`D.wipe`, 0.76s),
// so 2200 lands at just under three seconds; any key, click or scroll still
// skips it. MAX is the ceiling when health is slow but answering -- it never
// overrides a halt.
const MIN_VISIBLE_MS = 2200;
const MAX_VISIBLE_MS = 3000;
// One station per STEP_MS, the first after one interval: four steps land at
// ~1.7s, which leaves the last station lit for half a second before the wipe.
const STEP_MS = 420;

type NodeState = "pending" | "ready" | "degraded" | "failed";

const NODES = [
  { key: "postgres", required: true },
  { key: "kafka", required: false },
  { key: "chain_rpc", required: false },
  { key: "payment_rail", required: true },
] as const;

// The mark, assembling. Four quadrant arcs of the ring, clockwise from the
// top, one per check, and the joint each arc sets out from.
const ARCS = [
  "M 50 10 A 40 40 0 0 1 90 50",
  "M 90 50 A 40 40 0 0 1 50 90",
  "M 50 90 A 40 40 0 0 1 10 50",
  "M 10 50 A 40 40 0 0 1 50 10",
] as const;
const JOINTS: readonly (readonly [number, number])[] = [
  [50, 10],
  [90, 50],
  [50, 90],
  [10, 50],
];
const TICK = "M 33 52 L 45 64 L 68 40";

export function Boot({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const reduced = useReducedMotion();
  const [health, setHealth] = useState<Health | null>(null);
  const [counter, setCounter] = useState(0);
  const [phase, setPhase] = useState<"checking" | "wiping" | "done">("checking");
  const [halted, setHalted] = useState(false);
  // How many stations the line has reached, 0..NODES.length.
  const [reached, setReached] = useState(0);
  const started = useRef(Date.now());

  // The bail timer below is armed once, on mount. A closure over mount-time
  // state would see `checking` and `!halted` forever -- and it did: measured,
  // the screen showed the red Postgres halt, then wiped at 4.0s and booted
  // into the app anyway, setting `aegis-booted`. The one promise this screen
  // makes is that it will not do that. It reads live state through refs.
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const haltedRef = useRef(halted);
  haltedRef.current = halted;

  // Nothing is written to sessionStorage here any more: the sequence runs on
  // every load. `BOOT_KEY` is still honoured by `bootSuppressed` for anyone who
  // sets it deliberately -- an operator who wants to bypass it, or a test.
  const finish = useCallback(() => {
    setPhase("done");
    onDone();
  }, [onDone]);

  const check = useCallback(async () => {
    try {
      const result = await api.health();
      setHealth(result);
      if (!result.checks.postgres?.ready) {
        setHalted(true);
        return;
      }
    } catch {
      setHalted(true);
      return;
    }
    const elapsed = Date.now() - started.current;
    const wait = Math.max(0, MIN_VISIBLE_MS - elapsed);
    setTimeout(() => setPhase(reduced ? "done" : "wiping"), wait);
    if (reduced) setTimeout(finish, wait);
  }, [reduced, finish]);

  useEffect(() => {
    void check();
    const bail = setTimeout(() => {
      if (phaseRef.current === "checking" && !haltedRef.current) {
        setPhase(reduced ? "done" : "wiping");
      }
    }, MAX_VISIBLE_MS);
    return () => clearTimeout(bail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The line advances one station per STEP_MS. A halt freezes it; reduced
  // motion shows every station at once and lets the existing fades carry it.
  useEffect(() => {
    if (halted) return;
    if (reduced) {
      setReached(NODES.length);
      return;
    }
    const id = setInterval(() => {
      setReached((current) => {
        if (current >= NODES.length) {
          clearInterval(id);
          return current;
        }
        return current + 1;
      });
    }, STEP_MS);
    return () => clearInterval(id);
  }, [halted, reduced]);

  // The counter tracks the stations -- 25 each -- rather than the old 72 that
  // parked until health answered and then leapt to 100 (reference D).
  useEffect(() => {
    if (halted) return;
    const target = Math.round((reached / NODES.length) * 100);
    const id = setInterval(() => {
      setCounter((current) => (current >= target ? target : current + 2));
    }, 24);
    return () => clearInterval(id);
  }, [reached, halted]);

  // Any key, click or scroll during boot jumps straight to the wipe.
  useEffect(() => {
    if (phase !== "checking" || halted) return;
    const skip = () => setPhase(reduced ? "done" : "wiping");
    window.addEventListener("keydown", skip);
    window.addEventListener("pointerdown", skip);
    window.addEventListener("wheel", skip, { passive: true });
    return () => {
      window.removeEventListener("keydown", skip);
      window.removeEventListener("pointerdown", skip);
      window.removeEventListener("wheel", skip);
    };
  }, [phase, halted, reduced]);

  useEffect(() => {
    if (phase === "done") finish();
  }, [phase, finish]);

  const nodeState = (key: string): NodeState => {
    if (!health) return "pending";
    const check = health.checks[key];
    if (!check) return "pending";
    if (check.ready) return "ready";
    return check.required ? "failed" : "degraded";
  };

  const degraded = health
    ? NODES.filter((n) => nodeState(n.key) === "degraded").map((n) => n.key)
    : [];

  const note = halted
    ? t("boot.halted")
    : degraded.includes("chain_rpc")
      ? t("boot.degradedChain")
      : degraded.includes("kafka")
        ? t("boot.degradedKafka")
        : "";

  const segment = reduced
    ? { duration: D.fast }
    : { duration: D.slow, ease: E.expo as [number, number, number, number] };

  if (phase === "done") return null;

  return (
    <AnimatePresence>
      <motion.div
        className="boot"
        initial={reduced ? { opacity: 1 } : { clipPath: stepWipeClip(0) }}
        animate={
          phase === "wiping"
            ? reduced
              ? { opacity: 0 }
              : { clipPath: stepWipeClip(1) }
            : reduced
              ? { opacity: 1 }
              : { clipPath: stepWipeClip(0) }
        }
        transition={
          reduced
            ? { duration: D.fast }
            : { duration: D.wipe, ease: E.expo as [number, number, number, number] }
        }
        onAnimationComplete={() => {
          if (phase === "wiping") setPhase("done");
        }}
      >
        <span className="boot-corner boot-corner--tl nano">
          {t("brand")} - {t("tagline")}
        </span>
        <span className="boot-corner boot-corner--tr nano num">
          {String(Math.min(100, counter)).padStart(3, "0")}
        </span>
        <span className="boot-corner boot-corner--bl nano num" role="status" aria-live="polite">
          {t("boot.label")} · {String(reached).padStart(2, "0")} /{" "}
          {String(NODES.length).padStart(2, "0")}
        </span>

        <div className="boot-inner">
          {/* The mark assembles itself. Four arcs, one per check, each drawn in
              the colour the check actually reported -- green, amber or red --
              and the tick once the fourth has landed. It is the same four steps
              as before with the system names taken off the screen: a loading
              screen should be beautiful first and a diagnostics panel never,
              and the note below still says exactly what is degraded. */}
          <motion.svg
            className="boot-glyph"
            viewBox="0 0 100 100"
            variants={chipPop}
            initial="hidden"
            animate="show"
            aria-hidden
          >
            <circle className="boot-halo" cx="50" cy="50" r="46" />
            <circle className="boot-ring-base" cx="50" cy="50" r="40" />
            {NODES.map((node, index) => {
              const lit = reached > index;
              const state = lit ? nodeState(node.key) : "pending";
              const [jx, jy] = JOINTS[index] ?? [50, 10];
              return (
                <g key={node.key}>
                  <motion.path
                    className="boot-arc"
                    d={ARCS[index] ?? ""}
                    data-state={state}
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: lit ? 1 : 0 }}
                    transition={segment}
                  />
                  <motion.circle
                    className="boot-joint"
                    cx={jx}
                    cy={jy}
                    data-state={state}
                    initial={{ r: 0.01, opacity: 0 }}
                    animate={lit ? { r: 2.6, opacity: 1 } : { r: 0.01, opacity: 0 }}
                    transition={segment}
                  />
                </g>
              );
            })}
            <motion.path
              className="boot-tick"
              d={TICK}
              initial={{ pathLength: 0, opacity: 0 }}
              animate={
                reached >= NODES.length ? { pathLength: 1, opacity: 1 } : { pathLength: 0, opacity: 0 }
              }
              transition={segment}
            />
          </motion.svg>

          <p className="boot-note micro" style={{ color: halted ? "var(--sig-fail)" : undefined }}>
            {note}
          </p>

          {halted ? (
            <button className="btn btn--ghost" onClick={() => window.location.reload()}>
              {t("boot.retry")}
            </button>
          ) : (
            <button
              className="btn btn--ghost"
              onClick={() => setPhase(reduced ? "done" : "wiping")}
            >
              {t("boot.skip")}
            </button>
          )}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

/**
 * True when this tab has asked to bypass the boot. The app never sets the key
 * itself -- the sequence runs on every load -- so this is only ever an explicit
 * choice: a demo operator in devtools, or a test harness.
 */
export function bootSuppressed() {
  try {
    return window.sessionStorage.getItem(BOOT_KEY) === "1";
  } catch {
    return false;
  }
}

export { STEP_WIPE_STEPS };
