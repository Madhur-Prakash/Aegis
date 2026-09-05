/**
 * Create .env if it is missing, then replace any placeholder secret with real
 * entropy.
 *
 * Why this exists:  JWT_SECRET signs access tokens AND keys the HMAC on the
 * presigned artifact URLs (backend/app/storage/store.py).  docker-compose.yml
 * carries a fallback so that a clean clone starts with one command -- but that
 * fallback is a constant published in this repository, so anyone who reads the
 * repo can forge a session for any user and mint a download token for any
 * storage key.  `make up` and `make up-build` both depend on this, so there is
 * no path through the documented quick start that boots on it.
 *
 * Why Node and not sh:  GNU Make on Windows cannot resolve `SHELL := /bin/sh`
 * unless a POSIX layer is on PATH, and falls back to cmd.exe -- where `sh` does
 * not exist, so `make up` died before reaching Docker.  `node <file>` is one
 * command with no shell metacharacters and no quoting, so cmd.exe, PowerShell
 * and sh all run it identically.  Node 22 is already a prerequisite, and
 * `frontend/scripts/*.mjs` is the existing convention for this kind of gate.
 *
 * It is deliberately a no-op once a real value is present: regenerating the
 * secret on every `make up` would sign every user out on every restart.
 */

import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, copyFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const ENV_FILE = join(ROOT, ".env");
const EXAMPLE_FILE = join(ROOT, ".env.example");

/** Secrets that must never keep their placeholder value.  Add a name here and
 *  it is filled on the next `make up`. */
const KEYS = ["JWT_SECRET"];

/**
 * A value is a placeholder if it is empty, is the published compose fallback,
 * shouts CHANGE_ME, or is too short to be 32 bytes of hex.  A real secret never
 * matches any of these.
 */
function isPlaceholder(value) {
  if (!value) return true;
  if (value.startsWith("CHANGE_ME")) return true;
  if (value.includes("change-me")) return true;
  return value.length < 32;
}

if (!existsSync(ENV_FILE)) {
  if (!existsSync(EXAMPLE_FILE)) {
    console.error("ensure-env: no .env and no .env.example to copy from");
    process.exit(1);
  }
  copyFileSync(EXAMPLE_FILE, ENV_FILE);
  console.log("created .env from .env.example");
}

let text = readFileSync(ENV_FILE, "utf8");
// Keep whatever line ending the file already uses; .gitattributes normalises to
// LF, but a hand-edited file on Windows may not have.
const eol = text.includes("\r\n") ? "\r\n" : "\n";

for (const key of KEYS) {
  const lines = text.split(/\r?\n/);
  const index = lines.findIndex((line) => line.startsWith(`${key}=`));
  const current = index === -1 ? "" : lines[index].slice(key.length + 1).trim();

  if (!isPlaceholder(current)) continue;

  const value = randomBytes(32).toString("hex");
  if (index === -1) {
    // Append, keeping a single trailing newline.
    while (lines.length && lines[lines.length - 1] === "") lines.pop();
    lines.push(`${key}=${value}`, "");
  } else {
    // Rewrite in place so the key keeps its position and its comment context.
    lines[index] = `${key}=${value}`;
  }
  text = lines.join(eol);
  writeFileSync(ENV_FILE, text);
  console.log(`ensure-env: generated ${key} (32 bytes) - any existing session is now invalid`);
}
