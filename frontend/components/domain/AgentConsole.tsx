"use client";

/**
 * The agent console (ui/06 §1).
 *
 * A monospace log of what actually happened, newest last, fed by two sources:
 * the deal's hash-chained ledger (the durable record) and the verification SSE
 * stream (the live one).  Lines are never invented client-side -- every row here
 * corresponds to a row in `ledger_events` or an event the backend published.
 *
 * The console is the honest counterpart to the seal: the seal says "this was
 * decided", the console says "here is the sequence that decided it".
 */

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Empty, Loading, ErrorBlock, Panel } from "@/components/ui/primitives";
import { D, E } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useAsync } from "@/hooks/useAsync";
import { useSse } from "@/hooks/useSse";
import { api, sseUrl, type LedgerEntry } from "@/lib/api";
import { timeOnly } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

type Line = { id: string; time: string; actor: string; event: string; live?: boolean };

const toLine = (entry: LedgerEntry): Line => ({
  id: `seq-${entry.seq}`,
  time: timeOnly(entry.created_at),
  actor: entry.actor,
  event: entry.reason ? `${entry.event_type} — ${entry.reason}` : entry.event_type,
});

export function AgentConsole({
  dealId,
  milestoneId,
  onCompleted,
}: {
  dealId: string;
  milestoneId?: string | null;
  onCompleted?: () => void;
}) {
  const { t } = useI18n();
  const reduced = useReducedMotion();
  const state = useAsync(() => api.timeline(dealId), [dealId]);
  const [live, setLive] = useState<Line[]>([]);
  const scroller = useRef<HTMLDivElement | null>(null);

  const onEvent = useCallback(
    (event: string, data: unknown) => {
      const payload = (data ?? {}) as Record<string, unknown>;
      if (event === "ready" || event === "message") return;
      const detail =
        typeof payload.stage === "string"
          ? String(payload.stage)
          : typeof payload.decision === "string"
            ? `${payload.decision} @ ${payload.confidence}`
            : "";
      setLive((lines) => [
        ...lines,
        {
          id: `${event}-${lines.length}`,
          time: timeOnly(new Date()),
          actor: "VERIFIER",
          event: detail ? `${event} — ${detail}` : event,
          live: true,
        },
      ]);
      if (event === "verification.completed") {
        state.reload();
        setLive([]);
        onCompleted?.();
      }
    },
    [state, onCompleted],
  );

  useSse(milestoneId ? sseUrl(`/verification/${milestoneId}`) : null, onEvent, {
    enabled: Boolean(milestoneId),
  });

  const lines: Line[] = [
    ...(state.status === "ready" ? state.data.map(toLine) : []),
    ...live,
  ];

  useEffect(() => {
    // Newest last, so the console must follow.  `scrollTop` rather than
    // scrollIntoView: the latter scrolls the whole page on some browsers.
    const node = scroller.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [lines.length]);

  return (
    <Panel title={t("deal.agentConsole")}>
      {state.status === "loading" ? <Loading /> : null}
      {state.status === "error" ? (
        <ErrorBlock code={state.error.code} message={state.error.message} onRetry={state.reload} />
      ) : null}
      {state.status === "ready" && lines.length === 0 ? (
        <Empty label={t("deal.agentConsole")} body={t("console.empty")} />
      ) : null}

      {lines.length > 0 ? (
        <div className="console" ref={scroller} role="log" aria-live="polite" aria-relevant="additions">
          <AnimatePresence initial={false}>
            {lines.map((line) => (
              <motion.div
                key={line.id}
                className="console-line"
                initial={reduced ? { opacity: 0 } : { opacity: 0, x: -4 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{
                  duration: reduced ? D.instant : D.fast,
                  ease: E.enter as [number, number, number, number],
                }}
              >
                <span className="console-time">{line.time}</span>
                <span className="console-actor">{line.actor}</span>
                <span className="console-event">{line.event}</span>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      ) : null}
    </Panel>
  );
}
