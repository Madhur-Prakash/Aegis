/**
 * Fails when a component asks for a string that no dictionary has, or when the
 * Hindi dictionary is missing a key English defines.
 *
 * `t()` falls back to English at runtime, which is the right behaviour for a
 * user and the wrong behaviour for CI: a missing key would otherwise ship
 * silently and only surface as English text on a Hindi screen.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const ROOTS = ["app", "components", "hooks", "lib"];
const CALL = /\b(?:t|list)\(\s*"([a-zA-Z0-9_.]+)"/g;

const walk = (dir, out = []) => {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if ([".ts", ".tsx"].includes(extname(path))) out.push(path);
  }
  return out;
};

const load = (name) => JSON.parse(readFileSync(join("i18n", name), "utf8"));
const en = load("en.json");
const hi = load("hi.json");

const lookup = (dict, path) =>
  path.split(".").reduce((node, key) => (node && typeof node === "object" ? node[key] : undefined), dict);

const flatten = (node, prefix = "", out = []) => {
  for (const [key, value] of Object.entries(node)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) flatten(value, path, out);
    else out.push(path);
  }
  return out;
};

const files = ROOTS.flatMap((root) => walk(root));
const used = new Map();
for (const file of files) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(CALL)) {
    if (!used.has(match[1])) used.set(match[1], file);
  }
}

const problems = [];
for (const [key, file] of used) {
  if (lookup(en, key) === undefined) problems.push(`missing in en.json: ${key}  (${file})`);
}
for (const key of flatten(en)) {
  if (lookup(hi, key) === undefined) problems.push(`missing in hi.json: ${key}`);
}

if (problems.length) {
  console.error(`check-i18n: ${problems.length} problem(s)`);
  for (const problem of problems) console.error(`  ${problem}`);
  process.exit(1);
}
console.log(`check-i18n: ok - ${used.size} keys used, ${flatten(en).length} defined`);
