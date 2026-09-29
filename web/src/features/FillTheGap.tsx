import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  GapQuestion,
  PlanEstimate,
  QuestionSet,
  SubmitEstimate,
  Submitted,
} from "../api/types";
import {
  Button,
  Done,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
} from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { type AdvisorTarget, targetQuery } from "./target";
import { messageOf } from "./useAsync";

const POLL_MS = 2000;

type Draft = { choice: string | null; text: string };

/**
 * Fill the gap, the Advisor's first step (ADR 0023): questions written for
 * the gaps between the user's evidence and the target role, answered here and
 * submitted together.
 *
 * Nothing is saved per question. One submit records every answer as evidence
 * ("Your answers" on Sources) and has the gap plan and résumé written again,
 * if they exist. A question left blank stays a gap.
 */
export function FillTheGap({
  target,
  onSubmitted,
}: {
  target: AdvisorTarget;
  /** Answers were submitted: the plan and résumé are being written again. */
  onSubmitted: () => void;
}) {
  const { status, navigate } = useShell();
  const flash = useToast();
  const model = modelName(status.credential);
  const [set, setSet] = useState<QuestionSet | null | undefined>(undefined);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [writeCost, setWriteCost] = useState<PlanEstimate | null>(null);
  const [submitCost, setSubmitCost] = useState<SubmitEstimate | null>(null);
  const [submitted, setSubmitted] = useState<Submitted | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wasWriting = useRef(false);

  // The Target's current questions, re-read while they are being written.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const next = await api.get<QuestionSet | null>(
          `/gap-question-sets/current?${targetQuery(target.ref)}`,
        );
        if (cancelled) return;
        setSet(next);
        if (next?.status === "writing") {
          wasWriting.current = true;
          timer = setTimeout(load, POLL_MS);
        } else if (wasWriting.current && next) {
          wasWriting.current = false;
          flash(
            next.status === "ready"
              ? `${next.model_id ?? model} wrote ${next.questions.length} questions.`
              : "Writing the questions failed — the reason is on the page.",
          );
        }
      } catch (caught) {
        if (!cancelled) setError(messageOf(caught));
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // Re-read when a new set is requested (its id changes to "writing").
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.ref.role_id, target.ref.job_posting_id, set?.id]);

  // What submitting will cost, once there is something to submit.
  useEffect(() => {
    if (!set || set.status !== "ready" || set.submitted_at) return;
    api
      .get<SubmitEstimate>(`/gap-question-sets/${set.id}/submit-estimate`)
      .then(setSubmitCost)
      .catch((caught: unknown) => setError(messageOf(caught)));
  }, [set]);

  async function run(work: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  const price = () =>
    run(async () => {
      if (!status.credential) {
        flash("Questions are written on your model — add a key.");
        navigate("model");
        return;
      }
      setWriteCost(
        await api.get<PlanEstimate>(
          `/gap-question-sets/cost-estimate?${targetQuery(target.ref)}`,
        ),
      );
    });

  const write = () =>
    run(async () => {
      const created = await api.post<QuestionSet>(
        "/gap-question-sets",
        target.ref,
      );
      setWriteCost(null);
      setDrafts({});
      setSubmitted(null);
      setSet(created);
    });

  const answers = (set?.questions ?? [])
    .map((q) => ({ question: q, draft: drafts[q.id] }))
    .filter(({ draft }) => draft && (draft.choice || draft.text.trim()));

  const submit = () =>
    run(async () => {
      if (!set) return;
      const done = await api.post<Submitted>(
        `/gap-question-sets/${set.id}/answers`,
        {
          answers: answers.map(({ question, draft }) => ({
            question_id: question.id,
            choice: draft?.choice ?? null,
            text: draft?.text.trim() || null,
          })),
        },
      );
      setSubmitted(done);
      setSet(await api.get<QuestionSet>(`/gap-question-sets/${set.id}`));
      onSubmitted();
    });

  if (set === undefined) return <Loading what="the questions" />;

  const writeConfirm = writeCost && (
    <CostConfirm
      busy={busy}
      onConfirm={() => void write()}
      onCancel={() => setWriteCost(null)}
    >
      Writing questions for the gaps of <strong>{target.label}</strong> costs
      about <strong>${writeCost.cost_usd}</strong> on {writeCost.model_id},
      charged to your own provider.
    </CostConfirm>
  );

  if (set === null || set.status === "superseded") {
    return (
      <section>
        {writeConfirm}
        <EmptyState title="No questions yet">
          {model} compares your sources with what {target.roleName} asks for and
          writes a few questions for each gap. Your answers become evidence, and
          the gap plan and résumé use them.
          <span style={{ display: "block", marginTop: 14 }}>
            <Button busy={busy} onClick={() => void price()}>
              Write questions
            </Button>
          </span>
        </EmptyState>
        <ErrorNote error={error} />
      </section>
    );
  }

  if (set.status === "writing") {
    return (
      <div className="panel" role="status">
        <Eyebrow>Fill the gap</Eyebrow>
        <p className="subcopy">
          Writing questions on {set.model_id ?? model} for the gaps of{" "}
          {set.label}…
        </p>
      </div>
    );
  }

  if (set.status === "failed") {
    return (
      <section>
        {writeConfirm}
        <div className="panel">
          <Eyebrow>Fill the gap</Eyebrow>
          <ErrorNote
            error={set.error?.message ?? "Writing the questions failed."}
          />
          <Button busy={busy} onClick={() => void price()}>
            Try again
          </Button>
        </div>
      </section>
    );
  }

  const isSubmitted = set.submitted_at !== null;
  const answeredCount = isSubmitted
    ? set.questions.filter((q) => q.evidence_id).length
    : answers.length;

  return (
    <section>
      {writeConfirm}
      <div className="panel" style={{ marginBottom: 20 }}>
        <Eyebrow>Between your evidence and {set.label}</Eyebrow>
        <p className="subcopy" style={{ margin: "6px 0 0" }}>
          {set.model_id ?? model} compared your sources with what this role asks
          for and wrote a few questions for each gap. Answer what you can, then
          submit. Anything you skip stays a gap.
        </p>
      </div>

      {set.gaps.map((gap, index) => (
        <div
          key={gap.key}
          className="panel gap-card"
          role="group"
          aria-label={gap.label}
          style={{ marginBottom: 16 }}
        >
          <div className="row-between" style={{ flexWrap: "wrap" }}>
            <h3 style={{ margin: 0 }}>
              {index + 1} · {gap.label}{" "}
              <span
                className={gap.status === "partial" ? "chip" : "chip chip-warn"}
              >
                {gap.status === "partial" ? "Partial" : "No evidence"}
              </span>
            </h3>
            <span className="muted" style={{ fontWeight: 700 }}>
              up to +{gap.lift} fit pts
            </span>
          </div>
          {set.questions
            .filter((q) => q.gap_key === gap.key)
            .map((question) => (
              <QuestionCard
                key={question.id}
                number={set.questions.indexOf(question) + 1}
                question={question}
                draft={drafts[question.id] ?? { choice: null, text: "" }}
                locked={isSubmitted}
                onChange={(draft) =>
                  setDrafts({ ...drafts, [question.id]: draft })
                }
              />
            ))}
        </div>
      ))}

      <div
        className="panel panel-tight target-bar"
        role="region"
        aria-label="Submit answers"
      >
        <div style={{ minWidth: 0 }}>
          <div className="target-bar-label">
            {answeredCount} of {set.questions.length} answered
          </div>
          <div className="muted" style={{ fontSize: 12.5 }}>
            {isSubmitted
              ? "Your answers are on Sources as evidence."
              : submitNote(submitCost)}
          </div>
        </div>
        {isSubmitted ? (
          <Button variant="secondary" busy={busy} onClick={() => void price()}>
            Ask again
          </Button>
        ) : (
          <Button
            busy={busy}
            disabled={answers.length === 0}
            onClick={() => void submit()}
          >
            Submit answers
          </Button>
        )}
      </div>
      {submitted && (
        <Done>
          {submitted.answered} answer{submitted.answered === 1 ? "" : "s"} added
          to your evidence
          {submitCost?.regenerates_plan || submitCost?.regenerates_resume
            ? "; your gap plan and résumé are being written again"
            : ""}
          .
        </Done>
      )}
      <ErrorNote error={error} />
    </section>
  );
}

