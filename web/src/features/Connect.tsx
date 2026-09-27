import { useRef, useState } from "react";
import type { CallbackOutcome } from "./oauthCallback";
import { api } from "../api/client";
import type {
  Assessment,
  Connection,
  Dimension,
  Evidence,
  ProfileSummary,
  ResumeFile,
} from "../api/types";
import type { FactSelection } from "../charts/selection";
import { SourceMix } from "../charts/SourceMix";
import { WorkPlaces } from "../charts/WorkPlaces";
import {
  AutoGrid,
  Button,
  Done,
  ErrorNote,
  Eyebrow,
  Loading,
} from "../components/ui";
import { useShell } from "../shell/ShellContext";
import { FollowUpQuestions } from "./FollowUpQuestions";
import { messageOf, useAsync } from "./useAsync";

const LABELS: Record<string, { name: string; kind: string; note: string }> = {
  github: {
    name: "GitHub",
    kind: "Code, reviews, RFCs",
    note: "Commits, reviews and RFCs — the work a resume usually flattens.",
  },
  jira: {
    name: "Jira",
    kind: "Delivery scope",
    note: "Cycle time, epic ownership and incident response — your scope.",
  },
};

/**
 * Where evidence comes from: authorised sources, an uploaded resume, and the
 * user's answers to follow-up questions.
 */
