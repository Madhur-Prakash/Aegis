/**
 * Browser storage keys, in a module with no `"use client"` directive.
 *
 * These are read by `app/layout.tsx`, which is a Server Component. Importing
 * them from a client module made Next replace each export with a server-side
 * throwing stub, and interpolating that stub into the inline no-flash script
 * produced invalid JavaScript:
 *
 *     var theme = localStorage.getItem("function() { throw new Error("Attempted
 *     to call THEME_KEY() from the server ...
 *
 * The script then failed to parse, so the guard it exists to provide -- applying
 * the stored theme before first paint -- silently did nothing, and every load
 * flashed the dark canvas at a light-theme user. Plain constants in a plain
 * module are importable from both sides.
 */

export const THEME_KEY = "aegis-theme";
export const LOCALE_KEY = "aegis-locale";
export const MOTION_KEY = "aegis-motion";
