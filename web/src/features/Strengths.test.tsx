import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Assessment } from "../api/types";
import type { Activity } from "../api/types";
import { ActivityContext } from "../shell/activity";
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
    profile_confidence: 0.72,
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
    "/assessments/cost-estimate": {
      cost_usd: "0.60",
      model_id: "claude-opus-5",
      input_tokens: 1200,
      rate_is_published: true,
      analysis_cost_usd: "0.10",
      role_map_cost_usd: "0.40",
      fits_cost_usd: "0.10",
      max_roles: 10,
    },
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

function renderStrengths(activity: Activity | null = null) {
  const shell = {
    status: { me: null, credential: null },
    navigate: vi.fn(),
    setHeading: vi.fn(),
  } as unknown as Shell;
  render(
    <ShellContext.Provider value={shell}>
      <ActivityContext.Provider
        value={{
          activity,
          refresh: async () => {},
          settled: { sources: 0, analysis: 0, roleMap: 0 },
        }}
      >
        <Strengths />
      </ActivityContext.Provider>
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

    expect(
      await screen.findByText(/^Analysed 27 Sep 2026 on claude-opus-5/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Out of date/)).not.toBeInTheDocument();
  });

  // The journey runs 01 → 04; the role map reclusters and rescores as the
  // market moves, so it must not reach back and reshape this report.
  it("reads nothing from the role map", async () => {
    const fetch = serve(assessment({}));
    renderStrengths();

    expect(
      await screen.findByText(/^Analysed 27 Sep 2026 on claude-opus-5/),
    ).toBeInTheDocument();
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

  it("waits for a résumé still parsing before it offers an analysis", async () => {
    serve(assessment({}));
    renderStrengths({
      syncing: [],
      parsing: [{ label: "cv.pdf", started_at: "2026-09-28T09:00:00Z" }],
      analysis: null,
      role_map: null,
    });

    expect(
      await screen.findByRole("button", { name: "Re-analyse" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Waiting for your sources to finish/),
    ).toBeInTheDocument();
  });

  it("offers no second analysis while one runs, and says why the last one failed", async () => {
    serve(assessment({}));
    renderStrengths({
      syncing: [],
      parsing: [],
      analysis: {
        status: "failed",
        started_at: "2026-09-28T09:00:00Z",
        finished_at: "2026-09-28T09:01:00Z",
        error: { code: "ai_budget_exceeded", message: "The budget is spent" },
      },
      role_map: null,
    });

    expect(
      await screen.findByText(
        /The last analysis did not finish: The budget is spent/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-analyse" })).toBeEnabled();
  });

  it("prices the analysis with the role map and fits after it, in one confirmation", async () => {
    serve(assessment({}));
    renderStrengths();

    fireEvent.click(await screen.findByRole("button", { name: "Re-analyse" }));

    const dialog = await screen.findByText(/for the analysis/);
    expect(dialog).toHaveTextContent(
      "$0.10 for the analysis, at most $0.40 for the role map built after it, up to 10 roles, and at most $0.10 for scoring your fit against them.",
    );
    expect(dialog).toHaveTextContent("$0.60");
  });

  it("puts Re-analyse first, then when and on what it ran", async () => {
    serve(assessment({}));
    renderStrengths();

    const button = await screen.findByRole("button", { name: "Re-analyse" });
    const line = await screen.findByText(/^Analysed 27 Sep 2026/);
    expect(button.compareDocumentPosition(line)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("shows the analysis's own profile confidence next to Re-analyse", async () => {
    serve(assessment({ profile_confidence: 0.72 }));
    renderStrengths();

    expect(
      await screen.findByRole("progressbar", {
        name: /Profile confidence: how well the evidence supports these scores/,
      }),
    ).toHaveAttribute("aria-valuenow", "72");
  });

  it("shows the analysing screen while an analysis runs, and the last report on request", async () => {
    serve(assessment({}));
    renderStrengths({
      syncing: [],
      parsing: [],
      analysis: {
        status: "running",
        started_at: "2026-09-28T09:00:00Z",
        finished_at: null,
        error: null,
      },
      role_map: null,
    });

    const progress = await screen.findByRole("region", {
      name: "Strength analysis progress",
    });
    expect(
      within(progress)
        .getAllByRole("listitem")
        .map((step) => step.lastChild?.textContent),
    ).toEqual(["Done", "Running", "Waiting"]);
    expect(
      screen.queryByRole("button", { name: /Re-analyse|Analysing/ }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "See your last report" }),
    );
    expect(
      await screen.findByRole("button", { name: "Analysing…" }),
    ).toBeDisabled();
  });
});
