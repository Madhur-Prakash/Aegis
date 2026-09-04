"use client";

/**
 * Theme, persisted per user server-side, with an immediate localStorage read so
 * there is no flash (spec 24).  The inline script in the layout applies the
 * attribute before first paint; this hook keeps React in step with it.
 */
import { useCallback, useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark";
import { THEME_KEY } from "@/lib/storage-keys";

// Re-exported so existing call sites keep importing it from here, while the
// single definition lives in a module a Server Component can also read.
export { THEME_KEY };

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function useTheme(initial: Theme = "system") {
  const [theme, setThemeState] = useState<Theme>(initial);

  useEffect(() => {
    let stored: Theme | null = null;
    try {
      stored = window.localStorage.getItem(THEME_KEY) as Theme | null;
    } catch {
      stored = null;
    }
    const resolved = stored ?? initial;
    setThemeState(resolved);
    apply(resolved);
  }, [initial]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    apply(next);
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // ignore
    }
  }, []);

  return { theme, setTheme };
}
