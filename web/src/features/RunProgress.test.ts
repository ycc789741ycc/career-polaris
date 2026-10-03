import { describe, expect, it } from "vitest";
import type { Activity, Assessment, Evidence } from "../api/types";
import {
  factsLine,
  getAnalysisSteps,
  getBuildSteps,
  isMapComing,
} from "./RunProgress";

const running = {
  started_at: "2026-09-28T09:00:00Z",
  finished_at: null,
  error: null,
};

function activity(overrides: Partial<Activity>): Activity {
  return {
    syncing: [],
    advisor_jobs: [],
    parsing: [],
    analysis: null,
    role_map: null,
    ...overrides,
  };
}

function fact(source: string): Evidence {
  return { id: source, source, reference: "", fact: "" } as Evidence;
}

const assessment = {
  dimensions: [{}, {}, {}],
  profile_confidence: 0.72,
} as unknown as Assessment;

function states(steps: { state: string }[]): string[] {
  return steps.map((step) => step.state);
}

describe("the analysis's steps", () => {
  it("has read the facts, scores on the model, and builds the map next", () => {
    const steps = getAnalysisSteps([fact("github"), fact("resume")], "m");
    expect(states(steps)).toEqual(["done", "running", "waiting"]);
    expect(steps[1]?.label).toBe("Scoring your strengths on m");
  });

  it("counts the facts by source, in the chart's order", () => {
    expect(
      factsLine([
        fact("user_answer"),
        fact("github"),
        fact("github"),
        fact("resume"),
      ]),
    ).toBe("4 facts · GitHub 2, Résumé 1, Your answers 1");
    expect(factsLine([])).toBe("0 facts");
  });
});

describe("the build's steps", () => {
  const args = {
    assessment,
    scope: "12 open postings in Berlin",
    maxRoles: 10,
  };

  it("waits on an analysis that is still running", () => {
    const steps = getBuildSteps({
      ...args,
      activity: activity({ analysis: { status: "running", ...running } }),
    });
    expect(states(steps)).toEqual(["running", "waiting", "waiting"]);
  });

  it("searches the market while the build waits for it", () => {
    const steps = getBuildSteps({
      ...args,
      activity: activity({
        role_map: { status: "waiting", waiting_for: "market", ...running },
      }),
    });
    expect(states(steps)).toEqual(["done", "running", "waiting"]);
    expect(steps[0]?.detail).toBe("3 dimensions · profile confidence 72%");
    expect(steps[1]?.detail).toBe("12 open postings in Berlin");
  });

  it("picks and scores the roles once the build runs", () => {
    const steps = getBuildSteps({
      ...args,
      activity: activity({ role_map: { status: "running", ...running } }),
    });
    expect(states(steps)).toEqual(["done", "done", "running"]);
    expect(steps[2]?.label).toBe(
      "Pick your 10 best-fit roles and score your fit",
    );
  });
});

describe("whether a map is on its way", () => {
  it("is while a build runs or waits, or an analysis runs", () => {
    expect(isMapComing(null)).toBe(false);
    expect(isMapComing(activity({}))).toBe(false);
    expect(
      isMapComing(activity({ analysis: { status: "running", ...running } })),
    ).toBe(true);
    expect(
      isMapComing(activity({ role_map: { status: "waiting", ...running } })),
    ).toBe(true);
    expect(
      isMapComing(
        activity({
          role_map: {
            status: "failed",
            ...running,
            error: { code: "x", message: "y" },
          },
        }),
      ),
    ).toBe(false);
  });
});
