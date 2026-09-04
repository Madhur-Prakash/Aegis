import type { Config } from "tailwindcss";

/**
 * Tailwind is wired to the design tokens, not to its own palette.  There is no
 * literal colour in this file and none in any component: `bg-raised` resolves to
 * `var(--bg-raised)`, so a theme change is a token change (spec 25.1).
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    // Replace, not extend: Tailwind's default palette must not be reachable, or
    // a component could quietly introduce a hue the state system does not own.
    colors: {
      transparent: "transparent",
      current: "currentColor",
      ink: {
        900: "var(--ink-900)",
        800: "var(--ink-800)",
        700: "var(--ink-700)",
        600: "var(--ink-600)",
      },
      line: { 1: "var(--line-1)", 2: "var(--line-2)" },
      grey: { 500: "var(--grey-500)", 300: "var(--grey-300)" },
      bone: { 100: "var(--bone-100)" },
      white: "var(--white)",
      bg: "var(--bg)",
      raised: "var(--bg-raised)",
      "raised-hi": "var(--bg-raised-hi)",
      fg: "var(--fg)",
      "fg-display": "var(--fg-display)",
      "fg-secondary": "var(--fg-secondary)",
      "fg-micro": "var(--fg-micro)",
      border: "var(--border)",
      "border-strong": "var(--border-strong)",
      focus: "var(--focus)",
      pass: "var(--sig-pass)",
      unverified: "var(--sig-unverified)",
      fail: "var(--sig-fail)",
      "pass-tint": "var(--sig-pass-tint)",
      "unverified-tint": "var(--sig-unverified-tint)",
      "fail-tint": "var(--sig-fail-tint)",
      "pass-edge": "var(--sig-pass-edge)",
      "unverified-edge": "var(--sig-unverified-edge)",
      "fail-edge": "var(--sig-fail-edge)",
      "money-held": "var(--money-held)",
      "money-released": "var(--money-released)",
      "money-refunded": "var(--money-refunded)",
    },
    fontFamily: {
      display: "var(--font-display)",
      mono: "var(--font-mono)",
    },
    fontSize: {
      "display-1": ["var(--fs-display-1)", { lineHeight: "var(--lh-display-1)" }],
      "display-2": ["var(--fs-display-2)", { lineHeight: "var(--lh-display-2)" }],
      "display-3": ["var(--fs-display-3)", { lineHeight: "var(--lh-display-3)" }],
      h4: ["var(--fs-h4)", { lineHeight: "1.15" }],
      body: ["var(--fs-body)", { lineHeight: "var(--lh-body)" }],
      sm: ["var(--fs-sm)", { lineHeight: "1.5" }],
      micro: ["var(--fs-micro)", { lineHeight: "1.3" }],
      nano: ["var(--fs-nano)", { lineHeight: "1.25" }],
    },
    spacing: {
      0: "0",
      1: "var(--sp-1)",
      2: "var(--sp-2)",
      3: "var(--sp-3)",
      4: "var(--sp-4)",
      5: "var(--sp-5)",
      6: "var(--sp-6)",
      7: "var(--sp-7)",
      8: "var(--sp-8)",
      gutter: "var(--gutter)",
      section: "var(--section)",
      px: "1px",
    },
    borderRadius: {
      none: "0",
      sm: "var(--r-sm)",
      md: "var(--r-md)",
      lg: "var(--r-lg)",
      full: "var(--r-full)",
    },
    maxWidth: { container: "var(--container)", prose: "52ch" },
    gap: { grid: "var(--grid-gap)" },
    zIndex: {
      base: "var(--z-base)",
      sticky: "var(--z-sticky)",
      nav: "var(--z-nav)",
      modal: "var(--z-modal)",
      toast: "var(--z-toast)",
      cursor: "var(--z-cursor)",
      boot: "var(--z-boot)",
    },
    extend: {
      screens: { sm: "480px", md: "768px", lg: "1024px", xl: "1280px", "2xl": "1536px" },
      transitionDuration: {
        instant: "90ms",
        fast: "180ms",
        base: "260ms",
        slow: "420ms",
        reveal: "520ms",
      },
      boxShadow: { lift: "var(--lift)" },
    },
  },
  plugins: [],
};

export default config;
