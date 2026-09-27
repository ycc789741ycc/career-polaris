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
      focus: { kind: "role" as const, id: "r1" },
    };
    expect(hashFor(place)).toBe("#/advisor/resume?role=r1");
    expect(placeFromHash(hashFor(place))).toEqual(place);
    expect(placeFromHash("#/roles?jd=j1")).toEqual({
      screen: "roles",
      tab: "plan",
      focus: { kind: "jd", id: "j1" },
    });
  });

  it("lands on the first screen for an empty or unknown hash", () => {
    expect(placeFromHash("").screen).toBe(DEFAULT_SCREEN);
    expect(placeFromHash("#/nowhere").screen).toBe(DEFAULT_SCREEN);
    expect(placeFromHash("#/plan").screen).toBe(DEFAULT_SCREEN);
  });

  it("opens the plan tab, with nothing selected, when the hash says neither", () => {
    expect(placeFromHash("#/advisor")).toEqual({
      screen: "advisor",
      tab: "plan",
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
