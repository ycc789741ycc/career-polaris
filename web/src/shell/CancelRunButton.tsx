import { useState } from "react";
import { api } from "../api/client";
import { Button } from "../components/ui";
import { type CancellableRun, isBusy, useActivity } from "./activity";

/**
 * Cancel for a running or waiting analysis or role-map build (ADR 0072): on
 * its progress screen, and in the running bar's pill everywhere else.
 *
 * There is no confirmation: cancelling costs nothing, and a call already sent
 * is still charged. It reads "Cancelling…" until `/activity` says the run is
 * closed; the activity provider then says so in a toast, never as a failure.
 * Cancelling an analysis also cancels a build waiting for it.
 */
export function CancelRunButton({
  run,
  isCompact = false,
}: {
  run: CancellableRun;
  isCompact?: boolean;
}) {
  const { activity, refresh } = useActivity();
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const status = run === "analysis" ? activity?.analysis : activity?.role_map;
  const id = status?.id ?? null;
  if (!id || !isBusy(status)) return null;
  const isCancelling = asked === id;

  async function cancel() {
    if (!id) return;
    setAsked(id);
    setError(null);
    try {
      await api.post(cancelPath(run, id));
    } catch (caught) {
      // An ApiError carries the server's wording.
      setError(caught instanceof Error ? caught.message : "Could not cancel");
      setAsked(null);
      return;
    }
    await refresh();
  }

  const label = isCancelling ? "Cancelling…" : "Cancel";
  return (
    <>
      {isCompact ? (
        <button
          type="button"
          className="pill-cancel"
          disabled={isCancelling}
          aria-label={
            isCancelling
              ? "Cancelling"
              : run === "analysis"
                ? "Cancel the analysis"
                : "Cancel the role map build"
          }
          onClick={() => void cancel()}
        >
          {isCancelling ? label : `× ${label}`}
        </button>
      ) : (
        <Button
          variant="secondary"
          disabled={isCancelling}
          onClick={() => void cancel()}
        >
          {label}
        </Button>
      )}
      {error && (
        <span role="alert" className="muted" style={{ fontSize: 12.5 }}>
          {error}
        </span>
      )}
    </>
  );
}

/** Where a run is cancelled. Pure. */
export function cancelPath(run: CancellableRun, id: string): string {
  return run === "analysis"
    ? `/assessments/runs/${id}/cancel`
    : `/roles/builds/${id}/cancel`;
}
