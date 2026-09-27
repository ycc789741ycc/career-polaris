import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Assessment, Connection, Evidence } from "../api/types";
import { formatDate, todayUtc } from "../charts/timeline";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { Connect } from "./Connect";

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
      const body = route(call);
      return new Response(JSON.stringify(body ?? noData(call)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

/** What an unrouted call gets: no analysis yet, an empty list otherwise. */
function noData(call: Call): unknown {
  if (call.url === "/assessments/latest") return null;
  if (call.url === "/profile") return { version: 1, evidence_count: 0 };
  return [];
}

function assessment(overrides: Partial<Assessment>): Assessment {
  return {
    id: "a1",
    profile_version: 1,
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
  confidence: 0.8,
  granularity: "item",
  tally: null,
  subject: "acme/ledger",
} satisfies Evidence;

function renderConnect() {
  const shell = {
    status: { me: null, credential: null, openQuestions: 0, confidence: 0 },
    navigate: vi.fn(),
    handoff: null,
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

  it("lists only the work picked on the timeline, until asked for all", async () => {
    const today = todayUtc();
    const pr = { ...prFact, observed_on: today } satisfies Evidence;
    serve((call) => {
      if (call.url === "/connections") return [connection({})];
      if (call.url === "/evidence") return [jiraFact, pr];
      return undefined;
    });
    renderConnect();
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", {
        name: `${formatDate(today)}: acme/ledger#214 · Split the ledger writer`,
      }),
    );

    const table = screen.getByRole("table", { name: "Evidence gathered" });
    expect(within(table).queryByText("Closed ACME-1")).not.toBeInTheDocument();
    expect(within(table).getAllByText("Split the ledger writer")).toHaveLength(
      1,
    );
    expect(
      screen.getByText("Showing 1 fact: GitHub · acme/ledger#214."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show all" }));
    expect(within(table).getByText("Closed ACME-1")).toBeInTheDocument();
  });

  it("names the scores each fact backs, and lists the ones none cite", async () => {
    serve((call) => {
      if (call.url === "/connections") return [connection({})];
      if (call.url === "/evidence") return [jiraFact, prFact];
      if (call.url === "/assessments/latest")
        return assessment({
          dimensions: [
            {
              key: "delivery",
              name: "Delivery at scale",
              short_name: "Delivery",
              score: 70,
              confidence: 0.8,
              read: "",
              evidence_ids: [prFact.id],
            },
          ],
        });
      return undefined;
    });
    renderConnect();
    const user = userEvent.setup();

    const table = await screen.findByRole("table", {
      name: "Evidence gathered",
    });
    expect(
      await screen.findByText(/1 of 2 facts back a score/),
    ).toBeInTheDocument();
    const prRow = within(table)
      .getByText("Split the ledger writer")
      .closest("tr");
    expect(prRow).toHaveTextContent("Delivery");

    await user.click(
      screen.getByRole("button", { name: "Show the 1 not cited" }),
    );

    expect(within(table).getByText("Closed ACME-1")).toBeInTheDocument();
    expect(
      within(table).queryByText("Split the ledger writer"),
    ).not.toBeInTheDocument();
  });

  it("says when sources changed after the analysis", async () => {
    serve((call) => {
      if (call.url === "/evidence") return [prFact];
      if (call.url === "/assessments/latest")
        return assessment({ profile_version: 2 });
      if (call.url === "/profile") return { version: 3, evidence_count: 1 };
      return undefined;
    });
    renderConnect();

    expect(
      await screen.findByText(
        /Your sources have changed since, so newer facts are not scored yet/,
      ),
    ).toBeInTheDocument();
  });

  it("asks for an analysis before it can say what backs a score", async () => {
    serve((call) => (call.url === "/evidence" ? [prFact] : undefined));
    renderConnect();

    expect(
      await screen.findByText(
        "Run an analysis to see which facts back your scores.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "Cited by" }),
    ).not.toBeInTheDocument();
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
