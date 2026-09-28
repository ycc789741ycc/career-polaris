import { useState } from "react";
import { api } from "../api/client";
import type {
  Assessment,
  CostEstimate,
  Evidence,
  EvidencePage,
} from "../api/types";
import { SkillRadar } from "../charts/SkillRadar";
import {
  AutoGrid,
  Button,
  Done,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
  YouVsBar,
} from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { CostConfirm } from "./CostConfirm";
import { messageOf, useAsync } from "./useAsync";

type Layout = "radar" | "ledger";

/**
 * The strength report.
 *
 * Nothing is spent without asking: the first run shows its estimated cost and
 * waits for a yes.
 *
 * The journey runs Sources → Strengths → Role map → Advisor, and a later step
 * never changes an earlier one's result. So the report reads only the evidence
 * and the analysis: no fit, role or bar from the role map, which reclusters
 * and rescores as the market moves. Comparing against a role's bar is the role
 * map's job, where "Where you clear it / where you don't" already does it.
 */
export function Strengths() {
  const { status, navigate } = useShell();
  const assessment = useAsync<Assessment | null>(
    () => api.get("/assessments/latest"),
    [],
  );
  const evidence = useAsync<Evidence[]>(
    () => api.items<EvidencePage>("/evidence"),
    [],
  );
  const [layout, setLayout] = useState<Layout>("radar");
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState(false);
  const [selected, setSelected] = useState<string | undefined>(undefined);

  async function askForEstimate() {
    setBusy(true);
    setError(null);
    try {
      setEstimate(await api.get<CostEstimate>("/assessments/cost-estimate"));
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
      setQueued(true);
      setEstimate(null);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  const dimensions = assessment.data?.dimensions ?? [];
  const activeKey = selected ?? dimensions[0]?.key;
  const active = dimensions.find((d) => d.key === activeKey);
  const byId = new Map((evidence.data ?? []).map((item) => [item.id, item]));
  const ledger = [...dimensions].sort((a, b) => a.score - b.score);

  return (
    <section>
      <div
        className="row-between"
        style={{ alignItems: "center", flexWrap: "wrap", marginBottom: 18 }}
      >
        <div className="row">
          <Eyebrow>Report layout</Eyebrow>
          <PillToggle
            pressed={layout === "radar"}
            onClick={() => setLayout("radar")}
          >
            Radar &amp; evidence
          </PillToggle>
          <PillToggle
            pressed={layout === "ledger"}
            onClick={() => setLayout("ledger")}
          >
            Ranked ledger
          </PillToggle>
        </div>
        <div className="row">
          {assessment.data && (
            <span className="muted" style={{ fontSize: 12.5 }}>
              Profile v{assessment.data.profile_version} ·{" "}
              {assessment.data.model_id} ·{" "}
              {new Date(assessment.data.created_at).toLocaleDateString()}
            </span>
          )}
          <Button
            variant={assessment.data ? "secondary" : "primary"}
            onClick={askForEstimate}
            busy={busy}
          >
            {assessment.data ? "Re-analyse" : "Analyse with AI"}
          </Button>
        </div>
      </div>

      <ErrorNote error={error} />
      {assessment.data?.is_out_of_date && !queued && (
        <p role="status" className="note-warning" style={{ margin: "8px 0" }}>
          {/* Never colour alone. */}
          <span aria-hidden="true">⚠</span> Out of date: your evidence has
          changed since this analysis ran, so these scores may not match it.
          Re-analyse to catch up.
        </p>
      )}
      {queued && (
        <Done>Queued. This runs on your model — reload in a moment.</Done>
      )}
      {estimate && (
        <CostConfirm
          busy={busy}
          onConfirm={confirm}
          onCancel={() => setEstimate(null)}
        >
          This will cost about <strong>${estimate.cost_usd}</strong> on{" "}
          {estimate.model_id}, charged to your own provider.
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
        <AutoGrid col={layout === "radar" ? 380 : 360} gap={20}>
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
              onSelect={(key) => {
                setSelected(key);
                setLayout("radar");
              }}
              selectedKey={activeKey}
            />
            <p className="subcopy" style={{ fontSize: 12.5, marginTop: 8 }}>
              Click a dimension to see the work it was scored from.
            </p>
          </div>

          <div className="panel panel-column">
            {layout === "radar" && active ? (
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
                  <span className="subcopy">
                    confidence {Math.round(active.confidence * 100)}%
                  </span>
                </div>
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
            ) : (
              <div>
                <Eyebrow style={{ marginBottom: 10 }}>
                  Every dimension, weakest first
                </Eyebrow>
                {ledger.map((dimension) => (
                  <button
                    key={dimension.key}
                    type="button"
                    className="ledger-row"
                    onClick={() => {
                      setSelected(dimension.key);
                      setLayout("radar");
                    }}
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
                        {dimension.score}
                      </span>
                    </div>
                    <div style={{ marginTop: 7 }}>
                      <YouVsBar you={dimension.score} label={dimension.name} />
                    </div>
                    <div
                      className="subcopy"
                      style={{ fontSize: 12.5, marginTop: 6 }}
                    >
                      {firstSentence(dimension.read)}
                    </div>
                  </button>
                ))}
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

function firstSentence(text: string): string {
  const end = text.search(/[.!?](\s|$)/);
  return end === -1 ? text : text.slice(0, end + 1);
}
