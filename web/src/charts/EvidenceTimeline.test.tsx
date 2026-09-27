import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Evidence } from "../api/types";
import { EvidenceTimeline } from "./EvidenceTimeline";
import { formatDate, formatMonth } from "./timeline";

const TODAY = "2026-09-27";
// The viewer's locale decides how a date reads, so tests ask the same way.
const WEEK = `Week of ${formatDate("2026-05-11")}`;
const DAY = formatDate("2026-05-12");

let next = 0;
function fact(overrides: Partial<Evidence>): Evidence {
  next += 1;
  return {
    id: `e${next}`,
    source: "github",
    reference: `GitHub · acme/ledger#${next}`,
    fact: `Pull request ${next}`,
    observed_on: "2026-05-12",
    confidence: 0.8,
    granularity: "item",
    tally: null,
    subject: null,
    ...overrides,
  };
}

/** Enough dated work for the grid rather than the sparse dot strip. */
function busyYear(): Evidence[] {
  return Array.from({ length: 10 }, (_, i) =>
    fact({ observed_on: `2026-0${1 + (i % 8)}-1${i % 3}` }),
  );
}

describe("EvidenceTimeline", () => {
  it("lists a week's pull requests when its cell is clicked", async () => {
    const onSelect = vi.fn();
    const inWeek = [
      fact({ observed_on: "2026-05-12" }),
      fact({ observed_on: "2026-05-14" }),
    ];
    render(
      <EvidenceTimeline
        facts={[...busyYear(), ...inWeek]}
        today={TODAY}
        onSelect={onSelect}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", {
        name: new RegExp(`^${WEEK}: \\d+ pull requests`),
      }),
    );

    const [selection] = onSelect.mock.calls[0] as [
      { key: string; ids: string[] },
    ];
    expect(selection.key).toBe("github:2026-05-11");
    expect(selection.ids).toEqual(
      expect.arrayContaining(inWeek.map((f) => f.id)),
    );
  });

  it("clicking the chosen week again shows everything", async () => {
    const onSelect = vi.fn();
    render(
      <EvidenceTimeline
        facts={busyYear()}
        today={TODAY}
        selectedKey="github:2026-05-11"
        onSelect={onSelect}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: new RegExp(`^${WEEK}`) }),
    );
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("draws a dot per pull request when there is too little for a grid", () => {
    render(
      <EvidenceTimeline
        facts={[
          fact({ observed_on: "2026-05-12", fact: "Split the ledger writer" }),
        ]}
        today={TODAY}
        onSelect={() => {}}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: new RegExp(`${DAY}: .*Split the ledger writer`),
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Week of/ }),
    ).not.toBeInTheDocument();
  });

  it("never plots a tally, and says what has no work date", () => {
    render(
      <EvidenceTimeline
        facts={[
          fact({}),
          fact({
            granularity: "summary",
            fact: "12 merged pull requests in acme/ledger.",
          }),
          fact({ source: "resume", observed_on: null }),
          fact({ source: "resume", observed_on: null }),
        ]}
        today={TODAY}
        onSelect={() => {}}
      />,
    );
    expect(
      screen.getAllByRole("button", { name: new RegExp(`^${DAY}: `) }),
    ).toHaveLength(1);
    expect(screen.getByText(/2 facts have no work date/)).toBeInTheDocument();
  });

  it("says Jira dates arrive at the next sync for issues synced without them", () => {
    render(
      <EvidenceTimeline
        facts={[
          fact({}),
          fact({
            source: "jira",
            reference: "Jira · PAY-1",
            observed_on: null,
          }),
        ]}
        today={TODAY}
        onSelect={() => {}}
      />,
    );
    expect(
      screen.getByText("Dates arrive at your next Jira sync."),
    ).toBeInTheDocument();
  });

  it("offers older work, and shows it under Everything", async () => {
    render(
      <EvidenceTimeline
        facts={[
          fact({}),
          fact({ observed_on: "2024-03-05", fact: "An old one" }),
        ]}
        today={TODAY}
        onSelect={() => {}}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /An old one/ }),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Show 1 fact from earlier" }),
    );

    expect(
      screen.getByRole("button", { name: /An old one/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Everything" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("gives screen readers the counts per month", () => {
    render(
      <EvidenceTimeline facts={busyYear()} today={TODAY} onSelect={() => {}} />,
    );
    const table = screen.getByRole("table", { name: "Dated work per month" });
    expect(table).toHaveTextContent("GitHub PRs");
    expect(table).toHaveTextContent(formatMonth("2026-05"));
  });
});
