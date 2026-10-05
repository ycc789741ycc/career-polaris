import type { ReactNode } from "react";
import { Button } from "../components/ui";
import { AWAY_NOTICE, isProcessingAway, useActivity } from "../shell/activity";

/**
 * "Before we spend anything": the estimate for a run on the user's own key,
 * and nothing happens until they say yes (domain model 2.10). While the
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
