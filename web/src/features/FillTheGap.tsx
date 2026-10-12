import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  AnsweredFit,
  GapQuestion,
  PlanEstimate,
  QuestionSet,
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
import {
  getShownModel,
  hasAi,
  isOnPlatform,
  modelName,
  useShell,
} from "../shell/ShellContext";
import { useActivity } from "../shell/activity";
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
 * The gap analysis starts here and only here (ADR 0073): aiming the Advisor
 * from the role map runs nothing. For an opening it first reads what the
 * posting asks for and scores the user's fit to it, then writes the
 * questions, in one job at one confirmed price.
 *
 * Nothing is saved per question. One submit records every answer as evidence
 * ("Your answers" on Sources), and reads them into the Target's fit in one
 * priced call (ADR 0077): on the user's own key the price is confirmed first,
 * on CareerPolaris AI it just runs. The gap plan and résumé then say they are
 * outdated, and the user regenerates them (ADR 0035). A question left blank
 * stays a gap.
 */
export function FillTheGap({
  target,
  onSubmitted,
}: {
  target: AdvisorTarget;
  /** Answers were submitted: the plan and résumé now read as outdated. */
  onSubmitted: () => void;
}) {
  const { status, navigate } = useShell();
  const flash = useToast();
  // A job just started: the shell polls it, and the tab shows its card.
  const { refresh: refreshActivity } = useActivity();
  const model = modelName(status);
  const isOpening = target.ref.job_posting_id != null;
  const [set, setSet] = useState<QuestionSet | null | undefined>(undefined);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [writeCost, setWriteCost] = useState<PlanEstimate | null>(null);
  const [submitted, setSubmitted] = useState<Submitted | null>(null);
  // What reading the answers into the fit costs, confirmed before it runs:
  // with the submit, or again after it failed.
  const [readCost, setReadCost] = useState<{
    cost: PlanEstimate;
    isRetry: boolean;
  } | null>(null);
  // The fit before and after the answers, once they are read.
  const [answered, setAnswered] = useState<AnsweredFit | null>(null);
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
  }, [
    target.ref.role_id,
    target.ref.job_posting_id,
    target.ref.private_job_posting_id,
    set?.id,
  ]);

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
      if (!hasAi(status)) {
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
      void refreshActivity();
    });

  const answers = (set?.questions ?? [])
    .map((q) => ({ question: q, draft: drafts[q.id] }))
    .filter(({ draft }) => draft && (draft.choice || draft.text.trim()));

  /** Price reading the answers into the fit; CostConfirm runs it at once on
   * CareerPolaris AI (ADR 0067). */
  const priceReading = (isRetry: boolean) =>
    run(async () => {
      if (!set) return;
      setReadCost({
        cost: await api.get<PlanEstimate>(
          `/gap-question-sets/${set.id}/fit-reading-estimate`,
        ),
        isRetry,
      });
    });

  const submit = (updateFit: boolean) =>
    run(async () => {
      if (!set) return;
      setReadCost(null);
      const done = await api.post<Submitted>(
        `/gap-question-sets/${set.id}/answers`,
        {
          answers: answers.map(({ question, draft }) => ({
            question_id: question.id,
            choice: draft?.choice ?? null,
            text: draft?.text.trim() || null,
          })),
          update_fit: updateFit,
        },
      );
      setSubmitted(done);
      setSet(await api.get<QuestionSet>(`/gap-question-sets/${set.id}`));
      onSubmitted();
      if (updateFit) void refreshActivity();
    });

  const readAgain = () =>
    run(async () => {
      if (!set) return;
      setReadCost(null);
      setSet(
        await api.post<QuestionSet>(`/gap-question-sets/${set.id}/fit-reading`),
      );
      void refreshActivity();
    });

  // Once read, the fit before and after, and what moved it.
  const isRead = set?.fit_reading === "ready";
  useEffect(() => {
    if (!isRead) return;
    let isCurrent = true;
    api
      .get<AnsweredFit>(`/answered-fit?${targetQuery(target.ref)}`)
      .then((fit) => {
        if (isCurrent) setAnswered(fit);
      })
      // The answers are evidence either way; the fit just goes unshown.
      .catch(() => {
        if (isCurrent) setAnswered(null);
      });
    return () => {
      isCurrent = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRead, set?.id]);

  if (set === undefined) return <Loading what="the questions" />;

  const writeConfirm = writeCost && (
    <CostConfirm
      busy={busy}
      onConfirm={() => void write()}
      onCancel={() => setWriteCost(null)}
    >
      {isOpening
        ? "Reading what this opening asks for, scoring your fit to it and writing questions for the gaps of "
        : "Writing questions for the gaps of "}
      <strong>{target.label}</strong> costs {isOpening ? "at most" : "about"}{" "}
      <strong>${writeCost.cost_usd}</strong> on{" "}
      {getShownModel(status, writeCost.model_id)}, charged to your own provider.
    </CostConfirm>
  );

  if (set === null || set.status === "superseded") {
    return (
      <section>
        {writeConfirm}
        <EmptyState title="No gap analysis yet">
          {isOpening
            ? `${model} reads what this opening asks for, scores your fit to it, and writes a few questions for each gap.`
            : `${model} compares your sources with what ${target.roleName} asks for and writes a few questions for each gap.`}{" "}
          Your answers become evidence, and the gap plan and résumé use them.
          <span style={{ display: "block", marginTop: 14 }}>
            <Button busy={busy} onClick={() => void price()}>
              Analyse the gaps
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
          {set.gaps.length === 0
            ? `Reading ${set.label} and scoring your fit to it…`
            : `Writing questions on ${set.model_id ?? model} for the gaps of ${set.label}…`}
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
  const canRead = hasAi(status);
  const readConfirm = readCost && (
    <CostConfirm
      busy={busy}
      onConfirm={() => void (readCost.isRetry ? readAgain() : submit(true))}
      onCancel={() => setReadCost(null)}
    >
      {readCost.isRetry ? "Reading" : "Submitting and reading"} your answers
      into your fit for <strong>{set.label}</strong> costs at most{" "}
      <strong>${readCost.cost.cost_usd}</strong> on{" "}
      {getShownModel(status, readCost.cost.model_id)}, charged to your own
      provider.
    </CostConfirm>
  );
  const answeredCount = isSubmitted
    ? set.questions.filter((q) => q.evidence_id).length
    : answers.length;

  return (
    <section>
      {writeConfirm}
      {readConfirm}
      <div className="panel" style={{ marginBottom: 20 }}>
        <Eyebrow>Between your evidence and {set.label}</Eyebrow>
        <p className="subcopy" style={{ margin: "6px 0 0" }}>
          {set.model_id ?? model} compared your sources with what this{" "}
          {isOpening ? "opening" : "role"} asks for and wrote a few questions
          for each gap. Answer what you can, then submit. Anything you skip
          stays a gap.
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
              : canRead
                ? "Submitting adds your answers to Sources and reads them into your fit."
                : "Submitting adds your answers to Sources. It spends nothing."}
          </div>
        </div>
        {isSubmitted ? (
          <Button variant="secondary" busy={busy} onClick={() => void price()}>
            Ask again
          </Button>
        ) : (
          <span className="row" style={{ gap: 10 }}>
            {canRead && !isOnPlatform(status) && (
              <Button
                variant="ghost"
                busy={busy}
                disabled={answers.length === 0}
                onClick={() => void submit(false)}
              >
                Submit without updating fit
              </Button>
            )}
            <Button
              busy={busy}
              disabled={answers.length === 0}
              onClick={() =>
                void (canRead ? priceReading(false) : submit(false))
              }
            >
              Submit answers
            </Button>
          </span>
        )}
      </div>
      {isSubmitted &&
        (set.fit_reading === "failed" || set.fit_reading === "cancelled") && (
          <div className="panel panel-tight" style={{ marginTop: 12 }}>
            <ErrorNote
              error={
                set.fit_reading === "failed"
                  ? (set.fit_reading_error?.message ??
                    "Reading your answers into your fit failed.")
                  : "Reading your answers into your fit was cancelled."
              }
            />
            <Button
              variant="secondary"
              busy={busy}
              disabled={!canRead}
              onClick={() => void priceReading(true)}
            >
              Update fit
            </Button>
          </div>
        )}
      {isSubmitted && set.fit_reading === null && canRead && (
        <p className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
          Your fit does not count these answers yet.{" "}
          <button
            type="button"
            className="link-button"
            disabled={busy}
            onClick={() => void priceReading(true)}
          >
            Update fit
          </button>
        </p>
      )}
      {answered && answered.answered_fit !== null && (
        <div
          className="panel panel-tight"
          role="region"
          aria-label="Your fit with your answers"
          style={{ marginTop: 12 }}
        >
          <div className="target-bar-label">
            {answeredFitLine(answered.fit, answered.answered_fit)}
          </div>
          <ul className="fit-readings">
            {answered.readings.map((reading) => (
              <li key={reading.gap_key}>
                <strong>{reading.label}</strong> {readingChange(reading)}
                <div className="muted" style={{ fontSize: 12.5 }}>
                  {reading.reasoning}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {submitted && (
        <Done>
          {submitted.answered} answer{submitted.answered === 1 ? "" : "s"} added
          to your evidence. Your gap plan and résumé use them once you
          regenerate them.
        </Done>
      )}
      <ErrorNote error={error} />
    </section>
  );
}

/** "Your fit: 64% → 71% with your answers". Pure. */
export function answeredFitLine(fit: number | null, answered: number): string {
  return fit === null
    ? `Your fit with your answers: ${answered}%`
    : `Your fit: ${fit}% → ${answered}% with your answers`;
}

/** "52 → 63", or "now partly covered". Pure. */
export function readingChange(reading: {
  score_before: number | null;
  score_after: number | null;
  coverage: "covered" | "partly" | "not" | null;
}): string {
  if (reading.score_after !== null)
    return `${reading.score_before ?? "—"} → ${reading.score_after}`;
  switch (reading.coverage) {
    case "covered":
      return "now covered";
    case "partly":
      return "now partly covered";
    default:
      return "still not covered";
  }
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
