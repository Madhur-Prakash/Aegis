"use client";

/**
 * The Merkle proof and the tamper check (ui/06 §5, motion moment 3.5).
 *
 * Two claims are made here and both are re-checked live rather than asserted:
 *
 *   1. this artifact is in the bundle the attestation signed -- the sibling path
 *      is fetched and re-verified by `POST /evidence/verify`, which recomputes
 *      the root from the leaf and the path alone;
 *   2. these bytes are the bytes that were hashed -- the file is downloaded
 *      through its short-lived presigned link, hashed in the browser, and the
 *      digest compared with the sha256 recorded at submission time.
 *
 * The tamper button flips exactly one bit of one byte of the downloaded copy and
 * re-runs the check.  Nothing on the server changes: the modified bytes are sent
 * to `POST /provenance/tamper-check`, which reports the digest it actually
 * computed for them.  The row shakes once and the mismatched digest is underlined
 * in red -- the only place in the product where red means "stop".
 */

import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion, useAnimationControls } from "motion/react";
import { useCallback, useEffect, useState } from "react";

import { Meta } from "@/components/ui/StateChip";
import { Button, ErrorBlock, Hash, Loading, Panel } from "@/components/ui/primitives";
import { D, E } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { ApiError, api, type Artifact, type MerkleProof } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const toHex = (buffer: ArrayBuffer) =>
  [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, "0")).join("");

const toBase64 = (bytes: Uint8Array) => {
  let binary = "";
  const CHUNK = 0x8000; // String.fromCharCode has an argument-count limit
  for (let offset = 0; offset < bytes.length; offset += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + CHUNK));
  }
  return btoa(binary);
};

type ProofState =
  | { kind: "loading" }
  | { kind: "ready"; proof: MerkleProof; recomputed: boolean }
  | { kind: "error"; code: string; message: string };

type TamperState = {
  running: boolean;
  localHash: string | null;
  expected: string | null;
  serverHash: string | null;
  ok: boolean | null;
  tampered: boolean;
  note: string | null;
};

const EMPTY_TAMPER: TamperState = {
  running: false,
  localHash: null,
  expected: null,
  serverHash: null,
  ok: null,
  tampered: false,
  note: null,
};

