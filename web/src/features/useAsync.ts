import { useEffect, useState } from "react";
import { ApiError } from "../api/client";

/** What the last finished load gave, and the deps it was loaded for. */
type Settled<T> = { deps: unknown[]; data: T | null; error: string | null };

/**
 * Server data with its own loading and error state, refetched when `deps`
 * change or on demand.
 *
 * Loading is derived, not set: it holds while nothing has settled for the
 * current deps, or while a reload runs. State changes only once a load
 * settles, never while the effect that starts it runs
 * (react-hooks/set-state-in-effect), and a load for deps that have since
 * changed is dropped.
 */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [reloading, setReloading] = useState(0);

  useEffect(() => {
    let isCurrent = true;
    void load().then(
      (data) => {
        if (isCurrent) setSettled({ deps, data, error: null });
      },
      (caught: unknown) => {
        if (isCurrent) setSettled(failed(deps, caught));
      },
    );
    return () => {
      isCurrent = false;
    };
    // The caller's deps decide when to load again; `load` is read fresh then.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  async function reload() {
    setReloading((count) => count + 1);
    try {
      const data = await load();
      setSettled({ deps, data, error: null });
    } catch (caught) {
      setSettled(failed(deps, caught));
    } finally {
      setReloading((count) => count - 1);
    }
  }

  function setError(error: string | null) {
    setSettled((previous) => ({
      deps: previous?.deps ?? deps,
      data: previous?.data ?? null,
      error,
    }));
  }

  const isCurrent = settled !== null && isSameDeps(settled.deps, deps);
  return {
    data: settled?.data ?? null,
    loading: !isCurrent || reloading > 0,
    error: isCurrent ? settled.error : null,
    reload,
    setError,
  };
}

/** A failed load keeps the data already shown, and says why. */
function failed<T>(deps: unknown[], caught: unknown) {
  return (previous: Settled<T> | null): Settled<T> => ({
    deps,
    data: previous?.data ?? null,
    error: messageOf(caught),
  });
}

function isSameDeps(a: unknown[], b: unknown[]): boolean {
  return a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
}

export function messageOf(caught: unknown): string {
  if (caught instanceof ApiError) return caught.message;
  if (caught instanceof Error) return caught.message;
  return "Something went wrong";
}
