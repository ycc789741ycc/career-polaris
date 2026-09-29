import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Credential } from "../api/types";
import { ActivityContext } from "./activity";
import { initialsOf } from "./PageHeader";
import type { ShellStatus } from "./ShellContext";
import { Sidebar } from "./Sidebar";

const credential: Credential = {
  provider: "anthropic",
  model: "claude-opus-5",
  base_url: null,
  last_four: "abcd",
  status: "active",
  last_error: null,
};

function status(overrides: Partial<ShellStatus> = {}): ShellStatus {
  return {
    me: null,
    credential,
    ...overrides,
  };
}

describe("sidebar", () => {
  it("marks the current screen and navigates on click", async () => {
    const onNavigate = vi.fn();
    render(
      <Sidebar current="roles" status={status()} onNavigate={onNavigate} />,
    );

    const nav = screen.getByRole("navigation", { name: "Screens" });
    expect(
      within(nav).getByRole("button", { name: /Role map/ }),
    ).toHaveAttribute("aria-current", "page");

    await userEvent.click(within(nav).getByRole("button", { name: /Advisor/ }));
    expect(onNavigate).toHaveBeenCalledWith("advisor");
  });

  it("flags the model when no key is set, and names the model once it is", () => {
    const { rerender } = render(
      <Sidebar
        current="sources"
        status={status({ credential: null })}
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByLabelText("needs a key")).toBeInTheDocument();
    expect(screen.getByText("No key yet")).toBeInTheDocument();

    rerender(
      <Sidebar current="sources" status={status()} onNavigate={() => {}} />,
    );
    expect(screen.queryByLabelText("needs a key")).not.toBeInTheDocument();
    expect(screen.getByText("claude-opus-5")).toBeInTheDocument();
  });

  it("shows no profile confidence: it belongs to Strengths now", () => {
    render(
      <Sidebar current="sources" status={status()} onNavigate={() => {}} />,
    );
    expect(
      screen.queryByRole("progressbar", { name: "Profile confidence" }),
    ).not.toBeInTheDocument();
  });
});

describe("account initials", () => {
  it("takes one letter from each of the first two parts of the address", () => {
    expect(initialsOf("maya.chen@example.com")).toBe("MC");
    expect(initialsOf("maya_lin-chen@example.com")).toBe("ML");
  });

  it("falls back to the first two letters, or a placeholder", () => {
    expect(initialsOf("maya@example.com")).toBe("MA");
    expect(initialsOf(null)).toBe("?");
  });
});

describe("sidebar while work runs", () => {
  it("marks each step whose stage is still working, and only those", () => {
    render(
      <ActivityContext.Provider
        value={{
          activity: {
            syncing: [],
            parsing: [{ label: "cv.pdf", started_at: "2026-09-28T09:00:00Z" }],
            analysis: null,
            role_map: {
              status: "waiting",
              started_at: "2026-09-28T09:00:00Z",
              finished_at: null,
              error: null,
            },
          },
          refresh: async () => {},
          settled: { sources: 0, analysis: 0, roleMap: 0 },
        }}
      >
        <Sidebar current="sources" status={status()} onNavigate={() => {}} />
      </ActivityContext.Provider>,
    );

    const nav = screen.getByRole("navigation", { name: "Screens" });
    const running = (name: RegExp) =>
      within(within(nav).getByRole("button", { name })).queryByRole("img", {
        name: "running",
      });
    expect(running(/Sources/)).toBeInTheDocument();
    expect(running(/Strengths/)).not.toBeInTheDocument();
    expect(running(/Role map/)).toBeInTheDocument();
  });
});
