import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Activity, Fit, Role, RoleCandidate } from "../api/types";
import { ActivityContext } from "../shell/activity";
import type { Focus } from "../shell/navigation";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { Roles, scopeLine } from "./Roles";
import { page } from "../test/page";

function role(id: string, name: string, overrides: Partial<Role> = {}): Role {
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
    origin: "recommended",
    company_name: null,
    private_posting_id: null,
    ...overrides,
  };
}

function fit(roleId: string, score: number): Fit {
  return {
    role_id: roleId,
    score,
    reasoning: "",
    gaps: [],
    uncovered: [],
    model_id: "claude-opus-5",
    computed_at: "2026-09-20T10:00:00Z",
  };
}

function candidate(
  rank: number,
  title: string,
  roleId: string | null,
): RoleCandidate {
  return {
    id: `c${rank}`,
    rank,
    title,
    description: `${title} work.`,
    dimension_keys: ["backend"],
    role_id: roleId,
    opening_count: roleId ? 4 : 1,
  };
}

const yours = role("r3", "Staff Platform Engineer", {
  origin: "custom",
  company_name: "Meridian Labs",
  private_posting_id: "jd-1",
  opening_count: 0,
});

function serve() {
  const routes: Record<string, unknown> = {
    "/roles": page([
      role("r1", "Backend Engineer"),
      role("r2", "Platform Engineer"),
      yours,
    ]),
    "/fits": page([fit("r1", 60), fit("r2", 84)]),
    "/assessments/latest": null,
    "/market-scope": {
      target_locations: ["Berlin", "Remote EU"],
      open_posting_count: 1284,
    },
    "/matched-postings?page_size=10": page([
      {
        posting_id: "p1",
        role_id: "r1",
        role_name: "Backend Engineer",
        title: "Staff Engineer, Ledger",
        company_name: "Northwind Pay",
        location: "Berlin",
        url: null,
        salary: null,
        fit: 62,
        fit_basis: "role",
        source_kind: "atsBoard",
        credited_to: null,
      },
      {
        posting_id: "p2",
        role_id: "r2",
        role_name: "Platform Engineer",
        title: "Platform Engineer, Clusters",
        company_name: "Kestrel Labs",
        location: "Remote, Worldwide",
        url: "https://himalayas.app/companies/kestrel-labs/jobs/platform-engineer",
        salary: null,
        fit: 84,
        fit_basis: "role",
        source_kind: "publicApi",
        credited_to: "Himalayas",
      },
    ]),
    "/role-candidates": page([
      candidate(0, "Backend Engineer", "r1"),
      candidate(1, "Platform Engineer", "r2"),
      candidate(2, "Payments Engineer", null),
    ]),
    "/role-map": {
      market_data_at: "2026-09-30T12:00:00+00:00",
      built_for_locations: ["Berlin"],
      locations_changed: true,
    },
    "/roles/cost-estimate": {
      max_roles: 8,
      fits_cost_usd: "0.10",
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
    status: { me: null, credential: null },
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
      focus: { role: "r2" },
    });
  });

  it("aims at the picked role", async () => {
    renderRoles({ role: "r1" });

    const bar = await screen.findByRole("region", { name: "Advisor target" });
    expect(bar).toHaveTextContent("Backend Engineer");
  });

  it("aims at a custom role as a role, like any other", async () => {
    const user = userEvent.setup();
    const shell = renderRoles({ role: "r3" });

    const bar = await screen.findByRole("region", { name: "Advisor target" });
    expect(
      await within(bar).findByText("Staff Platform Engineer · Meridian Labs"),
    ).toBeInTheDocument();
    await user.click(
      within(bar).getByRole("button", { name: "Target this role" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("advisor", {
      focus: { role: "r3" },
    });
  });

  it("aims at an opening picked in its role", async () => {
    const user = userEvent.setup();
    const shell = renderRoles({ role: "r1", opening: "p1" });

    const bar = await screen.findByRole("region", { name: "Advisor target" });
    expect(
      await within(bar).findByText("Backend Engineer · Northwind Pay"),
    ).toBeInTheDocument();
    await user.click(
      within(bar).getByRole("button", { name: "Target this opening" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("advisor", {
      focus: { role: "r1", opening: "p1" },
    });
  });

  it("selects an opening when its row is picked", async () => {
    const user = userEvent.setup();
    const shell = renderRoles({ role: "r1" });

    await user.click(
      await screen.findByRole("button", {
        name: /Backend Engineer · Northwind Pay: Staff Engineer, Ledger/,
      }),
    );
    expect(shell.setFocus).toHaveBeenCalledWith({ role: "r1", opening: "p1" });
  });

  it("has no other button that aims the Advisor", async () => {
    renderRoles({ role: "r1" });

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
      await screen.findByRole("button", { name: "Rebuild role map" }),
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

  it("says when a build is searching the market for its roles", async () => {
    renderRoles(null, {
      syncing: [],
      parsing: [],
      analysis: null,
      role_map: { status: "waiting", waiting_for: "market", ...running },
    });

    expect(
      await screen.findByRole("button", { name: "Searching the market…" }),
    ).toBeDisabled();
  });

  it("says how old the market is and that the locations moved since", async () => {
    renderRoles(null);

    expect(
      await screen.findByText(
        `Market data as of ${new Date("2026-09-30T12:00:00+00:00").toLocaleDateString()}.`,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Your locations changed since this map was built/),
    ).toBeInTheDocument();
  });
});

describe("an opening found through a job site", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("names the site and links back to the opening there", async () => {
    renderRoles(null);

    const credit = await screen.findByRole("link", { name: "Himalayas" });
    expect(credit).toHaveAttribute(
      "href",
      "https://himalayas.app/companies/kestrel-labs/jobs/platform-engineer",
    );
    expect(credit.parentElement).toHaveTextContent("via Himalayas");
  });

  it("credits nobody for an opening from the employer's own board", async () => {
    renderRoles(null);

    await screen.findByRole("link", { name: "Himalayas" });
    expect(screen.getAllByRole("link", { name: "Himalayas" })).toHaveLength(1);
    for (const row of screen.getAllByText(/Staff Engineer, Ledger/)) {
      expect(row).not.toHaveTextContent("via");
    }
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

describe("ten roles, chosen by the system", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("offers no count of roles to choose", async () => {
    renderRoles(null);

    await screen.findByText(/The 10 best-fit roles on the market/);
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});

describe("roles from your strengths that the market lacks", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("names only the recommended roles that did not make the map", async () => {
    renderRoles(null);

    const list = await screen.findByRole("list", {
      name: "Recommended roles without openings",
    });
    expect(within(list).getByText("Payments Engineer")).toBeInTheDocument();
    expect(
      within(list).queryByText("Backend Engineer"),
    ).not.toBeInTheDocument();
  });

  it("sends the user to Sources to widen where they want to work", async () => {
    const user = userEvent.setup();
    const shell = renderRoles(null);

    await user.click(
      await screen.findByRole("button", { name: "where you want to work" }),
    );

    expect(shell.navigate).toHaveBeenCalledWith("sources");
  });
});

describe("roles of your own", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("prices a role before adding it, then adds it and selects it", async () => {
    const calls: { method: string; url: string; body: unknown }[] = [];
    serve();
    const base = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input).replace("http://api.test/api/v1", "");
        const method = init?.method ?? "GET";
        calls.push({
          method,
          url,
          body: init?.body ? JSON.parse(String(init.body)) : null,
        });
        if (url === "/roles/custom/cost-estimate") {
          return Response.json({
            cost_usd: "0.08",
            fits_cost_usd: "0.03",
            model_id: "claude-opus-5",
            matches: 3,
          });
        }
        if (url === "/roles/custom" && method === "POST") {
          return Response.json(
            role("r9", "Principal Engineer", {
              origin: "custom",
              company_name: "Halden Labs",
            }),
          );
        }
        return base(input, init);
      }),
    );
    const user = userEvent.setup();
    const shell = renderRoles(null);

    await user.type(
      await screen.findByLabelText("Job title"),
      "Principal Engineer",
    );
    await user.type(screen.getByLabelText(/Company name/), "Halden Labs");
    await user.click(screen.getByRole("button", { name: "Add to Role Map" }));

    expect(
      await screen.findByText(/It takes in 3 open postings in your locations/),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/roles/custom")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Run it" }));

    expect(
      await screen.findByText("Principal Engineer · Halden Labs"),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.url === "/roles/custom")?.body).toEqual({
      title: "Principal Engineer",
      company_name: "Halden Labs",
      job_description: null,
    });
    expect(shell.setFocus).toHaveBeenCalledWith({ role: "r9" });
  });
});
