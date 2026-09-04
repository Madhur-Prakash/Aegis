"use client";

/**
 * Deal-scoped chat (ui/06 §1).
 *
 * The footnote is not decoration: messages are deliberately *not* evidence.
 * Anything that decides money has to go through the evidence bundle, be hashed
 * into the Merkle tree and be signed.  A chat message is neither, so the panel
 * says so where a user can see it.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Button, ErrorBlock, Input, Loading, Panel } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { useSse } from "@/hooks/useSse";
import { api, sseUrl } from "@/lib/api";
import { relative } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function DealChat({ dealId }: { dealId: string }) {
  const { t } = useI18n();
  const state = useAsync(() => api.messages(dealId), [dealId]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const log = useRef<HTMLDivElement | null>(null);

  const reload = state.reload;
  useSse(sseUrl(`/chat/${dealId}`), (event) => {
    if (event === "chat.message") reload();
  });

  const messages = state.status === "ready" ? state.data : [];

  useEffect(() => {
    const node = log.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length]);

  const send = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      const body = draft.trim();
      if (!body) return;
      setSending(true);
      try {
        await api.sendMessage(dealId, body);
        setDraft("");
        reload();
      } finally {
        setSending(false);
      }
    },
    [draft, dealId, reload],
  );

  return (
    <Panel title={t("deal.messages")}>
      {state.status === "loading" ? <Loading /> : null}
      {state.status === "error" ? (
        <ErrorBlock code={state.error.code} message={state.error.message} onRetry={reload} />
      ) : null}

      <div className="chat">
        <div className="chat-log" ref={log}>
          {messages.length === 0 && state.status === "ready" ? (
            <p className="state-body">{t("deal.noMessages")}</p>
          ) : null}
          {messages.map((message) => (
            <article key={message.id} className={`chat-msg ${message.mine ? "is-mine" : ""}`}>
              <span className="nano">
                {message.sender_name} · {relative(message.created_at)}
              </span>
              <span style={{ fontSize: "var(--fs-sm)" }}>{message.body}</span>
            </article>
          ))}
        </div>

        <form className="chat-form" onSubmit={(event) => void send(event)}>
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={t("deal.messagePlaceholder")}
            aria-label={t("deal.messagePlaceholder")}
            maxLength={4000}
          />
          <Button type="submit" disabled={sending || !draft.trim()}>
            {t("deal.sendMessage")}
          </Button>
        </form>

        <span className="nano">{t("deal.chatNote")}</span>
      </div>
    </Panel>
  );
}
