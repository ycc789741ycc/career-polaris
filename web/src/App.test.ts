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
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("averages confidence across dimensions and asks nothing about questions", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/questions")) throw new Error("no questions route");
        if (url.endsWith("/assessments/latest"))
          return json({
            dimensions: [{ confidence: 0.8 }, { confidence: 0.9 }],
          });
        if (url.endsWith("/ai-credential")) return json(null);
        return json({ id: "u1", email: "maya@example.com" });
      }),
    );

    const status = await loadStatus();

    expect(status.confidence).toBe(85);
    expect(status.credential).toBeNull();
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
    expect(status.confidence).toBeNull();
    expect(status.me?.email).toBe("maya@example.com");
  });
});
