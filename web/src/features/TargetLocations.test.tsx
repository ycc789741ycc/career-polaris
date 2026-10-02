import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { page } from "../test/page";
import { TargetLocations } from "./TargetLocations";

type Call = { method: string; url: string; body: unknown };

const OPTIONS = [
  { name: "Remote", kind: "remote" },
  { name: "Asia-Pacific", kind: "region" },
  { name: "Europe", kind: "region" },
  { name: "Germany", kind: "country" },
  { name: "Portugal", kind: "country" },
  { name: "Singapore", kind: "country" },
  { name: "Taiwan", kind: "country" },
];

/** The api as a stand-in: the options, GET answers `saved`, PUT saves what
 * it is sent. */
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
      const sent =
        call.url === "/target-location-options"
          ? page(OPTIONS)
          : call.method === "GET"
            ? page(current)
            : current;
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

  it("adds a place picked from the list by saving the whole set", async () => {
    const calls = serve(["Germany"]);
    render(<TargetLocations />);

    await screen.findByText("1 of 3 chosen");
    await userEvent.click(screen.getByRole("button", { name: "Add Taiwan" }));

    expect(await screen.findByText("2 of 3 chosen")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      locations: ["Germany", "Taiwan"],
    });
    expect(
      screen.getByText("1 slot left. At 3, remove one to add another."),
    ).toBeInTheDocument();
  });

  it("groups the places as Remote, regions and countries", async () => {
    serve([]);
    render(<TargetLocations />);

    const regions = await screen.findByRole("group", { name: "Regions" });
    expect(
      within(regions).getByRole("button", { name: "Add Europe" }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("group", { name: "Remote" })).getByRole(
        "button",
        { name: "Add Remote" },
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("group", { name: "Countries" })).getAllByRole(
        "button",
      ),
    ).toHaveLength(4);
  });

  it("filters the list as the user types", async () => {
    serve([]);
    render(<TargetLocations />);

    await userEvent.type(await screen.findByLabelText("Find a place"), "tai");

    expect(
      screen.getByRole("button", { name: "Add Taiwan" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add Germany" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Regions" })).toBeNull();

    await userEvent.clear(screen.getByLabelText("Find a place"));
    await userEvent.type(screen.getByLabelText("Find a place"), "atlantis");
    expect(
      screen.getByText("No place matches “atlantis”."),
    ).toBeInTheDocument();
  });

  it("shows a chosen place but does not offer it twice", async () => {
    serve(["Taiwan"]);
    render(<TargetLocations />);

    expect(
      await screen.findByRole("button", { name: "Taiwan, already chosen" }),
    ).toBeDisabled();
  });

  it("removes a location with its own button", async () => {
    const calls = serve(["Germany", "Taiwan"]);
    render(<TargetLocations />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove Germany" }),
    );

    expect(await screen.findByText("1 of 3 chosen")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      locations: ["Taiwan"],
    });
  });

  it("offers no fourth location until one is removed", async () => {
    serve(["Germany", "Portugal", "Taiwan"]);
    render(<TargetLocations />);

    await screen.findByText("3 of 3 chosen");
    expect(screen.getByLabelText("Find a place")).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Add Singapore" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("At 3, remove one to add another."),
    ).toBeInTheDocument();
  });

  it("says a chosen region is not searched", async () => {
    serve(["Europe"]);
    render(<TargetLocations />);

    expect(
      await screen.findByText(
        /Regions use the postings we already have\. Pick a country/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("region")).toBeInTheDocument();
  });

  it("says nothing about regions while only countries are chosen", async () => {
    serve(["Taiwan"]);
    render(<TargetLocations />);

    await screen.findByText("1 of 3 chosen");
    expect(screen.queryByText(/Regions use the postings/)).toBeNull();
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
