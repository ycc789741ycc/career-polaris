import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Fit, MatchedPosting, PlanSummary, Role } from "../api/types";
import type { AdvisorTab, Focus } from "../shell/navigation";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { Advisor, focusOf, targetFor } from "./Advisor";
import { page } from "../test/page";

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
    origin: "recommended",
    company_name: null,
    private_posting_id: null,
    ...overrides,
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

const backend = role("r1", "Staff Backend Engineer");
const yours = role("r3", "Principal Engineer", {
  origin: "custom",
  company_name: "Halden Labs",
  salary_bands: {},
});

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
};

function plan(roleId: string, opening: string | null, id: string): PlanSummary {
  return {
    id,
    target: { role_id: roleId, job_posting_id: opening },
    label: "Principal Engineer · Halden Labs",
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
          ? page([backend, yours])
          : url === "/fits"
            ? page([fit("r1", 81), fit("r3", 64)])
            : url.startsWith("/matched-postings?role_id=r1")
              ? page([northwind])
              : url.startsWith("/matched-postings")
                ? page([])
                : url === "/gap-plans"
                  ? page([plan("r3", null, "plan-1")])
                  : url === "/tailored-resumes"
                    ? page([])
                    : null;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderAdvisor(focus: Focus | null, tab: AdvisorTab = "plan") {
  const shell: Shell = {
    status: {
      me: null,
      credential: null,
      openQuestions: 0,
      confidence: null,
    },
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
        <Advisor tab={tab} />
      </ToastProvider>
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

  it("asks for a role when the role map has not aimed it", () => {
    renderAdvisor(null);
    expect(
      screen.getByText("Pick a role on the role map first"),
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
      "Everything on this page is measured against this one role.",
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

  it("offers no picker of its own: changing role goes back to the map", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor({ role: "r1" });

    const banner = await screen.findByRole("region", {
      name: "Your target role",
    });
    expect(document.querySelector(".target-chip")).toBeNull();
    await user.click(
      within(banner).getByRole("button", { name: "Change role" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("roles");
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

    const row = (
      await screen.findByText("Principal Engineer · Halden Labs")
    ).closest(".history-row") as HTMLElement;
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
    expect(target?.ref).toEqual({ role_id: "r1", job_posting_id: "p1" });
    expect(target?.band).toBe("EUR 165k–190k");
    expect(target?.fit).toBe(86);
  });

  it("is a custom role with its own company, drawn as yours", () => {
    const target = targetFor({ role: "r3" }, [yours], [fit("r3", 64)], []);
    expect(target?.label).toBe("Principal Engineer · Halden Labs");
    expect(target?.isCustom).toBe(true);
    expect(target?.band).toBeNull();
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
  });
});
