import { type ReactNode, useEffect } from "react";
import { Button } from "../components/ui";
import { AWAY_NOTICE, isProcessingAway, useActivity } from "../shell/activity";
import {
  chargedTo,
  isOnPlatform,
  type ShellStatus,
  useShell,
} from "../shell/ShellContext";

/**
 * "Before we spend anything": the estimate for a run, and nothing happens
 * until the user says yes (domain model 2.10). It says whose key pays, and on
 * CareerPolaris's, what is left of this month's quota (ADR 0064). While the
 * machine that runs the work is away, it says so: the run is queued, and
 * starts when it is back (ADR 0052).
 */
export function CostConfirm({
  children,
  busy,
  onConfirm,
  onCancel,
}: {
  children: ReactNode;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { activity } = useActivity();
  const { status, refresh } = useShell();
  // The quota moves with every run, so read it again when asked to confirm.
  useEffect(() => {
    void refresh();
  }, [refresh]);
  return (
    <div
      className="callout"
      role="region"
      aria-label="Cost estimate"
      style={{ maxWidth: 620, margin: "0 0 20px", padding: 22 }}
    >
      <div className="eyebrow" style={{ marginBottom: 6 }}>
        Before we spend anything
      </div>
      <p className="callout-note" style={{ fontSize: 14, lineHeight: 1.6 }}>
        {children}
      </p>
      {status.aiSource?.source && (
        <p className="callout-note" style={{ fontSize: 13.5 }}>
          {getPayerLine(status)}
        </p>
      )}
      {isProcessingAway(activity) && (
        <p className="callout-note" role="note" style={{ fontSize: 14 }}>
          {AWAY_NOTICE}.
        </p>
      )}
      <div className="row">
        <Button onClick={onConfirm} busy={busy}>
          Run it
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** "Runs on CareerPolaris's AI (claude-haiku-4-5) · $1.25 of $2 left this
 * month", or "Runs on your own key on claude-opus-5". Pure. */
export function getPayerLine(status: ShellStatus): string {
  const line = `Runs on ${chargedTo(status)}`;
  const quota = status.aiSource?.platform_quota;
  if (!isOnPlatform(status) || !quota) return `${line}.`;
  return `${line} · $${Number(quota.remaining_usd).toFixed(2)} of $${Number(
    quota.allowed_usd,
  ).toFixed(2)} left this month.`;
}
