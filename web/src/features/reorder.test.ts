import { describe, expect, it } from "vitest";
import { getKeyStep, getMoved } from "./reorder";

describe("moving in a list", () => {
  it("puts the item where it is dropped", () => {
    expect(getMoved(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);
    expect(getMoved(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
  });

  it("leaves the list alone for a move out of range", () => {
    expect(getMoved(["a", "b"], 0, 5)).toEqual(["a", "b"]);
    expect(getMoved(["a", "b"], -1, 0)).toEqual(["a", "b"]);
  });

  it("reads the arrow keys as one step, and nothing else as a move", () => {
    expect(getKeyStep({ key: "ArrowUp" })).toBe(-1);
    expect(getKeyStep({ key: "ArrowDown" })).toBe(1);
    expect(getKeyStep({ key: "Enter" })).toBeNull();
  });
});
