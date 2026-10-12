import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { QuestionSet } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { answeredFitLine, FillTheGap, readingChange } from "./FillTheGap";
import type { AdvisorTarget } from "./target";

const target: AdvisorTarget = {
  ref: { role_id: "r1", job_posting_id: null },
  label: "Staff Backend Engineer · Northwind Pay",
  roleName: "Staff Backend Engineer",
  company: "Northwind Pay",
  location: null,
  postingTitle: null,
  url: null,
  creditedTo: null,
  fit: 86,
  band: null,
  isOwnPosting: false,
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
  fit_reading: null,
  fit_reading_error: null,
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

function renderGaps(onSubmitted = vi.fn(), aimed: AdvisorTarget = target) {
  const shell = {
    status: {
      me: null,
      credential: { provider: "anthropic", model: "claude-sonnet-5" },
    },
    navigate: vi.fn(),
    refresh: async () => {},
  } as unknown as Shell;
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <FillTheGap target={aimed} onSubmitted={onSubmitted} />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return { onSubmitted };
}

describe("Fill the gap", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("for an opening, prices reading and scoring it with the questions", async () => {
    const calls = serve((call) => {
      if (call.url.startsWith("/gap-question-sets/cost-estimate"))
        return { cost_usd: "0.08", model_id: "claude-sonnet-5" };
      return null;
    });
    const user = userEvent.setup();
    renderGaps(vi.fn(), {
      ...target,
      ref: {
        role_id: "r1",
        job_posting_id: "p1",
        private_job_posting_id: null,
      },
      label: "Staff Backend Engineer · Northwind Pay",
      company: "Northwind Pay",
    });

    expect(
      await screen.findByText(/reads what this opening asks for/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Analyse the gaps" }));
    const confirm = await screen.findByRole("region", {
      name: "Cost estimate",
    });
    expect(confirm).toHaveTextContent(
      "Reading what this opening asks for, scoring your fit to it",
    );
    expect(confirm).toHaveTextContent("at most $0.08");
    expect(calls).toContainEqual({
      method: "GET",
      url: "/gap-question-sets/cost-estimate?role_id=r1&job_posting_id=p1",
      body: null,
    });
  });

  it("prices the questions before any are written", async () => {
    const calls = serve((call) => {
      if (call.url.startsWith("/gap-question-sets/cost-estimate"))
        return { cost_usd: "0.03", model_id: "claude-sonnet-5" };
      if (call.method === "POST") return { ...ready, status: "writing" };
      return null;
    });
    const user = userEvent.setup();
    renderGaps();

    expect(await screen.findByText("No gap analysis yet")).toBeInTheDocument();
    await user.click(
      await screen.findByRole("button", { name: "Analyse the gaps" }),
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

  it("submits every answer at once, priced first, and reads them into the fit", async () => {
    const onSubmitted = vi.fn();
    const calls = serve((call) => {
      if (call.url.startsWith("/gap-question-sets/current")) return ready;
      if (call.url === "/gap-question-sets/s1/fit-reading-estimate")
        return { cost_usd: "0.03", model_id: "claude-sonnet-5" };
      if (call.url === "/gap-question-sets/s1/answers")
        return { set_id: "s1", answered: 2, skipped: 1 };
      if (call.url === "/gap-question-sets/s1")
        return {
          ...ready,
          submitted_at: "2026-09-29T10:05:00Z",
          fit_reading: "reading",
        };
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
    expect(bar).toHaveTextContent("reads them into your fit");

    await user.click(
      within(bar).getByRole("button", { name: "Submit answers" }),
    );
    // On the user's own key the price is confirmed before anything is sent.
    expect(await screen.findByText(/costs at most/)).toHaveTextContent("$0.03");
    expect(calls.some((c) => c.url.endsWith("/answers"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Run it" }));

    expect(
      calls.find((c) => c.url === "/gap-question-sets/s1/answers")?.body,
    ).toEqual({
      answers: [
        { question_id: "q1", choice: "Yes, as primary", text: null },
        { question_id: "q2", choice: "Yes", text: "The Feb payment outage." },
      ],
      update_fit: true,
    });
    expect(
      await screen.findByText(/2 answers added to your evidence/),
    ).toHaveTextContent("use them once you regenerate them");
    expect(onSubmitted).toHaveBeenCalled();
  });

  it("submits without updating the fit, spending nothing", async () => {
    const calls = serve((call) => {
      if (call.url.startsWith("/gap-question-sets/current")) return ready;
      if (call.url === "/gap-question-sets/s1/answers")
        return { set_id: "s1", answered: 1, skipped: 2 };
      if (call.url === "/gap-question-sets/s1")
        return { ...ready, submitted_at: "2026-09-29T10:05:00Z" };
      return null;
    });
    const user = userEvent.setup();
    renderGaps();

    await user.click(
      await screen.findByRole("button", { name: "Yes, as primary" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Submit without updating fit" }),
    );

    const posted = calls.find((c) => c.url === "/gap-question-sets/s1/answers");
    expect(posted?.body).toMatchObject({ update_fit: false });
    expect(calls.some((c) => c.url.includes("estimate"))).toBe(false);
    expect(
      await screen.findByText(/Your fit does not count these answers yet/),
    ).toBeInTheDocument();
  });

  it("shows the fit the answers moved, and each gap they moved", async () => {
    serve((call) => {
      if (call.url.startsWith("/gap-question-sets/current"))
        return {
          ...ready,
          submitted_at: "2026-09-29T10:05:00Z",
          fit_reading: "ready",
        };
      if (call.url.startsWith("/answered-fit"))
        return {
          fit: 86,
          answered_fit: 91,
          readings: [
            {
              gap_key: "dim:incidents",
              label: "Own incidents end to end",
              score_before: 60,
              score_after: 75,
              coverage: null,
              reasoning: "Led the February outage bridge.",
            },
            {
              gap_key: "req:multi-region",
              label: "Multi-region capacity planning",
              score_before: null,
              score_after: null,
              coverage: "partly",
              reasoning: "Planned one region's failover.",
            },
          ],
        };
      return null;
    });
    renderGaps();

    const fit = await screen.findByRole("region", {
      name: "Your fit with your answers",
    });
    expect(fit).toHaveTextContent("Your fit: 86% → 91% with your answers");
    expect(fit).toHaveTextContent("Own incidents end to end 60 → 75");
    expect(fit).toHaveTextContent(
      "Multi-region capacity planning now partly covered",
    );
  });

  it("offers to read the answers again when reading them failed", async () => {
    const calls = serve((call) => {
      if (call.url.startsWith("/gap-question-sets/current"))
        return {
          ...ready,
          submitted_at: "2026-09-29T10:05:00Z",
          fit_reading: "failed",
          fit_reading_error: { code: "ai_budget_exceeded", message: "Spent." },
        };
      if (call.url === "/gap-question-sets/s1/fit-reading-estimate")
        return { cost_usd: "0.02", model_id: "claude-sonnet-5" };
      if (call.url === "/gap-question-sets/s1/fit-reading")
        return { ...ready, fit_reading: "reading" };
      return null;
    });
    const user = userEvent.setup();
    renderGaps();

    expect(await screen.findByText("Spent.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Update fit" }));
    await user.click(await screen.findByRole("button", { name: "Run it" }));

    expect(
      calls.some(
        (c) =>
          c.method === "POST" && c.url === "/gap-question-sets/s1/fit-reading",
      ),
    ).toBe(true);
  });
});

describe("the fit with your answers (ADR 0077)", () => {
  it("words the fit before and after", () => {
    expect(answeredFitLine(64, 71)).toBe(
      "Your fit: 64% → 71% with your answers",
    );
    expect(answeredFitLine(null, 71)).toBe("Your fit with your answers: 71%");
  });

  it("words what moved each gap", () => {
    const none = { score_before: null, score_after: null };
    expect(
      readingChange({ score_before: 52, score_after: 63, coverage: null }),
    ).toBe("52 → 63");
    expect(readingChange({ ...none, coverage: "covered" })).toBe("now covered");
    expect(readingChange({ ...none, coverage: "not" })).toBe(
      "still not covered",
    );
  });
});
