import type { Activity } from "../api/types";
import { ProgressBar } from "../components/ui";
import { describe, useActivity } from "./activity";
import type { Screen } from "./navigation";
import { modelName, useShell } from "./ShellContext";

/**
 * The running bar: on every screen while a sync, a parse, an analysis or a
 * role-map build is under way, so leaving a page never hides that work is
 * still going (ADR 0018). Gone as soon as nothing is running.
 *
 * Strengths and the role map show their own run as a waiting screen instead,
 * so there the bar leaves out the analysis and the build.
 */
export function ActivityBar({ screen }: { screen: Screen }) {
  const { activity } = useActivity();
  const { status } = useShell();
  const lines = describe(
    withoutOwnRuns(activity, screen),
    modelName(status.credential),
  );
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

/** What the bar reports on a screen: everything, except on Strengths and the
 * role map, whose waiting screens show the analysis and the build. Pure. */
export function withoutOwnRuns(
  activity: Activity | null,
  screen: Screen,
): Activity | null {
  if (activity === null) return null;
  if (screen !== "strengths" && screen !== "roles") return activity;
  return { ...activity, analysis: null, role_map: null };
}
