import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Assessment } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { Strengths } from "./Strengths";
import { page } from "../test/page";

function assessment(overrides: Partial<Assessment>): Assessment {
  return {
    id: "a1",
    profile_version: 2,
    is_out_of_date: false,
    model_id: "claude-opus-5",
    template_version: "skill_assessment@v1",
    created_at: "2026-09-27T09:00:00Z",
    dimensions: [
      {
        key: "api",
        name: "API design",
        short_name: "APIs",
        score: 70,
        confidence: 0.8,
        read: "Solid",
        evidence_ids: [],
        needs_more_evidence: false,
      },
    ],
    ...overrides,
  };
}

function dimension(
  overrides: Partial<Assessment["dimensions"][number]>,
): Assessment["dimensions"][number] {
  return {
    key: "api",
    name: "API design",
    short_name: "APIs",
    score: 70,
    confidence: 0.8,
    read: "Solid",
    evidence_ids: [],
    needs_more_evidence: false,
    ...overrides,
  };
}

function serve(latest: Assessment) {
  const routes: Record<string, unknown> = {
    "/assessments/latest": latest,
    "/evidence": page([]),
  };
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input).replace("http://api.test/api/v1", "");
    return new Response(JSON.stringify(routes[url] ?? null), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function renderStrengths() {
  const shell = {
    status: { me: null, credential: null, openQuestions: 0, confidence: 0 },
    navigate: vi.fn(),
  } as unknown as Shell;
  render(
    <ShellContext.Provider value={shell}>
      <Strengths />
    </ShellContext.Provider>,
  );
}

describe("Strengths", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("says the report is out of date once the evidence has changed", async () => {
    serve(assessment({ is_out_of_date: true }));
    renderStrengths();

    expect(
      await screen.findByText(/Out of date: your evidence has changed/),
    ).toBeInTheDocument();
  });

  it("says nothing while the report matches the evidence", async () => {
    serve(assessment({}));
    renderStrengths();

    expect(await screen.findByText(/Profile v2/)).toBeInTheDocument();
    expect(screen.queryByText(/Out of date/)).not.toBeInTheDocument();
  });

  // The journey runs 01 → 04; the role map reclusters and rescores as the
  // market moves, so it must not reach back and reshape this report.
  it("reads nothing from the role map", async () => {
    const fetch = serve(assessment({}));
    renderStrengths();

    expect(await screen.findByText(/Profile v2/)).toBeInTheDocument();
    const paths = fetch.mock.calls.map(([input]) => String(input));
    expect(paths.some((path) => /\/(fits|roles)\b/.test(path))).toBe(false);
    expect(screen.queryByText(/Compared against/)).not.toBeInTheDocument();

    expect(
      screen.queryByRole("button", { name: "Ranked ledger" }),
    ).not.toBeInTheDocument();
  });

  it("explains a score by its confidence, and says when evidence is thin", async () => {
    serve(
      assessment({
        dimensions: [
          dimension({
            key: "api",
            name: "API design",
            confidence: 0.8,
            evidence_ids: ["e1", "e2"],
          }),
          dimension({
            key: "tests",
            name: "Testing",
            confidence: 0.3,
            evidence_ids: ["e1"],
            needs_more_evidence: true,
          }),
        ],
      }),
    );
    renderStrengths();

    // The least certain dimension is the one shown first.
    expect(
      await screen.findByRole("heading", { name: "Testing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Confidence in Testing" }),
    ).toHaveAttribute("aria-valuenow", "30");
    expect(
      screen.getByText(/Thin evidence: this score rests on 1 fact/),
    ).toBeInTheDocument();

    const list = screen.getByRole("list", {
      name: "Dimensions, least certain first",
    });
    fireEvent.click(within(list).getByRole("button", { name: /^API design/ }));
    expect(
      screen.getByRole("heading", { name: "API design" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Well supported: backed by 2 facts/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Thin evidence/)).not.toBeInTheDocument();
  });

  it("lists every dimension least certain first", async () => {
    serve(
      assessment({
        dimensions: [
          dimension({ key: "a", name: "APIs", confidence: 0.9 }),
          dimension({
            key: "b",
            name: "Builds",
            confidence: 0.2,
            needs_more_evidence: true,
          }),
          dimension({ key: "c", name: "Caching", confidence: 0.6 }),
        ],
      }),
    );
    renderStrengths();

    const list = await screen.findByRole("list", {
      name: "Dimensions, least certain first",
    });
    expect(
      within(list)
        .getAllByRole("button")
        .map((row) => row.textContent),
    ).toEqual(["Builds⚠ 20% sure", "Caching60% sure", "APIs90% sure"]);
  });
});
