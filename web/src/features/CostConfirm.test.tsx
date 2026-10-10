import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Activity } from "../api/types";
import { ActivityContext } from "../shell/activity";
import {
  type Shell,
  ShellContext,
  type ShellStatus,
} from "../shell/ShellContext";
import { AWAY, ONLINE } from "../test/activity";
import { CostConfirm, getPayerLine } from "./CostConfirm";

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

const ON_PLATFORM: ShellStatus = {
  me: null,
  credential: null,
  aiSource: {
    source: "platform",
    has_credential: false,
    is_platform_on: true,
    is_eligible: true,
    platform_quota: {
      allowed_usd: "2",
      spent_usd: "0.75",
      remaining_usd: "1.25",
    },
  },
};

function renderOn(status: ShellStatus, onConfirm: () => void, strict = false) {
  const shell = {
    status,
    navigate: vi.fn(),
    refresh: async () => {},
  } as unknown as Shell;
  const tree = (
    <ShellContext.Provider value={shell}>
      <CostConfirm busy={false} onConfirm={onConfirm} onCancel={vi.fn()}>
        About $0.63 for the analysis.
      </CostConfirm>
    </ShellContext.Provider>
  );
  render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

describe("on CareerPolaris AI (ADR 0067)", () => {
  it("asks nothing and starts the run at once", () => {
    const onConfirm = vi.fn();
    renderOn(ON_PLATFORM, onConfirm);

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByText("Before we spend anything"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run it" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/\$0\.63/)).not.toBeInTheDocument();
  });

  it("starts it once, even when React mounts twice in development", () => {
    const onConfirm = vi.fn();
    renderOn(ON_PLATFORM, onConfirm, true);

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("still asks on the user's own key", () => {
    const onConfirm = vi.fn();
    const ownKey: ShellStatus = {
      me: null,
      credential: null,
      aiSource: {
        source: "own",
        has_credential: true,
        is_platform_on: true,
        is_eligible: true,
        platform_quota: null,
      },
    };
    renderOn(ownKey, onConfirm);

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Run it" })).toBeInTheDocument();
  });
});

describe("who pays", () => {
  it("names the user's own key and model", () => {
    expect(
      getPayerLine({
        me: null,
        credential: {
          provider: "anthropic",
          model: "claude-opus-5",
          base_url: null,
          last_four: "abcd",
          status: "active",
          last_error: null,
        },
        aiSource: null,
      }),
    ).toBe("Runs on your own key on claude-opus-5.");
  });
});
