"use client";

/**
 * Reset password.
 *
 * A successful reset revokes every other session on the server side, so the copy
 * says so: someone resetting a password because they think it was stolen needs
 * to know the other sessions are gone, not guess.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button, Field, Input, Loading } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function ResetPasswordInner() {
  const { t } = useI18n();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      className="auth-card"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        setError(null);
        void api
          .resetPassword(token, password)
          .then(
            () => {
              setDone(true);
              window.setTimeout(() => router.push("/login"), 1400);
            },
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

      {!token ? (
        <span className="field-error" role="alert">
          {t("auth.missingToken")}
        </span>
      ) : null}

      {done ? (
        <span className="micro" role="status" style={{ color: "var(--sig-pass)" }}>
          {t("auth.resetDone")}
        </span>
      ) : (
        <>
          <Field label={t("auth.newPassword")} hint={t("auth.passwordHint")}>
            <Input
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          {error ? (
            <span className="field-error" role="alert">
              {error}
            </span>
          ) : null}
          <Button type="submit" disabled={busy || !token}>
            {t("auth.reset")}
          </Button>
          <span className="nano">{t("auth.resetRevokes")}</span>
        </>
      )}

      <Link href="/login" className="link" data-cursor="">
        {t("auth.signIn")}
      </Link>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ResetPasswordInner />
    </Suspense>
  );
}
