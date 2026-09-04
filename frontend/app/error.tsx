"use client";

/**
 * The route error boundary.
 *
 * `digest` is Next's server-side error id.  It is shown because it is the only
 * thing that ties this screen to a line in the server log, and a support
 * conversation that starts with an id is shorter than one that starts with
 * "it broke".
 */

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="auth-screen">
      <div className="auth-card" role="alert">
        <span className="mono-code">{error.digest ?? "CLIENT_ERROR"}</span>
        <h1 className="display-3">Something went wrong</h1>
        <p className="state-body">{error.message}</p>
        <button className="btn btn--ghost" onClick={reset}>
          Retry
        </button>
      </div>
    </div>
  );
}
