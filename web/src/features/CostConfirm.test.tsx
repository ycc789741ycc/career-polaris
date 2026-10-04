import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Activity } from "../api/types";
import { ActivityContext } from "../shell/activity";
import { AWAY, ONLINE } from "../test/activity";
import { CostConfirm } from "./CostConfirm";

function activity(processing: Activity["processing"]): Activity {
  return {
    syncing: [],
    parsing: [],
    analysis: null,
    role_map: null,
    advisor_jobs: [],
    processing,
  };
}

function renderWith(processing: Activity["processing"]) {
  render(
    <ActivityContext.Provider
      value={{
        activity: activity(processing),
        refresh: async () => {},
        settled: { sources: 0, analysis: 0, roleMap: 0, advisor: 0 },
      }}
    >
      <CostConfirm busy={false} onConfirm={vi.fn()} onCancel={vi.fn()}>
        About $0.04 on your key.
      </CostConfirm>
    </ActivityContext.Provider>,
  );
}

describe("the cost estimate", () => {
  it("says the run waits while the processing machine is away", () => {
    renderWith(AWAY);

    expect(
      screen.getByText("Processing is offline; this starts when it is back."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run it" })).toBeEnabled();
  });

  it("says nothing more while it is up", () => {
    renderWith(ONLINE);

    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
