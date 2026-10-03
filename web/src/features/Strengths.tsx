import { useState } from "react";
import { api } from "../api/client";
import type {
  Assessment,
  AnalysisEstimate,
  Evidence,
  EvidencePage,
} from "../api/types";
import { SkillRadar } from "../charts/SkillRadar";
import {
  AutoGrid,
  Button,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  ProgressBar,
} from "../components/ui";
import { isBusy, sourcesBusy, useActivity } from "../shell/activity";
import { modelName, useShell } from "../shell/ShellContext";
import { CostConfirm } from "./CostConfirm";
import { dayLabel } from "./time";
import { messageOf, useAsync } from "./useAsync";

/**
 * The strength report.
 *
 * Nothing is spent without asking: the first run shows its estimated cost and
 * waits for a yes.
 *
 * One layout, the radar and its evidence, and it explains every score by how
 * sure it is: confidence, whether the evidence is thin (the server's
 * `needs_more_evidence`), and
 * the facts it cites. The least certain dimensions come first, since they
 * are the ones more evidence would change.
 *
 * The journey runs Sources → Strengths → Role map → Advisor, and a later step
 * never changes an earlier one's result. So the report reads only the evidence
 * and the analysis: no fit, role or bar from the role map, which reclusters
 * and rescores as the market moves. Comparing against a role's bar is the role
 * map's job, where "How you fit each skill" already does it.
 *
 * An analysis reads the evidence as it stands, so it cannot start while a
 * source is still syncing or a résumé still parsing (ADR 0018); the running
 * bar says what it waits for, and the report reloads when a run finishes.
 */