function QuestionCard({
  number,
  question,
  draft,
  locked,
  onChange,
}: {
  number: number;
  question: GapQuestion;
  draft: Draft;
  locked: boolean;
  onChange: (draft: Draft) => void;
}) {
  const hasChoices = question.answer_type !== "free_text";
  const hasText = question.answer_type !== "choice";
  return (
    <div className="gap-question" style={{ marginTop: 14 }}>
      <div className="row" style={{ gap: 12, alignItems: "baseline" }}>
        <span className="nav-num" aria-hidden="true">
          {String(number).padStart(2, "0")}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700 }}>{question.text}</div>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
            Asked because: {question.asked_because}
          </div>
          {hasChoices && (
            <div
              className="row"
              role="group"
              aria-label={`Answers to ${question.text}`}
              style={{ gap: 8, marginTop: 10, flexWrap: "wrap" }}
            >
              {question.choices.map((choice) => (
                <PillToggle
                  key={choice}
                  small
                  disabled={locked}
                  pressed={draft.choice === choice}
                  onClick={() =>
                    onChange({
                      ...draft,
                      choice: draft.choice === choice ? null : choice,
                    })
                  }
                >
                  {choice}
                </PillToggle>
              ))}
            </div>
          )}
          {hasText && (
            <textarea
              className="input"
              rows={2}
              aria-label={`Your answer to ${question.text}`}
              placeholder={hasChoices ? "Say more (optional)" : "Your answer"}
              disabled={locked}
              value={draft.text}
              style={{ marginTop: 10 }}
              onChange={(event) =>
                onChange({ ...draft, text: event.target.value })
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}

/** "Submitting adds your answers to Sources and updates …". Pure. */
export function submitNote(cost: SubmitEstimate | null): string {
  const base = "Submitting adds your answers to Sources";
  if (!cost) return `${base}.`;
  const updates = [
    cost.regenerates_plan ? "the gap plan" : null,
    cost.regenerates_resume ? "the résumé" : null,
  ].filter(Boolean);
  if (updates.length === 0) return `${base}.`;
  return `${base} and updates ${updates.join(" and ")} · about $${cost.cost_usd} on your key`;
}
