import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OwnPosting } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { draftIsReady, OwnPostingForm, statusLine } from "./OwnPosting";

function own(overrides: Partial<OwnPosting> = {}): OwnPosting {
  return {
    private_job_posting_id: "j1",
    title: "Staff Platform Engineer",
    company_name: "Meridian Labs",
    source: "pasted",
    filename: null,
    status: "ready",
    error_code: null,
    error_message: null,
    fit: 64,
    is_stale: false,
    scored_at: "2026-10-03T09:00:00Z",
    ...overrides,
  };
}

const estimate = {
  cost_usd: "0.22",
  model_id: "claude-opus-5",
  rate_is_published: true,
};

type Sent = { url: string; body: BodyInit | null | undefined };

function serve(): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      sent.push({ url, body: init?.body });
      const body = url.endsWith("estimate")
        ? estimate
        : own({ source: "uploaded", filename: "jd.pdf", status: "running" });
      return new Response(JSON.stringify(body), {
        status: url.endsWith("estimate") ? 200 : 202,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return sent;
}

/** The request sent n-th; fails the test if there was none. */
function nth(sent: Sent[], n: number): Sent {
  const found = sent[n];
  if (!found) throw new Error(`no request number ${n}`);
  return found;
}

function renderForm(onAdded = vi.fn(async () => {})) {
  const shell: Shell = {
    status: { me: null, credential: null },
    navigate: vi.fn(),
    focus: null,
    setFocus: vi.fn(),
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
  };
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <OwnPostingForm onAdded={onAdded} />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return onAdded;
}

describe("a posting of your own, pasted or uploaded", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("is uploaded as a file, priced first, with its title beside it", async () => {
    const sent = serve();
    const user = userEvent.setup();
    const onAdded = renderForm();
    const file = new File(["Own the ledger."], "jd.pdf", {
      type: "application/pdf",
    });

    await user.click(screen.getByRole("button", { name: "Upload a file" }));
    expect(screen.queryByLabelText("Job description")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Job title"), "Staff Engineer");
    await user.upload(screen.getByLabelText("Job description file"), file);
    await user.click(screen.getByRole("button", { name: "Read and score it" }));

    expect(await screen.findByText(/at most/)).toHaveTextContent("$0.22");
    expect(nth(sent, 0).url).toBe("/own-postings/upload-estimate");
    expect(JSON.parse(String(nth(sent, 0).body))).toEqual({
      title: "Staff Engineer",
      company_name: null,
    });

    await user.click(screen.getByRole("button", { name: "Run it" }));

    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(nth(sent, 1).url).toBe("/own-postings/upload");
    const form = nth(sent, 1).body as FormData;
    expect(form.get("title")).toBe("Staff Engineer");
    expect(form.get("company_name")).toBeNull();
    expect((form.get("file") as File).name).toBe("jd.pdf");
  });

  it("is pasted as text by default", async () => {
    const sent = serve();
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText("Job title"), "Staff Engineer");
    await user.type(screen.getByLabelText("Job description"), "Own it.");
    await user.click(screen.getByRole("button", { name: "Read and score it" }));

    await screen.findByText(/about/);
    expect(nth(sent, 0).url).toBe("/own-postings/cost-estimate");
  });

  it("needs a title, and the JD or the file the chosen way asks for", () => {
    const empty = { title: "", company: "", jd: "", file: null };
    const file = new File(["x"], "jd.txt", { type: "text/plain" });

    expect(
      draftIsReady({ ...empty, title: "Staff", jd: "Own it." }, "paste"),
    ).toBe(true);
    expect(draftIsReady({ ...empty, title: "Staff", file }, "paste")).toBe(
      false,
    );
    expect(draftIsReady({ ...empty, title: "Staff", file }, "upload")).toBe(
      true,
    );
    expect(draftIsReady({ ...empty, file }, "upload")).toBe(false);
  });

  it("says it reads an uploaded file before scoring it", () => {
    expect(
      statusLine(
        own({
          source: "uploaded",
          filename: "jd.pdf",
          status: "running",
          fit: null,
        }),
      ),
    ).toBe("Reading jd.pdf, then scoring it…");
    expect(statusLine(own({ status: "running", fit: null }))).toBe(
      "Reading and scoring it…",
    );
  });
});
