"use client";

/**
 * Accept an organization invitation.
 *
 * The token is consumed against the signed-in session, so the screen asks the
 * user to sign in first rather than silently creating an account for the invited
 * address -- an invitation is a permission grant, and it should land on a person
 * who has proven they hold the mailbox.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { useSession } from "@/components/domain/AppProviders";
import { Button, Loading } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function AcceptInner() {
  const { t } = useI18n();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const { status, refresh } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="auth-card">
      <Link href="/" className="nav-brand" data-cursor="">
        {t("brand")}
      </Link>
      <h1 className="display-3">{t("invitation.title")}</h1>

      {!token ? (
        <span className="field-error" role="alert">
          {t("auth.missingToken")}
        </span>
      ) : null}

      {status === "signed-out" ? (
        <>
          <p className="state-body">{t("invitation.signInFirst")}</p>
          <Link href="/login" data-cursor="">
            <Button>{t("auth.signIn")}</Button>
          </Link>
        </>
      ) : (
        <>
          <p className="state-body">{t("invitation.body")}</p>
          {error ? (
            <span className="field-error" role="alert">
              {error}
            </span>
          ) : null}
          <Button
            disabled={busy || !token}
            onClick={() => {
              setBusy(true);
              setError(null);
              void api
                .acceptInvitation(token)
                .then(
                  async () => {
                    await refresh();
                    router.push("/deals");
                  },
                  (caught: unknown) =>
                    setError(
                      caught instanceof ApiError
                        ? `${caught.code}: ${caught.message}`
                        : String(caught),
                    ),
                )
                .finally(() => setBusy(false));
            }}
          >
            {t("invitation.accept")}
          </Button>
        </>
      )}
    </div>
  );
}

export default function AcceptInvitationPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AcceptInner />
    </Suspense>
  );
}
