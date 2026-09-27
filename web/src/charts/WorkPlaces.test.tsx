import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Evidence } from "../api/types";
import { WorkPlaces, placeGroups } from "./WorkPlaces";

let next = 0;
function fact(overrides: Partial<Evidence>): Evidence {
  next += 1;
  return {
    id: `e${next}`,
    source: "github",
    reference: "GitHub · acme/ledger#1",
    fact: "Split the ledger writer",
    observed_on: "2026-05-12",
    confidence: 0.8,
    granularity: "item",
    tally: null,
    subject: "acme/ledger",
    ...overrides,
  };
}

function tally(source: string, subject: string, count: number): Evidence {
  return fact({ source, subject, granularity: "summary", tally: count });
}

describe("WorkPlaces", () => {
  it("bars each place by its tally, busiest first, one scale per source", () => {
    const groups = placeGroups([
      tally("github", "acme/web", 3),
      tally("github", "acme/ledger", 12),
      tally("jira", "PAY", 40),
    ]);
    expect(
      groups.map((g) => [g.source, g.places.map((p) => [p.subject, p.count])]),
    ).toEqual([
      [
        "github",
        [
          ["acme/ledger", 12],
          ["acme/web", 3],
        ],
      ],
      ["jira", [["PAY", 40]]],
    ]);
  });

  it("counts from the tally, not from the few items a sync kept", () => {
    const [github] = placeGroups([
      tally("github", "acme/ledger", 12),
      fact({}),
      fact({}),
    ]);
    expect(github?.places[0]?.count).toBe(12);
  });

  it("leaves out totals that belong to no place", () => {
    const groups = placeGroups([
      fact({ granularity: "summary", tally: 30, subject: null }),
    ]);
    expect(groups).toEqual([]);
  });

  it("picks a place's tally and every item in it", async () => {
    const onSelect = vi.fn();
    const ledger = tally("github", "acme/ledger", 12);
    const pr = fact({});
    const elsewhere = fact({ subject: "acme/web" });
    render(
      <WorkPlaces
        facts={[ledger, pr, elsewhere, tally("github", "acme/web", 1)]}
        onSelect={onSelect}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "acme/ledger: 12" }),
    );

    expect(onSelect).toHaveBeenCalledWith({
      key: "place:github:acme/ledger",
      label: "acme/ledger",
      ids: [ledger.id, pr.id],
    });
  });

  it("names what each group counts", () => {
    render(
      <WorkPlaces facts={[tally("jira", "PAY", 4)]} onSelect={() => {}} />,
    );
    const group = screen.getByRole("heading", {
      name: "Issues by Jira project",
    });
    expect(
      within(group.parentElement as HTMLElement).getByText("PAY"),
    ).toBeInTheDocument();
  });
});
