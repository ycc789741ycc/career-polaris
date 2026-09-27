import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Assessment, Question, QuestionStatus } from "../api/types";
import {
  AutoGrid,
  Button,
  Done,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
  ProgressBar,
} from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { messageOf, useAsync } from "./useAsync";

/** How often the page re-reads the question round while work is running. */
const POLL_MS = 2000;
/** How long an answer's re-analysis is waited for: five minutes of polls. */
const MAX_REANALYSIS_POLLS = 150;
/** Polls to wait, once the new analysis is in, for the round it opens. */
const ROUND_GRACE_POLLS = 2;

/** What an answer is waiting on: the analysis and round it replaces. */
interface Reanalysis {
  assessmentId: string | null;
  roundId: string | null;
}

/**
 * Follow-up questions.
 *
 * These appear when a dimension's confidence is below the threshold — the
 * domain's definition of "the context is not enough". Each says why it is being
 * asked and what it moves, and an answer becomes evidence like any other.
 *
 * Questions are written by a background round on the user's key, after a sync
 * or upload and after every analysis (ADR 0012). The page polls the newest
 * round while it is generating, and while an answer's re-analysis runs, and
 * shows a status bar until the work is done (ADR 0006).
 */
export function Clarify() {
  const { status, navigate, refresh } = useShell();
  const model = modelName(status.credential);
  const questions = useAsync<Question[]>(() => api.get("/questions"), []);
  const assessment = useAsync<Assessment | null>(
    () => api.get("/assessments/latest"),
    [],
  );
  const [round, setRound] = useState<QuestionStatus | null>(null);
  const [roundLoaded, setRoundLoaded] = useState(false);
  const [reanalysis, setReanalysis] = useState<Reanalysis | null>(null);
  const [slow, setSlow] = useState(false);
  const [poll, setPoll] = useState(0);
  const [answering, setAnswering] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answered, setAnswered] = useState(0);
  const [refreshed, setRefreshed] = useState(false);

  const wasGenerating = useRef(false);
  const reanalysisPolls = useRef(0);
  const analysedPolls = useRef(0);

  const generating = round?.status === "generating";
  const working = generating || reanalysis !== null;

  // Read the round once, then keep re-reading it while anything is running.
  useEffect(() => {
    if (poll > 0 && !working) return;
    let cancelled = false;
    const timer = setTimeout(
      async () => {
        try {
          let waiting = reanalysis;
          let analysed = false;
          if (waiting) {
            const latest = await api.get<Assessment | null>(
              "/assessments/latest",
            );
            if (cancelled) return;
            analysed = latest !== null && latest.id !== waiting.assessmentId;
          }
          const next = await api.get<QuestionStatus | null>(
            "/questions/status",
          );
          if (cancelled) return;
          setRound(next);
          setRoundLoaded(true);

          if (waiting) {
            reanalysisPolls.current += 1;
            if (analysed) analysedPolls.current += 1;
            const opened = next !== null && next.id !== waiting.roundId;
            if (opened || analysedPolls.current > ROUND_GRACE_POLLS) {
              // The analysis is in, and either its round has opened or none
              // was needed. From here the round's own status drives polling.
              waiting = null;
              void assessment.reload();
            } else if (reanalysisPolls.current >= MAX_REANALYSIS_POLLS) {
              waiting = null;
              setSlow(true);
            }
            if (waiting === null) setReanalysis(null);
          }

          const nowGenerating = next?.status === "generating";
          if (wasGenerating.current && !nowGenerating) {
            void questions.reload();
            void refresh();
            if (next?.status === "ready") setRefreshed(true);
          }
          wasGenerating.current = nowGenerating;
        } catch (caught) {
          if (!cancelled) setError(messageOf(caught));
        }
        if (!cancelled) setPoll((count) => count + 1);
      },
      poll === 0 ? 0 : POLL_MS,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // Each poll schedules the next by bumping `poll`; the reloads are stable
    // enough, and re-running on them would restart polling for no reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poll, working]);

  async function answer(id: string, value: string) {
    setAnswering(id);
    setError(null);
    setRefreshed(false);
    setSlow(false);
    try {
      await api.post(`/questions/${id}/answer`, { answer: value });
      setAnswered((count) => count + 1);
      // The answer re-runs the analysis, which ends in a new round.
      reanalysisPolls.current = 0;
      analysedPolls.current = 0;
      setReanalysis(
        (current) =>
          current ?? {
            assessmentId: assessment.data?.id ?? null,
            roundId: round?.id ?? null,
          },
      );
      await Promise.all([questions.reload(), refresh()]);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setAnswering(null);
    }
  }

  const open = (questions.data ?? []).filter((q) => q.answer === null);
  const dimensions = new Map(
    (assessment.data?.dimensions ?? []).map((d) => [d.key, d]),
  );
  const moved = [...new Set(open.map((q) => q.dimension_key))]
    .map((key) => dimensions.get(key))
    .filter((d) => d !== undefined);
  const failed = !working && round?.status === "failed" ? round : null;
  const rerunning = reanalysis !== null && !generating;

  return (
    <AutoGrid col={340}>
      <div>
        <span className="model-pill">
          Written by {model} after reading your profile
        </span>

        <section
          className="panel panel-tight"
          style={{ marginTop: 14 }}
          aria-label="What this is for"
        >
          <Eyebrow style={{ marginBottom: 6 }}>What this is for</Eyebrow>
          <p className="lead" style={{ margin: 0 }}>
            Every skill in your report carries a confidence — how sure the
            analysis can be, given the evidence behind it. When a skill&apos;s
            confidence is low, a question about it appears here. Answer what you
            can: each answer becomes evidence, re-runs the analysis on your
            model, and raises the confidence of the skill it is about.
          </p>
          <p className="subcopy" style={{ marginTop: 8, marginBottom: 0 }}>
            Questions refresh by themselves after you sync a source or upload a
            résumé.
          </p>
        </section>

        <ErrorNote error={error} />
        {answered > 0 && !working && !slow && (
          <Done>
            {answered} answered — your analysis has re-run with{" "}
            {answered === 1 ? "it" : "them"}.
          </Done>
        )}
        {refreshed && !working && (
          <Done>
            {round?.question_count
              ? "New questions are ready below."
              : "Nothing left to ask — your evidence covers every skill well enough."}
          </Done>
        )}
        {slow && (
          <p className="subcopy" role="status">
            The analysis is taking longer than usual. Your skill report and
            these questions update when it finishes — check back in a few
            minutes.
          </p>
        )}

        {working && (
          <div className="panel" role="status" style={{ marginTop: 14 }}>
            <span className="model-pill">
              {rerunning
                ? `Re-running your analysis on ${model}…`
                : `Analysing your evidence on ${model}…`}
            </span>
            <div style={{ marginTop: 12 }}>
              <ProgressBar
                indeterminate
                label="Generating follow-up questions"
              />
            </div>
            <p className="subcopy" style={{ marginTop: 12, marginBottom: 0 }}>
              {rerunning
                ? "Scoring your skills again with your answer, then checking what is still unclear."
                : "Looking for what your evidence doesn't settle yet."}{" "}
              New questions appear here when it finishes; the page updates
              itself.
            </p>
          </div>
        )}

        {failed && (
          <div className="panel" style={{ marginTop: 14 }}>
            <h3>New questions could not be written</h3>
            <ErrorNote error={failed.error?.message ?? "Generation failed."} />
            {failed.error?.code?.startsWith("ai_") ? (
              <p className="subcopy">
                This is about your model or budget, not your evidence.{" "}
                <Button variant="ghost" onClick={() => navigate("model")}>
                  Open AI &amp; model
                </Button>
              </p>
            ) : (
              <p className="subcopy">
                Your next sync, upload or analysis tries again.
              </p>
            )}
          </div>
        )}

        {questions.loading || assessment.loading || !roundLoaded ? (
          <Loading what="questions" />
        ) : open.length > 0 ? (
          open.map((question, index) => (
            <div
              key={question.id}
              className="panel panel-tight"
              style={{ marginTop: 14 }}
            >
              <div style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
                <span
                  style={{
                    fontFamily: "var(--font-heading)",
                    color: "var(--color-accent-700)",
                    fontSize: 14,
                  }}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <div className="card-title">{question.text}</div>
                  <div className="subcopy" style={{ marginTop: 6 }}>
                    Asked because: {question.why}
                  </div>
                </div>
              </div>
              <div className="row" style={{ gap: 8, marginTop: 14 }}>
                {question.options.map((option) => (
                  <PillToggle
                    key={option}
                    pressed={false}
                    disabled={answering === question.id}
                    onClick={() => void answer(question.id, option)}
                  >
                    {option}
                  </PillToggle>
                ))}
              </div>
            </div>
          ))
        ) : working ? null : assessment.data === null ? (
          <EmptyState title="No analysis yet">
            Questions come after your first analysis. Run it from your skill
            report, and anything it can&apos;t settle shows up here.
          </EmptyState>
        ) : (
          <EmptyState title="Nothing to clarify">
            Every skill in your report is confident enough to stand on the
            evidence alone.
          </EmptyState>
        )}

        <div className="row" style={{ marginTop: 20 }}>
          <Button onClick={() => navigate("strengths")}>
            See my skill report
          </Button>
          {open.length > 0 && (
            <Button variant="ghost" onClick={() => navigate("strengths")}>
              Skip for now
            </Button>
          )}
        </div>
      </div>

      <div className="panel">
        <Eyebrow style={{ marginBottom: 4 }}>What your answers sharpen</Eyebrow>
        {moved.length === 0 ? (
          <p className="subcopy" style={{ marginTop: 10, marginBottom: 0 }}>
            No open questions, so every score stands on the evidence alone.
          </p>
        ) : (
          <div className="divided">
            {moved.map((dimension) => (
              <div key={dimension.key}>
                <div
                  className="row-between"
                  style={{ fontSize: 14, fontWeight: 600 }}
                >
                  <span>{dimension.name}</span>
                  <span style={{ color: "var(--color-accent-700)" }}>
                    {Math.round(dimension.confidence * 100)}% sure
                  </span>
                </div>
                <div
                  className="subcopy"
                  style={{ fontSize: 12.5, marginTop: 4 }}
                >
                  Scored {dimension.score}/100 on thin evidence — an answer
                  firms this up.
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AutoGrid>
  );
}
