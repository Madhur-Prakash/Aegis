"use client";

/** Right-docked panel.  Unread rows carry a 4px amber left border, grouped by day. */

import { motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";

import { Button, ErrorBlock, Loading } from "@/components/ui/primitives";
import { D, E } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { dateOnly, relative } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function NotificationPanel({ onClose }: { onClose: () => void }) {
  const { t, locale } = useI18n();
  const reduced = useReducedMotion();
  const state = useAsync(() => api.notifications(), []);
  const [marking, setMarking] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const markAll = useCallback(async () => {
    setMarking(true);
    try {
      await api.markRead();
      state.reload();
    } finally {
      setMarking(false);
    }
  }, [state]);

  // Grouped by day, in arrival order: a notification list without day breaks
  // reads as one undifferentiated stream.
  const items = state.status === "ready" ? state.data.items : [];
  const byDay = new Map<string, typeof items>();
  for (const item of items) {
    const day = dateOnly(item.created_at, locale);
    byDay.set(day, [...(byDay.get(day) ?? []), item]);
  }

  return (
    <motion.aside
      className="notif-panel"
      role="dialog"
      aria-label={t("notifications.title")}
      initial={reduced ? { opacity: 0 } : { x: "100%" }}
      animate={reduced ? { opacity: 1 } : { x: 0 }}
      transition={
        reduced
          ? { duration: D.fast }
          : { duration: D.base, ease: E.enter as [number, number, number, number] }
      }
    >
      <header className="row-between">
        <h2 className="micro">{t("notifications.title")}</h2>
        <div className="row">
          <Button variant="ghost" onClick={() => void markAll()} disabled={marking}>
            {t("notifications.markRead")}
          </Button>
          <button className="icon-btn" onClick={onClose} aria-label={t("common.close")}>
            <span aria-hidden>✕</span>
          </button>
        </div>
      </header>

      {state.status === "loading" ? <Loading /> : null}
      {state.status === "error" ? (
        <ErrorBlock code={state.error.code} message={state.error.message} onRetry={state.reload} />
      ) : null}

      {state.status === "ready" && items.length === 0 ? (
        <p className="state-body">{t("notifications.empty")}</p>
      ) : null}

      {[...byDay.entries()].map(([day, group]) => (
        <section key={day} className="stack">
          <span className="nano">{day}</span>
          {group.map((item) => (
            <article key={item.id} className={`notif ${item.read_at ? "" : "is-unread"}`}>
              <span className="micro">{item.kind.replaceAll("_", " ")}</span>
              <strong style={{ fontSize: "var(--fs-sm)" }}>{item.title}</strong>
              <p className="state-body">{item.body}</p>
              <span className="nano">{relative(item.created_at)}</span>
            </article>
          ))}
        </section>
      ))}
    </motion.aside>
  );
}
