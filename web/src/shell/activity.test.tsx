import "@testing-library/jest-dom/vitest";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Activity, RunStatus } from "../api/types";
import { ActivityBar, withoutOwnRuns } from "./ActivityBar";
import {
  ActivityProvider,
  describe as describeWork,
  useActivity,
} from "./activity";
import { ToastProvider } from "./toast";

const IDLE: Activity = {
  syncing: [],
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
  it("names every piece of work in journey order", () => {
    const lines = describeWork(
      {
        syncing: [{ label: "github", started_at: "2026-09-28T09:00:00Z" }],
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
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
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
