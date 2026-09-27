import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TargetOption } from "../api/types";
import { OwnJdPanel } from "./OwnJd";

const pasted: TargetOption = {
  kind: "privatePosting",
  id: "jd-1",
  title: "Staff Platform Engineer",
  role_name: null,
  role_id: null,
  company_name: "Meridian Labs",
  label: "Staff Platform Engineer · Meridian Labs",
  fit: null,
  salary: null,
  source_kind: "pasted",
  url: null,
  subscription_id: null,
};

type Call = { method: string; url: string; body: unknown };

function serve() {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      calls.push({
        method: init?.method ?? "GET",
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      return new Response(
        JSON.stringify(url === "/job-descriptions" ? { id: "jd-2" } : null),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );
  return calls;
}

function renderPanel(selectedId: string | null = null) {
  const onSelect = vi.fn();
  const onAdded = vi.fn(async () => {});
  render(
    <OwnJdPanel
      pasted={[pasted]}
      selectedId={selectedId}
      error={null}
      onSelect={onSelect}
      onAdded={onAdded}
    />,
  );
  return { onSelect, onAdded };
}

describe("my own JD on the role map", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("saves a pasted JD privately and hands it back to be selected", async () => {
    const calls = serve();
    const user = userEvent.setup();
    const { onAdded } = renderPanel();

    await user.click(screen.getByRole("button", { name: "Use a sample" }));
    await user.click(screen.getByRole("button", { name: "Add JD" }));

    expect(calls).toContainEqual(
      expect.objectContaining({
        method: "POST",
        url: "/job-descriptions",
        body: expect.objectContaining({
          title: "Staff Platform Engineer",
          company_name: "Meridian Labs",
        }),
      }),
    );
    expect(onAdded).toHaveBeenCalledWith("jd-2");
  });

  it("asks for a title and company before saving", async () => {
    const calls = serve();
    const user = userEvent.setup();
    renderPanel();

    await user.type(
      screen.getByRole("textbox", { name: "Job description" }),
      "Lead a platform team.",
    );
    await user.click(screen.getByRole("button", { name: "Add JD" }));

    expect(
      await screen.findByText("Give the posting a title and a company first."),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("selects a saved JD without aiming the Advisor at it", async () => {
    serve();
    const user = userEvent.setup();
    const { onSelect } = renderPanel("jd-1");

    const chip = screen.getByRole("button", { name: /Meridian Labs/ });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    await user.click(chip);
    expect(onSelect).toHaveBeenCalledWith("jd-1");
    expect(
      screen.queryByRole("button", { name: /Tailor|Plan a route|Target/ }),
    ).not.toBeInTheDocument();
  });
});
