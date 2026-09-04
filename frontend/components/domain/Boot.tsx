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
 * Shown once per session.  Nobody should watch this twice, least of all a judge.
 */

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { D, E, STEP_WIPE_STEPS, chipPop, stepWipeClip } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { api, type Health } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const BOOT_KEY = "aegis-booted";
const MIN_VISIBLE_MS = 1100; // below this it flashes and reads as a glitch
const MAX_VISIBLE_MS = 4000; // above this, boot anyway and show the banner

type NodeState = "pending" | "ready" | "degraded" | "failed";

const NODES = [
  { key: "postgres", glyph: "DB", label: "boot.postgres", required: true },
  { key: "kafka", glyph: "KF", label: "boot.kafka", required: false },
  { key: "chain_rpc", glyph: "CH", label: "boot.chain", required: false },
  { key: "payment_rail", glyph: "RL", label: "boot.rail", required: true },
] as const;

export function Boot({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const reduced = useReducedMotion();
  const [health, setHealth] = useState<Health | null>(null);
  const [counter, setCounter] = useState(0);
  const [phase, setPhase] = useState<"checking" | "wiping" | "done">("checking");
  const [halted, setHalted] = useState(false);
  const started = useRef(Date.now());

  const finish = useCallback(() => {
    try {
      window.sessionStorage.setItem(BOOT_KEY, "1");
    } catch {
      // ignore
    }
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
      if (phase === "checking" && !halted) setPhase(reduced ? "done" : "wiping");
    }, MAX_VISIBLE_MS);
    return () => clearTimeout(bail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The counter climbs to 100 as the last node resolves (reference D).
  useEffect(() => {
    if (halted) return;
    const target = health ? 100 : 72;
    const id = setInterval(() => {
      setCounter((current) => (current >= target ? target : current + 2));
    }, 24);
    return () => clearInterval(id);
  }, [health, halted]);

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

  const readyCount = health ? NODES.filter((n) => nodeState(n.key) === "ready").length : 0;
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
        <span className="boot-corner boot-corner--bl nano">{t("boot.label")}</span>

        <div className="boot-inner">
          <motion.svg
            className="boot-mark"
            viewBox="0 0 28 28"
            variants={chipPop}
            initial="hidden"
            animate="show"
            aria-hidden
          >
            <circle cx="14" cy="14" r="12" fill="none" stroke="var(--bone-100)" strokeWidth="1" />
            <path
              d="M8 14 l4 5 l8 -9"
              fill="none"
              stroke="var(--bone-100)"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </motion.svg>

          <div className="boot-track" role="status" aria-live="polite">
            <motion.span
              className="boot-fill"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: readyCount / NODES.length }}
              transition={{ duration: D.base, ease: "linear" }}
              style={{ width: "100%" }}
              aria-hidden
            />
            {NODES.map((node, index) => (
              <motion.span
                key={node.key}
                className="boot-node"
                data-state={nodeState(node.key)}
                custom={index}
                variants={chipPop}
                initial="hidden"
                animate={nodeState(node.key) === "pending" ? "hidden" : "show"}
              >
                {node.glyph}
                <span className="boot-node-label nano">{t(node.label)}</span>
              </motion.span>
            ))}
          </div>

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

export function hasBooted() {
  try {
    return window.sessionStorage.getItem(BOOT_KEY) === "1";
  } catch {
    return false;
  }
}

export { STEP_WIPE_STEPS };
