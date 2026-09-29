import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Assessment, Connection, Evidence } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { Connect } from "./Connect";
import { page } from "../test/page";

function connection(overrides: Partial<Connection>): Connection {
  return {
    kind: "jira",
    connected: true,
    account: "Ada Lovelace (ada@acme.io) · acme",
    status: "connected",
    last_synced_at: null,
    last_error: null,
    scopes: [],
    ...overrides,
  };
}

const jiraFact = {
  id: "e1",
  source: "jira",
  reference: "Jira · ACME-1",
  fact: "Closed ACME-1",
} as Evidence;

type Call = { method: string; url: string };

function serve(route: (call: Call) => unknown) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call = {
        method: init?.method ?? "GET",
        url: String(input).replace("http://api.test/api/v1", ""),
      };
      calls.push(call);
      if (call.method === "DELETE") return new Response(null, { status: 204 });
      const body = route(call) ?? noData(call);
      // Every list the API sends is a page (ADR 0014); the routes here return
      // the list itself.
      const sent =
        call.method === "GET" && Array.isArray(body) ? page(body) : body;
      return new Response(JSON.stringify(sent), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

/**
 * What an unrouted call gets: no analysis or question round yet, an empty
 * list otherwise.
 */
function noData(call: Call): unknown {
  if (call.url === "/assessments/latest") return null;
  if (call.url === "/profile") return { version: 1, evidence_count: 0 };
  return [];
}

function assessment(overrides: Partial<Assessment>): Assessment {
  return {
    id: "a1",
    profile_version: 1,
    profile_confidence: null,
    is_out_of_date: false,
    model_id: "m",
    template_version: "t",
    created_at: "2026-09-20T10:00:00Z",
    dimensions: [],
    ...overrides,
  };
}

const prFact = {
  id: "e2",
  source: "github",
  reference: "GitHub · acme/ledger#214",
  fact: "Split the ledger writer",
  observed_on: null,
  granularity: "item",
  tally: null,
  subject: "acme/ledger",
} satisfies Evidence;

function renderConnect() {
  const shell = {
    status: { me: null, credential: null },
    navigate: vi.fn(),
    focus: null,
    setFocus: vi.fn(),
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
  } as unknown as Shell;
  render(
    <ShellContext.Provider value={shell}>
      <Connect />
    </ShellContext.Provider>,
  );
}

describe("Connect", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("says which account each source is connected as", async () => {
    serve((call) => {
      if (call.url === "/connections")
        return [
          connection({}),
          connection({ kind: "github", account: null, connected: false }),
        ];
      return undefined;
    });
    renderConnect();

    expect(
      await screen.findByText("Ada Lovelace (ada@acme.io) · acme"),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Disconnect" })).toHaveLength(
      1,
    );
  });

  it("marks each source with its own logo, not letters from its name", async () => {
    serve((call) => {
      if (call.url === "/connections")
        return [
          connection({}),
          connection({ kind: "github", account: null, connected: false }),
        ];
      return undefined;
    });
    renderConnect();

    await screen.findByText("Ada Lovelace (ada@acme.io) · acme");
    expect(document.querySelector('svg[data-source="jira"]')).not.toBeNull();
    expect(document.querySelector('svg[data-source="github"]')).not.toBeNull();
    expect(screen.queryByText("Ji")).toBeNull();
    expect(screen.queryByText("Gi")).toBeNull();
  });

  it("disconnects only after confirming, then reloads", async () => {
    let connected = true;
    const calls = serve((call) => {
      if (call.url === "/connections")
        return [
          connected
            ? connection({})
            : connection({ connected: false, account: null }),
        ];
      if (call.url === "/evidence") return connected ? [jiraFact] : [];
      return undefined;
    });
    renderConnect();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Disconnect" }));
    const confirm = screen.getByRole("group", { name: "Disconnect Jira" });
    expect(confirm).toHaveTextContent("removes 1 fact gathered from Jira");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    connected = false;
    await user.click(
      within(confirm).getByRole("button", { name: "Disconnect" }),
    );

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(calls).toContainEqual({
      method: "DELETE",
      url: "/connections/jira",
    });
  });

  it("cancelling leaves the connection alone", async () => {
    const calls = serve((call) =>
      call.url === "/connections" ? [connection({})] : undefined,
    );
    renderConnect();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Disconnect" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("lists only the work in a picked repository, until asked for all", async () => {
    const ledger = {
      ...prFact,
      id: "e3",
      reference: "GitHub · acme/ledger",
      fact: "12 merged pull requests authored in acme/ledger.",
      granularity: "summary",
      tally: 12,
    } satisfies Evidence;
    serve((call) => {
      if (call.url === "/connections") return [connection({})];
      if (call.url === "/evidence") return [jiraFact, prFact, ledger];
      return undefined;
    });
    renderConnect();
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: "acme/ledger: 12" }),
    );

    const table = screen.getByRole("table", { name: "Evidence gathered" });
    expect(within(table).queryByText("Closed ACME-1")).not.toBeInTheDocument();
    expect(within(table).getAllByText("Split the ledger writer")).toHaveLength(
      1,
    );
    expect(
      screen.getByText("Showing 2 facts: acme/ledger."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show all" }));
    expect(within(table).getByText("Closed ACME-1")).toBeInTheDocument();
  });

  it("removes a résumé only after confirming, then reloads", async () => {
    let uploaded = true;
    const calls = serve((call) => {
      if (call.url === "/resumes")
        return uploaded
          ? [
              {
                id: "r1",
                filename: "cv.pdf",
                status: "parsed",
                parse_error: null,
                uploaded_at: "2026-09-20T10:00:00Z",
              },
            ]
          : [];
      return undefined;
    });
    renderConnect();
    const user = userEvent.setup();

    const listed = (await screen.findAllByText(/cv\.pdf/)).find((node) =>
      node.closest("li"),
    );
    await user.click(
      within(listed!.closest("li")!).getByRole("button", { name: "Remove" }),
    );
    const confirm = screen.getByRole("group", { name: "Remove cv.pdf" });
    expect(confirm).toHaveTextContent("the facts taken from it");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    uploaded = false;
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(calls).toContainEqual({ method: "DELETE", url: "/resumes/r1" });
    await vi.waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Remove" }),
      ).not.toBeInTheDocument(),
    );
    const reloads = calls.filter(
      (c) => c.method === "GET" && c.url === "/evidence",
    );
    expect(reloads.length).toBeGreaterThan(1);
  });

  // Step 01 shows what was collected; what the analysis made of it is
  // Strengths' to show.
  it("lists the facts without anything the analysis made of them", async () => {
    serve((call) => {
      if (call.url === "/evidence") return [jiraFact, prFact];
      if (call.url === "/assessments/latest")
        return assessment({
          is_out_of_date: true,
          dimensions: [
            {
              key: "delivery",
              name: "Delivery at scale",
              short_name: "Delivery",
              score: 70,
              confidence: 0.8,
              read: "",
              evidence_ids: [prFact.id],
              needs_more_evidence: false,
            },
          ],
        });
      return undefined;
    });
    renderConnect();

    const table = await screen.findByRole("table", {
      name: "Evidence gathered",
    });
    expect(
      within(table).getByText("Split the ledger writer"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "Cited by" }),
    ).not.toBeInTheDocument();
    expect(within(table).queryByText("Delivery")).not.toBeInTheDocument();
    expect(screen.queryByText(/back a score/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/evidence has changed since/),
    ).not.toBeInTheDocument();
  });

  it("filters the facts by source, and all brings them back", async () => {
    serve((call) =>
      call.url === "/evidence" ? [jiraFact, prFact] : undefined,
    );
    renderConnect();
    const user = userEvent.setup();

    const filters = await screen.findByRole("group", {
      name: "Filter by source",
    });
    const table = screen.getByRole("table", { name: "Evidence gathered" });
    expect(
      within(filters).getByRole("button", { name: "All · 2" }),
    ).toHaveAttribute("aria-pressed", "true");

    await user.click(within(filters).getByRole("button", { name: "Jira · 1" }));
    expect(within(table).getByText("Closed ACME-1")).toBeInTheDocument();
    expect(
      within(table).queryByText("Split the ledger writer"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("All 1 fact from Jira.")).toBeInTheDocument();

    await user.click(within(filters).getByRole("button", { name: "All · 2" }));
    expect(
      within(table).getByText("Split the ledger writer"),
    ).toBeInTheDocument();
    expect(within(table).getByText("Closed ACME-1")).toBeInTheDocument();
  });

  it("drops a picked repository when another source is filtered", async () => {
    const ledger = {
      ...prFact,
      id: "e3",
      reference: "GitHub · acme/ledger",
      fact: "12 merged pull requests authored in acme/ledger.",
      granularity: "summary",
      tally: 12,
    } satisfies Evidence;
    serve((call) =>
      call.url === "/evidence" ? [jiraFact, prFact, ledger] : undefined,
    );
    renderConnect();
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: "acme/ledger: 12" }),
    );
    const filters = screen.getByRole("group", { name: "Filter by source" });

    // The pick is GitHub's, so filtering to GitHub keeps it.
    await user.click(
      within(filters).getByRole("button", { name: "GitHub · 2" }),
    );
    expect(
      screen.getByText("Showing 2 facts: acme/ledger."),
    ).toBeInTheDocument();

    await user.click(within(filters).getByRole("button", { name: "Jira · 1" }));
    const table = screen.getByRole("table", { name: "Evidence gathered" });
    expect(
      screen.queryByText(/Showing .*acme\/ledger/),
    ).not.toBeInTheDocument();
    expect(within(table).getByText("Closed ACME-1")).toBeInTheDocument();
  });

  it("splits what it found by source", async () => {
    serve((call) =>
      call.url === "/evidence" ? [jiraFact, prFact] : undefined,
    );
    renderConnect();

    expect(
      await screen.findByRole("img", {
        name: /^Facts by source: GitHub 1 \(50%\), Jira 1/,
      }),
    ).toBeInTheDocument();
  });
});
