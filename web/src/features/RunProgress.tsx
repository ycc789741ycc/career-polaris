import type { ReactNode } from "react";
import type { Activity, Assessment, Evidence } from "../api/types";
import { radarPolygon } from "../charts/geometry";
import { sourceShares } from "../charts/SourceMix";
import { Button, ProgressBar } from "../components/ui";
import { isBusy } from "../shell/activity";
import { ago } from "./time";

/**
 * The waiting screen a long AI run shows while it works: the strength
 * analysis on Strengths, the role-map build on the role map (the prototype's
 * StrengthsBuilding and RolesBuilding).
 *
 * Each step is worked out from what `/activity` already says — waiting for
 * the analysis, searching the market, building — so the screen claims no
 * progress the server has not reported: there is no percentage and no time
 * left, only how far through its steps a run is and when it started. Nothing
 * here stops a run; leaving the page does not either. While a run is going,
 * this screen is the only place its screen shows it: the shell's running bar
 * leaves it out there.
 */

export type StepState = "done" | "running" | "waiting";

export interface RunStep {
  label: string;
  detail: string;
  state: StepState;
}

export function RunProgress({
  label,
  heading,
  subline,
  startedAt,
  steps,
  previewTitle,
  preview,
  previewNote,
  leaveCopy,
  back,
  costCopy,
}: {
  /** The section's accessible name, e.g. "Strength analysis progress". */
  label: string;
  heading: string;
  subline: string;
  startedAt: string | null;
  steps: RunStep[];
  previewTitle: string;
  preview: ReactNode;
  previewNote: string;
  leaveCopy: string;
  back: { label: string; onClick: () => void };
  costCopy: string;
}) {
  const done = steps.filter((step) => step.state === "done").length;
  return (
    <div className="stack" style={{ gap: 20 }}>
      <section aria-label={label} className="panel run-progress">
        <div
          className="row-between"
          style={{ alignItems: "flex-end", gap: 20 }}
        >
          <div>
            <div
              className="eyebrow"
              style={{ color: "var(--color-accent-700)" }}
            >
              Analysis running
            </div>
            <h2 className="run-progress-heading">{heading}</h2>
            <p className="run-progress-subline">{subline}</p>
          </div>
          <div style={{ textAlign: "right", flex: "0 0 auto" }}>
            <div className="run-progress-count">
              {done} of {steps.length}
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
              {startedAt ? `started ${ago(startedAt)}` : "steps done"}
            </div>
          </div>
        </div>
        <div style={{ margin: "18px 0 20px" }}>
          <ProgressBar label={label} indeterminate />
        </div>
        <div className="run-progress-grid">
          <ol aria-label="Steps" className="run-steps">
            {steps.map((step) => (
              <li
                key={step.label}
                className={`run-step run-step-${step.state}`}
                aria-current={step.state === "running" ? "step" : undefined}
              >
                <StepIcon state={step.state} />
                <div style={{ flexGrow: 1, minWidth: 0 }}>
                  <div className="run-step-label">{step.label}</div>
                  <div className="run-step-detail">{step.detail}</div>
                </div>
                <span className="run-step-state">
                  {STATE_NAMES[step.state]}
                </span>
              </li>
            ))}
          </ol>
          <div className="run-preview">
            <div className="eyebrow">{previewTitle}</div>
            {preview}
            <p className="run-step-detail" style={{ margin: "6px 0 0" }}>
              {previewNote}
            </p>
          </div>
        </div>
      </section>

      <div className="run-progress-cards">
        <div className="panel">
          <h3 className="run-card-heading">You don&apos;t need to wait here</h3>
          <p className="run-card-copy">{leaveCopy}</p>
          <Button variant="secondary" onClick={back.onClick}>
            {back.label}
          </Button>
        </div>
        <div className="panel">
          <h3 className="run-card-heading">What this run costs</h3>
          <p className="run-card-copy">{costCopy}</p>
        </div>
      </div>
    </div>
  );
}

const STATE_NAMES: Record<StepState, string> = {
  done: "Done",
  running: "Running",
  waiting: "Waiting",
};

function StepIcon({ state }: { state: StepState }) {
  if (state === "done") {
    return (
      <span className="run-step-icon run-step-icon-done">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M5 12l5 5 9-10" />
        </svg>
      </span>
    );
  }
  return (
    <span
      className={`run-step-icon run-step-icon-${state}`}
      aria-hidden="true"
    />
  );
}

