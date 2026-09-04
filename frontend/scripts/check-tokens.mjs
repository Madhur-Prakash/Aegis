/**
 * Token discipline (spec 25.1).
 *
 * Fails the build when a component contains a hex colour, an rgb()/hsl()
 * literal, a raw millisecond or second duration, or an inline cubic-bezier.
 * Colour comes from `design/tokens.css`; duration and easing come from
 * `design/motion.ts`.  Those two files are the source of truth and are the only
 * place a literal is allowed, together with `design/brand.ts` -- which exists
 * solely because `<meta name="theme-color">` is read before any stylesheet.
 *
 * The point is not tidiness.  A hex colour in a component is a colour that does
 * not flip with the theme and does not carry a semantic meaning, and a raw
 * duration is a duration that ignores the reduced-motion preference.  Both are
 * bugs that look like style.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, sep } from "node:path";

const ROOTS = ["app", "components", "hooks", "lib"];
const EXTENSIONS = [".ts", ".tsx", ".css", ".mjs"];

/** `design/` holds the tokens themselves; everything else must reference them. */
const ALLOWED_DIRECTORIES = ["design"];

const RULES = [
  {
    name: "hex colour",
    // #abc, #aabbcc, #aabbccdd -- but not a CSS id selector or a URL fragment.
    pattern: /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g,
  },
  {
    name: "rgb()/hsl() literal",
    pattern: /\b(?:rgb|rgba|hsl|hsla)\(/g,
  },
  {
    name: "inline easing curve",
    pattern: /cubic-bezier\(/g,
  },
  {
    name: "raw CSS duration",
    // `0.3s`, `240ms` in a transition/animation value.  Token values read as
    // `var(--d-fast)`, so any literal here is a bypass.
    pattern: /(?:transition|animation)(?:-duration|-delay)?\s*:\s*[^;{}]*?\b\d+(?:\.\d+)?m?s\b/g,
  },
  {
    name: "raw Framer duration",
    // `duration: 0.42` inside a transition object.  Named durations come from
    // `D` in motion.ts, so a number here is an unowned timing.
    pattern: /\bduration:\s*(?!0\b)\d+(?:\.\d+)?/g,
  },
];

/**
 * Lines that are exempt, each for a stated reason.  An exemption is a comment
 * on the line itself, so it shows up in review rather than living in this file.
 */
const EXEMPT = /tokens-allow:/;

const walk = (dir, out = []) => {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      walk(path, out);
    } else if (EXTENSIONS.includes(extname(path))) {
      out.push(path);
    }
  }
  return out;
};

const files = ROOTS.filter((root) => {
  try {
    return statSync(root).isDirectory();
  } catch {
    return false;
  }
})
  .flatMap((root) => walk(root))
  .filter((path) => !ALLOWED_DIRECTORIES.some((allowed) => path.split(sep).includes(allowed)));

const violations = [];

for (const file of files) {
  const lines = readFileSync(file, "utf8").split(/\r?\n/);
  lines.forEach((line, index) => {
    if (EXEMPT.test(line)) return;
    for (const rule of RULES) {
      rule.pattern.lastIndex = 0;
      const found = line.match(rule.pattern);
      if (found) {
        violations.push({
          file,
          line: index + 1,
          rule: rule.name,
          text: found.join(", "),
          source: line.trim().slice(0, 120),
        });
      }
    }
  });
}

/**
 * The CSS duration scale in `app/globals.css` must equal `D` in
 * `design/motion.ts`.  Without this, a CSS transition and its Framer
 * counterpart could drift apart and the same interaction would take two
 * different times depending on which layer animated it.
 */
const motionSource = readFileSync(join("design", "motion.ts"), "utf8");
const cssSource = readFileSync(join("app", "globals.css"), "utf8");

const framer = new Map();
const framerBlock = motionSource.match(/export const D = \{([\s\S]*?)\}/);
if (framerBlock?.[1]) {
  for (const [, name, value] of framerBlock[1].matchAll(/(\w+):\s*([0-9.]+)/g)) {
    framer.set(name, Number(value));
  }
}

const css = new Map();
for (const [, name, value] of cssSource.matchAll(/--d-([a-z]+):\s*([0-9.]+)s;/g)) {
  css.set(name, Number(value));
}

for (const [name, seconds] of framer) {
  if (!css.has(name)) {
    violations.push({
      file: "app/globals.css",
      line: 0,
      rule: "duration scale",
      text: `--d-${name} is missing`,
      source: `design/motion.ts defines D.${name} = ${seconds}`,
    });
  } else if (Math.abs((css.get(name) ?? 0) - seconds) > 1e-9) {
    violations.push({
      file: "app/globals.css",
      line: 0,
      rule: "duration scale",
      text: `--d-${name} is ${css.get(name)}s but D.${name} is ${seconds}`,
      source: "the CSS scale and the Framer scale must agree",
    });
  }
}

if (violations.length > 0) {
  console.error(`check-tokens: ${violations.length} violation(s)\n`);
  for (const violation of violations) {
    console.error(`  ${violation.file}:${violation.line}  ${violation.rule} -> ${violation.text}`);
    console.error(`    ${violation.source}`);
  }
  console.error(
    "\nColour comes from design/tokens.css; duration and easing from design/motion.ts.",
  );
  process.exit(1);
}

console.log(`check-tokens: ok — ${files.length} files, no literal colour, duration or easing`);
