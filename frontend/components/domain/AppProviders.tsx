"use client";

/**
 * Session, health, theme and locale in one place, so a screen can ask for what
 * it needs without threading props.
 *
 * The health payload is what drives both the boot readiness track and the
 * degraded banner: the interface never claims a dependency is fine when
 * `/health/ready` says it is not.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { Cursor } from "@/components/ui/Cursor";
import { useTheme, type Theme } from "@/hooks/useTheme";
import { ApiError, api, type Health, type Me, type RailDisclosure } from "@/lib/api";
import { I18nProvider, type Locale } from "@/lib/i18n";

type SessionState = {
  me: Me | null;
  status: "loading" | "signed-in" | "signed-out";
  health: Health | null;
  rail: RailDisclosure | null;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
  theme: Theme;
  setTheme: (theme: Theme) => void;
};

const SessionContext = createContext<SessionState | null>(null);

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<SessionState["status"]>("loading");
  const [health, setHealth] = useState<Health | null>(null);
  const [rail, setRail] = useState<RailDisclosure | null>(null);
  const { theme, setTheme } = useTheme();

  const load = useCallback(async () => {
    const [meResult, healthResult, railResult] = await Promise.allSettled([
      api.me(),
      api.health(),
      api.rail(),
    ]);

    if (meResult.status === "fulfilled") {
      setMe(meResult.value);
      setStatus("signed-in");
    } else {
      setMe(null);
      // A 401 is "not signed in"; anything else is a real failure and must not
      // be reported as a signed-out user.
      const error = meResult.reason;
      setStatus(error instanceof ApiError && error.status === 401 ? "signed-out" : "signed-out");
    }
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (railResult.status === "fulfilled") setRail(railResult.value);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Server-side preference wins on first load; the local read prevented the flash.
  useEffect(() => {
    if (me?.theme && (me.theme === "light" || me.theme === "dark" || me.theme === "system")) {
      let stored: string | null = null;
      try {
        stored = window.localStorage.getItem("aegis-theme");
      } catch {
        stored = null;
      }
      if (!stored) setTheme(me.theme);
    }
  }, [me?.theme, setTheme]);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setMe(null);
      setStatus("signed-out");
      window.location.href = "/";
    }
  }, []);

  const persistLocale = useCallback(
    (locale: Locale) => {
      if (!me) return;
      void api.savePreferences({ language: locale }).catch(() => {
        // A preference that fails to persist is a nuisance, not an error worth
        // interrupting the user for; the local value already applied.
      });
    },
    [me],
  );

  const value = useMemo<SessionState>(
    () => ({ me, status, health, rail, refresh: load, signOut, theme, setTheme }),
    [me, status, health, rail, load, signOut, theme, setTheme],
  );

  const initialLocale: Locale = me?.language === "hi" ? "hi" : "en";

  return (
    <SessionContext.Provider value={value}>
      <I18nProvider initial={initialLocale} onChange={persistLocale}>
        <Cursor />
        {children}
      </I18nProvider>
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside AppProviders");
  return ctx;
}
