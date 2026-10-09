import "@testing-library/jest-dom/vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OwnPosting } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import {
  draftIsReady,
  OwnRole,
  requirementLines,
  roleLine,
  statusLine,
} from "./OwnRole";
import { getStoredTargets } from "./advisorTarget";

function own(overrides: Partial<OwnPosting> = {}): OwnPosting {
  return {
    private_job_posting_id: "j1",
    title: "Principal Engineer",
    company_name: "Halden Labs",
    source: "uploaded",
    filename: "halden.pdf",
    has_estimated_requirements: false,
    created_at: "2026-09-12T09:00:00Z",
    status: null,
    error_code: null,
    error_message: null,
    fit: null,
    is_stale: false,
    scored_at: null,
    ...overrides,
  };
}

type Sent = { method: string; url: string; body: BodyInit | null | undefined };

function serve(estimate = "0.06"): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      const method = init?.method ?? "GET";
      sent.push({ method, url, body: init?.body });
      const body = url.endsWith("/target-estimate?with_questions=true")
        ? {
            cost_usd: estimate,
            model_id: "claude-opus-5",
            rate_is_published: true,
          }
        : method === "DELETE"
          ? null
          : own({
              title: "Platform Lead",
              status: url.endsWith("/target") ? "running" : null,
            });
      return new Response(method === "DELETE" ? null : JSON.stringify(body), {
        status: method === "DELETE" ? 204 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return sent;
}

function renderOwnRole(postings: OwnPosting[] = [own()]) {
  const reload = vi.fn(async () => {});
  const shell: Shell = {
    status: { me: null, credential: null },
    navigate: vi.fn(),
    focus: null,
    setFocus: vi.fn(),
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
    account: "maya@example.com",
    setHeading: vi.fn(),
  };
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <OwnRole
          own={{ data: postings, reload }}
          currentTarget="Staff Backend Engineer"
        />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return { shell, reload };
}

function posted(sent: Sent[], url: string): Sent | undefined {
  return sent.find((s) => s.method === "POST" && s.url === url);
}

describe("bringing a role of your own", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("adds a role filled in by hand without pricing or spending anything", async () => {
    const user = userEvent.setup();
    const sent = serve();
    const { reload } = renderOwnRole([]);

    const add = screen.getByRole("button", { name: "Add to my roles" });
    expect(add).toBeDisabled();
    await user.type(screen.getByLabelText(/Job title/), "Platform Lead");
    await user.type(
      screen.getByLabelText(/What the role asks for/),
      "Leads platform teams{enter}{enter}Owns uptime",
    );
    await user.click(add);

    await waitFor(() => expect(reload).toHaveBeenCalled());
    const request = posted(sent, "/own-postings");
    expect(JSON.parse(String(request?.body))).toEqual({
      title: "Platform Lead",
      company_name: null,
      requirements: ["Leads platform teams", "Owns uptime"],
    });
    expect(sent.some((s) => s.url.includes("estimate"))).toBe(false);
  });

  it("adds an uploaded job description with no title of its own", async () => {
    const sent = serve();
    const { reload } = renderOwnRole([]);

    const file = new File(["Own the ledger."], "halden.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(screen.getByLabelText("Job description file"), {
      target: { files: [file] },
    });
    expect(screen.getByText("halden.pdf")).toBeInTheDocument();
    expect(screen.getByLabelText(/What the role asks for/)).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Add to my roles" }));

    await waitFor(() => expect(reload).toHaveBeenCalled());
    const body = posted(sent, "/own-postings/upload")?.body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("file")).toBeInstanceOf(File);
    expect((body as FormData).get("title")).toBeNull();
  });

  it("prices setting a role as target, then opens Fill the gap for it", async () => {
    const user = userEvent.setup();
    const sent = serve("0.06");
    const { shell, reload } = renderOwnRole();

    expect(
      screen.getByText(/It replaces Staff Backend Engineer as your target\./),
    ).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "My roles" });
    await user.click(
      within(list).getByRole("button", { name: "Set as target" }),
    );

    expect(
      await screen.findByRole("region", { name: "Cost estimate" }),
    ).toHaveTextContent("$0.06");
    expect(
      posted(sent, "/own-postings/j1/target?write_questions=true"),
    ).toBeUndefined();

    await user.click(screen.getByRole("button", { name: "Run it" }));

    await waitFor(() =>
      expect(shell.navigate).toHaveBeenCalledWith("advisor", {
        tab: "gaps",
        focus: { posting: "j1" },
      }),
    );
    expect(
      posted(sent, "/own-postings/j1/target?write_questions=true"),
    ).toBeDefined();
    expect(reload).toHaveBeenCalled();
    // The target from now on, even while it is still being scored.
    expect(getStoredTargets("maya@example.com").current).toEqual({
      role_id: null,
      job_posting_id: null,
      private_job_posting_id: "j1",
    });
  });

  it("skips the confirmation when the fit is current and costs nothing", async () => {
    const user = userEvent.setup();
    const sent = serve("0");
    const { shell } = renderOwnRole([own({ status: "ready", fit: 70 })]);

    await user.click(screen.getByRole("button", { name: "Set as target" }));

    await waitFor(() => expect(shell.navigate).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "Cost estimate" })).toBeNull();
    expect(
      posted(sent, "/own-postings/j1/target?write_questions=true"),
    ).toBeDefined();
  });

  it("removes a role", async () => {
    const user = userEvent.setup();
    const sent = serve();
    const { reload } = renderOwnRole();

    await user.click(
      screen.getByRole("button", { name: "Remove Principal Engineer" }),
    );

    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(
      sent.some((s) => s.method === "DELETE" && s.url === "/own-postings/j1"),
    ).toBe(true);
  });
});

describe("the own role helpers", () => {
  it("is ready with a file or a title", () => {
    const empty = { title: " ", company: "", requirements: "", file: null };
    expect(draftIsReady(empty)).toBe(false);
    expect(draftIsReady({ ...empty, title: "Lead" })).toBe(true);
    expect(draftIsReady({ ...empty, file: new File([""], "jd.txt") })).toBe(
      true,
    );
  });

  it("reads one requirement per line", () => {
    expect(requirementLines(" a \n\n b\n ")).toEqual(["a", "b"]);
  });

  it("says how a role came and where it stands", () => {
    expect(roleLine(own())).toBe("Uploaded JD · added 12 Sep 2026");
    expect(
      roleLine(
        own({
          source: "filled_in",
          company_name: "",
          has_estimated_requirements: true,
          created_at: "2026-10-01T09:00:00Z",
        }),
      ),
    ).toBe(
      "Filled in · no company · requirements estimated · added 1 Oct 2026",
    );
    expect(statusLine(own({ status: "running" }))).toBe(
      "reading halden.pdf, then scoring it…",
    );
    expect(
      statusLine(own({ status: "failed", error_message: "no text" })),
    ).toBe("no text");
    expect(statusLine(own({ fit: 60, is_stale: true }))).toBe(
      "scored against an earlier analysis",
    );
    expect(statusLine(own({ status: "ready", fit: 60 }))).toBeNull();
  });
});
