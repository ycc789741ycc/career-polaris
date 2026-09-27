import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Connection, Evidence } from "../api/types";
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
      return new Response(JSON.stringify(route(call)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

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
      return [];
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
      return [];
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
      call.url === "/connections" ? [connection({})] : [],
    );
    renderConnect();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Disconnect" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });
});
