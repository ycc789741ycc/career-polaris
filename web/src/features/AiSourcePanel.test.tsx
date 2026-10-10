import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AiSource } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import {
  AiSourcePanel,
  getQuotaPercent,
  getSourceNote,
  PLATFORM_TERMS,
} from "./AiSourcePanel";

function source(overrides: Partial<AiSource> = {}): AiSource {
  return {
    source: null,
    has_credential: false,
    is_platform_on: true,
    is_eligible: true,
    platform_model: "claude-haiku-4-5",
    has_accepted_platform_terms: false,
    platform_quota: {
      allowed_usd: "2",
      spent_usd: "0.5",
      remaining_usd: "1.5",
    },
    ...overrides,
  };
}

type Sent = { method: string; body: unknown };

function serve(first: AiSource, after: AiSource = first): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      sent.push({
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      const body = sent.some((s) => s.method === "PUT") ? after : first;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return sent;
}

function renderPanel() {
  const refresh = vi.fn(async () => {});
  const shell: Shell = {
    status: { me: null, credential: null },
    navigate: vi.fn(),
    focus: null,
    setFocus: vi.fn(),
    refresh,
    target: null,
    setTarget: vi.fn(),
    account: "maya@example.com",
    setHeading: vi.fn(),
  };
  render(
    <ShellContext.Provider value={shell}>
      <AiSourcePanel />
    </ShellContext.Provider>,
  );
  return { refresh };
}

describe("which AI runs your work", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("asks for the terms before the first switch, then switches", async () => {
    const user = userEvent.setup();
    const sent = serve(
      source(),
      source({ source: "platform", has_accepted_platform_terms: true }),
    );
    const { refresh } = renderPanel();

    const platform = await screen.findByRole("button", {
      name: "CareerPolaris's AI",
    });
    expect(platform).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: PLATFORM_TERMS }));
    await user.click(platform);

    await waitFor(() =>
      expect(sent.find((s) => s.method === "PUT")?.body).toEqual({
        source: "platform",
        accept_platform_terms: true,
      }),
    );
    expect(refresh).toHaveBeenCalled();
    expect(
      await screen.findByRole("button", { name: "CareerPolaris's AI" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("offers nothing to an account Google has not verified", async () => {
    serve(source({ is_eligible: false }));
    renderPanel();

    expect(
      await screen.findByText(/for accounts signed in with Google/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "CareerPolaris's AI" }),
    ).toBeDisabled();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("is not shown while CareerPolaris offers no AI", async () => {
    const sent = serve(source({ is_platform_on: false }));
    const { container } = render(
      <ShellContext.Provider
        value={{
          status: { me: null, credential: null },
          navigate: vi.fn(),
          focus: null,
          setFocus: vi.fn(),
          refresh: async () => {},
          target: null,
          setTarget: vi.fn(),
          account: null,
          setHeading: vi.fn(),
        }}
      >
        <AiSourcePanel />
      </ShellContext.Provider>,
    );

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("what the panel says", () => {
  it("says what runs the work now", () => {
    expect(getSourceNote(source({ source: "platform" }))).toMatch(
      /runs on CareerPolaris's AI \(claude-haiku-4-5\)/,
    );
    expect(getSourceNote(source({ source: "own" }))).toMatch(/your own key/);
    expect(getSourceNote(source())).toMatch(/Nothing is set up/);
  });

  it("measures the quota spent", () => {
    expect(
      getQuotaPercent({
        allowed_usd: "2",
        spent_usd: "0.5",
        remaining_usd: "1.5",
      }),
    ).toBe(25);
  });
});