export function Connect({ callback }: { callback?: CallbackOutcome | null }) {
  const { navigate } = useShell();
  // Refetched when a callback finishes, so a fresh connection shows as
  // connected without a reload.
  const connections = useAsync<Connection[]>(
    () => api.get("/connections"),
    [callback],
  );
  const resumes = useAsync<ResumeFile[]>(() => api.get("/resumes"), []);
  const evidence = useAsync<Evidence[]>(() => api.get("/evidence"), []);
  // Which facts the latest analysis cites, and whether it predates them.
  const assessment = useAsync<Assessment | null>(
    () => api.get("/assessments/latest"),
    [],
  );
  const profile = useAsync<ProfileSummary>(() => api.get("/profile"), []);
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The connector whose card is asking "are you sure?", if any.
  const [confirming, setConfirming] = useState<string | null>(null);
  // Facts picked on a chart or filter; the table lists only these while set.
  const [selection, setSelection] = useState<FactSelection | null>(null);

  async function connect(kind: string) {
    setBusy(kind);
    setError(null);
    try {
      const { url } = await api.get<{ url: string }>(
        `/connections/${kind}/authorize-url`,
      );
      window.location.href = url;
    } catch (caught) {
      setError(messageOf(caught));
      setBusy(null);
    }
  }

  async function sync(kind: string) {
    setBusy(kind);
    setError(null);
    try {
      await api.post(`/connections/${kind}/sync`);
      await connections.reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(null);
    }
  }

  async function disconnect(kind: string) {
    setBusy(kind);
    setError(null);
    try {
      await api.del(`/connections/${kind}`);
      setConfirming(null);
      setSelection(null);
      await Promise.all([connections.reload(), evidence.reload()]);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(null);
    }
  }

  async function upload(file: File) {
    setBusy("resume");
    setError(null);
    try {
      await api.upload("/resumes", file);
      await resumes.reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(null);
    }
  }

  const facts = evidence.data ?? [];
  const bySource = countBy(facts, (item) => item.source);
  const citedBy = citations(assessment.data);
  const uncited = facts.filter((item) => !citedBy.has(item.id));
  const isAnalysisBehind =
    assessment.data !== null &&
    profile.data !== null &&
    profile.data.version > assessment.data.profile_version;
  const picked = selection ? new Set(selection.ids) : null;
  const listed = picked
    ? facts.filter((item) => picked.has(item.id))
    : facts.slice(0, 50);
  const latestResume = (resumes.data ?? [])[0];

  return (
    <AutoGrid col={340}>
      <div>
        <p className="lead" style={{ marginTop: 0 }}>
          Every connector runs on OAuth — you approve the scopes, we never hold
          a password, and every claim the analysis makes points back at
          something here.
        </p>
        {callback?.connected && <Done>{callback.message}</Done>}
        <ErrorNote
          error={callback && !callback.connected ? callback.message : error}
        />

        {connections.loading ? (
          <Loading what="your sources" />
        ) : (
          <div className="stack" style={{ marginTop: 18 }}>
            {(connections.data ?? []).map((connection) => {
              const label = LABELS[connection.kind] ?? {
                name: connection.kind,
                kind: "",
                note: "",
              };
              return (
                <div key={connection.kind} className="panel panel-tight">
                  <div
                    className="row-between"
                    style={{ alignItems: "flex-start" }}
                  >
                    <div
                      className="row"
                      style={{ gap: 14, flexWrap: "nowrap" }}
                    >
                      <SourceGlyph
                        name={label.name}
                        on={connection.connected}
                      />
                      <div>
                        <div className="card-title">{label.name}</div>
                        <div className="subcopy">
                          {connection.connected ? (
                            connection.account ? (
                              <>
                                Connected as{" "}
                                <strong>{connection.account}</strong>
                              </>
                            ) : (
                              "Account unknown — sync to refresh"
                            )
                          ) : (
                            label.kind
                          )}
                        </div>
                      </div>
                    </div>
                    <span
                      className={
                        connection.connected
                          ? "tag tag-accent-2"
                          : "tag tag-outline"
                      }
                    >
                      {connection.connected ? "Connected" : "Not connected"}
                    </span>
                  </div>
                  <p
                    className="subcopy"
                    style={{
                      fontSize: 13.5,
                      lineHeight: 1.55,
                      margin: "13px 0",
                    }}
                  >
                    {label.note}
                  </p>
                  {connection.last_error && (
                    <p
                      style={{
                        color: "var(--status-critical)",
                        fontSize: 13,
                        fontWeight: 600,
                      }}
                    >
                      <span aria-hidden="true">⚠</span> {connection.last_error}
                    </p>
                  )}
                  {!connection.connected && connection.scopes.length > 0 && (
                    <ul
                      className="subcopy"
                      style={{
                        fontSize: 12.5,
                        margin: "0 0 13px 18px",
                        padding: 0,
                      }}
                    >
                      {connection.scopes.map((scope) => (
                        <li key={scope}>{scope}</li>
                      ))}
                    </ul>
                  )}
                  {confirming === connection.kind ? (
                    <div
                      role="group"
                      aria-label={`Disconnect ${label.name}`}
                      className="stack"
                      style={{ gap: 10 }}
                    >
                      <p style={{ margin: 0, fontSize: 13.5 }}>
                        Disconnect {connection.account ?? label.name}? This
                        removes {factCount(bySource[connection.kind] ?? 0)}{" "}
                        gathered from {label.name}.
                      </p>
                      <div className="row">
                        <Button
                          variant="danger"
                          busy={busy === connection.kind}
                          onClick={() => void disconnect(connection.kind)}
                        >
                          Disconnect
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={busy === connection.kind}
                          onClick={() => setConfirming(null)}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="row">
                      <Button
                        variant={connection.connected ? "secondary" : "primary"}
                        busy={busy === connection.kind}
                        onClick={() =>
                          connection.connected
                            ? sync(connection.kind)
                            : connect(connection.kind)
                        }
                      >
                        {connection.connected ? "Sync now" : "Connect"}
                      </Button>
                      {connection.connected && (
                        <Button
                          variant="ghost"
                          disabled={busy === connection.kind}
                          onClick={() => setConfirming(connection.kind)}
                        >
                          Disconnect
                        </Button>
                      )}
                      {connection.connected && (
                        <span className="muted" style={{ fontSize: 12.5 }}>
                          {connection.last_synced_at
                            ? `last synced ${new Date(connection.last_synced_at).toLocaleDateString()}`
                            : "not synced yet"}
                        </span>
                      )}
                    </div>
                  )}
                  {connection.connected && confirming !== connection.kind && (
                    <p
                      className="muted"
                      style={{ fontSize: 12.5, margin: "10px 0 0" }}
                    >
                      To use a different account, disconnect, then connect again
                      and pick the other account.
                    </p>
                  )}
                </div>
              );
            })}

            <div
              className="panel panel-tight row-between"
              style={{ alignItems: "center", flexWrap: "wrap" }}
            >
              <div>
                <div className="card-title">Existing résumé</div>
                <div className="subcopy" style={{ marginTop: 3 }}>
                  {latestResume
                    ? `${latestResume.filename} — ${latestResume.parse_error ?? latestResume.status}`
                    : "PDF or Word. Used as evidence now, and as the base document to revise later."}
                </div>
              </div>
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.docx,.txt"
                aria-label="Résumé file"
                style={{ display: "none" }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void upload(file);
                  event.target.value = "";
                }}
              />
              <div className="row">
                <Button
                  variant="secondary"
                  busy={busy === "resume"}
                  onClick={() => fileInput.current?.click()}
                >
                  Upload PDF / DOCX
                </Button>
                <Button onClick={() => navigate("strengths")}>
                  Analyze with AI
                </Button>
              </div>
            </div>

            <FollowUpQuestions
              onAnswered={() =>
                void Promise.all([
                  evidence.reload(),
                  assessment.reload(),
                  profile.reload(),
                ])
              }
            />
          </div>
        )}
      </div>

      <div className="stack" style={{ gap: 20 }}>
        <div className="callout">
          <Eyebrow style={{ marginBottom: 6 }}>What it found so far</Eyebrow>
          {evidence.loading ? (
            <Loading what="evidence" />
          ) : facts.length === 0 ? (
            <p
              className="callout-note"
              style={{ fontSize: 13.5, margin: "8px 0 0" }}
            >
              Nothing gathered yet. Connect a source or upload a résumé, then
              sync.
            </p>
          ) : (
            <>
              <SourceMix facts={facts} />
              <p
                className="callout-note"
                style={{ fontSize: 13.5, lineHeight: 1.55, margin: "14px 0 0" }}
              >
                {factCount(facts.length)}, each traceable to where it came from.
                The bar shares out facts, not effort: one fact can be a single
                pull request or a total of many.
              </p>
            </>
          )}
        </div>

        <WorkPlaces
          facts={facts}
          selectedKey={selection?.key ?? null}
          onSelect={setSelection}
        />

        {facts.length > 0 && (
          <div className="panel">
            <h3>Evidence gathered</h3>
            {selection ? (
              <div
                className="row-between"
                style={{ alignItems: "baseline", gap: 12 }}
              >
                <p className="subcopy">
                  Showing {factCount(listed.length)}: {selection.label}.
                </p>
                <button
                  type="button"
                  className="link-button"
                  style={{ fontSize: 13 }}
                  onClick={() => setSelection(null)}
                >
                  Show all
                </button>
              </div>
            ) : (
              <p className="subcopy">The first 50, grouped by source.</p>
            )}
            <CitationNote
              assessment={assessment.data}
              isLoading={assessment.loading}
              isBehind={isAnalysisBehind}
              total={facts.length}
              uncited={uncited.length}
              isShowingUncited={selection?.key === UNCITED}
              onShowUncited={() =>
                setSelection({
                  key: UNCITED,
                  label: "not cited by any score",
                  ids: uncited.map((item) => item.id),
                })
              }
            />
            <div className="table-scroll">
              <table className="data-table" aria-label="Evidence gathered">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Fact</th>
                    {assessment.data && <th>Cited by</th>}
                  </tr>
                </thead>
                <tbody>
                  {listed.map((item) => (
                    <tr key={item.id}>
                      <td className="muted" style={{ minWidth: 120 }}>
                        {item.reference}
                      </td>
                      <td>{item.fact}</td>
                      {assessment.data && (
                        <td style={{ minWidth: 110 }}>
                          <CitedBy dimensions={citedBy.get(item.id) ?? []} />
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </AutoGrid>
  );
}

function SourceGlyph({ name, on }: { name: string; on: boolean }) {
  return (
    <div
      aria-hidden="true"
      style={{
        width: 42,
        height: 42,
        flex: "0 0 auto",
        borderRadius: 999,
        background: on
          ? "var(--color-accent-2-200)"
          : "var(--color-accent-200)",
        color: on ? "var(--color-accent-2-800)" : "var(--color-accent-800)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-heading)",
        fontSize: 15,
      }}
    >
      {name.slice(0, 2)}
    </div>
  );
}

/** The table's selection key for facts no score cites. */
const UNCITED = "uncited";

/** Each fact's id, mapped to the dimensions whose score cites it. */
function citations(assessment: Assessment | null): Map<string, Dimension[]> {
  const cited = new Map<string, Dimension[]>();
  for (const dimension of assessment?.dimensions ?? []) {
    for (const id of dimension.evidence_ids) {
      cited.set(id, [...(cited.get(id) ?? []), dimension]);
    }
  }
  return cited;
}

function CitedBy({ dimensions }: { dimensions: Dimension[] }) {
  if (dimensions.length === 0) {
    return <span className="muted">—</span>;
  }
  return (
    <span className="cited-by">
      {dimensions.map((dimension) => (
        <span
          key={dimension.key}
          className="tag tag-accent-2"
          title={dimension.name}
        >
          {dimension.short_name || dimension.name}
        </span>
      ))}
    </span>
  );
}

/**
 * How much of the evidence the latest analysis actually leans on.
 *
 * A fact nothing cites is not wrong, but it is not helping a score either,
 * which is worth knowing before adding more of the same.
 */
function CitationNote({
  assessment,
  isLoading,
  isBehind,
  total,
  uncited,
  isShowingUncited,
  onShowUncited,
}: {
  assessment: Assessment | null;
  isLoading: boolean;
  isBehind: boolean;
  total: number;
  uncited: number;
  isShowingUncited: boolean;
  onShowUncited: () => void;
}) {
  if (isLoading) return null;
  if (assessment === null) {
    return (
      <p className="subcopy" style={{ fontSize: 13 }}>
        Run an analysis to see which facts back your scores.
      </p>
    );
  }
  return (
    <p className="subcopy" style={{ fontSize: 13 }}>
      {total - uncited} of {factCount(total)} back a score in your latest
      analysis ({new Date(assessment.created_at).toLocaleDateString()}).
      {isBehind &&
        " Your sources have changed since, so newer facts are not scored yet."}
      {uncited > 0 && !isShowingUncited && (
        <>
          {" "}
          <button type="button" className="link-button" onClick={onShowUncited}>
            Show the {uncited} not cited
          </button>
        </>
      )}
    </p>
  );
}

function factCount(count: number): string {
  return `${count} ${count === 1 ? "fact" : "facts"}`;
}

function countBy<T>(
  items: T[],
  key: (item: T) => string,
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) counts[key(item)] = (counts[key(item)] ?? 0) + 1;
  return counts;
}
