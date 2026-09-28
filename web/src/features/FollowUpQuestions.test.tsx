import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Assessment, Question, QuestionStatus } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { FollowUpQuestions } from "./FollowUpQuestions";
import { page } from "../test/page";

const assessment: Assessment = {
  id: "a1",
  profile_version: 3,
  is_out_of_date: false,
  model_id: "claude-opus-5",
  template_version: "skill_assessment@v1",
  created_at: "2026-09-27T09:00:00Z",
  dimensions: [
    {
      key: "api",
      name: "API design",
      short_name: "APIs",
      score: 62,
      confidence: 0.35,
      read: "One repository shows it.",
      evidence_ids: ["e1"],
      needs_more_evidence: true,
    },
  ],
};

const question: Question = {
  id: "q1",
  dimension_key: "api",
  text: "Did you design the public API, or extend one?",
  why: "Only one repository shows it.",
  options: ["Designed it", "Extended it", "Neither"],
  answer: null,
};

function round(
  status: QuestionStatus["status"],
  error: QuestionStatus["error"] = null,
): QuestionStatus {
  return {
    id: "r1",
    status,
    trigger: "evidence",
    question_count: status === "ready" ? 1 : 0,
    created_at: "2026-09-27T09:01:00Z",
    finished_at: status === "generating" ? null : "2026-09-27T09:02:00Z",
    error,
  };
}

type Route = (method: string, url: string) => unknown;

function serve(route: Route) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      const method = init?.method ?? "GET";
      const answer = route(method, url);
      // Every list the API sends is a page (ADR 0014); the routes here return
      // the list itself.
      const body =
        method === "GET" && Array.isArray(answer) ? page(answer) : answer;
      return new Response(body === undefined ? null : JSON.stringify(body), {
        status: body === undefined ? 204 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderQuestions(onAnswered: () => void = () => {}) {
  const shell: Shell = {
    status: {
      me: null,
      credential: {
        provider: "anthropic",
        model: "claude-opus-5",
        base_url: null,
        last_four: "abcd",
        status: "active",
        last_error: null,
      },
      openQuestions: 0,
      confidence: 80,
    },
    navigate: vi.fn(),
    focus: null,
    setFocus: vi.fn(),
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
  };
  render(
    <ShellContext.Provider value={shell}>
      <FollowUpQuestions onAnswered={onAnswered} />
    </ShellContext.Provider>,
  );
  return shell;
}

describe("follow-up questions", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("says the questions are there to raise the report's confidence", async () => {
    serve(() => null);
    renderQuestions();

    const guide = screen.getByRole("region", { name: "What this is for" });
    expect(guide).toHaveTextContent(/carries a confidence/);
    expect(guide).toHaveTextContent(/raises the confidence/);
    expect(guide).toHaveTextContent(/refresh by themselves after you sync/);
    expect(await screen.findByText("No analysis yet")).toBeInTheDocument();
  });

  it("shows a status bar while questions are generated, then the questions", async () => {
    let status = round("generating");
    let asked: Question[] = [];
    serve((_method, url) => {
      if (url === "/questions/status") {
        const current = status;
        // The next poll finds the round finished.
        status = round("ready");
        asked = [question];
        return current;
      }
      if (url === "/questions") return asked;
      if (url === "/assessments/latest") return assessment;
      return null;
    });
    renderQuestions();

    const bar = await screen.findByRole("progressbar", {
      name: "Generating follow-up questions",
    });
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(
      screen.getByText("Analysing your evidence on claude-opus-5…"),
    ).toBeInTheDocument();

    expect(
      await screen.findByText(question.text, undefined, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(
      screen.getByText("New questions are ready below."),
    ).toBeInTheDocument();
  });

  it("says why a round failed and points at the model settings", async () => {
    serve((_method, url) => {
      if (url === "/questions/status")
        return round("failed", {
          code: "ai_budget_exceeded",
          message: "This month's AI budget is spent.",
        });
      if (url === "/questions") return [];
      if (url === "/assessments/latest") return assessment;
      return null;
    });
    const user = userEvent.setup();
    const shell = renderQuestions();

    expect(
      await screen.findByText("New questions could not be written"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("This month's AI budget is spent."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open AI & model" }));
    expect(shell.navigate).toHaveBeenCalledWith("model");
  });

  it("tells the Sources screen when an answer adds evidence", async () => {
    let answer: string | null = null;
    serve((method, url) => {
      if (url === "/questions/status") return round("ready");
      if (url === "/questions") return [{ ...question, answer }];
      if (url === "/assessments/latest") return assessment;
      if (method === "POST" && url === "/questions/q1/answer") {
        answer = "Designed it";
        return {};
      }
      return null;
    });
    const user = userEvent.setup();
    const onAnswered = vi.fn();
    renderQuestions(onAnswered);

    await user.click(
      await screen.findByRole("button", { name: "Designed it" }),
    );

    await vi.waitFor(() => expect(onAnswered).toHaveBeenCalled());
    expect(screen.queryByText(question.text)).not.toBeInTheDocument();
  });
});
