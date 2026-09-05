"use client";

/**
 * Email verification.
 *
 * Two jobs on one screen: consume a `?token=` if the user arrived from the link,
 * and offer a resend with a cooldown if they did not.  The copy states exactly
 * what an unverified account can and cannot do, because "please verify your
 * email" without consequences is a message people ignore.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useSession } from "@/components/domain/AppProviders";
import { ScrambleText, SonarArcs } from "@/components/ui/ScrambleText";
import { Button, Field, Input, Loading } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// 60s, per ui/06 §7. Long enough that the button is not a retry loop, short
// enough that a judge whose mail is slow is not stuck on this screen.
const COOLDOWN_S = 60;

function VerifyEmailInner() {
  const { t, list } = useI18n();
  const router = useRouter();
  const parameters = useSearchParams();
  const { me, refresh } = useSession();
  const token = parameters.get("token");

  const [email, setEmail] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const [status, setStatus] = useState<"idle" | "verifying" | "verified" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEmail(me?.email ?? "");
  }, [me?.email]);

  useEffect(() => {
    if (!token) return;
    setStatus("verifying");
    api.verifyEmail(token).then(
      async () => {
        setStatus("verified");
        await refresh();
        window.setTimeout(() => router.push("/deals"), 1200);
      },
      (caught: unknown) => {
        setStatus("error");
        setError(caught instanceof ApiError ? `${caught.code}: ${caught.message}` : String(caught));
      },
    );
  }, [token, refresh, router]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const id = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(id);
  }, [cooldown]);

  return (
    <div className="auth-card">
      <Link href="/" className="nav-brand" data-cursor="">
        {t("brand")}
      </Link>
      {/* The gate is a waiting state, so it wears the sonar and the scramble:
          the same two motifs as every other place in the product where
          something has not resolved yet (ui/06 §7). The heading keeps the
          translated sentence for screen readers via `aria-label` inside
          ScrambleText; the glyphs themselves are `aria-hidden`. */}
      <h1 className="display-3 verify-head">
        <span className="sonar-flank">
          <SonarArcs side="left" tone="unverified" inline />
          <ScrambleText phrases={list("auth.verifyPhrases")} />
          <SonarArcs side="right" tone="unverified" inline />
        </span>
      </h1>

      {status === "verifying" ? <Loading /> : null}
      {status === "verified" ? (
        <span className="micro" role="status" style={{ color: "var(--sig-pass)" }}>
          {t("auth.verified")}
        </span>
      ) : null}
      {error ? (
        <span className="field-error" role="alert">
          {error}
        </span>
      ) : null}

      {status !== "verified" ? (
        <>
          <p className="state-body">
            {t("auth.verifyBody", { email: me?.email ?? t("auth.email").toLowerCase() })}
          </p>

          <Field label={t("auth.email")}>
            <Input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>

          <Button
            disabled={cooldown > 0 || !email}
            onClick={() => {
              setError(null);
              void api.resendVerification(email).then(
                () => setCooldown(COOLDOWN_S),
                (caught: unknown) =>
                  setError(
                    caught instanceof ApiError
                      ? `${caught.code}: ${caught.message}`
                      : String(caught),
                  ),
              );
            }}
          >
            {cooldown > 0 ? t("auth.resendIn", { seconds: cooldown }) : t("auth.resend")}
          </Button>
        </>
      ) : null}

      <Link href="/deals" className="link" data-cursor="">
        {t("nav.deals")}
      </Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<Loading />}>
      <VerifyEmailInner />
    </Suspense>
  );
}
