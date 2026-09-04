"use client";

/**
 * Settings: appearance, language, motion, notification preferences, and the
 * organization the session is acting for.
 *
 * The motion switch is not a gimmick.  The interface has a lot of motion, and a
 * user who finds it distracting should be able to turn it off inside the product
 * rather than being told to change an OS setting -- it writes through the same
 * hook the OS preference uses, so nothing diverges.
 */

import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/domain/AppProviders";
import { Reveal } from "@/components/ui/Reveal";
import { CornerMeta, Meta, StateChip } from "@/components/ui/StateChip";
import {
  Button,
  ErrorBlock,
  Field,
  Input,
  Loading,
  Panel,
  SegmentedControl,
  Select,
  Toggle,
} from "@/components/ui/primitives";
import { RailDisclosurePanel } from "@/components/domain/RailDisclosure";
import {
  readMotionPreference,
  setMotionPreference,
  useReducedMotion,
} from "@/hooks/useReducedMotion";
import { useAsync } from "@/hooks/useAsync";
import { ApiError, api } from "@/lib/api";
import { dateOnly } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { Theme } from "@/hooks/useTheme";

type MotionChoice = "system" | "on" | "off";

export default function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const { me, theme, setTheme, rail, refresh } = useSession();
  const reduced = useReducedMotion();

  const [motion, setMotion] = useState<MotionChoice>("system");
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("MEMBER");

  useEffect(() => {
    setMotion(readMotionPreference());
  }, []);

  const preferences = useAsync(() => api.notificationPreferences(), []);
  const members = useAsync(() => api.members(), []);
  const invitations = useAsync(() => api.invitations(), []);

  const flash = useCallback((message: string) => {
    setSaved(message);
    setError(null);
    window.setTimeout(() => setSaved(null), 2400);
  }, []);

  const fail = useCallback((caught: unknown) => {
    setError(caught instanceof ApiError ? `${caught.code}: ${caught.message}` : String(caught));
  }, []);

  const applyTheme = (next: Theme) => {
    setTheme(next);
    void api.savePreferences({ theme: next }).then(
      () => flash(t("settings.saved")),
      () => {
        // The theme already applied locally; a failed persist is a nuisance.
      },
    );
  };

  return (
    <section className="section">
      <CornerMeta left={t("settings.title")} right={me?.email ?? ""} />
      <h1 className="display-3">{t("settings.title")}</h1>

      {saved ? (
        <span className="micro" role="status" style={{ color: "var(--sig-pass)" }}>
          {saved}
        </span>
      ) : null}
      {error ? (
        <span className="field-error" role="alert">
          {error}
        </span>
      ) : null}

      <div className="cockpit" style={{ paddingTop: "var(--sp-5)" }}>
        <Reveal>
          <Panel title={t("settings.appearance")}>
            <div className="stack">
              <Field label={t("settings.theme")}>
                <SegmentedControl<Theme>
                  label={t("settings.theme")}
                  value={theme}
                  onChange={applyTheme}
                  options={[
                    { value: "system", label: t("settings.system") },
                    { value: "light", label: t("settings.light") },
                    { value: "dark", label: t("settings.dark") },
                  ]}
                />
              </Field>

              <Field label={t("settings.language")}>
                <SegmentedControl<"en" | "hi">
                  label={t("settings.language")}
                  value={locale}
                  onChange={(next) => {
                    setLocale(next);
                    flash(t("settings.saved"));
                  }}
                  options={[
                    { value: "en", label: "English" },
                    { value: "hi", label: "हिन्दी" },
                  ]}
                />
              </Field>

              <Field label={t("settings.motion")} hint={t("settings.motionHint")}>
                <SegmentedControl<MotionChoice>
                  label={t("settings.motion")}
                  value={motion}
                  onChange={(next) => {
                    setMotion(next);
                    setMotionPreference(next);
                    flash(t("settings.saved"));
                  }}
                  options={[
                    { value: "system", label: t("settings.system") },
                    { value: "on", label: t("settings.motionOn") },
                    { value: "off", label: t("settings.motionOff") },
                  ]}
                />
              </Field>

              {reduced ? <span className="nano">{t("common.reducedMotion")}</span> : null}
            </div>
          </Panel>
        </Reveal>

        <Reveal index={1}>
          <Panel title={t("settings.notifications")}>
            {preferences.status === "loading" ? <Loading /> : null}
            {preferences.status === "error" ? (
              <ErrorBlock
                code={preferences.error.code}
                message={preferences.error.message}
                onRetry={preferences.reload}
              />
            ) : null}
            {preferences.status === "ready" ? (
              <div className="stack" style={{ gap: "var(--sp-3)" }}>
                <div className="row-between">
                  <span className="nano">{t("settings.kind")}</span>
                  <span className="row">
                    <span className="nano">{t("settings.inApp")}</span>
                    <span className="nano">{t("settings.email")}</span>
                  </span>
                </div>
                {preferences.data.map((preference) => (
                  <div className="row-between" key={preference.kind}>
                    <span style={{ fontSize: "var(--fs-sm)" }}>{preference.title}</span>
                    <span className="row">
                      <Toggle
                        pressed={preference.in_app}
                        label={`${preference.title} - ${t("settings.inApp")}`}
                        onToggle={() => {
                          void api
                            .saveNotificationPreference({
                              kind: preference.kind,
                              in_app: !preference.in_app,
                              email: preference.email,
                            })
                            .then(() => {
                              preferences.reload();
                              flash(t("settings.saved"));
                            }, fail);
                        }}
                      />
                      <Toggle
                        pressed={preference.email}
                        label={`${preference.title} - ${t("settings.email")}`}
                        onToggle={() => {
                          void api
                            .saveNotificationPreference({
                              kind: preference.kind,
                              in_app: preference.in_app,
                              email: !preference.email,
                            })
                            .then(() => {
                              preferences.reload();
                              flash(t("settings.saved"));
                            }, fail);
                        }}
                      />
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </Panel>
        </Reveal>
      </div>

      <Reveal index={2}>
        <Panel title={t("settings.organizations")}>
          <div className="stack" style={{ gap: "var(--sp-3)" }}>
            {(me?.organizations ?? []).map((organization) => (
              <div className="row-between" key={organization.id}>
                <span className="stack" style={{ gap: "var(--sp-1)" }}>
                  <span>{organization.name}</span>
                  <span className="nano">
                    {organization.slug}
                    {organization.city ? ` · ${organization.city}` : ""} · {organization.role}
                  </span>
                </span>
                {organization.active ? (
                  <StateChip tone="pass" animate={false}>
                    {t("settings.active")}
                  </StateChip>
                ) : (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      void api.switchOrganization(organization.id).then(async () => {
                        await refresh();
                        flash(t("settings.switched"));
                      }, fail);
                    }}
                  >
                    {t("settings.switchTo")}
                  </Button>
                )}
              </div>
            ))}
          </div>
        </Panel>
      </Reveal>

      <Reveal index={3}>
        <Panel title={t("settings.members")}>
          {members.status === "loading" ? <Loading /> : null}
          {members.status === "error" ? (
            <ErrorBlock
              code={members.error.code}
              message={members.error.message}
              onRetry={members.reload}
            />
          ) : null}
          {members.status === "ready" ? (
            <div className="stack" style={{ gap: "var(--sp-3)" }}>
              {members.data.map((member) => (
                <div className="row-between" key={member.user_id}>
                  <span className="stack" style={{ gap: "var(--sp-1)" }}>
                    <span>{member.name}</span>
                    <span className="nano">
                      {member.email} · {t("settings.joined")}{" "}
                      {dateOnly(member.joined_at, locale)}
                    </span>
                  </span>
                  <span className="row">
                    {member.verified ? null : (
                      <StateChip tone="unverified" animate={false}>
                        {t("settings.unverified")}
                      </StateChip>
                    )}
                    <Select
                      value={member.role}
                      aria-label={t("settings.role")}
                      onChange={(event) => {
                        void api
                          .changeRole(member.user_id, event.target.value)
                          .then(() => {
                            members.reload();
                            flash(t("settings.saved"));
                          }, fail);
                      }}
                    >
                      {["OWNER", "ADMIN", "MEMBER", "VIEWER"].map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </Select>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        void api.removeMember(member.user_id).then(() => {
                          members.reload();
                          flash(t("settings.saved"));
                        }, fail);
                      }}
                    >
                      {t("settings.remove")}
                    </Button>
                  </span>
                </div>
              ))}
              <p className="table-note">{t("settings.lastOwner")}</p>
            </div>
          ) : null}

          <hr className="rule" />

          <form
            className="row"
            style={{ paddingTop: "var(--sp-4)", alignItems: "flex-end" }}
            onSubmit={(event) => {
              event.preventDefault();
              void api.invite(inviteEmail, inviteRole).then(() => {
                setInviteEmail("");
                invitations.reload();
                flash(t("settings.invited"));
              }, fail);
            }}
          >
            <Field label={t("settings.inviteEmail")}>
              <Input
                type="email"
                value={inviteEmail}
                required
                onChange={(event) => setInviteEmail(event.target.value)}
              />
            </Field>
            <Field label={t("settings.role")}>
              <Select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}>
                {["ADMIN", "MEMBER", "VIEWER"].map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </Select>
            </Field>
            <Button type="submit" disabled={!inviteEmail}>
              {t("settings.invite")}
            </Button>
          </form>

          {invitations.status === "ready" && invitations.data.length > 0 ? (
            <div className="stack" style={{ gap: "var(--sp-2)", paddingTop: "var(--sp-4)" }}>
              {invitations.data.map((invitation) => (
                <Meta
                  key={invitation.id}
                  label={invitation.email}
                  value={`${invitation.role} · ${
                    invitation.accepted ? t("settings.accepted") : t("settings.pending")
                  } · ${dateOnly(invitation.expires_at, locale)}`}
                />
              ))}
            </div>
          ) : null}
        </Panel>
      </Reveal>

      {rail ? (
        <Reveal index={4}>
          <div id="rail">
            <RailDisclosurePanel rail={rail} />
          </div>
        </Reveal>
      ) : null}
    </section>
  );
}
