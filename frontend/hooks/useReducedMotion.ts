"use client";

/**
 * One hook, honoured globally (ui/01 §6).
 *
 * Copied from the design pack, with the addition that it also reports a
 * user-forced preference: the settings screen can turn animation off explicitly,
 * and that must reach every component through the same channel as the OS
 * setting, or the two would diverge.
 */
import { useEffect, useState } from "react";

export const MOTION_KEY = "aegis-motion";

export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const read = () => {
      const forced = window.localStorage.getItem(MOTION_KEY);
      if (forced === "off") return true;
      if (forced === "on") return false;
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    };
    setReduced(read());

    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onSystem = () => setReduced(read());
    mq.addEventListener("change", onSystem);
    window.addEventListener("aegis:motion", onSystem);
    return () => {
      mq.removeEventListener("change", onSystem);
      window.removeEventListener("aegis:motion", onSystem);
    };
  }, []);

  return reduced;
}

export function setMotionPreference(value: "system" | "on" | "off") {
  try {
    if (value === "system") window.localStorage.removeItem(MOTION_KEY);
    else window.localStorage.setItem(MOTION_KEY, value);
  } catch {
    // ignore: motion preference is a convenience, not state the app depends on
  }
  window.dispatchEvent(new Event("aegis:motion"));
}

export function readMotionPreference(): "system" | "on" | "off" {
  try {
    const value = window.localStorage.getItem(MOTION_KEY);
    return value === "on" || value === "off" ? value : "system";
  } catch {
    return "system";
  }
}
