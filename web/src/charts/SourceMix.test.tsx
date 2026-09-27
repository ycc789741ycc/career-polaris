import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Evidence } from "../api/types";
import { SourceMix, sourceShares } from "./SourceMix";

function facts(source: string, count: number): Evidence[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `${source}-${i}`,
    source,
    reference: source,
    fact: "A fact",
    observed_on: null,
    confidence: 0.8,
    granularity: "item",
    tally: null,
    subject: null,
  }));
}

describe("SourceMix", () => {
  it("orders sources the same way on every chart", () => {
    const shares = sourceShares([
      ...facts("resume", 2),
      ...facts("self_reported", 1),
      ...facts("jira", 3),
      ...facts("github", 4),
    ]);
    expect(shares.map((s) => s.source)).toEqual([
      "github",
      "jira",
      "resume",
      "self_reported",
    ]);
  });

  it("gives whole percents that add up to exactly 100", () => {
    const shares = sourceShares([
      ...facts("github", 1),
      ...facts("jira", 1),
      ...facts("resume", 1),
    ]);
    expect(shares.map((s) => s.percent)).toEqual([34, 33, 33]);
  });

  it("describes the split in words, not just colour", () => {
    render(
      <SourceMix facts={[...facts("github", 3), ...facts("resume", 1)]} />,
    );
    expect(
      screen.getByRole("img", {
        name: "Facts by source: GitHub 3 (75%), Résumé 1 (25%)",
      }),
    ).toBeInTheDocument();
  });

  it("draws nothing when there is nothing to split", () => {
    const { container } = render(<SourceMix facts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
