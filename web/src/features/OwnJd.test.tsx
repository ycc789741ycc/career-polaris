import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TargetOption } from "../api/types";
import type { Focus } from "../shell/navigation";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { OwnJdPanel } from "./OwnJd";

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

type Call = { method: string; url: string; body: unknown };

function serve(saved: TargetOption[]) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      const method = init?.method ?? "GET";
      calls.push({
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const body =
        url === "/targets"
          ? saved
          : url === "/job-descriptions"
            ? { id: "jd-2" }
            : null;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

function renderPanel(focus: Focus | null) {
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
      <OwnJdPanel />
    </ShellContext.Provider>,
  );
  return shell;
}

describe("my own JD on the role map", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("saves a pasted JD privately and selects it for the Advisor", async () => {
    const calls = serve([]);
    const user = userEvent.setup();
    const shell = renderPanel(null);

    await user.click(screen.getByRole("button", { name: "Use a sample" }));
    await user.click(screen.getByRole("button", { name: "Save & select" }));

    expect(calls).toContainEqual(
      expect.objectContaining({
        method: "POST",
        url: "/job-descriptions",
        body: expect.objectContaining({
          title: "Staff Platform Engineer",
          company_name: "Meridian Labs",
        }),
      }),
    );
    expect(shell.setFocus).toHaveBeenCalledWith({ kind: "jd", id: "jd-2" });
  });

  it("asks for a title and company before saving", async () => {
    const calls = serve([]);
    const user = userEvent.setup();
    renderPanel(null);

    await user.type(
      screen.getByRole("textbox", { name: "Job description" }),
      "Lead a platform team.",
    );
    await user.click(screen.getByRole("button", { name: "Save & select" }));

    expect(
      await screen.findByText("Give the posting a title and a company first."),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("opens the Advisor on the selected JD", async () => {
    serve([pasted]);
    const user = userEvent.setup();
    const shell = renderPanel({ kind: "jd", id: "jd-1" });

    expect(
      await screen.findByRole("button", { name: /Meridian Labs/ }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Tailor résumé" }));
    expect(shell.navigate).toHaveBeenCalledWith("advisor", {
      tab: "resume",
      focus: { kind: "jd", id: "jd-1" },
    });
  });
});
