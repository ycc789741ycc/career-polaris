import { useState } from "react";
import { api } from "../api/client";
import type { Activity, TargetRef } from "../api/types";
import { Button, ErrorNote } from "../components/ui";
import type { AdvisorTab } from "../shell/navigation";
import { sameTarget } from "./target";
import { messageOf } from "./useAsync";

/** One of the Advisor's short AI jobs, as `GET /activity` lists it. */
export type AdvisorJob = Activity["advisor_jobs"][number];

/** The tab a job's result lands on. Pure. */
export function jobTab(kind: AdvisorJob["kind"]): Exclude<AdvisorTab, "own"> {
  switch (kind) {
    case "questions":
    case "own_posting_evaluation":
      return "gaps";
    case "gap_plan":
      return "plan";
    case "resume":
    case "section":
      return "resume";
  }
}

/** The word a tab shows beside its name while its job runs. Pure. */
export function jobWord(kind: AdvisorJob["kind"]): string {
  switch (jobTab(kind)) {
    case "gaps":
      return "preparing…";
    case "plan":
      return "drafting…";
    case "resume":
      return "writing…";
  }
}

const TITLES: Record<AdvisorJob["kind"], string> = {
  questions: "Writing your follow-up questions…",
  own_posting_evaluation: "Reading and scoring your role…",
  gap_plan: "Drafting your gap plan…",
  resume: "Writing your résumé…",
  section: "Filling the new section…",
};

const STAGES: Record<string, string> = {
  reading: "Reading your evidence and what this role asks for.",
  writing: "Your model is writing.",
  drafting: "Your model is drafting the plan.",
  checking: "Checking every line against your evidence.",
  saving: "Saving it as a new version.",
  reading_file: "Reading the file you uploaded.",
  reading_requirements: "Reading what the role asks for.",
  scoring: "Scoring your fit to it.",
  working_out_fit: "Working out your fit.",
};

/** The card's status line, from the stage the job has reached. Pure. */
export function jobStatusLine(job: AdvisorJob): string {
  return (job.stage && STAGES[job.stage]) || "Queued — starting in a moment.";
}

/** "Writing your résumé · 50%". Pure. */
export function jobSummary(job: AdvisorJob): string {
  return `${TITLES[job.kind].replace(/…$/, "")} · ${Math.round(job.progress * 100)}%`;
}

/** The jobs running for one Target. Pure. */
export function jobsFor(
  activity: Activity | null,
  ref: TargetRef,
): AdvisorJob[] {
  return (activity?.advisor_jobs ?? []).filter((job) =>
    sameTarget(job.target, ref),
  );
}

/** Where a job is cancelled. Pure. */
export function cancelPath(job: AdvisorJob): string {
  switch (job.kind) {
    case "questions":
      return `/gap-question-sets/${job.id}/cancel`;
    case "gap_plan":
      return `/gap-plans/${job.id}/cancel`;
    case "resume":
    case "section":
      return `/tailored-resumes/${job.id}/cancel`;
    case "own_posting_evaluation":
      return `/own-postings/${job.target.private_job_posting_id}/cancel`;
  }
}

const TAB_NAMES: Record<Exclude<AdvisorTab, "own">, string> = {
  gaps: "Fill the gap",
  plan: "Gap plan",
  resume: "Résumé",
};

/** A spinning ring, for a tab or a card whose job is running. */
export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

/**
 * The slim card a tab shows while its job runs (ADR 0042): what is happening,
 * how far it is, what it costs, and Cancel. The other tabs stay usable, and
 * the card links to them.
 */
export function AdvisorJobCard({
  job,
  onSwitch,
  onCancelled,
}: {
  job: AdvisorJob;
  onSwitch: (tab: Exclude<AdvisorTab, "own">) => void;
  onCancelled: () => void;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const here = jobTab(job.kind);
  const others = (["gaps", "plan", "resume"] as const).filter(
    (t) => t !== here,
  );
  const percent = Math.round(job.progress * 100);

  async function cancel() {
    setCancelling(true);
    setError(null);
    try {
      await api.post(cancelPath(job));
      onCancelled();
    } catch (caught) {
      setError(messageOf(caught));
      setCancelling(false);
    }
  }

  return (
    <div
      className="panel advisor-job"
      role="status"
      aria-label={TITLES[job.kind]}
    >
      <div className="row" style={{ gap: 10, alignItems: "center" }}>
        <Spinner />
        <h3 style={{ margin: 0 }}>{TITLES[job.kind]}</h3>
      </div>
      <p className="subcopy" style={{ margin: "8px 0 12px" }}>
        {jobStatusLine(job)} Usually under a minute.
      </p>
      <div
        className="progress"
        role="progressbar"
        aria-label="Progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <p className="subcopy" style={{ fontSize: 13, marginTop: 12 }}>
        You can keep working while this runs: switch to{" "}
        <button
          type="button"
          className="link-button"
          onClick={() => onSwitch(others[0]!)}
        >
          {TAB_NAMES[others[0]!]}
        </button>{" "}
        or{" "}
        <button
          type="button"
          className="link-button"
          onClick={() => onSwitch(others[1]!)}
        >
          {TAB_NAMES[others[1]!]}
        </button>
        . The {TAB_NAMES[here]} tab shows a spinner until it&apos;s ready.
      </p>
      <div
        className="row-between"
        style={{ marginTop: 12, gap: 10, flexWrap: "wrap" }}
      >
        <span className="muted" style={{ fontSize: 13 }}>
          {job.estimated_cost_usd !== null
            ? `About $${Number(job.estimated_cost_usd).toFixed(2)} on your key`
            : "On your key"}
        </span>
        <Button variant="ghost" busy={cancelling} onClick={() => void cancel()}>
          Cancel
        </Button>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
        Cancel stops it before the next call; a call already sent is still
        charged.
      </p>
      {error && <ErrorNote error={error} />}
    </div>
  );
}

/** The corner notice on the other tabs: "Writing your résumé · 50% · View". */
export function AdvisorJobNotice({
  job,
  onView,
}: {
  job: AdvisorJob;
  onView: () => void;
}) {
  return (
    <div className="advisor-job-notice" role="status">
      <Spinner />
      <span>{jobSummary(job)}</span>
      <span aria-hidden="true">·</span>
      <button type="button" className="link-button" onClick={onView}>
        View
      </button>
    </div>
  );
}
