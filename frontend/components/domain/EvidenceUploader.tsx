"use client";

/**
 * Evidence submission (ui/06 §2, motion moment 3.6).
 *
 * The dropzone computes sha256 in the browser *before* the upload and shows it
 * next to the hash the server computed for the same bytes.  That is the point of
 * the screen: a user can see that the fingerprint the system will sign is the
 * fingerprint of the file they actually chose, computed on their own machine.
 *
 * `crypto.subtle` exists only on a secure context, so the local hash is
 * best-effort and says so plainly when it cannot be computed.  It is never
 * back-filled from the server's answer -- a local hash that is really the remote
 * hash would prove nothing while looking like proof.
 */

import { motion } from "motion/react";
import { useCallback, useRef, useState } from "react";

import { Meta } from "@/components/ui/StateChip";
import { Button, Empty, Hash, Panel, Select } from "@/components/ui/primitives";
import { D, E } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { ApiError, api, type Artifact, type Bundle, type Condition } from "@/lib/api";
import { num } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const MAX_BYTES = 20 * 1024 * 1024;

async function sha256Hex(file: File): Promise<string | null> {
  if (!globalThis.crypto?.subtle) return null;
  try {
    const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;
  }
}

type Pending = {
  key: string;
  filename: string;
  size: number;
  localHash: string | null;
  progress: number;
  error: string | null;
};

