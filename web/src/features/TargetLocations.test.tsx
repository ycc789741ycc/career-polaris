import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
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

describe("where you want to work, in one line", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("is one line: the label, the chips and + Add, no panel heading", async () => {
    serve(["Germany", "Taiwan"]);
    render(<TargetLocations note="1,284 open postings" />);

    const line = await screen.findByRole("region", {
      name: "Where you want to work",
    });
    expect(
      await within(line).findByRole("button", { name: "Remove Germany" }),
    ).toBeInTheDocument();
    expect(within(line).getByRole("button", { name: "+ Add" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(within(line).getByText("1,284 open postings")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).toBeNull();
    // The list stays closed until asked for.
    expect(screen.queryByLabelText("Find a place")).toBeNull();
  });

  it("adds a place from the dropdown by saving the whole set, then closes it", async () => {
    const calls = serve(["Germany"]);
    const onSaved = vi.fn();
    render(<TargetLocations onSaved={onSaved} />);

    await userEvent.click(await screen.findByRole("button", { name: "+ Add" }));
    expect(screen.getByRole("dialog", { name: "Add a place" })).toBeVisible();
    expect(screen.getByRole("button", { name: "+ Add" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add Taiwan" }));

    expect(
      await screen.findByRole("button", { name: "Remove Taiwan" }),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      locations: ["Germany", "Taiwan"],
    });
    expect(onSaved).toHaveBeenCalledWith(["Germany", "Taiwan"]);
    expect(screen.queryByRole("dialog", { name: "Add a place" })).toBeNull();
  });

  it("closes the dropdown on Escape without saving", async () => {
    const calls = serve(["Germany"]);
    render(<TargetLocations />);

    await userEvent.click(await screen.findByRole("button", { name: "+ Add" }));
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Add a place" })).toBeNull();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("closes the dropdown on a click outside", async () => {
    serve(["Germany"]);
    render(
      <>
        <TargetLocations />
        <p>elsewhere</p>
      </>,
    );

    await userEvent.click(await screen.findByRole("button", { name: "+ Add" }));
    fireEvent.pointerDown(screen.getByText("elsewhere"));

    expect(screen.queryByRole("dialog", { name: "Add a place" })).toBeNull();
  });

  it("groups the places as Remote, regions and countries, and filters them", async () => {
    serve([]);
    render(<TargetLocations />);

    await userEvent.click(await screen.findByRole("button", { name: "+ Add" }));
    expect(
      within(screen.getByRole("group", { name: "Countries" })).getAllByRole(
        "button",
      ),
    ).toHaveLength(4);
    await userEvent.type(screen.getByLabelText("Find a place"), "tai");

    expect(
      screen.getByRole("button", { name: "Add Taiwan" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Regions" })).toBeNull();
    await userEvent.clear(screen.getByLabelText("Find a place"));
    await userEvent.type(screen.getByLabelText("Find a place"), "atlantis");
    expect(
      screen.getByText("No place matches “atlantis”."),
    ).toBeInTheDocument();
  });

  it("shows a chosen place in the list but does not offer it twice", async () => {
    serve(["Taiwan"]);
    render(<TargetLocations />);

    await userEvent.click(await screen.findByRole("button", { name: "+ Add" }));

    expect(
      screen.getByRole("button", { name: "Taiwan, already chosen" }),
    ).toBeDisabled();
  });

  it("removes a location with its own button", async () => {
    const calls = serve(["Germany", "Taiwan"]);
    render(<TargetLocations />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove Germany" }),
    );

    expect(
      await screen.findByRole("button", { name: "+ Add" }),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      locations: ["Taiwan"],
    });
  });

  it("offers no + Add at three places, and says why behind the ⓘ", async () => {
    serve(["Germany", "Portugal", "Taiwan"]);
    render(<TargetLocations />);

    await screen.findByRole("button", { name: "Remove Taiwan" });
    expect(screen.queryByRole("button", { name: "+ Add" })).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: "About where you want to work" }),
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "At 3, remove one to add another.",
    );
  });

  it("explains the places, the slots left and regions behind the ⓘ", async () => {
    serve(["Europe"]);
    render(<TargetLocations />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: "About where you want to work",
      }),
    );

    const about = screen.getByRole("note");
    expect(about).toHaveTextContent("salary bands are shown for them");
    expect(about).toHaveTextContent("2 slots left.");
    expect(about).toHaveTextContent(
      /Regions use the postings we already have\. Pick a country/,
    );
    expect(screen.getByText("region")).toBeInTheDocument();
  });

  it("says nothing about regions while only countries are chosen", async () => {
    serve(["Taiwan"]);
    render(<TargetLocations />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: "About where you want to work",
      }),
    );

    expect(screen.getByRole("note")).not.toHaveTextContent(/Regions use/);
  });

  it("says Anywhere while nothing is chosen, with the list closed", async () => {
    serve([]);
    render(<TargetLocations />);

    expect(
      await screen.findByText("Anywhere (newest baseline postings)"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Find a place")).toBeNull();
  });

  it("keeps the set as it is while a build reads it", async () => {
    serve(["Germany"]);
    render(<TargetLocations isReadOnly note="12 open postings" />);

    expect(await screen.findByText("12 open postings")).toBeInTheDocument();
    expect(await screen.findByText("Germany")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Germany" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Add" })).toBeNull();
  });
});
