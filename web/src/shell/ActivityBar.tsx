import { ProgressBar } from "../components/ui";
import { describe, useActivity } from "./activity";
import { modelName, useShell } from "./ShellContext";

/**
 * The running bar: on every screen while a sync, a parse, an analysis or a
 * role-map build is under way, so leaving a page never hides that work is
 * still going (ADR 0018). Gone as soon as nothing is running.
 */
export function ActivityBar() {
  const { activity } = useActivity();
  const { status } = useShell();
  const lines = describe(activity, modelName(status.credential));
  if (lines.length === 0) return null;

  return (
    <div className="activity-bar" role="status" aria-label="Running now">
      <ProgressBar indeterminate label="Background work in progress" />
      <ul className="activity-list">
        {lines.map((line) => (
          <li key={line} className="model-pill">
            {line}…
          </li>
        ))}
      </ul>
    </div>
  );
}
