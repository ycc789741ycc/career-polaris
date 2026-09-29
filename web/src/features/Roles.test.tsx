import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Activity, Fit, Role, TargetOption } from "../api/types";
import { ActivityContext } from "../shell/activity";
import type { Focus } from "../shell/navigation";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { Roles, scopeLine } from "./Roles";
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
    "/market-scope": {
      target_locations: ["Berlin", "Remote EU"],
      open_posting_count: 1284,
    },
    "/matched-postings?page_size=10": page([]),
    "/targets": page([pasted]),
    "/roles/cost-estimate?role_count=8": {
      max_clusters: 8,
      role_count: 8,
      cost_usd: "0.40",
      model_id: "claude-opus-5",
      rate_is_published: true,
    },
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

function renderRoles(focus: Focus | null, activity: Activity | null = null) {
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
      <ActivityContext.Provider
        value={{
          activity,
          refresh: async () => {},
          settled: { sources: 0, analysis: 0, roleMap: 0 },
        }}
      >
        <ToastProvider>
          <Roles />
        </ToastProvider>
      </ActivityContext.Provider>
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

describe("the role map while an analysis runs", () => {
  const running = {
    started_at: "2026-09-28T09:00:00Z",
    finished_at: null,
    error: null,
  };

  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("queues a build that starts when the analysis finishes", async () => {
    const user = userEvent.setup();
    renderRoles(null, {
      syncing: [],
      parsing: [],
      analysis: { status: "running", ...running },
      role_map: null,
    });

    await user.click(
      await screen.findByRole("button", { name: "Build role map" }),
    );
    await user.click(await screen.findByRole("button", { name: "Run it" }));

    expect(
      await screen.findByText(
        "Role map queued — it starts when your analysis finishes.",
      ),
    ).toBeInTheDocument();
  });

  it("offers no second build while one waits", async () => {
    renderRoles(null, {
      syncing: [],
      parsing: [],
      analysis: { status: "running", ...running },
      role_map: { status: "waiting", ...running },
    });

    expect(
      await screen.findByRole("button", { name: "Waiting for analysis…" }),
    ).toBeDisabled();
  });
});

describe("how much of the market the role map takes in", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("counts the open postings in the chosen locations", async () => {
    renderRoles(null);

    expect(
      await screen.findByText(/1,284 open postings in Berlin and Remote EU\./),
    ).toBeInTheDocument();
  });

  it("has no market pills to switch between", async () => {
    renderRoles(null);

    await screen.findByText(/1,284 open postings/);
    expect(
      screen.queryByRole("button", { name: "Best sample" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Market")).not.toBeInTheDocument();
  });

  it("names the baseline when no location is chosen", () => {
    expect(scopeLine({ target_locations: [], open_posting_count: 1 })).toBe(
      "1 open posting in the platform's baseline.",
    );
    expect(
      scopeLine({
        target_locations: ["Berlin", "Lisbon", "Remote EU"],
        open_posting_count: 12,
      }),
    ).toBe("12 open postings in Berlin, Lisbon and Remote EU.");
  });
});