export function Strengths() {
  const { status, navigate } = useShell();
  const { activity, refresh: refreshActivity, settled } = useActivity();
  const assessment = useAsync<Assessment | null>(
    () => api.get("/assessments/latest"),
    [settled.analysis],
  );
  const evidence = useAsync<Evidence[]>(
    () => api.items<EvidencePage>("/evidence"),
    [],
  );
  const [estimate, setEstimate] = useState<AnalysisEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | undefined>(undefined);

  async function askForEstimate() {
    setBusy(true);
    setError(null);
    try {
      setEstimate(
        await api.get<AnalysisEstimate>("/assessments/cost-estimate"),
      );
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/assessments");
      setEstimate(null);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
      // Refused or started, the running bar should say why.
      await refreshActivity();
    }
  }

  const processing = sourcesBusy(activity);
  const analysing = isBusy(activity?.analysis);
  const lastRun = activity?.analysis ?? null;
  const lastRunFailed =
    lastRun?.status === "failed" &&
    (!assessment.data ||
      new Date(lastRun.started_at) > new Date(assessment.data.created_at));

  const dimensions = assessment.data?.dimensions ?? [];
  const leastCertain = [...dimensions].sort(
    (a, b) => a.confidence - b.confidence || a.name.localeCompare(b.name),
  );
  const activeKey = selected ?? leastCertain[0]?.key;
  const active = dimensions.find((d) => d.key === activeKey);
  const byId = new Map((evidence.data ?? []).map((item) => [item.id, item]));

  return (
    <section>
      <div
        className="row report-toolbar"
        style={{ gap: 14, flexWrap: "wrap", marginBottom: 18 }}
      >
        <Button
          variant={assessment.data ? "secondary" : "primary"}
          onClick={askForEstimate}
          busy={busy}
          disabled={processing || analysing}
        >
          {analysing
            ? "Analysing…"
            : assessment.data
              ? "Re-analyse"
              : "Analyse with AI"}
        </Button>
        {assessment.data && (
          <span style={{ fontSize: 13, color: "var(--color-neutral-800)" }}>
            {analysedLine(
              assessment.data.created_at,
              assessment.data.model_id,
              evidence.data?.length ?? null,
            )}
          </span>
        )}
        {assessment.data?.profile_confidence != null && (
          <ProfileConfidence value={assessment.data.profile_confidence} />
        )}
      </div>

      <ErrorNote error={error} />
      {processing && !analysing && (
        <p role="status" className="subcopy" style={{ margin: "8px 0" }}>
          Waiting for your sources to finish syncing and parsing — the analysis
          reads every fact, so it starts once they are in.
        </p>
      )}
      {lastRunFailed && !analysing && (
        <div role="alert" className="note-warning" style={{ margin: "8px 0" }}>
          <span aria-hidden="true">⚠</span> The last analysis did not finish:{" "}
          {lastRun?.error?.message ?? "it stopped before finishing"}.
          {lastRun?.error?.code.startsWith("ai_") && (
            <>
              {" "}
              <Button variant="ghost" onClick={() => navigate("model")}>
                Open AI &amp; model
              </Button>
            </>
          )}
        </div>
      )}
      {assessment.data?.is_out_of_date && !analysing && (
        <p role="status" className="note-warning" style={{ margin: "8px 0" }}>
          {/* Never colour alone. */}
          <span aria-hidden="true">⚠</span> Out of date: your evidence has
          changed since this analysis ran, so these scores may not match it.
          Re-analyse to catch up.
        </p>
      )}
      {estimate && (
        <CostConfirm
          busy={busy}
          onConfirm={confirm}
          onCancel={() => setEstimate(null)}
        >
          This will cost about <strong>${estimate.cost_usd}</strong> on{" "}
          {estimate.model_id}, charged to your own provider: $
          {estimate.analysis_cost_usd} for the analysis, at most $
          {estimate.role_map_cost_usd} for the role map built after it
          {estimate.max_roles > 0
            ? `, up to ${estimate.max_roles} roles`
            : ", which has no roles to name yet"}
          , and at most ${estimate.fits_cost_usd} for scoring your fit against
          them.
          {estimate.rate_is_published === false && (
            <>
              {" "}
              We have no published price for that model, so this is a
              deliberately high guess.
            </>
          )}
        </CostConfirm>
      )}

      {assessment.loading ? (
        <Loading what="your analysis" />
      ) : !assessment.data ? (
        <EmptyState title="No analysis yet">
          Connect a source or upload a résumé, then run the analysis.
        </EmptyState>
      ) : (
        <AutoGrid col={380} gap={20}>
          <div className="panel">
            <h3>Skill strength</h3>
            <SkillRadar
              dimensions={dimensions.map((d) => ({
                key: d.key,
                name: d.name,
                shortName: d.short_name,
                score: d.score,
                confidence: d.confidence,
                read: d.read,
              }))}
              onSelect={setSelected}
              selectedKey={activeKey}
            />
            <p className="subcopy" style={{ fontSize: 12.5, marginTop: 8 }}>
              Click a dimension to see how sure its score is, and why.
            </p>

            <Eyebrow style={{ margin: "18px 0 6px" }}>
              Least certain first
            </Eyebrow>
            <ul
              aria-label="Dimensions, least certain first"
              style={{ listStyle: "none", margin: 0, padding: 0 }}
            >
              {leastCertain.map((dimension) => (
                <li key={dimension.key}>
                  <button
                    type="button"
                    className="ledger-row"
                    aria-pressed={dimension.key === activeKey}
                    onClick={() => setSelected(dimension.key)}
                  >
                    <div className="row-between">
                      <span
                        style={{
                          fontSize: 14,
                          fontWeight: dimension.key === activeKey ? 700 : 500,
                        }}
                      >
                        {dimension.name}
                      </span>
                      <span style={{ fontSize: 12.5, fontWeight: 700 }}>
                        {dimension.needs_more_evidence && (
                          <span title="Thin evidence">⚠ </span>
                        )}
                        {percent(dimension.confidence)} sure
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="panel panel-column">
            {active && (
              <div>
                <Eyebrow>
                  Evidence · cited by {modelName(status.credential)}
                </Eyebrow>
                <h3 style={{ fontSize: 25, margin: "10px 0 4px" }}>
                  {active.name}
                </h3>
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 10,
                    marginBottom: 14,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--font-heading)",
                      fontSize: 40,
                      lineHeight: 1,
                      color: "var(--color-accent-700)",
                    }}
                  >
                    {active.score}
                  </span>
                  <span className="subcopy">/ 100</span>
                </div>

                <div className="row-between" style={{ marginBottom: 6 }}>
                  <Eyebrow>Confidence</Eyebrow>
                  <span style={{ fontSize: 13, fontWeight: 700 }}>
                    {percent(active.confidence)}
                  </span>
                </div>
                <ProgressBar
                  percent={active.confidence * 100}
                  label={`Confidence in ${active.name}`}
                />
                {active.needs_more_evidence ? (
                  <p
                    role="status"
                    className="note-warning"
                    style={{ margin: "10px 0 14px" }}
                  >
                    {/* Never colour alone. */}
                    <span aria-hidden="true">⚠</span> Thin evidence: this score
                    rests on {factCount(active.evidence_ids.length)}, not enough
                    to be sure of it.{" "}
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => navigate("sources")}
                    >
                      Connect more sources, like Jira,
                    </button>{" "}
                    to add more.
                  </p>
                ) : (
                  <p className="subcopy" style={{ margin: "10px 0 14px" }}>
                    Well supported: backed by{" "}
                    {factCount(active.evidence_ids.length)}.
                  </p>
                )}

                <p style={{ fontSize: 14.5, lineHeight: 1.65 }}>
                  {active.read}
                </p>
                {active.evidence_ids.map((id) => {
                  const item = byId.get(id);
                  return (
                    <div
                      key={id}
                      className="inset"
                      style={{ padding: "13px 16px", marginBottom: 10 }}
                    >
                      <div
                        className="eyebrow"
                        style={{
                          fontSize: 11,
                          letterSpacing: "0.08em",
                          color: "var(--color-accent-2-800)",
                        }}
                      >
                        {item?.reference ?? "Evidence"}
                      </div>
                      <div
                        style={{ fontSize: 14, lineHeight: 1.5, marginTop: 4 }}
                      >
                        {item?.fact ?? "No longer in your profile."}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="panel-actions">
              <Button onClick={() => navigate("roles")}>
                Match me to roles
              </Button>
            </div>
          </div>
        </AutoGrid>
      )}
    </section>
  );
}

function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

function factCount(count: number): string {
  return `${count} ${count === 1 ? "fact" : "facts"}`;
}

/**
 * How well the evidence backs these scores overall (domain decision 28),
 * computed with the analysis, next to Re-analyse.
 */
function ProfileConfidence({ value }: { value: number }) {
  const percent = Math.round(value * 100);
  return (
    <span className="confidence-pill">
      <span className="eyebrow" style={{ fontSize: 11.5 }}>
        Profile confidence
      </span>
      <span
        className="progress"
        style={{ width: 140, height: 10 }}
        role="progressbar"
        aria-label="Profile confidence: how well the evidence supports these scores"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span
          className="progress-fill progress-fill-positive"
          style={{ display: "block", width: `${percent}%`, height: "100%" }}
        />
      </span>
      <span style={{ fontFamily: "var(--font-heading)", fontSize: 20 }}>
        {percent}%
      </span>
      <span style={{ fontSize: 12.5, color: "var(--color-neutral-800)" }}>
        how well the evidence backs these scores
      </span>
    </span>
  );
}

/**
 * "Analysed 26 Sep 2026 on claude-sonnet-5 · 158 facts read". The fact count
 * is left out until the evidence has loaded. Pure.
 */
export function analysedLine(
  createdAt: string,
  modelId: string,
  factsRead: number | null,
): string {
  const parts = [`Analysed ${dayLabel(createdAt)} on ${modelId}`];
  if (factsRead !== null) parts.push(`${factCount(factsRead)} read`);
  return parts.join(" · ");
}
