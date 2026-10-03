import { Button } from "../components/ui";

export type OutdatedReason = "evidence" | "target";

/**
 * Says a gap plan or résumé no longer matches what it was drafted from (ADR
 * 0035): the user's evidence changed, the target changed, or both. Nothing is
 * rewritten by itself, so the banner offers Regenerate, which prices the
 * rewrite before anything runs.
 */
export function OutdatedBanner({
  reasons,
  busy,
  onRegenerate,
}: {
  reasons: OutdatedReason[];
  busy?: boolean | undefined;
  onRegenerate: () => void;
}) {
  if (reasons.length === 0) return null;
  return (
    <div
      className="panel panel-tight row-between"
      role="status"
      aria-label="Outdated"
      style={{ marginBottom: 16, flexWrap: "wrap", gap: 12 }}
    >
      <div style={{ minWidth: 0 }}>
        <strong>{outdatedTitle(reasons)}</strong>
        <div className="muted" style={{ fontSize: 12.5 }}>
          Nothing is rewritten until you ask; regenerating is priced first.
        </div>
      </div>
      <Button busy={busy ?? false} onClick={onRegenerate}>
        Regenerate
      </Button>
    </div>
  );
}

/** "Outdated: your evidence changed", "… the target changed", or both. Pure. */
export function outdatedTitle(reasons: OutdatedReason[]): string {
  const parts = [
    reasons.includes("evidence") ? "your evidence changed" : null,
    reasons.includes("target") ? "the target changed" : null,
  ].filter(Boolean);
  return `Outdated: ${parts.join(" and ")}`;
}
