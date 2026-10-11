import { describe, expect, it } from "vitest";
import type { PlanSummary, QuestionSet, ResumeSummary } from "../api/types";
import { getGapFillState, getStepNotes } from "./AdvisorSteps";
import type { AdvisorTarget } from "./target";

const ref = {
  role_id: "r1",
  job_posting_id: null,
  private_job_posting_id: null,
};

const target: AdvisorTarget = {
  ref,
  label: "Backend Engineer",
  roleName: "Backend Engineer",
  company: null,
  location: null,
  postingTitle: null,
  url: null,
  creditedTo: null,
  fit: 70,
  band: null,
  isOwnPosting: false,
};

function set(overrides: Partial<QuestionSet> = {}): QuestionSet {
  return {
    id: "s1",
    target: ref,
    label: "Backend Engineer",
    status: "ready",
    gaps: [],
    questions: [
      {
        id: "q1",
        gap_key: "dim:incidents",
        text: "On call?",
        asked_because: "",
        answer_type: "choice",
        choices: ["Yes", "No"],
        evidence_id: "e1",
      },
      {
        id: "q2",
        gap_key: "dim:incidents",
        text: "Led one?",
        asked_because: "",
        answer_type: "free_text",
        choices: [],
        evidence_id: null,
      },
    ],
    model_id: null,
    error: null,
    created_at: "2026-10-01T09:00:00Z",
    submitted_at: null,
    ...overrides,
  };
}

const plan = (version: number): PlanSummary => ({
  id: "plan-1",
  target: ref,
  label: "Backend Engineer",
  version,
  status: "ready",
  error: null,
  model_id: null,
  created_at: "2026-10-01T09:00:00Z",
  drafted_at: "2026-10-01T09:00:00Z",
  progress: 0,
});

const resume = (version: number): ResumeSummary => ({
  id: "res-1",
  target: ref,
  label: "Backend Engineer",
  latest_version: version,
  status: "ready",
  error: null,
  created_at: "2026-10-01T09:00:00Z",
  updated_at: "2026-10-01T09:00:00Z",
});

describe("where Fill the gap stands", () => {
  it("is filled only once its answers are submitted", () => {
    expect(getGapFillState(null)).toEqual({ kind: "none" });
    expect(getGapFillState(set({ status: "superseded" }))).toEqual({
      kind: "none",
    });
    expect(getGapFillState(set({ status: "writing" }))).toEqual({
      kind: "writing",
    });
    expect(getGapFillState(set({ status: "failed" }))).toEqual({
      kind: "failed",
    });
    expect(getGapFillState(set())).toEqual({
      kind: "unsubmitted",
      questionCount: 2,
    });
    expect(
      getGapFillState(set({ submitted_at: "2026-10-02T09:00:00Z" })),
    ).toEqual({ kind: "submitted", answeredCount: 1, questionCount: 2 });
  });
});

describe("the line under each step", () => {
  it("starts at Fill the gap and warns on the plan and résumé until it is filled", () => {
    const notes = getStepNotes({
      gapFill: { kind: "none" },
      target,
      plans: [],
      resumes: [],
    });
    expect(notes.gaps).toEqual({ text: "Start here", tone: "todo" });
    expect(notes.plan).toEqual({ text: "Fill the gap first", tone: "warn" });
    expect(notes.resume).toEqual({ text: "Fill the gap first", tone: "warn" });
  });

  it("counts the answers and names the latest versions once it is filled", () => {
    const notes = getStepNotes({
      gapFill: { kind: "submitted", answeredCount: 6, questionCount: 8 },
      target,
      plans: [plan(2)],
      resumes: [],
    });
    expect(notes.gaps).toEqual({ text: "✓ 6 of 8 answered", tone: "done" });
    expect(notes.plan).toEqual({ text: "v2", tone: "done" });
    expect(notes.resume).toEqual({ text: "Not yet", tone: "todo" });
  });

  it("flags a version drafted before the gap was filled", () => {
    const notes = getStepNotes({
      gapFill: { kind: "unsubmitted", questionCount: 1 },
      target,
      plans: [],
      resumes: [resume(3)],
    });
    expect(notes.gaps).toEqual({ text: "1 question to answer", tone: "todo" });
    expect(notes.resume).toEqual({ text: "v3", tone: "warn" });
  });

  it("reads only this target's plan and résumé", () => {
    const other = { ...plan(4), target: { ...ref, role_id: "r9" } };
    const notes = getStepNotes({
      gapFill: { kind: "submitted", answeredCount: 1, questionCount: 1 },
      target,
      plans: [other],
      resumes: [],
    });
    expect(notes.plan).toEqual({ text: "Not yet", tone: "todo" });
  });
});
