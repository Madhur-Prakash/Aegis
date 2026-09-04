"use client";

/**
 * Centralised dictionaries and a `t()` helper.  No user-facing string is written
 * inline in a component (spec 24).
 *
 * The Hindi hero is a *shorter* headline rather than a literal translation:
 * Devanagari words are longer, and a literal translation turns the two-line hero
 * into four (ui/03 §6).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import en from "@/i18n/en.json";
import hi from "@/i18n/hi.json";

export type Locale = "en" | "hi";
export type Dictionary = typeof en;

const DICTIONARIES: Record<Locale, Dictionary> = {
  en,
  hi: hi as unknown as Dictionary,
};

export const LOCALE_KEY = "aegis-locale";

type Ctx = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  dict: Dictionary;
  t: (path: string, vars?: Record<string, string | number>) => string;
  list: (path: string) => string[];
};

const I18nContext = createContext<Ctx | null>(null);

function lookup(dict: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((node, key) => {
    if (node && typeof node === "object" && key in (node as Record<string, unknown>)) {
      return (node as Record<string, unknown>)[key];
    }
    return undefined;
  }, dict);
}

export function I18nProvider({
  children,
  initial = "en",
  onChange,
}: {
  children: React.ReactNode;
  initial?: Locale;
  onChange?: (locale: Locale) => void;
}) {
  const [locale, setLocaleState] = useState<Locale>(initial);

  useEffect(() => {
    const stored = window.localStorage.getItem(LOCALE_KEY) as Locale | null;
    if (stored === "en" || stored === "hi") setLocaleState(stored);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback(
    (next: Locale) => {
      setLocaleState(next);
      try {
        window.localStorage.setItem(LOCALE_KEY, next);
      } catch {
        // A blocked localStorage is not a reason to refuse the language change.
      }
      onChange?.(next);
    },
    [onChange],
  );

  const value = useMemo<Ctx>(() => {
    const dict = DICTIONARIES[locale];
    const t = (path: string, vars?: Record<string, string | number>) => {
      const found = lookup(dict, path) ?? lookup(DICTIONARIES.en, path);
      if (typeof found !== "string") return path;
      if (!vars) return found;
      return Object.entries(vars).reduce(
        (text, [key, replacement]) => text.replaceAll(`{${key}}`, String(replacement)),
        found,
      );
    };
    const list = (path: string) => {
      const found = lookup(dict, path) ?? lookup(DICTIONARIES.en, path);
      return Array.isArray(found) ? (found as string[]) : [];
    };
    return { locale, setLocale, dict, t, list };
  }, [locale, setLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): Ctx {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider");
  return ctx;
}

/** Convenience for components that only need the lookup. */
export function useT() {
  return useI18n().t;
}
