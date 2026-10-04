import { describe, expect, it, vi } from "vitest";
import { api } from "./client";

/**
 * The regression this guards: resolving configuration while this module is
 * imported made a bad value throw during import-graph evaluation, before any
 * error handling could run, and the page rendered nothing at all.
 */
describe("api client", () => {
  it("does not read configuration at import time", () => {
    // The import above already happened with no window.__APP_CONFIG__ set.
    // Reaching this line at all is the assertion.
    expect(api).toBeDefined();
  });

  it("reads configuration on the first request, not before", async () => {
    (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/health");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/api/v1/health",
      expect.anything(),
    );
    vi.unstubAllGlobals();
  });
});

describe("server-sent events", () => {
  it("splits complete events and keeps a partial one for later", async () => {
    const { parseEvents } = await import("./client");
    const { events, rest } = parseEvents(
      'event: text\ndata: {"text":"Hi"}\n\nevent: proposal\r\ndata: {"a":1}\r\n\r\nevent: te',
    );
    expect(events).toEqual([
      { event: "text", data: '{"text":"Hi"}' },
      { event: "proposal", data: '{"a":1}' },
    ]);
    expect(rest).toBe("event: te");
  });
});

describe("a refused request", () => {
  async function refusal(response: Response): Promise<unknown> {
    (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    try {
      await api.post("/connections/github/sync", {});
      return null;
    } catch (error) {
      return error;
    } finally {
      vi.unstubAllGlobals();
    }
  }

  it("keeps the app's own message, which says when to try again", async () => {
    const error = await refusal(
      new Response(
        JSON.stringify({
          error: {
            code: "rate_limited",
            message:
              "You have synced as often as one hour allows. Try again in 40 minutes.",
          },
        }),
        { status: 429, headers: { "retry-after": "2400" } },
      ),
    );

    expect(error).toMatchObject({
      code: "rate_limited",
      status: 429,
      message:
        "You have synced as often as one hour allows. Try again in 40 minutes.",
    });
  });

  it("says when to try again after the edge's own 429, which has no body", async () => {
    const error = await refusal(
      new Response("", { status: 429, headers: { "retry-after": "60" } }),
    );

    expect(error).toMatchObject({
      status: 429,
      message: "Too many requests. Try again in a minute.",
    });
  });

  it("says a file is too large when the edge refuses its body", async () => {
    const error = await refusal(new Response("", { status: 413 }));

    expect(error).toMatchObject({
      message: "That file is too large to upload.",
    });
  });

  it("reads an error page that is not JSON without failing", async () => {
    const error = await refusal(
      new Response("<html>Bad Gateway</html>", { status: 502 }),
    );

    expect(error).toMatchObject({
      status: 502,
      message: "The server is not answering. Try again in a moment.",
    });
  });
});

describe("how long to wait", () => {
  it("rounds up to whole minutes and hours", async () => {
    const { getWaitLabel } = await import("./client");
    expect([30, 61, 3600, 3601].map(getWaitLabel)).toEqual([
      "a minute",
      "2 minutes",
      "an hour",
      "2 hours",
    ]);
  });
});
