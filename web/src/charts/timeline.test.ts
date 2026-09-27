import { describe, expect, it } from "vitest";
import type { Evidence } from "../api/types";
import { buildTimeline, heatLevel, position, weekStart } from "./timeline";

// A Sunday, so "this week" began on Monday 21 September.
const TODAY = "2026-09-27";

function fact(overrides: Partial<Evidence>): Evidence {
  return {
    id: Math.random().toString(36).slice(2),
    source: "github",
    reference: "GitHub · acme/ledger#1",
    fact: "Split the ledger writer",
    observed_on: "2026-05-12",
    confidence: 0.8,
    granularity: "item",
    tally: null,
    subject: null,
    ...overrides,
  };
}

function weekOf(
  timeline: ReturnType<typeof buildTimeline>,
  source: string,
  start: string,
) {
  const row = timeline.rows.find((r) => r.source === source);
  return row?.weeks.find((w) => w.start === start)?.facts ?? [];
}

describe("evidence timeline", () => {
  it("weeks start on Monday, in UTC", () => {
    expect(weekStart("2026-09-27")).toBe("2026-09-21");
    expect(weekStart("2026-09-21")).toBe("2026-09-21");
    expect(weekStart("2026-05-12")).toBe("2026-05-11");
  });

  it("shows the last 52 weeks, ending with this one", () => {
    const timeline = buildTimeline([], { today: TODAY, range: "year" });
    expect(timeline.weeks).toHaveLength(52);
    expect(timeline.weeks.at(-1)).toBe("2026-09-21");
    expect(timeline.weeks[0]).toBe("2025-09-29");
  });

  it("puts each pull request and issue in the week the work happened", () => {
    const timeline = buildTimeline(
      [
        fact({ observed_on: "2026-05-12" }),
        fact({ observed_on: "2026-05-14" }),
        fact({ source: "jira", observed_on: "2026-06-03" }),
      ],
      { today: TODAY, range: "year" },
    );
    expect(weekOf(timeline, "github", "2026-05-11")).toHaveLength(2);
    expect(weekOf(timeline, "jira", "2026-06-01")).toHaveLength(1);
    expect(timeline.rows.map((r) => r.total)).toEqual([2, 1]);
    expect(timeline.dated).toBe(3);
  });

  it("never counts a tally as one more piece of work", () => {
    const timeline = buildTimeline(
      [
        fact({}),
        fact({
          granularity: "summary",
          fact: "12 merged pull requests in acme/ledger.",
        }),
      ],
      { today: TODAY, range: "year" },
    );
    expect(timeline.dated).toBe(1);
    expect(timeline.undated).toBe(0);
  });

  it("counts résumé lines and answers as undated rather than dropping them", () => {
    const timeline = buildTimeline(
      [
        fact({ source: "resume", observed_on: null }),
        // An answer is dated the day it was given, not the day of the work.
        fact({ source: "self_reported", observed_on: "2026-09-20" }),
        fact({ source: "jira", observed_on: null }),
      ],
      { today: TODAY, range: "year" },
    );
    expect(timeline.dated).toBe(0);
    expect(timeline.undated).toBe(3);
  });

  it("keeps older work out of a year but shows it under everything", () => {
    const facts = [fact({ observed_on: "2024-03-05" }), fact({})];

    const year = buildTimeline(facts, { today: TODAY, range: "year" });
    expect(year.dated).toBe(1);
    expect(year.older).toBe(1);

    const all = buildTimeline(facts, { today: TODAY, range: "all" });
    expect(all.weeks[0]).toBe("2024-03-04");
    expect(all.dated).toBe(2);
    expect(all.older).toBe(0);
  });

  it("puts a date after today in this week rather than losing it", () => {
    const timeline = buildTimeline([fact({ observed_on: "2026-10-30" })], {
      today: TODAY,
      range: "year",
    });
    expect(weekOf(timeline, "github", "2026-09-21")).toHaveLength(1);
  });

  it("names the two busiest months, the more recent first on a tie", () => {
    const timeline = buildTimeline(
      [
        fact({ observed_on: "2026-01-05" }),
        fact({ observed_on: "2026-01-06" }),
        fact({ observed_on: "2026-05-12" }),
        fact({ observed_on: "2026-05-13" }),
        fact({ observed_on: "2026-07-01" }),
      ],
      { today: TODAY, range: "year" },
    );
    expect(timeline.busiestMonths).toEqual([
      { month: "2026-05", count: 2 },
      { month: "2026-01", count: 2 },
    ]);
  });

  it("shades by count: none, one, a few, four or more", () => {
    expect([0, 1, 2, 3, 4, 9].map(heatLevel)).toEqual([0, 1, 2, 2, 3, 3]);
  });

  it("places a day proportionally between two others", () => {
    expect(position("2026-01-11", "2026-01-01", "2026-01-21")).toBe(0.5);
    expect(position("2025-12-01", "2026-01-01", "2026-01-21")).toBe(0);
  });
});
