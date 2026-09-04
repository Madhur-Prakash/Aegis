"use client";

/**
 * Loading, empty and error as one state machine, so every view can render all
 * three without inventing its own booleans (spec 24, ui/03 §7).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: { code: string; message: string } };

export function useAsync<T>(
  load: () => Promise<T>,
  deps: React.DependencyList = [],
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({
    status: "loading",
    data: null,
    error: null,
  });
  const [nonce, setNonce] = useState(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    setState({ status: "loading", data: null, error: null });
    load()
      .then((data) => {
        if (alive.current) setState({ status: "ready", data, error: null });
      })
      .catch((error: unknown) => {
        if (!alive.current) return;
        const typed =
          error instanceof ApiError
            ? { code: error.code, message: error.message }
            : { code: "UNEXPECTED", message: String(error) };
        setState({ status: "error", data: null, error: typed });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
