import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { QuestionSet } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { FillTheGap, submitNote } from "./FillTheGap";
import type { AdvisorTarget } from "./target";

const target: AdvisorTarget = {
  ref: { role_id: "r1", job_posting_id: null },
  label: "Staff Backend Engineer · Northwind Pay",
  roleName: "Staff Backend Engineer",
  company: "Northwind Pay",
  location: null,
  postingTitle: null,
  url: null,
  fit: 86,
  band: null,
  isCustom: false,
};

const ready: QuestionSet = {
  id: "s1",
  target: { role_id: "r1", job_posting_id: null },
  label: target.label,
  status: "ready",
  gaps: [
    {
      key: "dim:incidents",
      label: "Own incidents end to end",
      status: "partial",
      lift: 9,
    },
    {
      key: "req:multi-region",
      label: "Multi-region capacity planning",
      status: "no_evidence",
      lift: 4,
    },
  ],
  questions: [
    {
      id: "q1",
      gap_key: "dim:incidents",
      text: "Have you been on an on-call rotation?",
      asked_because: "Incident response rests on one review.",
      answer_type: "choice",
      choices: ["Yes, as primary", "As secondary", "Never"],
      evidence_id: null,
    },
    {
      id: "q2",
      gap_key: "dim:incidents",
      text: "Have you led an incident response?",
      asked_because: "Staff postings ask for rotation ownership.",
      answer_type: "both",
      choices: ["Yes", "Not yet"],
      evidence_id: null,
    },
    {
      id: "q3",
      gap_key: "req:multi-region",
      text: "Have you planned capacity across regions?",
      asked_because: "Nothing in your sources speaks to it.",
      answer_type: "free_text",
      choices: [],
      evidence_id: null,
    },
  ],
  model_id: "claude-sonnet-5",
  error: null,
  created_at: "2026-09-29T10:00:00Z",
  submitted_at: null,
};

type Call = { method: string; url: string; body: unknown };

function serve(route: (call: Call) => unknown) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call = {
        method: init?.method ?? "GET",
        url: String(input).replace("http://api.test/api/v1", ""),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      };
      calls.push(call);
      return new Response(JSON.stringify(route(call) ?? null), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

function renderGaps(onSubmitted = vi.fn()) {
  const shell = {
    status: {
      me: null,
      credential: { provider: "anthropic", model: "claude-sonnet-5" },
      confidence: null,
    },
    navigate: vi.fn(),
  } as unknown as Shell;
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <FillTheGap target={target} onSubmitted={onSubmitted} />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return { onSubmitted };
}

describe("Fill the gap", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("prices the questions before any are written", async () => {
    const calls = serve((call) => {
      if (call.url.startsWith("/gap-question-sets/cost-estimate"))
        return { cost_usd: "0.03", model_id: "claude-sonnet-5" };
      if (call.method === "POST") return { ...ready, status: "writing" };
      return null;
    });
    const user = userEvent.setup();
    renderGaps();

    await user.click(
      await screen.findByRole("button", { name: "Write questions" }),
    );
    const confirm = await screen.findByRole("region", {
      name: "Cost estimate",
    });
    expect(confirm).toHaveTextContent("$0.03");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.click(within(confirm).getByRole("button", { name: "Run it" }));
    expect(calls).toContainEqual({
      method: "POST",
      url: "/gap-question-sets",
      body: { role_id: "r1", job_posting_id: null },
    });
  });

  it("shows each gap with what it is worth and why each question is asked", async () => {
    serve((call) =>
      call.url.startsWith("/gap-question-sets/current") ? ready : null,
    );
    renderGaps();

    const card = await screen.findByRole("group", {
      name: "Own incidents end to end",
    });
    expect(card).toHaveTextContent("Partial");
    expect(card).toHaveTextContent("up to +9 fit pts");
    expect(card).toHaveTextContent(
      "Asked because: Incident response rests on one review.",
    );
    expect(
      screen.getByRole("group", { name: "Multi-region capacity planning" }),
    ).toHaveTextContent("No evidence");
  });

  it("submits every answer at once, leaving a blank one as a gap", async () => {
    const onSubmitted = vi.fn();
    const calls = serve((call) => {
      if (call.url.startsWith("/gap-question-sets/current")) return ready;
      if (call.url.endsWith("/submit-estimate"))
        return {
          cost_usd: "0.12",
          model_id: "claude-sonnet-5",
          regenerates_plan: true,
          regenerates_resume: true,
        };
      if (call.url === "/gap-question-sets/s1/answers")
        return { set_id: "s1", answered: 2, skipped: 1 };
      if (call.url === "/gap-question-sets/s1")
        return { ...ready, submitted_at: "2026-09-29T10:05:00Z" };
      return null;
    });
    const user = userEvent.setup();
    renderGaps(onSubmitted);

    await user.click(
      await screen.findByRole("button", { name: "Yes, as primary" }),
    );
    await user.click(screen.getByRole("button", { name: "Yes" }));
    await user.type(
      screen.getByLabelText(
        "Your answer to Have you led an incident response?",
      ),
      "The Feb payment outage.",
    );
    const bar = screen.getByRole("region", { name: "Submit answers" });
    expect(bar).toHaveTextContent("2 of 3 answered");
    expect(
      await within(bar).findByText(/updates the gap plan and the résumé/),
    ).toHaveTextContent("about $0.12");

    await user.click(
      within(bar).getByRole("button", { name: "Submit answers" }),
    );

    expect(
      calls.find((c) => c.url === "/gap-question-sets/s1/answers")?.body,
    ).toEqual({
      answers: [
        { question_id: "q1", choice: "Yes, as primary", text: null },
        { question_id: "q2", choice: "Yes", text: "The Feb payment outage." },
      ],
    });
    expect(await screen.findByText(/2 answers added/)).toBeInTheDocument();
    expect(onSubmitted).toHaveBeenCalled();
  });
});

describe("what submitting says it does", () => {
  it("names only what will be written again", () => {
    expect(submitNote(null)).toBe("Submitting adds your answers to Sources.");
    expect(
      submitNote({
        cost_usd: "0.05",
        model_id: "m",
        regenerates_plan: true,
        regenerates_resume: false,
      }),
    ).toBe(
      "Submitting adds your answers to Sources and updates the gap plan · about $0.05 on your key",
    );
  });
});
