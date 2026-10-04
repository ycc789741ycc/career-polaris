import { describe, expect, it } from "vitest";
import { postedLabel } from "./time";

describe("how long ago a posting went up", () => {
  const now = new Date(2026, 9, 4, 15, 0);

  it.each([
    ["2026-10-04", "today"],
    ["2026-10-03", "yesterday"],
    ["2026-09-30", "4 days ago"],
    ["2026-09-27", "1 week ago"],
    ["2026-09-13", "3 weeks ago"],
    ["2026-08-01", "1 Aug 2026"],
  ])("reads %s as %s", (day, label) => {
    expect(postedLabel(day, now)).toBe(label);
  });

  it("never says a posting is from the future", () => {
    expect(postedLabel("2026-10-06", now)).toBe("today");
  });
});
