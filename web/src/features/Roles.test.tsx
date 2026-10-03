import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Activity, Fit, Role } from "../api/types";
import { ActivityContext } from "../shell/activity";
import type { Focus } from "../shell/navigation";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import {
  builtLine,
  getClearCount,
  getSkillFits,
  humanizeKey,
  Roles,
  scopeLine,
  signed,
} from "./Roles";
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
    ...overrides,
  };
}

function fit(roleId: string, score: number, gaps: Fit["gaps"] = []): Fit {
  return {
    role_id: roleId,
    score,
    reasoning: "",
    gaps,
    uncovered: [],
    model_id: "claude-opus-5",
    computed_at: "2026-09-20T10:00:00Z",
  };
}

function serve() {
  const routes: Record<string, unknown> = {
    "/roles": page([
      role("r1", "Backend Engineer", {
        salary_bands: {
          Berlin: {
            low: 70_000,
            mid: 80_000,
            high: 90_000,
            currency: "EUR",
            sample_size: 12,
            is_confident: true,
          },
        },
      }),
      role("r2", "Platform Engineer"),
    ]),
    "/fits": page([
      fit("r1", 60, [
        {
          dimension_key: "testing",
          user_score: 70,
          target_score: 55,
          delta: 15,
        },
        {
          dimension_key: "system_design",
          user_score: 48,
          target_score: 80,
          delta: -32,
        },
      ]),
      fit("r2", 84),
    ]),
    "/assessments/latest": null,
    "/market-scope": {
      target_locations: ["Berlin", "Remote EU"],
      open_posting_count: 1284,
    },
    "/matched-postings?role_id=r1&one_per_company=true&page_size=10": page([
      {
        posting_id: "p1",
        role_id: "r1",
        role_name: "Backend Engineer",
        title: "Staff Engineer, Ledger",
        company_name: "Northwind Pay",
        location: "Berlin",
        url: null,
        salary: { min: 165_000, max: 190_000, currency: "EUR" },
        fit: 62,
        fit_basis: "posting",
        source_kind: "atsBoard",
        credited_to: null,
      },
    ]),
    "/matched-postings?role_id=r2&one_per_company=true&page_size=10": page([
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
        fit_basis: "posting",
        source_kind: "publicApi",
        credited_to: "Himalayas",
      },
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

  it("leaves a posting of your own to the Advisor: the map selects roles", async () => {
    renderRoles({ posting: "j1" });

    const bar = await screen.findByRole("region", { name: "Advisor target" });
    // Nothing picked here, so the best fit is what the map shows.
    expect(bar).toHaveTextContent("Platform Engineer");
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
        name: "Staff Engineer, Ledger · Northwind Pay",
      }),
    );
    expect(shell.setFocus).toHaveBeenCalledWith({ role: "r1", opening: "p1" });
  });

  it("lists the selected role's openings in Top matched, by their own fit", async () => {
    renderRoles({ role: "r1" });

    expect(
      await screen.findByRole("heading", {
        name: "Top matched openings in Backend Engineer",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Staff Engineer, Ledger/)).toBeInTheDocument();
    expect(
      screen.queryByText(/Platform Engineer, Clusters/),
    ).not.toBeInTheDocument();
  });

  it("names the currency and the year on every salary", async () => {
    renderRoles({ role: "r1" });

    expect(
      await screen.findByText(/EUR 165k–190k a year · Berlin/),
    ).toBeInTheDocument();
    expect(screen.getByText("Annual pay").parentElement).toHaveTextContent(
      "EUR 70k–90k",
    );
    expect(
      screen.getByText("Annual salary in EUR, midpoint of the band"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("table")).getByText("EUR 70k–90k a year"),
    ).toBeInTheDocument();
  });

  it("follows the picked role: another bubble, another list", async () => {
    renderRoles({ role: "r2" });

    expect(
      await screen.findByRole("heading", {
        name: "Top matched openings in Platform Engineer",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Platform Engineer, Clusters/)).toBeInTheDocument();
    expect(
      screen.queryByText(/Staff Engineer, Ledger/),
    ).not.toBeInTheDocument();
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

describe("the selected role's fit", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows you against what the role asks on each skill, biggest gap first", async () => {
    renderRoles({ role: "r1" });

    expect(
      await screen.findByText("How you fit each skill"),
    ).toBeInTheDocument();
    expect(screen.getByText("Biggest gap first")).toBeInTheDocument();
    expect(
      screen.getByText("You clear 1 of 2 skills this role screens for."),
    ).toBeInTheDocument();
    const bars = screen.getAllByRole("img", { name: /: you \d+, role asks/ });
    expect(bars.map((bar) => bar.getAttribute("aria-label"))).toEqual([
      "System design: you 48, role asks 80",
      "Testing: you 70, role asks 55",
    ]);
    expect(screen.getByText("\u221232")).toBeInTheDocument();
    expect(screen.getByText("+15")).toBeInTheDocument();
  });

  it("says no more about what has no evidence than the bars do", async () => {
    renderRoles({ role: "r1" });

    await screen.findByText("How you fit each skill");
    expect(
      screen.queryByText("No evidence at all for these"),
    ).not.toBeInTheDocument();
  });

  it("gives each stat its context", async () => {
    renderRoles({ role: "r1" });

    expect(await screen.findByText("across 4 postings")).toBeInTheDocument();
    expect(screen.getByText("Berlin · Remote EU")).toBeInTheDocument();
    expect(screen.getByText("in your locations")).toBeInTheDocument();
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

  it("says when the map was built and that the locations moved since", async () => {
    renderRoles(null);

    expect(
      await screen.findByText(/^Built 30 Sep 2026 on your model · /),
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
    // Backend Engineer's openings: only Northwind Pay's, from its own board.
    renderRoles({ role: "r1" });

    for (const row of await screen.findAllByText(/Staff Engineer, Ledger/)) {
      expect(row).not.toHaveTextContent("via");
    }
    expect(
      screen.queryByRole("link", { name: "Himalayas" }),
    ).not.toBeInTheDocument();
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
      await screen.findByText(/1,284 open postings in Berlin and Remote EU/),
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

    await screen.findByText(/The 2 best-fit roles on the market/);
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});

describe("what the role map leaves out", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists no recommended roles beside the map, and never asks for them", async () => {
    renderRoles(null);

    await screen.findByRole("region", { name: "Advisor target" });
    expect(
      screen.queryByRole("list", {
        name: "Recommended roles without openings",
      }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Payments Engineer")).not.toBeInTheDocument();
    const asked = vi
      .mocked(globalThis.fetch)
      .mock.calls.map(([input]) => String(input));
    expect(asked.some((url) => url.includes("/role-candidates"))).toBe(false);
  });

  it("names each opening by its title and company, never its role", async () => {
    renderRoles({ role: "r1" });

    const row = await screen.findByRole("button", {
      name: "Staff Engineer, Ledger · Northwind Pay",
    });
    expect(row).toHaveTextContent("Staff Engineer, Ledger · Northwind Pay");
    expect(row).toHaveTextContent("Berlin");
    expect(row).not.toHaveTextContent("Backend Engineer");
  });
});

describe("no roles of your own", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("has nothing to add to the map: a posting of your own is the Advisor's", async () => {
    serve();
    renderRoles(null);

    await screen.findByRole("region", { name: "Advisor target" });
    expect(
      screen.queryByRole("button", { name: "Add to Role Map" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Job title")).not.toBeInTheDocument();
  });
});

describe("the role map toolbar", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("puts Rebuild first, with what the last build was and what a rebuild costs", async () => {
    renderRoles(null);

    expect(
      await screen.findByText(
        "Built 30 Sep 2026 on your model · 1,284 open postings in Berlin and Remote EU · about $0.40 on your key to rebuild",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rebuild role map" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Re-score fit" }),
    ).not.toBeInTheDocument();
  });

  it("leaves out what is not known yet", () => {
    expect(
      builtLine({
        builtAt: null,
        model: "m",
        scope: null,
        rebuildCostUsd: null,
      }),
    ).toBe("Not built yet");
  });
});

describe("the skill fit helpers", () => {
  const gaps = [
    { dimension_key: "a", user_score: 92, target_score: 78 },
    { dimension_key: "b", user_score: 42, target_score: 65 },
    { dimension_key: "c", user_score: 72, target_score: 80 },
    { dimension_key: "d", user_score: 60, target_score: 60 },
  ];

  it("counts a skill met exactly as cleared", () => {
    expect(getClearCount(gaps)).toBe(2);
  });

  it("sorts the biggest gap first and names each by its display name", () => {
    const names = new Map([["b", "Incident response"]]);
    expect(getSkillFits(gaps, names).map((s) => [s.name, s.delta])).toEqual([
      ["Incident response", -23],
      ["C", -8],
      ["D", 0],
      ["A", 14],
    ]);
  });

  it("never shows a raw slug", () => {
    expect(humanizeKey("backend-eng_python")).toBe("Backend eng python");
  });

  it("signs a gap with a real minus", () => {
    expect(signed(-23)).toBe("\u221223");
    expect(signed(14)).toBe("+14");
    expect(signed(0)).toBe("+0");
  });
});
