import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  Plan,
  PlanEstimate,
  PlanGap,
  PlanSummary,
  TargetRef,
} from "../api/types";
import {
  AutoGrid,
  Button,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  ProgressBar,
  RoundCheck,
  YouVsBar,
} from "../components/ui";
import { type AdvisorTarget, sameTarget, targetQuery } from "./target";
import { modelName, useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { ago } from "./time";
import { messageOf } from "./useAsync";

type Ref = TargetRef;

/** How often a drafting plan is re-read. */
const POLL_MS = 2000;

/**
 * The Advisor's plan tab: a route to the one Target the Advisor is aimed at.
 *
 * A plan is drafted by a background job on the user's key, so the tab asks
 * for a price first, then polls the plan until it is ready or says why it
 * failed (ADR 0006). Plans are kept per Target; the history reopens them, and
 * reopening one for another Target moves the Advisor there.
 */
export function GapPlan({
  target,
  history,
  onChanged,
  onRevisit,
}: {
  target: AdvisorTarget;
  /** Every plan, newest first — loaded by the Advisor. */
  history: PlanSummary[];
  /** A plan was drafted or ticked: the history and fits are out of date. */
  onChanged: () => void;
  /** Reopen a plan kept for another Target. */
  onRevisit: (entry: PlanSummary) => void;
}) {
  const { status, navigate } = useShell();
  const flash = useToast();
  const model = modelName(status.credential);
  const ref: Ref = target.ref;

  // Opens with this Target's latest plan, if it has one.
  const [planId, setPlanId] = useState<string | null>(
    () => history.find((p) => sameTarget(p.target, ref))?.id ?? null,
  );
  const [plan, setPlan] = useState<Plan | null>(null);
  const [estimate, setEstimate] = useState<{
    ref: Ref;
    label: string;
    cost: PlanEstimate;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wasDrafting = useRef(false);

  // Read the open plan, and keep re-reading it while it is being drafted.
  useEffect(() => {
    if (!planId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const next = await api.get<Plan>(`/gap-plans/${planId}`);
        if (cancelled) return;
        setPlan(next);
        if (next.status === "drafting") {
          wasDrafting.current = true;
          timer = setTimeout(load, POLL_MS);
        } else if (wasDrafting.current) {
          wasDrafting.current = false;
          onChanged();
          flash(
            next.status === "ready"
              ? `${next.model_id ?? model} drafted a plan for ${next.label}.`
              : "Drafting failed — the reason is on the page.",
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
    // onChanged is re-created by the Advisor; re-running on it would restart
    // polling for no reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId]);

  async function price(priced: Ref, label: string) {
    if (!status.credential) {
      flash("Plan drafting runs on your model — add a key.");
      navigate("model");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const cost = await api.get<PlanEstimate>(
        `/gap-plans/cost-estimate?${targetQuery(priced)}`,
      );
      setEstimate({ ref: priced, label, cost });
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!estimate) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.post<PlanSummary>("/gap-plans", estimate.ref);
      setEstimate(null);
      setPlan(null);
      setPlanId(created.id);
      onChanged();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function toggleTask(taskId: string, done: boolean) {
    if (!plan) return;
    // Optimistic: the tick shows at once, and the plan is re-read for progress.
    setPlan({
      ...plan,
      milestones: plan.milestones.map((m) => ({
        ...m,
        tasks: m.tasks.map((t) => (t.id === taskId ? { ...t, done } : t)),
      })),
    });
    try {
      await api.put(`/gap-plan-tasks/${taskId}`, { done });
      setPlan(await api.get<Plan>(`/gap-plans/${plan.id}`));
      onChanged();
    } catch (caught) {
      setError(messageOf(caught));
      setPlan(await api.get<Plan>(`/gap-plans/${plan.id}`));
    }
  }

  function revisit(entry: PlanSummary) {
    if (!sameTarget(entry.target, ref)) {
      onRevisit(entry);
      return;
    }
    setPlan(null);
    setPlanId(entry.id);
    flash(`Revisiting the ${entry.label.split(" · ").pop()} plan.`);
  }

  const planTarget = plan
    ? (plan.snapshot?.role_name ?? plan.snapshot?.title ?? plan.label)
    : null;
  const doneCount =
    plan?.milestones.flatMap((m) => m.tasks).filter((t) => t.done).length ?? 0;

  return (
    <section>
      <div className="panel panel-tight" style={{ marginBottom: 20 }}>
        <AutoGrid col={300} gap={22}>
          <div>
            <Eyebrow>Plan a route to {target.label}</Eyebrow>
            <p className="subcopy" style={{ margin: "6px 0 12px" }}>
              {target.isCustom
                ? "The gaps, milestones and tasks below are planned against the requirements of the role you added."
                : "The plan closes the distance to this role, drafted on your model from your own evidence."}
            </p>
            <div className="row" style={{ marginTop: 16 }}>
              <Button onClick={() => void price(ref, target.label)} busy={busy}>
                Generate gap plan
              </Button>
              {plan && (
                <span className="muted" style={{ fontSize: 12.5 }}>
                  Last generated{" "}
                  {plan.drafted_at
                    ? ago(plan.drafted_at)
                    : ago(plan.created_at)}
                </span>
              )}
            </div>
            <ErrorNote error={error} />
          </div>

          <div className="inset" style={{ padding: 18 }}>
            <Eyebrow style={{ marginBottom: 4 }}>Plan history</Eyebrow>
            {history.length === 0 ? (
              <p className="subcopy" style={{ margin: "8px 0 0" }}>
                No plans yet. The first one you generate is kept here.
              </p>
            ) : (
              history.map((entry) => (
                <div
                  key={entry.id}
                  className="history-row"
                  aria-current={
                    sameTarget(entry.target, ref) ? "true" : undefined
                  }
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="history-name">{entry.label}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {entry.status === "drafting"
                        ? "Drafting…"
                        : entry.status === "failed"
                          ? "Drafting failed"
                          : `Generated ${ago(entry.drafted_at ?? entry.created_at)} · ${entry.progress}% done`}
                    </div>
                  </div>
                  <Button variant="ghost" onClick={() => revisit(entry)}>
                    Revisit
                  </Button>
                </div>
              ))
            )}
            <p style={{ fontSize: 12.5, margin: "10px 0 0" }}>
              Plans are kept per role and company — reopen one to pick the
              milestones back up where you left them.
            </p>
          </div>
        </AutoGrid>
      </div>

      {estimate && (
        <CostConfirm
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setEstimate(null)}
        >
          Drafting a plan for <strong>{estimate.label}</strong> costs about{" "}
          <strong>${estimate.cost.cost_usd}</strong> on {estimate.cost.model_id}
          , charged to your own provider.
          {estimate.cost.rate_is_published === false &&
            " We have no published price for that model, so this is a deliberately high guess."}
        </CostConfirm>
      )}

      {!plan ? (
        planId ? (
          <Loading what="the plan" />
        ) : (
          <EmptyState title="No plan yet">
            Generate one for {target.label}. It is drafted on your model from
            your own evidence.
          </EmptyState>
        )
      ) : plan.status === "drafting" ? (
        <div className="panel" role="status">
          <span className="model-pill">
            Drafting on {model} for {plan.label}…
          </span>
          <p className="subcopy" style={{ marginTop: 12, marginBottom: 0 }}>
            Reading the gaps against your evidence and laying out milestones.
            This usually takes under a minute; the page updates itself.
          </p>
        </div>
      ) : plan.status === "failed" ? (
        <div className="panel">
          <h3>This plan could not be drafted</h3>
          <ErrorNote error={plan.error?.message ?? "Drafting failed."} />
          <FailureHint
            code={plan.error?.code}
            onNavigate={(screen) => navigate(screen)}
          />
        </div>
      ) : (
        <>
          <span className="model-pill" style={{ marginBottom: 16 }}>
            Drafted by {plan.model_id ?? model} for {plan.label}
            {plan.snapshot?.fit != null &&
              ` · ${plan.snapshot.fit}% fit today`}{" "}
            ·{" "}
            <button
              type="button"
              onClick={() => void price(plan.target, plan.label)}
              style={{
                all: "unset",
                cursor: "pointer",
                textDecoration: "underline",
              }}
            >
              regenerate
            </button>
          </span>

          <AutoGrid col={380} gap={20}>
            <div className="panel">
              <h3>
                The{" "}
                {plan.gaps.length === 1
                  ? "one thing"
                  : `${numberWord(plan.gaps.length)} things`}{" "}
                between you and {planTarget}
              </h3>
              <p className="subcopy" style={{ marginBottom: 14 }}>
                Ranked by how much each moves your fit score. Every line cites
                the work it was read from.
                {plan.snapshot?.basis === "posting"
                  ? " Requirements read from the posting itself."
                  : " Requirements are the role's, across its openings."}
              </p>
              {plan.gaps.map((gap, index) => (
                <GapCard key={gap.key} gap={gap} rank={index + 1} />
              ))}

              {plan.stepping_stones.length > 0 && (
                <div className="callout" style={{ padding: 18, marginTop: 16 }}>
                  <Eyebrow>
                    Stepping stones — if the jump is too far right now
                  </Eyebrow>
                  <div className="divided">
                    {plan.stepping_stones.map((stone) => (
                      <div
                        key={stone.role_id}
                        className="row-between"
                        style={{ padding: "10px 0" }}
                      >
                        <div>
                          <div style={{ fontSize: 14, fontWeight: 700 }}>
                            {stone.name}
                          </div>
                          <div
                            className="callout-note"
                            style={{ fontSize: 12.5 }}
                          >
                            {stone.openings} open roles · a credible 12-month
                            bridge
                          </div>
                        </div>
                        <span style={{ fontSize: 13, fontWeight: 700 }}>
                          {stone.fit}% fit
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="panel">
              <div className="row-between" style={{ marginBottom: 8 }}>
                <h3 style={{ margin: 0 }}>Milestones &amp; tasks</h3>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: "var(--color-accent-700)",
                  }}
                >
                  {plan.progress}% done
                </span>
              </div>
              <div style={{ marginBottom: 18 }}>
                <ProgressBar percent={plan.progress} label="Plan progress" />
              </div>
              {plan.milestones.map((milestone) => (
                <div key={milestone.id} className="milestone">
                  <div className="row-between">
                    <span className="milestone-title">{milestone.title}</span>
                    <span className="milestone-window">{milestone.window}</span>
                  </div>
                  <p className="milestone-outcome">{milestone.outcome}</p>
                  {milestone.tasks.map((task) => {
                    const counted = task.done || task.done_elsewhere;
                    return (
                      <div
                        key={task.id}
                        className="task-row"
                        data-done={counted}
                      >
                        <RoundCheck
                          checked={counted}
                          // Toggles this plan's own tick; one counted from
                          // another plan is ticked here explicitly on click.
                          onChange={() => void toggleTask(task.id, !task.done)}
                        >
                          <span className="task-text">{task.text}</span>
                          {task.done_elsewhere && (
                            <span
                              className="muted"
                              style={{ display: "block", fontSize: 12 }}
                            >
                              Done in another plan — it counts here too.
                            </span>
                          )}
                        </RoundCheck>
                        <span className="task-due">{task.due}</span>
                      </div>
                    );
                  })}
                </div>
              ))}
              {doneCount === 0 && plan.milestones.length > 0 && (
                <p className="subcopy" style={{ marginTop: -8 }}>
                  Tick a task when it is done. Real work shows up in your
                  sources at the next sync, and the next analysis scores it.
                </p>
              )}

              {plan.projects.length > 0 && (
                <div className="inset" style={{ padding: 18 }}>
                  <Eyebrow>
                    Build one of these — it produces the evidence you&apos;re
                    missing
                  </Eyebrow>
                  <div className="divided">
                    {plan.projects.map((project) => (
                      <div key={project.name} style={{ padding: "11px 0" }}>
                        <div style={{ fontSize: 14, fontWeight: 700 }}>
                          {project.name}
                        </div>
                        <div className="subcopy" style={{ fontSize: 12.5 }}>
                          {project.note}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {plan.versions.length > 1 && (
                <p className="muted" style={{ fontSize: 12.5, marginTop: 14 }}>
                  Version {plan.version} of {plan.versions.length}. Finished
                  tasks carry into each new version.
                </p>
              )}
            </div>
          </AutoGrid>
        </>
      )}
    </section>
  );
}

function GapCard({ gap, rank }: { gap: PlanGap; rank: number }) {
  return (
    <div className="gap-card">
      <div className="row-between">
        <span className="gap-card-title">
          {String(rank).padStart(2, "0")} · {gap.name}
        </span>
        <span className="gap-card-lift">+{gap.lift} fit pts</span>
      </div>
      <div style={{ margin: "12px 0" }}>
        {gap.kind === "dimension" &&
        gap.user_score !== null &&
        gap.target_score !== null ? (
          <YouVsBar
            you={gap.user_score}
            bar={gap.target_score}
            label={gap.name}
          />
        ) : (
          <span className="tag tag-neutral">No evidence at all</span>
        )}
      </div>
      <p className="gap-card-why">{gap.why}</p>
      {gap.evidence.map((item) => (
        <div key={item.id} className="gap-card-cite">
          {item.reference} — {item.fact}
        </div>
      ))}
    </div>
  );
}

function FailureHint({
  code,
  onNavigate,
}: {
  code: string | undefined;
  onNavigate: (screen: "model" | "roles") => void;
}) {
  if (code?.startsWith("ai_credential") || code === "ai_budget_exceeded") {
    return (
      <p className="subcopy">
        This is about your model or budget, not the plan.{" "}
        <Button variant="ghost" onClick={() => onNavigate("model")}>
          Open AI &amp; model
        </Button>
      </p>
    );
  }
  if (code === "target_unusable") {
    return (
      <p className="subcopy">
        <Button variant="ghost" onClick={() => onNavigate("roles")}>
          Back to the role map
        </Button>
      </p>
    );
  }
  return (
    <p className="subcopy">
      No plan was drafted this time. Regenerating tries again as a fresh
      version.
    </p>
  );
}

const WORDS = ["zero", "one", "two", "three", "four", "five", "six"];

function numberWord(n: number): string {
  return WORDS[n] ?? String(n);
}
