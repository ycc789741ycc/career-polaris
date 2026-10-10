import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AiSource, Budget, Credential } from "../api/types";
import {
  getAiRunsSettled,
  getQuotaLabel,
  getQuotaPercent,
  ShellContext,
  type Shell,
} from "../shell/ShellContext";
import { AiSettings, getQuotaLine, getSelectedSource } from "./AiSettings";

function source(overrides: Partial<AiSource> = {}): AiSource {
  return {
    source: "platform",
    has_credential: false,
    is_platform_on: true,
    is_eligible: true,
    platform_quota: {
      allowed_usd: "2",
      spent_usd: "0.5",
      remaining_usd: "1.5",
    },
    ...overrides,
  };
}

const KEY: Credential = {
  provider: "anthropic",
  model: "claude-opus-5",
  base_url: null,
  last_four: "abcd",
  status: "active",
  last_error: null,
};

const BUDGET: Budget = {
  monthly_cap_usd: "20",
  spent_this_month_usd: "3.10",
  remaining_usd: "16.90",
};

type Sent = { method: string; url: string; body: unknown };

/** Stands in for the API: `/ai-source` answers `first`, then `after` once
 * anything has been saved. */
function serve(
  first: AiSource,
  after: AiSource = first,
  credential: Credential | null = null,
): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      const method = init?.method ?? "GET";
      sent.push({
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      const saved = sent.some((s) => s.method === "PUT");
      const body =
        url === "/ai-source"
          ? saved
            ? after
            : first
          : url === "/ai-credential"
            ? method === "PUT"
              ? KEY
              : credential
            : url === "/ai-budget"
              ? BUDGET
              : url === "/ai-providers"
                ? { anthropic: ["claude-opus-5"], openai: ["gpt-5.1"] }
                : null;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return sent;
}

function renderSettings() {
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
  const view = render(
    <ShellContext.Provider value={shell}>
      <AiSettings />
    </ShellContext.Provider>,
  );
  return { refresh, ...view };
}

function puts(sent: Sent[], url: string): Sent[] {
  return sent.filter((s) => s.method === "PUT" && s.url === url);
}

describe("AI settings, by which AI runs the work", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("on CareerPolaris AI shows the quota only: no key, no budget, no model", async () => {
    serve(source());
    const { container } = renderSettings();

    expect(
      await screen.findByText(
        "25% of this month's free quota used · 75% left. It starts again on the 1st.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: /CareerPolaris AI/ }),
    ).toBeChecked();
    expect(
      screen.queryByRole("heading", { name: "Your provider and key" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Monthly budget" }),
    ).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/claude|gpt|gemini|\$/);
  });

  it("on one's own provider shows the key and the budget, and no quota", async () => {
    serve(source({ source: "own", has_credential: true }), undefined, KEY);
    renderSettings();

    expect(
      await screen.findByRole("heading", { name: "Your provider and key" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Monthly budget" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/free quota used/)).not.toBeInTheDocument();
  });

  it("switches to CareerPolaris AI at once, with nothing to accept", async () => {
    const user = userEvent.setup();
    const sent = serve(
      source({ source: "own", has_credential: true }),
      source(),
      KEY,
    );
    const { refresh } = renderSettings();

    await user.click(
      await screen.findByRole("radio", { name: /CareerPolaris AI/ }),
    );

    await waitFor(() =>
      expect(puts(sent, "/ai-source").map((s) => s.body)).toEqual([
        { source: "platform" },
      ]),
    );
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(
      await screen.findByText(/free quota used · 75% left/),
    ).toBeInTheDocument();
  });

  it("picking one's own provider with no key shows the form, and saving switches", async () => {
    const user = userEvent.setup();
    const sent = serve(
      source(),
      source({ source: "own", has_credential: true }),
    );
    renderSettings();

    await user.click(
      await screen.findByRole("radio", { name: /Your own provider/ }),
    );
    // Nothing switched yet: there is no key to switch to.
    expect(puts(sent, "/ai-source")).toEqual([]);
    expect(
      screen.getByRole("heading", { name: "Your provider and key" }),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText(/API key/), "sk-ant-1234");
    await user.click(screen.getByRole("button", { name: "Save key" }));

    await waitFor(() => expect(puts(sent, "/ai-credential")).toHaveLength(1));
    // Storing a key chooses it on the server (ADR 0066); no second call.
    expect(puts(sent, "/ai-source")).toEqual([]);
    expect(
      await screen.findByRole("radio", { name: /Your own provider/ }),
    ).toBeChecked();
  });

  it("offers CareerPolaris AI only to an account Google has verified", async () => {
    serve(source({ source: null, is_eligible: false, platform_quota: null }));
    renderSettings();

    const platform = await screen.findByRole("radio", {
      name: /CareerPolaris AI/,
    });
    expect(platform).toBeDisabled();
    expect(
      screen.getByText(/For accounts signed in with Google/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Your provider and key" }),
    ).toBeInTheDocument();
  });

  it("has no choice to make while CareerPolaris offers no AI", async () => {
    serve(
      source({ source: "own", is_platform_on: false, platform_quota: null }),
      undefined,
      KEY,
    );
    renderSettings();

    expect(
      await screen.findByRole("heading", { name: "Your provider and key" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  });
});

describe("what the page works out", () => {
  it("shows the card just picked, else the source in use, else one's own", () => {
    expect(getSelectedSource(source(), null)).toBe("platform");
    expect(getSelectedSource(source(), "own")).toBe("own");
    expect(getSelectedSource(source({ source: null }), null)).toBe("own");
    expect(getSelectedSource(null, null)).toBe("own");
  });

  it("says the quota in percentages, never dollars or the model", () => {
    const line = getQuotaLine({
      allowed_usd: "2",
      spent_usd: "0.5",
      remaining_usd: "1.5",
    });
    expect(line).toBe(
      "25% of this month's free quota used · 75% left. It starts again on the 1st.",
    );
    expect(
      getQuotaLine({ allowed_usd: "2", spent_usd: "2", remaining_usd: "0" }),
    ).toMatch(/free quota is used up.*your own provider/);
  });

  it("measures the quota in whole percentages that add up to 100", () => {
    const quota = (spent: string) => ({
      allowed_usd: "2",
      spent_usd: spent,
      remaining_usd: "0",
    });
    expect(getQuotaPercent(quota("0.5"))).toBe(25);
    expect(getQuotaLabel(quota("0.333"))).toEqual({ used: 17, left: 83 });
    expect(getQuotaLabel(quota("2.4"))).toEqual({ used: 100, left: 0 });
  });

  it("counts finished runs that spend AI, and not syncs", () => {
    expect(
      getAiRunsSettled({ sources: 9, analysis: 1, roleMap: 2, advisor: 3 }),
    ).toBe(6);
  });
});