export function MerklePanel({ artifacts, root }: { artifacts: Artifact[]; root: string }) {
  const { t } = useI18n();
  const reduced = useReducedMotion();
  const shake = useAnimationControls();
  const firstId = artifacts[0]?.id ?? null;
  const [selected, setSelected] = useState<string | null>(firstId);
  const [proof, setProof] = useState<ProofState>({ kind: "loading" });
  const [tamper, setTamper] = useState<TamperState>(EMPTY_TAMPER);

  const artifact = artifacts.find((candidate) => candidate.id === selected) ?? null;

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    setProof({ kind: "loading" });
    setTamper(EMPTY_TAMPER);
    (async () => {
      const result = await api.proof(selected);
      // Re-verified independently of the flag the proof endpoint returns: the
      // point of a proof is that a second party can check it.
      const recheck = await api.verifyProof({
        leaf: result.leaf,
        proof: result.proof,
        root: result.root,
      });
      if (alive) setProof({ kind: "ready", proof: result, recomputed: recheck.ok });
    })().catch((error: unknown) => {
      if (!alive) return;
      setProof(
        error instanceof ApiError
          ? { kind: "error", code: error.code, message: error.message }
          : { kind: "error", code: "UNEXPECTED", message: String(error) },
      );
    });
    return () => {
      alive = false;
    };
  }, [selected]);

  const runCheck = useCallback(
    async (flip: boolean) => {
      if (!artifact) return;
      if (!artifact.download_url) {
        setTamper({ ...EMPTY_TAMPER, tampered: flip, note: t("provenance.noDownload") });
        return;
      }
      setTamper({ ...EMPTY_TAMPER, running: true, tampered: flip });
      try {
        const response = await fetch(artifact.download_url, { credentials: "include" });
        if (!response.ok) throw new Error(`download failed with ${response.status}`);
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (flip && bytes.length > 0) {
          const index = Math.floor(bytes.length / 2);
          bytes[index] = (bytes[index] ?? 0) ^ 0x01;
        }
        const localHash = globalThis.crypto?.subtle
          ? toHex(await crypto.subtle.digest("SHA-256", bytes))
          : null;
        const verdict = await api.tamperCheck(toBase64(bytes), artifact.sha256);
        setTamper({
          running: false,
          localHash,
          expected: verdict.expected_sha256,
          serverHash: verdict.actual_sha256,
          ok: verdict.ok,
          tampered: flip,
          note: null,
        });
        if (!verdict.ok && !reduced) {
          await shake.start({
            x: [0, -6, 5, -3, 2, 0],
            transition: { duration: D.slow, ease: E.exit as [number, number, number, number] },
          });
        }
      } catch (error) {
        setTamper({
          ...EMPTY_TAMPER,
          tampered: flip,
          note: error instanceof ApiError ? `${error.code}: ${error.message}` : String(error),
        });
      }
    },
    [artifact, reduced, shake, t],
  );

  const cleanRoot = root.replace(/^0x/, "");

  return (
    <Panel title={t("provenance.tamperCheck")}>
      {artifacts.length > 1 ? (
        <div className="tabs">
          {artifacts.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              className={`tab ${selected === candidate.id ? "is-on" : ""}`}
              onClick={() => setSelected(candidate.id)}
              data-cursor=""
            >
              {candidate.artifact_type}
            </button>
          ))}
        </div>
      ) : null}

      {proof.kind === "loading" ? <Loading /> : null}
      {proof.kind === "error" ? <ErrorBlock code={proof.code} message={proof.message} /> : null}

      {proof.kind === "ready" ? (
        <div className="stack" style={{ gap: "var(--sp-3)" }}>
          <Meta
            label={t("provenance.leaf")}
            value={<Hash value={proof.proof.leaf} head={8} tail={8} />}
          />
          <div className="merkle-path">
            <span className="nano">{t("provenance.path")}</span>
            {proof.proof.proof.length === 0 ? (
              <span>{t("provenance.singleLeaf")}</span>
            ) : (
              proof.proof.proof.map((step, index) => (
                <span key={`${step.position}-${step.hash}`}>
                  {index + 1}.{" "}
                  {step.position === "left" ? (
                    <ChevronLeft className="ico" size={12} strokeWidth={2} aria-hidden />
                  ) : (
                    <ChevronRight className="ico" size={12} strokeWidth={2} aria-hidden />
                  )}{" "}
                  {step.hash.slice(0, 12)}…
                </span>
              ))
            )}
          </div>
          <Meta
            label={t("provenance.evidenceRoot")}
            value={<Hash value={proof.proof.root} head={8} tail={8} />}
          />
          <Meta
            label={t("provenance.result")}
            value={
              <span
                style={{
                  color:
                    proof.recomputed && proof.proof.root === cleanRoot
                      ? "var(--sig-pass)"
                      : "var(--sig-fail)",
                }}
              >
                {proof.recomputed && proof.proof.root === cleanRoot
                  ? t("provenance.proofValid")
                  : t("provenance.proofInvalid")}
              </span>
            }
          />
        </div>
      ) : null}

      <hr className="rule" />

      <motion.div className="tamper-row" animate={shake} data-failed={tamper.ok === false}>
        <div className="row-between">
          <span className="micro">{artifact ? artifact.filename : t("provenance.artifact")}</span>
          <div className="row">
            <Button
              variant="ghost"
              onClick={() => void runCheck(false)}
              disabled={!artifact || tamper.running}
            >
              {t("provenance.checkBytes")}
            </Button>
            <Button
              variant="danger"
              onClick={() => void runCheck(true)}
              disabled={!artifact || tamper.running}
            >
              {t("provenance.tamperOneByte")}
            </Button>
          </div>
        </div>

        {tamper.note ? (
          <span className="field-error" role="alert">
            {tamper.note}
          </span>
        ) : null}

        {tamper.expected ? (
          <div className="stack" style={{ gap: "var(--sp-2)" }}>
            <Meta
              label={t("provenance.expected")}
              value={<Hash value={tamper.expected} head={8} tail={8} />}
            />
            <Meta
              label={t("provenance.found")}
              value={
                <span className={tamper.ok ? "num" : "num tamper-underline"}>
                  {tamper.serverHash
                    ? `${tamper.serverHash.slice(0, 8)}…${tamper.serverHash.slice(-8)}`
                    : "-"}
                </span>
              }
            />
            <Meta
              label={t("provenance.localDigest")}
              value={
                tamper.localHash ? (
                  <Hash value={tamper.localHash} head={8} tail={8} />
                ) : (
                  t("evidence.hashUnavailable")
                )
              }
            />
            <Meta
              label={t("provenance.result")}
              value={
                <span style={{ color: tamper.ok ? "var(--sig-pass)" : "var(--sig-fail)" }}>
                  {tamper.ok ? t("provenance.bytesMatch") : t("provenance.bytesDiffer")}
                </span>
              }
            />
            {tamper.tampered ? <span className="nano">{t("provenance.tamperNote")}</span> : null}
          </div>
        ) : null}
      </motion.div>
    </Panel>
  );
}