export function EvidenceUploader({
  milestoneId,
  condition,
  bundle,
  onChanged,
}: {
  milestoneId: string;
  condition: Condition;
  bundle: Bundle | null;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const reduced = useReducedMotion();
  const types = condition.required_artifact_types.length
    ? condition.required_artifact_types
    : ["OTHER"];
  const [artifactType, setArtifactType] = useState<string>(types[0] ?? "OTHER");
  const [over, setOver] = useState(false);
  const [pending, setPending] = useState<Pending[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const input = useRef<HTMLInputElement | null>(null);

  const submitted = Boolean(bundle?.submitted_at);
  const artifacts: Artifact[] = bundle?.artifacts ?? [];
  const provided = new Set(artifacts.map((artifact) => artifact.artifact_type));

  const upload = useCallback(
    async (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const key = `${file.name}-${file.size}-${Date.now()}`;
        const localHash = await sha256Hex(file);
        const tooLarge = file.size > MAX_BYTES;
        setPending((rows) => [
          ...rows,
          {
            key,
            filename: file.name,
            size: file.size,
            localHash,
            progress: tooLarge ? 1 : 0.4,
            error: tooLarge ? t("evidence.tooLarge") : null,
          },
        ]);
        if (tooLarge) continue;
        try {
          await api.upload(milestoneId, artifactType, file);
          setPending((rows) => rows.filter((row) => row.key !== key));
          onChanged();
        } catch (error) {
          const message =
            error instanceof ApiError ? `${error.code}: ${error.message}` : String(error);
          setPending((rows) =>
            rows.map((row) => (row.key === key ? { ...row, progress: 1, error: message } : row)),
          );
        }
      }
    },
    [artifactType, milestoneId, onChanged, t],
  );

  const submit = useCallback(async () => {
    setSubmitting(true);
    try {
      await api.submitBundle(milestoneId);
      onChanged();
    } finally {
      setSubmitting(false);
    }
  }, [milestoneId, onChanged]);

  return (
    <Panel
      title={t("evidence.title")}
      right={
        bundle?.merkle_root ? (
          <span className="row" style={{ gap: "var(--sp-2)" }}>
            <span className="nano">{t("evidence.merkleRoot")}</span>
            <Hash value={bundle.merkle_root} head={6} tail={6} label={t("evidence.merkleRoot")} />
          </span>
        ) : null
      }
    >
      <div className="stack" style={{ gap: "var(--sp-3)" }}>
        <span className="micro">{t("evidence.required")}</span>
        <div className="row">
          {condition.required_artifact_types.map((type) => (
            <span
              key={type}
              className="chip"
              style={{
                color: provided.has(type) ? "var(--sig-pass)" : "var(--fg-micro)",
                background: provided.has(type) ? "var(--sig-pass-tint)" : "transparent",
                borderColor: provided.has(type) ? "var(--sig-pass-edge)" : "var(--border)",
              }}
            >
              {type} · {provided.has(type) ? t("evidence.provided") : t("evidence.notProvided")}
            </span>
          ))}
        </div>
      </div>

      {!submitted ? (
        <>
          <div className="row" style={{ paddingTop: "var(--sp-4)" }}>
            <label className="field" style={{ maxWidth: 280 }}>
              <span className="field-label micro">{t("evidence.artifactType")}</span>
              <Select
                value={artifactType}
                onChange={(event) => setArtifactType(event.target.value)}
              >
                {types.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          <div
            className={`dropzone ${over ? "is-over" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(event) => {
              event.preventDefault();
              setOver(false);
              void upload(event.dataTransfer.files);
            }}
          >
            <span className="micro">{t("evidence.drop")}</span>
            <span className="nano">{t("evidence.accepts")}</span>
            <input
              ref={input}
              type="file"
              multiple
              className="visually-hidden"
              onChange={(event) => {
                if (event.target.files) void upload(event.target.files);
                event.target.value = "";
              }}
              accept="application/pdf,image/png,image/jpeg"
            />
            <Button variant="ghost" onClick={() => input.current?.click()}>
              {t("evidence.browse")}
            </Button>
          </div>
        </>
      ) : null}

      <hr className="rule" />
      <span className="micro">{t("evidence.artifacts")}</span>

      {artifacts.length === 0 && pending.length === 0 ? (
        <Empty label={t("evidence.artifacts")} body={t("evidence.empty")} />
      ) : null}

      {pending.map((row) => (
        <div className="artifact-row" key={row.key}>
          <div className="artifact-head">
            <span style={{ fontSize: "var(--fs-sm)" }}>{row.filename}</span>
            <span className="nano">{num(row.size / 1024)} KB</span>
            <span className="nano">
              {row.localHash
                ? `LOCAL SHA256 ${row.localHash.slice(0, 10)}…`
                : t("evidence.hashUnavailable")}
            </span>
            {row.error ? (
              <span className="field-error" role="alert">
                {row.error}
              </span>
            ) : (
              <span className="nano">{t("evidence.computing")}</span>
            )}
          </div>
          <div className="artifact-progress">
            <motion.span
              initial={{ scaleX: 0 }}
              animate={{ scaleX: row.progress }}
              transition={{
                duration: reduced ? 0 : D.slow,
                ease: E.enter as [number, number, number, number],
              }}
              style={row.error ? { background: "var(--sig-fail)" } : undefined}
            />
          </div>
        </div>
      ))}

      {artifacts.map((artifact) => (
        <div className="artifact-row" key={artifact.id}>
          <div className="artifact-head">
            <span className="micro">{artifact.artifact_type}</span>
            <span style={{ fontSize: "var(--fs-sm)" }}>{artifact.filename}</span>
            <span className="nano">{num(artifact.size_bytes / 1024)} KB</span>
            <Hash value={artifact.sha256} head={6} tail={6} label="sha256" />
          </div>
          <div className="artifact-fields">
            {artifact.extraction_quality !== null ? (
              <span>
                {t("verification.extractionQuality")} {artifact.extraction_quality.toFixed(2)}
              </span>
            ) : null}
            {Object.entries(artifact.extracted_fields)
              .slice(0, 6)
              .map(([field, value]) => (
                <span key={field}>
                  {field}={String(value)}
                </span>
              ))}
            {artifact.unreadable_fields.length ? (
              <span style={{ color: "var(--sig-unverified)" }}>
                {t("evidence.unreadable")}: {artifact.unreadable_fields.join(", ")}
              </span>
            ) : null}
          </div>
        </div>
      ))}

      {bundle ? (
        <div className="meta-grid" style={{ paddingTop: "var(--sp-4)" }}>
          <Meta
            label={t("evidence.submit")}
            value={submitted ? t("evidence.submitted") : t("evidence.notProvided")}
          />
          <Meta label={t("evidence.merkleRoot")} value={<Hash value={bundle.merkle_root} />} />
        </div>
      ) : null}

      {!submitted ? (
        <div className="row" style={{ paddingTop: "var(--sp-4)" }}>
          <Button
            onClick={() => void submit()}
            disabled={submitting || artifacts.length === 0}
          >
            {t("evidence.submit")}
          </Button>
        </div>
      ) : null}
    </Panel>
  );
}
