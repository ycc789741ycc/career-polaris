import { useEffect, useId, useRef, useState } from "react";
import { type PreviousTarget, previousTargetLine } from "./advisorTarget";
import { targetKey } from "./AdvisorNoTarget";
import { dayLabel } from "./time";

/**
 * "Previous targets (n) ▾" on the target banner: the roles targeted before,
 * and a switch back to one, which restores what was written for it with no
 * AI call (ADR 0050). Shows nothing when there is none.
 */
export function PreviousTargets({
  previous,
  onSwitch,
}: {
  previous: PreviousTarget[];
  onSwitch: (target: PreviousTarget) => void;
}) {
  const [isOpen, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const popoverId = useId();

  // Escape or a click elsewhere closes it, as a menu would.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      toggle.current?.focus();
    };
    const onPointer = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [isOpen]);

  if (previous.length === 0) return null;
  return (
    <div className="previous-targets" ref={root}>
      <button
        ref={toggle}
        type="button"
        className="btn btn-secondary btn-block"
        aria-expanded={isOpen}
        aria-controls={popoverId}
        onClick={() => setOpen((open) => !open)}
      >
        Previous targets ({previous.length}) ▾
      </button>
      {isOpen && (
        <div
          id={popoverId}
          className="previous-targets-popover"
          role="region"
          aria-label="Previous targets"
        >
          <div className="eyebrow">Switch back to a role you targeted before</div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {previous.map((target) => (
              <li key={targetKey(target)}>
                <button
                  type="button"
                  className="previous-option"
                  onClick={() => {
                    setOpen(false);
                    onSwitch(target);
                  }}
                >
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span
                      className="ellipsis"
                      style={{ display: "block", fontWeight: 700 }}
                    >
                      {target.label}
                    </span>
                    <span
                      className="muted"
                      style={{ display: "block", fontSize: 12, marginTop: 2 }}
                    >
                      {previousTargetLine(target, dayLabel)}
                    </span>
                  </span>
                  <span className="source-chip">
                    {target.source === "own_role" ? "Own role" : "Role map"}
                  </span>
                  {target.fit !== null && (
                    <span className="no-target-fit">{target.fit}%</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          <p className="previous-targets-note">
            Switching back restores that role&apos;s saved answers, gap plan and
            résumé versions. No new AI calls, so no cost.
          </p>
        </div>
      )}
    </div>
  );
}
