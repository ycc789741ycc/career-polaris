import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PlanSummary, TargetOption } from "../api/types";
import type { AdvisorTab, Focus } from "../shell/navigation";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { Advisor, firstOpening, openingsFor } from "./Advisor";
import { page } from "../test/page";

function opening(overrides: Partial<TargetOption>): TargetOption {
  return {
    kind: "matchedPosting",
    id: "p1",
    title: "Senior Backend Engineer",
    role_name: "Senior Backend Engineer",
    role_id: "r1",
    company_name: "Northwind Pay",
    label: "Senior Backend Engineer · Northwind Pay",
    fit: 71,
    salary: null,
    source_kind: "atsBoard",
    url: null,
    ...overrides,
  };
}

const northwind = opening({});
const acme = opening({
  id: "p2",
  company_name: "Acme",
  label: "Senior Backend Engineer · Acme",
  fit: 90,
});
const kestrel = opening({
  id: "p4",
  company_name: "Kestrel",
  label: "Senior Backend Engineer · Kestrel",
  fit: 60,
});
const platform = opening({
  id: "p3",
  title: "Platform Engineer",
  role_name: "Platform Engineer",
  role_id: "r2",
  company_name: "Contoso",
  label: "Platform Engineer · Contoso",
  fit: 84,
});
const pasted = opening({
  kind: "privatePosting",
  id: "jd-1",
  title: "Staff Platform Engineer",
  role_name: null,
  role_id: null,
  company_name: "Meridian Labs",
  label: "Staff Platform Engineer · Meridian Labs",
  fit: null,
  source_kind: "pasted",
});
const targets = [northwind, acme, kestrel, platform, pasted];

function plan(target: TargetOption, id: string, at: string): PlanSummary {
  return {
    id,
    target: { kind: target.kind, id: target.id },
    label: target.label,
    version: 1,
    status: "ready",
    error: null,
    model_id: "claude-opus-5",
    created_at: at,
    drafted_at: at,
    progress: 0,
  };
}

// Northwind was worked on last, though Acme fits better.
const northwindPlan = plan(northwind, "plan-1", "2026-09-20T10:00:00Z");
const platformPlan = plan(platform, "plan-2", "2026-09-10T10:00:00Z");

function serve() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      const body =
        url === "/targets"
          ? page(targets)
          : url === "/gap-plans"
            ? page([northwindPlan, platformPlan])
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

describe("advisor screen", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
    serve();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends the user to the role map when nothing is selected", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor(null);

    expect(
      screen.getByText("Pick a role on the role map first"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open the role map" }));
    expect(shell.navigate).toHaveBeenCalledWith("roles");
  });

  it("offers only the selected role's openings, starting with the last worked on", async () => {
    const shell = renderAdvisor({ kind: "role", id: "r1" });

    const northwindChip = await screen.findByRole("button", {
      name: /Northwind Pay/,
    });
    expect(northwindChip).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Acme/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: /Kestrel/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Contoso/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Meridian Labs/ }),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(shell.setTarget).toHaveBeenCalledWith(
        "Senior Backend Engineer · Northwind Pay · 71%",
      ),
    );
  });

  it("switches tabs through the hash", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor({ kind: "role", id: "r1" });

    const tabs = await screen.findByRole("group", { name: "Advisor tabs" });
    await user.click(within(tabs).getByRole("button", { name: "Résumé" }));
    expect(shell.navigate).toHaveBeenCalledWith("advisor", { tab: "resume" });
  });

  it("moves to another role when a plan kept for it is revisited", async () => {
    const user = userEvent.setup();
    const shell = renderAdvisor({ kind: "role", id: "r1" });

    const row = (
      await screen.findByText("Platform Engineer · Contoso")
    ).closest(".history-row") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Revisit" }));
    expect(shell.navigate).toHaveBeenCalledWith("advisor", {
      focus: { kind: "role", id: "r2" },
    });
  });

  it("aims at a pasted JD on its own", async () => {
    renderAdvisor({ kind: "jd", id: "jd-1" });

    expect(
      await screen.findByRole("button", { name: /Meridian Labs/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", { name: /Northwind Pay/ }),
    ).not.toBeInTheDocument();
  });
});

describe("which opening the Advisor opens first", () => {
  const options = openingsFor({ kind: "role", id: "r1" }, targets);

  it("is the one worked on most recently", () => {
    expect(firstOpening(options, [northwindPlan], [])).toEqual({
      kind: "matchedPosting",
      id: "p1",
    });
  });

  it("is the best fit when none has been worked on", () => {
    expect(firstOpening(options, [platformPlan], [])).toEqual({
      kind: "matchedPosting",
      id: "p2",
    });
  });

  it("is the one a history entry asked for, when it is listed", () => {
    expect(
      firstOpening(options, [northwindPlan], [], {
        kind: "matchedPosting",
        id: "p4",
      }),
    ).toEqual({ kind: "matchedPosting", id: "p4" });
  });
});
