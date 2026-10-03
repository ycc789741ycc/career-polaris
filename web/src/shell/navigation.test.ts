import { describe, expect, it } from "vitest";
import {
  DEFAULT_SCREEN,
  JOURNEY,
  hashFor,
  metaOf,
  placeFromHash,
} from "./navigation";

describe("screen navigation", () => {
  it("numbers the journey 01 to 04, ending with the Advisor", () => {
    expect(JOURNEY.map((item) => `${item.num} ${item.label}`)).toEqual([
      "01 Sources",
      "02 Strengths",
      "03 Role map",
      "04 Advisor",
    ]);
  });

  it("reads the screen back from the hash it wrote", () => {
    for (const item of [...JOURNEY.map((j) => j.id), "model" as const]) {
      expect(placeFromHash(hashFor({ screen: item })).screen).toBe(item);
    }
  });

  it("carries the Advisor's tab and the role map's selection", () => {
    const place = {
      screen: "advisor" as const,
      tab: "resume" as const,
      focus: { role: "r1" },
    };
    expect(hashFor(place)).toBe("#/advisor/resume?role=r1");
    expect(placeFromHash(hashFor(place))).toEqual(place);

    const opening = { ...place, focus: { role: "r1", opening: "p1" } };
    expect(hashFor(opening)).toBe("#/advisor/resume?role=r1&opening=p1");
    expect(placeFromHash(hashFor(opening))).toEqual(opening);
  });

  it("no longer reads a pasted JD from the hash: it is a role now", () => {
    expect(placeFromHash("#/roles?jd=j1").focus).toBeNull();
  });

  it("carries a posting of your own the Advisor is aimed at", () => {
    const place = {
      screen: "advisor" as const,
      tab: "plan" as const,
      focus: { posting: "j1" },
    };
    expect(hashFor(place)).toBe("#/advisor/plan?posting=j1");
    expect(placeFromHash(hashFor(place))).toEqual(place);
  });

  it("lands on the first screen for an empty or unknown hash", () => {
    expect(placeFromHash("").screen).toBe(DEFAULT_SCREEN);
    expect(placeFromHash("#/nowhere").screen).toBe(DEFAULT_SCREEN);
    expect(placeFromHash("#/plan").screen).toBe(DEFAULT_SCREEN);
  });

  it("opens Fill the gap first, with nothing selected, when the hash says neither", () => {
    expect(placeFromHash("#/advisor")).toEqual({
      screen: "advisor",
      tab: "gaps",
      focus: null,
    });
    expect(placeFromHash("#/advisor/elsewhere?who=x").focus).toBeNull();
  });

  it("sends an old link to the Questions screen to Sources, where they live now", () => {
    expect(placeFromHash("#/questions").screen).toBe("sources");
  });

  it("gives settings its own title outside the numbered journey", () => {
    expect(metaOf("model")).toMatchObject({
      title: "Bring your own model",
      kicker: "System configuration",
    });
    expect(metaOf("model").num).toBeUndefined();
  });
});

describe("the Advisor's tabs", () => {
  it("reads each tab back from the hash it wrote", () => {
    for (const tab of ["gaps", "plan", "resume", "own"] as const) {
      expect(placeFromHash(hashFor({ screen: "advisor", tab })).tab).toBe(tab);
    }
  });
});
