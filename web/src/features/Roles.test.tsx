import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Fit, Role, TargetOption } from "../api/types";
import type { Focus } from "../shell/navigation";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { Roles } from "./Roles";
import { page } from "../test/page";

function role(id: string, name: string): Role {
  return {
    id,
    name,
    hiring_bar: 80,
    bar_basis: "estimated",
    bar_confidence: 0.6,
    bar_reasoning: null,
    opening_count: 4,
    salary_bands: {},
    is_coherent: true,
    requirements: [],
  };
}

function fit(roleId: string, score: number): Fit {
  return {
    role_id: roleId,
    private_posting_id: null,
    score,
    reasoning: "",
    gaps: [],
    uncovered: [],
    model_id: "claude-opus-5",
    computed_at: "2026-09-20T10:00:00Z",
  };
}

const pasted: TargetOption = {
  kind: "privatePosting",
  id: "jd-1",
  title: "Staff Platform Engineer",
  role_name: null,
  role_id: null,
  company_name: "Meridian Labs",
  label: "Staff Platform Engineer · Meridian Labs",
  fit: null,
  salary: null,
  source_kind: "pasted",
  url: null,
  subscription_id: null,
};

function serve() {
  const routes: Record<string, unknown> = {
    "/roles": page([
      role("r1", "Backend Engineer"),
      role("r2", "Platform Engineer"),
    ]),
    "/roles/settings": { role_count: 8 },
    "/fits": page([fit("r1", 60), fit("r2", 84)]),
    "/assessments/latest": null,
    "/role-subscriptions": page([]),
    "/market-preferences": page([]),
    "/matched-postings?page_size=10": page([]),
    "/targets": page([pasted]),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      return new Response(JSON.stringify(routes[url] ?? null), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderRoles(focus: Focus | null) {
  const shell: Shell = {
    status: { me: null, credential: null, openQuestions: 0, confidence: null },
    navigate: vi.fn(),
    focus,
    setFocus: vi.fn(),
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
  };
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <Roles />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return shell;
}

describe("the role map's one Advisor target", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("offers the best-fit role until one is picked, and aims the Advisor at it", async () => {
    const user = userEvent.setup();
    const shell = renderRoles(null);

    const bar = await screen.findByRole("region", { name: "Advisor target" });
    expect(bar).toHaveTextContent("Platform Engineer");
    await user.click(
      within(bar).getByRole("button", { name: "Target this role" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("advisor", {
      focus: { kind: "role", id: "r2" },
    });
  });

  it("aims at the picked role", async () => {
    renderRoles({ kind: "role", id: "r1" });

    const bar = await screen.findByRole("region", { name: "Advisor target" });
    expect(bar).toHaveTextContent("Backend Engineer");
  });

  it("aims at a picked JD instead of a role", async () => {
    const user = userEvent.setup();
    const shell = renderRoles({ kind: "jd", id: "jd-1" });

    const bar = await screen.findByRole("region", { name: "Advisor target" });
    expect(
      await within(bar).findByText("Staff Platform Engineer · Meridian Labs"),
    ).toBeInTheDocument();
    await user.click(
      within(bar).getByRole("button", { name: "Target this JD" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("advisor", {
      focus: { kind: "jd", id: "jd-1" },
    });
  });

  it("has no other button that aims the Advisor", async () => {
    renderRoles({ kind: "role", id: "r1" });

    await screen.findByRole("region", { name: "Advisor target" });
    expect(
      screen.queryByRole("button", { name: /Plan a route|Tailor résumé/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /^Target this/ }),
    ).toHaveLength(1);
  });
});
