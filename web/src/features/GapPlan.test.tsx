import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Plan, PlanSummary } from "../api/types";
import type { AdvisorTarget } from "./target";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { GapPlan } from "./GapPlan";
import { ago } from "./time";

const option: AdvisorTarget = {
  ref: { role_id: "r1", job_posting_id: "p1" },
  label: "Senior Backend Engineer · Northwind Pay",
  roleName: "Senior Backend Engineer",
  company: "Northwind Pay",
  location: "Berlin",
  postingTitle: "Senior Backend Engineer",
  url: null,
  creditedTo: null,
  fit: 71,
  band: null,
  isOwnPosting: false,
};

const yours: AdvisorTarget = {
  ...option,
  ref: { role_id: null, job_posting_id: null, private_job_posting_id: "j1" },
  label: "Staff Platform Engineer · Meridian Labs",
  roleName: "Staff Platform Engineer",
  company: "Meridian Labs",
  location: null,
  postingTitle: null,
  fit: null,
  isOwnPosting: true,
};

const summary: PlanSummary = {
  id: "plan-1",
  target: { role_id: "r1", job_posting_id: "p1" },
  label: option.label,
  version: 1,
  status: "ready",
  error: null,
  model_id: "claude-opus-5",
  created_at: "2026-09-20T10:00:00Z",
  drafted_at: "2026-09-20T10:01:00Z",
  progress: 25,
};

const readyPlan: Plan = {
  ...summary,
  template_version: "gap_plan@v1",
  snapshot: {
    title: "Senior Backend Engineer",
    company: "Northwind Pay",
    role_name: "Senior Backend Engineer",
    fit: 71,
    basis: "role",
    requirements: [],
    taken_at: "2026-09-20T10:00:00Z",
  },
  gaps: [
    {
      key: "req:org",
      kind: "uncovered",
      name: "Demonstrated org-level influence",
      user_score: null,
      target_score: null,
      lift: 25,
      why: "They ask for it; nothing shows it.",
      evidence: [],
    },
    {
      key: "dim:leadership",
      kind: "dimension",
      name: "Technical leadership",
      user_score: 70,
      target_score: 90,
      lift: 10,
      why: "They expect 90.",
      evidence: [
        { id: "e1", reference: "GitHub · payments-svc", fact: "38 merged PRs" },
      ],
    },
  ],
  milestones: [
    {
      id: "m1",
      title: "Own one cross-team outcome",
      window: "Weeks 1-6",
      outcome: "The artefact panels ask for.",
      tasks: [
        {
          id: "t1",
          text: "Lead the checkout migration",
          due: "Wk 1",
          closes: ["dim:leadership"],
          done: false,
          done_elsewhere: false,
        },
        {
          id: "t2",
          text: "Present at all-hands",
          due: "Wk 8",
          closes: ["req:org"],
          done: false,
          done_elsewhere: true,
        },
      ],
    },
  ],
  projects: [],
  stepping_stones: [
    { role_id: "r2", name: "Platform Engineer", fit: 84, openings: 9 },
  ],
  versions: [summary],
  is_outdated: false,
  lift_scale: 25,
  answer_count: 3,
  outdated_by: [],
};

type Route = (method: string, url: string, body: unknown) => unknown;

function json(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status: body === undefined ? 204 : status,
    headers: { "Content-Type": "application/json" },
  });
}

function serve(route: Route) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      return json(route(method, url, body));
    }),
  );
  return calls;
}

function renderPlan(
  history: PlanSummary[],
  overrides: Partial<Shell> = {},
  target: AdvisorTarget = option,
) {
  const onChanged = vi.fn();
  const onRevisit = vi.fn();
  const shell: Shell = {
    status: {
      me: null,
      credential: {
        provider: "anthropic",
        model: "claude-opus-5",
        base_url: null,
        last_four: "abcd",
        status: "active",
        last_error: null,
      },
    },
    navigate: vi.fn(),
    focus: null,
    setFocus: vi.fn(),
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
    account: "maya@example.com",
    setHeading: vi.fn(),
    ...overrides,
  };
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <GapPlan
          target={target}
          history={history}
          onChanged={onChanged}
          onRevisit={onRevisit}
        />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return { shell, onChanged, onRevisit };
}

