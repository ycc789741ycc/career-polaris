import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { page } from "../test/page";
import { TargetLocations } from "./TargetLocations";

type Call = { method: string; url: string; body: unknown };

/** The api as a stand-in: GET answers `saved`, PUT saves what it is sent. */
function serve(saved: string[]) {
  const calls: Call[] = [];
  let current = saved;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call = {
        method: init?.method ?? "GET",
        url: String(input).replace("http://api.test/api/v1", ""),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      };
      calls.push(call);
      if (call.method === "PUT") {
        current = [...(call.body as { locations: string[] }).locations].sort();
      }
      const sent = call.method === "GET" ? page(current) : current;
      return new Response(JSON.stringify(sent), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

describe("where you want to work", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("adds a location by saving the whole set", async () => {
    const calls = serve(["Berlin"]);
    render(<TargetLocations />);

    await screen.findByText("1 of 3 chosen");
    await userEvent.type(screen.getByLabelText("Add a location"), "Remote EU");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByText("2 of 3 chosen")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      locations: ["Berlin", "Remote EU"],
    });
    expect(
      screen.getByText("1 slot left. At 3, remove one to add another."),
    ).toBeInTheDocument();
  });

  it("removes a location with its own button", async () => {
    const calls = serve(["Berlin", "Remote EU"]);
    render(<TargetLocations />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove Berlin" }),
    );

    expect(await screen.findByText("1 of 3 chosen")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      locations: ["Remote EU"],
    });
  });

  it("offers no fourth location until one is removed", async () => {
    serve(["Berlin", "Lisbon", "Remote EU"]);
    render(<TargetLocations />);

    await screen.findByText("3 of 3 chosen");
    expect(screen.getByLabelText("Add a location")).toBeDisabled();
    expect(
      screen.getByText("At 3, remove one to add another."),
    ).toBeInTheDocument();
  });

  it("says the baseline is used while nothing is chosen", async () => {
    serve([]);
    render(<TargetLocations />);

    expect(
      await screen.findByText(
        /None chosen yet: the role map uses the platform's baseline postings/,
      ),
    ).toBeInTheDocument();
  });
});
