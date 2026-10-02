import { describe, expect, it } from "vitest";
import type { SalaryBand } from "../api/types";
import { salaryAxisTitle } from "../charts/RoleMap";
import { annualPay, payRange, pickBand } from "./Roles";

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

describe("salary wording", () => {
  it("writes a range in thousands of its currency, as a year's pay", () => {
    expect(payRange("EUR", 79_600, 105_200)).toBe("EUR 80k–105k");
    expect(annualPay("USD", 139_200, 235_200)).toBe("USD 139k–235k a year");
  });

  it("names the axis's currency only when every band shares it", () => {
    expect(salaryAxisTitle(["EUR", "EUR"])).toBe(
      "Annual salary in EUR, midpoint of the band",
    );
    expect(salaryAxisTitle(["EUR"])).toBe(
      "Annual salary in EUR, midpoint of the band",
    );
    expect(salaryAxisTitle(["EUR", "USD"])).toBe(
      "Annual salary, midpoint of each band, in its own currency",
    );
    expect(salaryAxisTitle([])).toBe(
      "Annual salary, midpoint of each band, in its own currency",
    );
  });
});
