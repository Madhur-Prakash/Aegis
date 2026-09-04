/**
 * The two literal colours the platform needs outside CSS.
 *
 * Next's `viewport.themeColor` becomes a `<meta name="theme-color">`, which the
 * browser reads before any stylesheet exists -- so it cannot be a `var()`.  The
 * values live here, beside `tokens.css`, rather than in a component: the rule
 * that no component contains a hex colour stays absolute, and `check-tokens.mjs`
 * scans everything except this directory.
 *
 * These two must equal `--bg` in `tokens.css` for each theme.  If a token
 * changes, change it here as well; there is no way to derive one from the other
 * without shipping a CSS parser into the build.
 */

export const BRAND_THEME_COLOR = {
  /** `:root { --bg }` — dark is the default. */
  dark: "#08080A",
  /** `:root[data-theme="light"] { --bg }`. */
  light: "#F2EFE9",
} as const;
