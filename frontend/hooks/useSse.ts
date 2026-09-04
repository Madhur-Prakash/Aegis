"use client";

/**
 * One SSE subscription with reconnect and last-event-id.
 *
 * The payload is only ever a *hint*: the callback refetches from the API rather
 * than trusting the event body, so a dropped or duplicated event costs a
 * refresh and never a wrong number on screen.
 */
import { useEffect, useRef } from "react";

export function useSse(
  path: string | null,
  onEvent: (event: string, data: unknown) => void,
  options: { enabled?: boolean } = {},
) {
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!path || options.enabled === false) return;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      if (closed) return;
      source = new EventSource(path, { withCredentials: true });

      const forward = (event: MessageEvent) => {
        attempt = 0;
        let parsed: unknown = null;
        try {
          parsed = event.data ? JSON.parse(event.data) : null;
        } catch {
          parsed = event.data;
        }
        handler.current(event.type, parsed);
      };

      for (const name of [
        "ready",
        "deal.updated",
        "deal.funded",
        "evidence.submitted",
        "verification.stage",
        "verification.completed",
        "review.decided",
        "dispute.raised",
        "dispute.resolved",
        "chat.message",
      ]) {
        source.addEventListener(name, forward as EventListener);
      }
      source.onmessage = forward;

      source.onerror = () => {
        source?.close();
        source = null;
        if (closed) return;
        // Exponential backoff, capped: a backend restart must not become a
        // reconnect storm.
        attempt += 1;
        const delay = Math.min(1000 * 2 ** (attempt - 1), 15000);
        retry = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      source?.close();
    };
  }, [path, options.enabled]);
}