/** The empty radar the analysis fills in: dashed rings, no points yet. */
export function EmptyRadar({ axes }: { axes: number }) {
  const count = Math.max(axes, 5);
  const centre = { x: 270, y: 150 };
  return (
    <svg
      viewBox="0 0 540 300"
      width="100%"
      role="img"
      aria-label="Empty skill radar, waiting for scored dimensions"
      style={{ display: "block", marginTop: 8 }}
    >
      {[130, 97, 65, 32].map((radius) => (
        <polygon
          key={radius}
          points={radarPolygon(Array(count).fill(100), radius, centre)}
          fill="none"
          stroke="rgba(32,30,29,0.16)"
          strokeDasharray="4 4"
        />
      ))}
    </svg>
  );
}

/** The empty map the build fills in: axes, and dashed bubbles. */
export function EmptyMap() {
  const bubbles: [number, number, number][] = [
    [190, 240, 30],
    [400, 90, 28],
    [310, 145, 24],
    [250, 190, 20],
    [360, 175, 16],
    [480, 40, 14],
  ];
  return (
    <svg
      viewBox="0 0 540 300"
      width="100%"
      role="img"
      aria-label="Empty map, waiting for scored roles"
      style={{ display: "block", marginTop: 8 }}
    >
      <line x1="40" x2="530" y1="280" y2="280" stroke="rgba(32,30,29,0.3)" />
      <line x1="40" x2="40" y1="10" y2="280" stroke="rgba(32,30,29,0.3)" />
      {bubbles.map(([cx, cy, r]) => (
        <circle
          key={`${cx}:${cy}`}
          cx={cx}
          cy={cy}
          r={r}
          fill="rgba(32,30,29,0.06)"
          stroke="rgba(32,30,29,0.18)"
          strokeWidth="1.5"
          strokeDasharray="4 4"
        />
      ))}
    </svg>
  );
}

/**
 * The analysis's steps. It is one call on the user's key, so between the
 * facts it has read and the build that follows there is one step running.
 * Pure.
 */
export function getAnalysisSteps(
  facts: Evidence[] | null,
  model: string,
): RunStep[] {
  return [
    {
      label: "Collected your facts",
      detail: facts ? factsLine(facts) : "Reading what your sources hold",
      state: "done",
    },
    {
      label: `Scoring your strengths on ${model}`,
      detail:
        "Each dimension, how sure each score is, and the evidence it cites",
      state: "running",
    },
    {
      label: "Building your role map",
      detail: "Starts by itself when the analysis finishes",
      state: "waiting",
    },
  ];
}

/** "158 facts · GitHub 118, Résumé 34, Your answers 6". Pure. */
export function factsLine(facts: Evidence[]): string {
  const total = `${facts.length} ${facts.length === 1 ? "fact" : "facts"}`;
  if (facts.length === 0) return total;
  const shares = sourceShares(facts)
    .map((share) => `${share.name} ${share.count}`)
    .join(", ");
  return `${total} · ${shares}`;
}

/**
 * The build's steps, from where `/activity` says it stands: waiting for the
 * analysis it reads, waiting for the market sources it searches, or running.
 * An analysis still running counts as the first step even before the build
 * is recorded, since a finished analysis always builds the map (ADR 0020).
 * Pure.
 */
export function getBuildSteps({
  activity,
  assessment,
  scope,
  maxRoles,
}: {
  activity: Activity | null;
  assessment: Assessment | null;
  scope: string | null;
  maxRoles: number | null;
}): RunStep[] {
  const build = activity?.role_map;
  const readingAnalysis =
    activity?.analysis?.status === "running" ||
    (build?.status === "waiting" && build.waiting_for === "analysis");
  const searching =
    !readingAnalysis &&
    build?.status === "waiting" &&
    build.waiting_for === "market";
  const building = !readingAnalysis && build?.status === "running";

  const confidence =
    assessment?.profile_confidence != null
      ? ` · profile confidence ${Math.round(assessment.profile_confidence * 100)}%`
      : "";
  return [
    {
      label: "Read your strength analysis",
      detail: readingAnalysis
        ? "Waiting for your analysis to finish"
        : assessment
          ? `${assessment.dimensions.length} dimensions${confidence}`
          : "Your latest analysis",
      state: readingAnalysis ? "running" : "done",
    },
    {
      label: "Search open postings in your locations",
      detail: scope ?? "The recommended roles, in each place you chose",
      state: searching ? "running" : building ? "done" : "waiting",
    },
    {
      label: maxRoles
        ? `Pick your ${maxRoles} best-fit roles and score your fit`
        : "Pick your best-fit roles and score your fit",
      detail: "Salary, hiring bar and fit for each role on the map",
      state: building ? "running" : "waiting",
    },
  ];
}

/** Whether the role map has a build on its way: running, waiting, or about to
 * follow the analysis that is running now. Pure. */
export function isMapComing(activity: Activity | null): boolean {
  return isBusy(activity?.role_map) || activity?.analysis?.status === "running";
}
