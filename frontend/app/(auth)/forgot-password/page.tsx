"use client";

/**
 * Forgot password.
 *
 * The confirmation is deliberately the same whether or not the address has an
 * account.  A form that says "no such user" is an account-enumeration oracle,
 * and this one is not going to be.
 */

import Link from "next/link";
import { useState } from "react";

import { Button, Field, Input } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function ForgotPasswordPage() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      className="auth-card"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        setError(null);
        void api
          .forgotPassword(email)
          .then(
            () => setSent(true),
            (caught: unknown) =>
              setError(
                caught instanceof ApiError ? `${caught.code}: ${caught.message}` : String(caught),
              ),
          )
          .finally(() => setBusy(false));
      }}
    >
      <Link href="/" className="nav-brand" data-cursor="">
        {t("brand")}
      </Link>
      <h1 className="display-3">{t("auth.reset")}</h1>

      {sent ? (
        <span className="micro" role="status" style={{ color: "var(--sig-pass)" }}>
          {t("auth.resetSent")}
        </span>
      ) : (
        <>
          <Field label={t("auth.email")}>
            <Input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          {error ? (
            <span className="field-error" role="alert">
              {error}
            </span>
          ) : null}
          <Button type="submit" disabled={busy}>
            {t("auth.sendReset")}
          </Button>
        </>
      )}

      <Link href="/login" className="link" data-cursor="">
        {t("auth.signIn")}
      </Link>
    </form>
  );
}
