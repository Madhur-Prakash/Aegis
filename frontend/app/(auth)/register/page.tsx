"use client";

/**
 * Create an account.
 *
 * Registration creates the user *and* their first organization, which is why the
 * organization name is on this form: a session with no organization can read
 * nothing, and asking for it on a second screen would leave a user staring at an
 * empty app wondering what they did wrong.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/domain/AppProviders";
import { Button, Field, Input } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function RegisterPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { refresh } = useSession();
  const [name, setName] = useState("");
  const [organization, setOrganization] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
          .register({
            email,
            password,
            name,
            organization_name: organization || undefined,
          })
          .then(
            async () => {
              await refresh();
              router.push("/verify-email");
            },
            (caught: unknown) => {
              setError(
                caught instanceof ApiError
                  ? `${caught.code}: ${caught.message}`
                  : String(caught),
              );
            },
          )
          .finally(() => setBusy(false));
      }}
    >
      <Link href="/" className="nav-brand" data-cursor="">
        {t("brand")}
      </Link>
      <h1 className="display-3">{t("auth.signUp")}</h1>

      <Field label={t("auth.name")}>
        <Input
          autoComplete="name"
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </Field>
      <Field label={t("auth.organization")} hint={t("auth.organizationHint")}>
        <Input
          autoComplete="organization"
          value={organization}
          onChange={(event) => setOrganization(event.target.value)}
        />
      </Field>
      <Field label={t("auth.email")}>
        <Input
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </Field>
      <Field label={t("auth.password")} hint={t("auth.passwordHint")}>
        <Input
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </Field>

      {error ? (
        <span className="field-error" role="alert">
          {error}
        </span>
      ) : null}

      <Button type="submit" disabled={busy} cursorLabel={t("auth.signUp")}>
        {t("auth.signUp")}
      </Button>

      <Link href="/login" className="link" data-cursor="">
        {t("auth.haveAccount")}
      </Link>
    </form>
  );
}
