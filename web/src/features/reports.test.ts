import { describe, expect, it } from "vitest";
import type { SalaryBand } from "../api/types";
import { pickBand } from "./Roles";

const band = (mid: number, is_confident: boolean): SalaryBand => ({
  low: mid - 10_000,
  mid,
  high: mid + 10_000,
  currency: "EUR",
  sample_size: is_confident ? 20 : 2,
  is_confident,
});

describe("salary band choice", () => {
  const bands = {
    Berlin: band(70_000, false),
    "Remote EU": band(80_000, true),
  };

  it("prefers a well-sampled band when no market is picked", () => {
    expect(pickBand(bands)?.mid).toBe(80_000);
  });

  it("uses the picked market's band, even a thin one", () => {
    expect(pickBand(bands, "Berlin")?.mid).toBe(70_000);
  });

  it("has nothing for a market the role has no band in", () => {
    expect(pickBand(bands, "Lisbon")).toBeNull();
    expect(pickBand({})).toBeNull();
  });
});
