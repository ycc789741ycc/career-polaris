import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  Activity,
  Fit,
  MatchedPosting,
  OwnPosting,
  PlanSummary,
  Role,
} from "../api/types";
import type { AdvisorTab, Focus } from "../shell/navigation";
import { ActivityContext } from "../shell/activity";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { Advisor, focusOf, ownTargetFor, targetFor } from "./Advisor";
import { page } from "../test/page";
import { cancelPath, jobTab, jobWord } from "./AdvisorJobs";

function role(id: string, name: string, overrides: Partial<Role> = {}): Role {
  return {
    id,
    name,
    hiring_bar: 70,
    bar_basis: "estimated",
    bar_confidence: 0.5,
    bar_reasoning: null,
    opening_count: 2,
    salary_bands: {
      Berlin: {
        low: 150000,
        mid: 170000,
        high: 190000,
        currency: "EUR",
        sample_size: 8,
        is_confident: true,
      },
    },
    is_coherent: true,
    requirements: [],
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

const backend = role("r1", "Staff Backend Engineer");
const principal = role("r3", "Principal Engineer", { salary_bands: {} });

function own(id: string, overrides: Partial<OwnPosting> = {}): OwnPosting {
  return {
    private_job_posting_id: id,
    title: "Staff Platform Engineer",
    company_name: "Meridian Labs",
    source: "filled_in",
    filename: null,
    has_estimated_requirements: false,
    created_at: "2026-10-01T09:00:00Z",
    status: "ready",
    error_code: null,
    error_message: null,
    fit: 64,
    is_stale: false,
    scored_at: "2026-10-03T09:00:00Z",
    ...overrides,
  };
}

const northwind: MatchedPosting = {
  posting_id: "p1",
  role_id: "r1",
  role_name: "Staff Backend Engineer",
  title: "Staff Engineer, Ledger",
  company_name: "Northwind Pay",
  location: "Berlin",
  url: null,
  salary: { min: 165000, max: 190000, currency: "EUR" },
  fit: 86,
  fit_basis: "role",
  source_kind: "atsBoard",
  credited_to: null,
};

function plan(
  roleId: string | null,
  opening: string | null,
  id: string,
  posting: string | null = null,
): PlanSummary {
  return {
    id,
    target: {
      role_id: roleId,
      job_posting_id: opening,
      private_job_posting_id: posting,
    },
    label: posting
      ? "Staff Platform Engineer · Meridian Labs"
      : "Principal Engineer",
    version: 1,
    status: "ready",
    error: null,
    model_id: "claude-opus-5",
    created_at: "2026-09-20T10:00:00Z",
    drafted_at: "2026-09-20T10:00:00Z",
    progress: 0,
  };
}

function serve() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      const body =
        url === "/roles"
          ? page([backend, principal])
          : url === "/fits"
            ? page([fit("r1", 81), fit("r3", 64)])
            : url.startsWith("/matched-postings?role_id=r1")
              ? page([northwind])
              : url.startsWith("/matched-postings")
                ? page([])
                : url === "/gap-plans"
                  ? page([
                      plan("r3", null, "plan-1"),
                      plan(null, null, "plan-2", "j1"),
                    ])
                  : url === "/tailored-resumes"
                    ? page([])
                    : url === "/own-postings"
                      ? page([
                          own("j1"),
                          own("j2", { status: "running", fit: null }),
                        ])
                      : null;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderAdvisor(
  focus: Focus | null,
  tab: AdvisorTab = "plan",
  activity: Activity | null = null,
) {
  const shell: Shell = {
    status: {
      me: null,
      credential: null,
    },
    navigate: vi.fn(),
    focus,
    setFocus: vi.fn(),
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
    setHeading: vi.fn(),
  };
  render(
    <ShellContext.Provider value={shell}>
      <ActivityContext.Provider
        value={{
          activity,
          refresh: async () => {},
          settled: { sources: 0, analysis: 0, roleMap: 0, advisor: 0 },
        }}
      >
        <ToastProvider>
          <Advisor tab={tab} />
        </ToastProvider>
      </ActivityContext.Provider>
    </ShellContext.Provider>,
  );
  return shell;
}

describe("the Advisor's one target role", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("asks for a target from the map or a role of your own, when nothing is aimed", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor(null);

    expect(screen.getByText("Pick a target first")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use your own role" }));
    expect(shell.navigate).toHaveBeenCalledWith("advisor", { tab: "own" });
    await user.click(
      screen.getByRole("button", { name: "Pick from role map" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("roles");
  });

  it("brings a role of your own on its own tab, even with nothing aimed", async () => {
    renderAdvisor(null, "own");

    expect(
      await screen.findByRole("heading", { name: "Bring the job yourself" }),
    ).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "My roles" });
    expect(list).toHaveTextContent("reading and scoring it…");
  });

  it("says which target a role of your own would replace", async () => {
    renderAdvisor({ role: "r1" }, "own");

    expect(
      await screen.findByText(
        /It replaces Staff Backend Engineer as your target\./,
      ),
    ).toBeInTheDocument();
  });

  it("measures everything against a role of your own", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor({ posting: "j1" });

    const banner = await screen.findByRole("region", {
      name: "Your target role",
    });
    expect(banner).toHaveTextContent("Staff Platform Engineer");
    expect(banner).toHaveTextContent("at Meridian Labs");
    expect(banner).toHaveTextContent("64%");
    expect(banner).toHaveTextContent("measured against this one role");
    await user.click(
      within(banner).getByRole("button", { name: "Use your own role" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("advisor", { tab: "own" });
  });

  it("waits for a role of your own to be scored before planning for it", async () => {
    renderAdvisor({ posting: "j2" });

    expect(
      await screen.findByText("Reading and scoring Staff Platform Engineer"),
    ).toBeInTheDocument();
  });

  it("names the role and opening it measures everything against", async () => {
    const shell = renderAdvisor({ role: "r1", opening: "p1" });

    const banner = await screen.findByRole("region", {
      name: "Your target role",
    });
    expect(banner).toHaveTextContent("Staff Backend Engineer");
    expect(banner).toHaveTextContent(
      "at Northwind Pay · Berlin · Staff Engineer, Ledger posting",
    );
    expect(banner).toHaveTextContent("86%");
    expect(banner).toHaveTextContent("EUR 165k–190k");
    expect(banner).toHaveTextContent(
      "Everything on this page is measured against this opening",
    );
    await waitFor(() =>
      expect(shell.setTarget).toHaveBeenCalledWith(
        "Staff Backend Engineer · Northwind Pay · 86%",
      ),
    );
  });

  it("aims at the role alone when no opening was picked", async () => {
    renderAdvisor({ role: "r1" });

    const banner = await screen.findByRole("region", {
      name: "Your target role",
    });
    expect(banner).toHaveTextContent("81%");
    expect(banner).toHaveTextContent("EUR 150k–190k");
    expect(banner).not.toHaveTextContent("posting");
  });

  it("offers no picker of its own: the map, or a role of your own", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor({ role: "r1" });

    const banner = await screen.findByRole("region", {
      name: "Your target role",
    });
    expect(document.querySelector(".target-chip")).toBeNull();
    await user.click(
      within(banner).getByRole("button", { name: "Pick from role map" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("roles");
    expect(
      within(banner).getByRole("button", { name: "Use your own role" }),
    ).toBeInTheDocument();
  });

  it("says so when the target has left the map", async () => {
    renderAdvisor({ role: "gone" });

    expect(
      await screen.findByText("That target is no longer on your role map"),
    ).toBeInTheDocument();
  });

  it("switches tabs through the hash", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor({ role: "r1" });

    const tabs = await screen.findByRole("group", { name: "Advisor tabs" });
    await user.click(within(tabs).getByRole("button", { name: "Résumé" }));
    expect(shell.navigate).toHaveBeenCalledWith("advisor", { tab: "resume" });
  });

  it("moves to another role when a plan kept for it is revisited", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor({ role: "r1" });

    const row = (await screen.findByText("Principal Engineer")).closest(
      ".history-row",
    ) as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Revisit" }));
    expect(shell.navigate).toHaveBeenCalledWith("advisor", {
      focus: { role: "r3" },
    });
  });
});

describe("what a focus aims at", () => {
  it("is the opening's fit and pay when an opening is named", () => {
    const target = targetFor(
      { role: "r1", opening: "p1" },
      [backend],
      [fit("r1", 81)],
      [northwind],
    );
    expect(target?.ref).toEqual({
      role_id: "r1",
      job_posting_id: "p1",
      private_job_posting_id: null,
    });
    expect(target?.band).toBe("EUR 165k–190k");
    expect(target?.fit).toBe(86);
    expect(target?.creditedTo).toBeNull();
  });

  it("carries the job site an opening was found through, to credit it", () => {
    const found = {
      ...northwind,
      url: "https://himalayas.app/companies/northwind-pay/jobs/staff-engineer",
      credited_to: "Himalayas",
    };
    const target = targetFor(
      { role: "r1", opening: "p1" },
      [backend],
      [fit("r1", 81)],
      [found],
    );
    expect(target?.creditedTo).toBe("Himalayas");
    expect(target?.url).toBe(found.url);
  });

  it("is a posting of your own, by its title and company, once it is scored", () => {
    const target = ownTargetFor("j1", [own("j1")]);
    expect(target?.label).toBe("Staff Platform Engineer · Meridian Labs");
    expect(target?.ref).toEqual({
      role_id: null,
      job_posting_id: null,
      private_job_posting_id: "j1",
    });
    expect(target?.isOwnPosting).toBe(true);
    expect(target?.requirementsEstimated).toBe(false);
    expect(
      ownTargetFor("j1", [own("j1", { has_estimated_requirements: true })])
        ?.requirementsEstimated,
    ).toBe(true);
    expect(ownTargetFor("j1", [own("j1", { fit: null })])).toBeNull();
    expect(ownTargetFor("gone", [own("j1")])).toBeNull();
  });

  it("is nothing when the opening has left the role", () => {
    expect(
      targetFor({ role: "r1", opening: "p9" }, [backend], [], [northwind]),
    ).toBeNull();
  });

  it("round-trips through the role map's focus", () => {
    expect(focusOf({ role_id: "r1", job_posting_id: "p1" })).toEqual({
      role: "r1",
      opening: "p1",
    });
    expect(focusOf({ role_id: "r1", job_posting_id: null })).toEqual({
      role: "r1",
    });
    expect(
      focusOf({
        role_id: null,
        job_posting_id: null,
        private_job_posting_id: "j1",
      }),
    ).toEqual({ posting: "j1" });
  });
});

describe("Advisor jobs in the background (ADR 0042)", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  const writing: Activity = {
    syncing: [],
    parsing: [],
    analysis: null,
    role_map: null,
    advisor_jobs: [
      {
        kind: "resume",
        id: "res-9",
        target: {
          role_id: "r1",
          job_posting_id: null,
          private_job_posting_id: null,
        },
        label: "Backend Engineer",
        stage: "writing",
        progress: 0.4,
        started_at: "2026-10-11T09:00:00+00:00",
        estimated_cost_usd: "0.031",
      },
    ],
  };

  it("keeps the gap plan open while the résumé is written, with a spinner and a notice", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor({ role: "r1" }, "plan", writing);

    const tabs = await screen.findByRole("group", { name: "Advisor tabs" });
    expect(
      within(tabs).getByRole("button", { name: /Résumé/ }),
    ).toHaveTextContent("writing…");
    expect(
      within(tabs).getByRole("button", { name: /Gap plan/ }),
    ).not.toHaveTextContent("drafting…");
    // The plan tab is its own page, not the résumé's card.
    expect(screen.queryByRole("progressbar")).toBeNull();
    const notice = screen
      .getByText("Writing your résumé · 40%")
      .closest("div")!;
    await user.click(within(notice).getByRole("button", { name: "View" }));
    expect(shell.navigate).toHaveBeenCalledWith("advisor", { tab: "resume" });
  });

  it("shows the job's card on its own tab, and Cancel posts", async () => {
    const user = userEvent.setup();
    renderAdvisor({ role: "r1" }, "resume", writing);

    const card = await screen.findByRole("status", {
      name: "Writing your résumé…",
    });
    expect(within(card).getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
    expect(card).toHaveTextContent("About $0.03 on your key");
    expect(card).toHaveTextContent("Your model is writing.");
    await user.click(within(card).getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.some(
            ([url, init]) =>
              String(url).endsWith("/tailored-resumes/res-9/cancel") &&
              init?.method === "POST",
          ),
      ).toBe(true),
    );
  });

  it("names each kind of job by its tab and words", () => {
    expect(jobTab("questions")).toBe("gaps");
    expect(jobTab("own_posting_evaluation")).toBe("gaps");
    expect(jobWord("gap_plan")).toBe("drafting…");
    expect(jobWord("section")).toBe("writing…");
    expect(
      cancelPath({ ...writing.advisor_jobs[0]!, kind: "gap_plan", id: "p1" }),
    ).toBe("/gap-plans/p1/cancel");
  });
});
