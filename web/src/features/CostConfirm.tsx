import { type ReactNode, useEffect, useRef } from "react";
import { Button } from "../components/ui";
import { AWAY_NOTICE, isProcessingAway, useActivity } from "../shell/activity";
import {
  chargedTo,
  isOnPlatform,
  type ShellStatus,
  useShell,
} from "../shell/ShellContext";

/**
 * "Before we spend anything": the estimate for a run on the user's own key,
 * and nothing happens until they say yes (domain model 2.10). While the
 * machine that runs the work is away, it says so: the run is queued, and
 * starts when it is back (ADR 0052).
 *
 * On CareerPolaris AI the money is ours, bounded by the free quota, so there
 * is nothing to confirm: it shows nothing and starts the run at once
 * (ADR 0067). A run the quota can't take is refused when it starts.
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
  const { status } = useShell();
  const onPlatform = isOnPlatform(status);
  // Once only, even when React mounts twice in development.
  const started = useRef(false);
  useEffect(() => {
    if (!onPlatform || started.current) return;
    started.current = true;
    onConfirm();
  }, [onPlatform, onConfirm]);

  if (onPlatform) return null;
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

/** "Runs on your own key on claude-opus-5.": who pays, which is only ever
 * said on the user's own key. Pure. */
export function getPayerLine(status: ShellStatus): string {
  return `Runs on ${chargedTo(status)}.`;
}