describe("gap plan screen", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("prices a plan before anything is spent, then shows it drafting", async () => {
    const calls = serve((method, url) => {
      if (url.startsWith("/gap-plans/cost-estimate"))
        return { cost_usd: "0.04", model_id: "claude-opus-5" };
      if (url === "/gap-plans" && method === "POST")
        return { ...summary, status: "drafting", progress: 0 };
      if (url === "/gap-plans/plan-1")
        return { ...readyPlan, status: "drafting", gaps: [], milestones: [] };
      return null;
    });
    const user = userEvent.setup();
    const { onChanged } = renderPlan([]);

    expect(await screen.findByText("No plan yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate gap plan" }));

    const confirm = await screen.findByRole("region", {
      name: "Cost estimate",
    });
    expect(confirm).toHaveTextContent("$0.04");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.click(within(confirm).getByRole("button", { name: "Run it" }));
    expect(
      await screen.findByText(/Drafting on claude-opus-5/),
    ).toBeInTheDocument();
    expect(calls).toContainEqual({
      method: "POST",
      url: "/gap-plans",
      body: { role_id: "r1", job_posting_id: "p1" },
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("opens the latest plan with its gaps ranked and cited", async () => {
    serve((_method, url) => {
      if (url === "/gap-plans/plan-1") return readyPlan;
      return null;
    });
    renderPlan([summary]);

    expect(
      await screen.findByText("1 · Demonstrated org-level influence"),
    ).toBeInTheDocument();
    expect(screen.getByText("+25 fit pts")).toBeInTheDocument();
    expect(screen.getByText("No evidence at all")).toBeInTheDocument();
    // Each gap's fit points, as a bar out of the plan's largest lift.
    const bar = screen.getByRole("img", {
      name: "Closing this gap adds 10 of 25 possible fit points",
    });
    expect(bar.firstElementChild).toHaveStyle({ width: "40%" });
    expect(
      screen.getByText(/The bar shows the fit points out of 25/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/uses your 3 answers from Fill the gap/),
    ).toBeInTheDocument();
    // Evidence is collapsed until opened; a gap with none says so.
    const shown = screen.getByText("Show evidence (1)").closest("details")!;
    expect(shown).not.toHaveAttribute("open");
    expect(within(shown).getByText("38 merged PRs")).toBeInTheDocument();
    expect(screen.getByText("Show evidence (none found)")).toBeInTheDocument();
    expect(screen.getByText("Platform Engineer")).toBeInTheDocument();
  });

  it("says an outdated plan is outdated and prices regenerating it", async () => {
    const calls = serve((_method, url) => {
      if (url === "/gap-plans/plan-1")
        return {
          ...readyPlan,
          is_outdated: true,
          outdated_by: ["evidence", "target"],
        };
      if (url.startsWith("/gap-plans/cost-estimate"))
        return { cost_usd: "0.04", model_id: "claude-opus-5" };
      return null;
    });
    const user = userEvent.setup();
    renderPlan([summary]);

    const banner = await screen.findByRole("status", { name: "Outdated" });
    expect(banner).toHaveTextContent(
      "Outdated: your evidence changed and the target changed",
    );
    await user.click(
      within(banner).getByRole("button", { name: "Regenerate" }),
    );

    expect(
      await screen.findByRole("region", { name: "Cost estimate" }),
    ).toHaveTextContent("$0.04");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows no banner on a plan that still matches what it read", async () => {
    serve((_method, url) => (url === "/gap-plans/plan-1" ? readyPlan : null));
    renderPlan([summary]);

    await screen.findByText("1 · Demonstrated org-level influence");
    expect(screen.queryByRole("status", { name: "Outdated" })).toBeNull();
  });

  it("ticks a task and counts one finished in another plan", async () => {
    const calls = serve((_method, url) => {
      if (url === "/gap-plans/plan-1") return readyPlan;
      if (url.startsWith("/gap-plan-tasks/")) return undefined;
      return null;
    });
    const user = userEvent.setup();
    renderPlan([summary]);

    const elsewhere = await screen.findByRole("checkbox", {
      name: /Present at all-hands/,
    });
    expect(elsewhere).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByText("Done in another plan — it counts here too."),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("checkbox", { name: /Lead the checkout migration/ }),
    );
    expect(calls).toContainEqual({
      method: "PUT",
      url: "/gap-plan-tasks/t1",
      body: { done: true },
    });
  });

  it("prices a posting of your own by the posting alone", async () => {
    const calls = serve((_method, url) => {
      if (url.startsWith("/gap-plans/cost-estimate"))
        return { cost_usd: "0.09" };
      return null;
    });
    const user = userEvent.setup();
    renderPlan([], {}, yours);

    await user.click(
      await screen.findByRole("button", { name: "Generate gap plan" }),
    );

    expect(
      await screen.findByRole("region", { name: "Cost estimate" }),
    ).toHaveTextContent("$0.09");
    expect(calls.map((c) => c.url)).toContain(
      "/gap-plans/cost-estimate?private_job_posting_id=j1",
    );
    expect(
      screen.getByText(/requirements of your posting/),
    ).toBeInTheDocument();
  });

  it("hands a plan kept for another target to the Advisor", async () => {
    serve((_method, url) => {
      if (url === "/gap-plans/plan-1") return readyPlan;
      return null;
    });
    const other: PlanSummary = {
      ...summary,
      id: "plan-2",
      target: { role_id: "r9", job_posting_id: null },
      label: "Platform Engineer · Contoso",
    };
    const user = userEvent.setup();
    const { onRevisit } = renderPlan([other, summary]);

    const row = (
      await screen.findByText("Platform Engineer · Contoso")
    ).closest(".history-row") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Revisit" }));
    expect(onRevisit).toHaveBeenCalledWith(other);
  });

  it("sends a user without a model to set one up instead of pricing", async () => {
    serve(() => null);
    const user = userEvent.setup();
    const { shell } = renderPlan([], {
      status: {
        me: null,
        credential: null,
      },
    });

    await user.click(
      await screen.findByRole("button", { name: "Generate gap plan" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("model");
  });
});

describe("relative time", () => {
  const now = new Date("2026-09-23T12:00:00Z");

  it("reads like the prototype's history", () => {
    expect(ago("2026-09-23T11:59:30Z", now)).toBe("just now");
    expect(ago("2026-09-23T11:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-09-23T09:00:00Z", now)).toBe("3 hours ago");
    expect(ago("2026-09-22T11:00:00Z", now)).toBe("yesterday");
    expect(ago("2026-09-17T12:00:00Z", now)).toBe("6 days ago");
  });
});
