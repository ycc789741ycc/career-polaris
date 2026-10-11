import "@testing-library/jest-dom/vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Activity, RunStatus } from "../api/types";
import { ActivityBar, withoutOwnRuns } from "./ActivityBar";
import {
  ActivityProvider,
  describe as describeWork,
  getActivityLines,
  getOutcomeToast,
  useActivity,
} from "./activity";
import { ToastProvider } from "./toast";
import { AWAY, ONLINE } from "../test/activity";

const IDLE: Activity = {
  syncing: [],
  advisor_jobs: [],
  processing: ONLINE,
  parsing: [],
  analysis: null,
  role_map: null,
};

function run(
  status: RunStatus["status"],
  error: RunStatus["error"] = null,
): RunStatus {
  return {
    status,
    started_at: "2026-09-28T09:00:00Z",
    finished_at:
      status === "running" || status === "waiting"
        ? null
        : "2026-09-28T09:03:00Z",
    error,
  };
}

/** Serves each `/activity` answer in turn, then keeps repeating the last. */
function serve(...answers: Activity[]) {
  const fetch = vi.fn(async () => {
    const body = answers.length > 1 ? answers.shift() : answers[0];
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function Settled() {
  const { settled } = useActivity();
  return <p>analysis settled {settled.analysis}</p>;
}

function renderShell() {
  render(
    <ToastProvider>
      <ActivityProvider>
        <ActivityBar screen="sources" />
        <Settled />
      </ActivityProvider>
    </ToastProvider>,
  );
}

describe("what is running", () => {
  it("leads with the processing machine when it is away and work waits", () => {
    const lines = describeWork(
      { ...IDLE, analysis: run("running"), processing: AWAY },
      "claude-opus-5",
    );

    expect(lines).toEqual([
      "Waiting for the processing machine to come back",
      "Analysing your strengths on claude-opus-5",
    ]);
  });

  it("says nothing of the machine when nothing waits for it", () => {
    expect(
      describeWork({ ...IDLE, processing: AWAY }, "claude-opus-5"),
    ).toEqual([]);
  });

  it("says a build waits for the market search to come back", () => {
    const lines = describeWork(
      {
        ...IDLE,
        role_map: { ...run("waiting"), waiting_for: "market" },
        processing: { ...ONLINE, is_crawler_online: false },
      },
      "claude-opus-5",
    );

    expect(lines).toEqual([
      "Role map waiting for the market search to come back online",
    ]);
  });

  it("names every piece of work in journey order", () => {
    const lines = describeWork(
      {
        syncing: [{ label: "github", started_at: "2026-09-28T09:00:00Z" }],
        advisor_jobs: [],
        processing: ONLINE,
        parsing: [{ label: "cv.pdf", started_at: "2026-09-28T09:00:00Z" }],
        analysis: run("running"),
        role_map: run("waiting"),
      },
      "claude-opus-5",
    );

    expect(lines).toEqual([
      "Syncing GitHub",
      "Reading cv.pdf",
      "Analysing your strengths on claude-opus-5",
      "Role map waiting for the analysis to finish",
    ]);
  });

  it("says a build is searching the market rather than waiting", () => {
    expect(
      describeWork(
        { ...IDLE, role_map: { ...run("waiting"), waiting_for: "market" } },
        "m",
      ),
    ).toEqual(["Searching the market for your recommended roles"]);
  });

  it("says nothing once work has finished or failed", () => {
    expect(
      describeWork(
        { ...IDLE, analysis: run("ready"), role_map: run("failed") },
        "m",
      ),
    ).toEqual([]);
  });
});

describe("the running bar", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows while an analysis runs, then says it finished and lets pages reload", async () => {
    serve(
      { ...IDLE, analysis: run("running") },
      { ...IDLE, analysis: run("ready") },
    );
    renderShell();

    const bar = await screen.findByRole("status", { name: "Running now" });
    expect(bar).toHaveTextContent("Analysing your strengths on your model…");
    expect(screen.getByText("analysis settled 0")).toBeInTheDocument();

    expect(
      await screen.findByText("Analysis finished.", undefined, {
        timeout: 4000,
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: "Running now" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("analysis settled 1")).toBeInTheDocument();
  });

  it("says why a role map build failed", async () => {
    serve(
      { ...IDLE, role_map: run("running") },
      {
        ...IDLE,
        role_map: run("failed", {
          code: "stale",
          message: "It stopped responding",
        }),
      },
    );
    renderShell();

    expect(
      await screen.findByText(
        "Role map failed — It stopped responding",
        undefined,
        {
          timeout: 4000,
        },
      ),
    ).toBeInTheDocument();
  });

  it("asks once and stops when nothing is running", async () => {
    const fetch = serve(IDLE);
    renderShell();

    // Longer than one poll: a second ask would have happened by now.
    await act(() => new Promise((resolve) => setTimeout(resolve, 2500)));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("status", { name: "Running now" }),
    ).not.toBeInTheDocument();
  });
});

describe("the running bar on a screen with its own waiting screen", () => {
  const activity = {
    syncing: [{ label: "github", started_at: "2026-09-28T09:00:00Z" }],
    advisor_jobs: [],
    processing: ONLINE,
    parsing: [],
    analysis: {
      status: "running" as const,
      started_at: "2026-09-28T09:00:00Z",
      finished_at: null,
      error: null,
    },
    role_map: {
      status: "waiting" as const,
      waiting_for: "analysis" as const,
      started_at: "2026-09-28T09:00:00Z",
      finished_at: null,
      error: null,
    },
  };

  it("leaves the analysis and the build to Strengths and the role map", () => {
    for (const screen of ["strengths", "roles"] as const) {
      expect(withoutOwnRuns(activity, screen)).toEqual({
        ...activity,
        analysis: null,
        role_map: null,
      });
    }
  });

  it("reports everything elsewhere", () => {
    expect(withoutOwnRuns(activity, "sources")).toBe(activity);
    expect(withoutOwnRuns(activity, "advisor")).toBe(activity);
    expect(withoutOwnRuns(null, "roles")).toBeNull();
  });
});

describe("cancelling from the running bar (ADR 0072)", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("offers Cancel for an analysis and a build, never for a sync", () => {
    const lines = getActivityLines(
      {
        ...IDLE,
        syncing: [{ label: "github", started_at: "2026-09-28T09:00:00Z" }],
        analysis: run("running"),
        role_map: { ...run("waiting"), waiting_for: "market" },
      },
      "m",
    );
    expect(lines.map((line) => line.cancels ?? null)).toEqual([
      null,
      "analysis",
      "role_map",
    ]);
  });

  it("cancels the analysis without asking, then says so, not that it failed", async () => {
    const user = userEvent.setup();
    let cancelled = false;
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input).replace("http://api.test/api/v1", "");
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (init?.method === "POST") {
          cancelled = true;
          return new Response(null, { status: 204 });
        }
        const analysis = cancelled
          ? { ...run("cancelled"), id: "run-1" }
          : { ...run("running"), id: "run-1" };
        return new Response(JSON.stringify({ ...IDLE, analysis }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    renderShell();

    await user.click(
      await screen.findByRole("button", { name: "Cancel the analysis" }),
    );

    expect(await screen.findByText("Analysis cancelled.")).toBeInTheDocument();
    expect(calls).toContain("POST /assessments/runs/run-1/cancel");
    expect(screen.queryByText(/failed/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: "Running now" }),
    ).not.toBeInTheDocument();
  });
});

describe("what a run that closed says", () => {
  const both = { analysisDone: true, roleMapDone: true };

  it("words a cancel as a cancel, and an analysis with its build as one", () => {
    expect(getOutcomeToast(run("cancelled"), run("cancelled"), both)).toBe(
      "Analysis cancelled, and the role map build that was waiting for it.",
    );
    expect(
      getOutcomeToast(null, run("cancelled"), {
        analysisDone: false,
        roleMapDone: true,
      }),
    ).toBe("Role map build cancelled.");
    expect(
      getOutcomeToast(run("cancelled"), null, {
        analysisDone: true,
        roleMapDone: false,
      }),
    ).toBe("Analysis cancelled.");
  });

  it("still says when a run finished or failed", () => {
    expect(
      getOutcomeToast(run("ready"), null, {
        analysisDone: true,
        roleMapDone: false,
      }),
    ).toBe("Analysis finished.");
    expect(
      getOutcomeToast(null, null, { analysisDone: false, roleMapDone: false }),
    ).toBeNull();
  });
});
