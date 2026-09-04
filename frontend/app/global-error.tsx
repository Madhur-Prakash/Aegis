"use client";

/**
 * The last boundary: an error thrown by the root layout itself, before the
 * providers exist.  It cannot use tokens, i18n or any component that needs a
 * context, so it renders its own minimal document.
 */

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "ui-monospace, monospace", padding: "2rem" }}>
        <p style={{ letterSpacing: "0.08em", textTransform: "uppercase" }}>
          {error.digest ?? "ROOT_ERROR"}
        </p>
        <h1>Aegis could not start this page</h1>
        <p>{error.message}</p>
        <button type="button" onClick={reset}>
          Retry
        </button>
      </body>
    </html>
  );
}
