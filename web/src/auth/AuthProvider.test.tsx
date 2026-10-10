import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";

/**
 * The refresh on load, under StrictMode as the SPA renders in development.
 *
 * Each refresh rotates the token, and the api revokes the whole chain when a
 * spent one comes back, so two refreshes racing on load sign the user out
 * straight after a Google sign-in lands.
 */

function configure(): void {
  (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = {
    apiBaseUrl: "http://api.test",
    privacyContactEmail: "privacy@example.test",
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function Status() {
  const { status, email } = useAuth();
  return <p>{status === "signed-in" ? `signed in as ${email}` : status}</p>;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  configure();
  fetchMock = vi.fn(async () =>
    jsonResponse({
      account_id: "11111111-1111-1111-1111-111111111111",
      email: "maya@example.com",
      access_token: "an-access-token",
      expires_in: 900,
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ =
    undefined;
});

function refreshCalls(): number {
  return fetchMock.mock.calls.filter(([input]) =>
    String(input).endsWith("/auth/refresh"),
  ).length;
}

describe("AuthProvider on load", () => {
  it("exchanges the refresh cookie once under StrictMode and stays signed in", async () => {
    render(
      <StrictMode>
        <AuthProvider>
          <Status />
        </AuthProvider>
      </StrictMode>,
    );

    expect(
      await screen.findByText("signed in as maya@example.com"),
    ).toBeInTheDocument();
    expect(refreshCalls()).toBe(1);
  });

  it("is signed out when there is no refresh cookie", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse({ error: { code: "unauthenticated", message: "no" } }, 401),
    );

    render(
      <StrictMode>
        <AuthProvider>
          <Status />
        </AuthProvider>
      </StrictMode>,
    );

    await waitFor(() =>
      expect(screen.getByText("signed-out")).toBeInTheDocument(),
    );
    expect(refreshCalls()).toBe(1);
  });
});
