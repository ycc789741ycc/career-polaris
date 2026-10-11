import type { ReactNode } from "react";
import type { PlanSummary, QuestionSet, ResumeSummary } from "../api/types";
import { Button, EmptyState } from "../components/ui";
import type { AdvisorTab } from "../shell/navigation";
import { type AdvisorJob, jobWord, Spinner } from "./AdvisorJobs";
import { type AdvisorTarget, sameTarget } from "./target";

type Step = Exclude<AdvisorTab, "own">;

/** How a step's note reads: still to do, done, or done out of order. */
export type StepTone = "todo" | "done" | "warn";

export type StepNote = { text: string; tone: StepTone };

/**
 * Where Fill the gap stands for one Target, from its current question set:
 * nothing asked yet, being written, failed, asked but not submitted, or
 * submitted. Only `submitted` counts as filled. Pure.
 */
export type GapFillState =
  | { kind: "none" }
  | { kind: "writing" }
  | { kind: "failed" }
  | { kind: "unsubmitted"; questionCount: number }
  | { kind: "submitted"; answeredCount: number; questionCount: number };

export function getGapFillState(set: QuestionSet | null): GapFillState {
  if (!set || set.status === "superseded") return { kind: "none" };
  if (set.status === "writing") return { kind: "writing" };
  if (set.status === "failed") return { kind: "failed" };
  if (set.submitted_at === null)
    return { kind: "unsubmitted", questionCount: set.questions.length };
  return {
    kind: "submitted",
    answeredCount: set.questions.filter((q) => q.evidence_id).length,
    questionCount: set.questions.length,
  };
}

/**
 * The line under each step: Fill the gap's progress, and for the plan and the
 * résumé the latest version for this Target, or a warning that the gap is not
 * filled yet. A running job's word wins. Pure.
 */
export function getStepNotes({
  gapFill,
  target,
  plans,
  resumes,
}: {
  gapFill: GapFillState;
  target: AdvisorTarget;
  plans: PlanSummary[];
  resumes: ResumeSummary[];
}): Record<Step, StepNote> {
  const isFilled = gapFill.kind === "submitted";
  const plan = plans.find((p) => sameTarget(p.target, target.ref));
  const resume = resumes.find((r) => sameTarget(r.target, target.ref));
  const later = (version: number | null | undefined): StepNote =>
    version != null
      ? { text: `v${version}`, tone: isFilled ? "done" : "warn" }
      : isFilled
        ? { text: "Not yet", tone: "todo" }
        : { text: "Fill the gap first", tone: "warn" };
  return {
    gaps: getGapNote(gapFill),
    plan: later(plan?.status === "ready" ? plan.version : null),
    resume: later(resume?.latest_version),
  };
}

function getGapNote(gapFill: GapFillState): StepNote {
  switch (gapFill.kind) {
    case "none":
      return { text: "Start here", tone: "todo" };
    case "writing":
      return { text: "Writing questions…", tone: "todo" };
    case "failed":
      return { text: "Didn't finish", tone: "warn" };
    case "unsubmitted":
      return {
        text: `${gapFill.questionCount} ${gapFill.questionCount === 1 ? "question" : "questions"} to answer`,
        tone: "todo",
      };
    case "submitted":
      return {
        text: `✓ ${gapFill.answeredCount} of ${gapFill.questionCount} answered`,
        tone: "done",
      };
  }
}

/**
 * The Advisor's three steps: Fill the gap first, then either the gap plan or
 * the résumé. Each says where it stands; a step whose job runs says so with a
 * spinner. Every step stays clickable — the plan and the résumé warn, they do
 * not lock.
 */
export function AdvisorSteps({
  tab,
  notes,
  jobOn,
  onPick,
}: {
  tab: Step;
  notes: Record<Step, StepNote>;
  jobOn: (step: Step) => AdvisorJob | undefined;
  onPick: (step: Step) => void;
}) {
  const step = (which: Step, number: number, name: string) => {
    const job = jobOn(which);
    const note = notes[which];
    return (
      <button
        type="button"
        className="advisor-step"
        aria-pressed={tab === which}
        aria-label={name}
        aria-describedby={`advisor-step-${which}`}
        onClick={() => onPick(which)}
      >
        <span className="advisor-step-number" aria-hidden="true">
          {number}
        </span>
        <span className="advisor-step-text">
          <span className="advisor-step-name">{name}</span>
          <span
            id={`advisor-step-${which}`}
            className={`advisor-step-note advisor-step-${job ? "todo" : note.tone}`}
          >
            {job ? (
              <span className="step-busy">
                <Spinner /> {jobWord(job.kind)}
              </span>
            ) : (
              <>
                {note.tone === "warn" && "⚠ "}
                {note.text}
              </>
            )}
          </span>
        </span>
      </button>
    );
  };
  return (
    <div className="advisor-stepper" role="group" aria-label="Advisor tabs">
      {step("gaps", 1, "Fill the gap")}
      <span className="advisor-stepper-then" aria-hidden="true">
        → then, either
      </span>
      {step("plan", 2, "Gap plan")}
      {step("resume", 3, "Résumé")}
    </div>
  );
}

/**
 * What the plan or résumé tab shows before Fill the gap is submitted and
 * nothing is drafted for the Target yet: go fill it, or draft anyway.
 */
export function FillGapFirst({
  tab,
  gapFill,
  target,
  onFill,
  onDraftAnyway,
}: {
  tab: "plan" | "resume";
  gapFill: GapFillState;
  target: AdvisorTarget;
  onFill: () => void;
  onDraftAnyway: () => void;
}) {
  const what = tab === "plan" ? "A gap plan" : "A résumé";
  return (
    <EmptyState title="Fill the gap first">
      {getGapFillLine(gapFill, target.label)} {what} written now sees only your
      sources, so every gap stays a gap. Your answers become evidence it can
      cite.
      <span
        className="row"
        style={{ marginTop: 14, gap: 10, justifyContent: "center" }}
      >
        <Button onClick={onFill}>Go to Fill the gap</Button>
        <Button variant="ghost" onClick={onDraftAnyway}>
          {tab === "plan" ? "Draft anyway" : "Write anyway"}
        </Button>
      </span>
    </EmptyState>
  );
}

/**
 * The slim reminder above a plan or résumé while Fill the gap is not
 * submitted: what is here cannot use answers that are not in yet.
 */
export function FillGapBanner({ onFill }: { onFill: () => void }) {
  return (
    <div
      className="panel panel-tight row-between"
      role="status"
      aria-label="Fill the gap first"
      style={{ marginBottom: 16, flexWrap: "wrap", gap: 12 }}
    >
      <div style={{ minWidth: 0 }}>
        <strong>⚠ Your gap answers aren't in yet</strong>
        <div className="muted" style={{ fontSize: 12.5 }}>
          What is written here can't use them. Fill the gap, then regenerate.
        </div>
      </div>
      <Button variant="secondary" onClick={onFill}>
        Go to Fill the gap
      </Button>
    </div>
  );
}

function getGapFillLine(gapFill: GapFillState, label: string): ReactNode {
  switch (gapFill.kind) {
    case "writing":
      return <>The gap questions for {label} are still being written.</>;
    case "unsubmitted":
      return <>You haven't submitted your answers for {label} yet.</>;
    default:
      return <>You haven't analysed the gaps for {label} yet.</>;
  }
}
