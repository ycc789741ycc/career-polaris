import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadStatus } from "./App";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("shell status", () => {
  beforeEach(() => {
    (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("reads the account, the credential and which AI runs, and nothing about the analysis", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/ai-credential")) return json(null);
      if (url.endsWith("/ai-source")) return json(null);
      return json({ id: "u1", email: "maya@example.com" });
    });
    vi.stubGlobal("fetch", fetch);

    const status = await loadStatus();

    expect(status).toEqual({
      me: { id: "u1", email: "maya@example.com" },
      credential: null,
      aiSource: null,
    });
    const urls = fetch.mock.calls.map(([input]) => String(input));
    expect(urls.some((url) => /assessments|questions/.test(url))).toBe(false);
  });

  it("keeps the rest when one piece fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).endsWith("/ai-credential")
          ? json({ error: { code: "internal", message: "boom" } }, 500)
          : String(input).endsWith("/me")
            ? json({ id: "u1", email: "maya@example.com" })
            : json(null),
      ),
    );

    const status = await loadStatus();

    expect(status.credential).toBeNull();
    expect(status.me?.email).toBe("maya@example.com");
  });
});
