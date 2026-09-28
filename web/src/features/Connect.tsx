import { useEffect, useRef, useState } from "react";
import type { CallbackOutcome } from "./oauthCallback";
import { api } from "../api/client";
import type {
  Connection,
  ConnectionPage,
  Evidence,
  EvidencePage,
  ResumeFile,
  ResumeFilePage,
} from "../api/types";
import type { FactSelection } from "../charts/selection";
import { SourceMix, sourceShares } from "../charts/SourceMix";
import { SourceIcon } from "../components/SourceIcon";
import { WorkPlaces } from "../charts/WorkPlaces";
import {
  AutoGrid,
  Button,
  Done,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
} from "../components/ui";
import { sourcesBusy, useActivity } from "../shell/activity";
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
 *
 * Step 01 of the journey shows the collected facts themselves, filterable by
 * source, and nothing the analysis made of them: which score cites a fact
 * belongs to Strengths. The follow-up questions stay here because answering
 * one is how the user adds evidence where it is too thin to be sure.
 *
 * A sync or a parse runs in the background; the card says so while it does,
 * the lists reload when it is done, and the analysis waits for it (ADR 0018).
 */
export function Connect({ callback }: { callback?: CallbackOutcome | null }) {
  const { navigate } = useShell();
  const { activity, refresh: refreshActivity, settled } = useActivity();
  // Refetched when a callback finishes, so a fresh connection shows as
  // connected without a reload, and when a sync or parse finishes, so what it
  // wrote shows without one either.
  const connections = useAsync<Connection[]>(
    () => api.items<ConnectionPage>("/connections"),
    [callback, settled.sources],
  );
  const resumes = useAsync<ResumeFile[]>(
    () => api.items<ResumeFilePage>("/resumes"),
    [settled.sources],
  );
  const evidence = useAsync<Evidence[]>(
    () => api.items<EvidencePage>("/evidence"),
    [settled.sources],
  );
  // A fresh connection starts syncing at once.
  useEffect(() => {
    if (callback?.connected) void refreshActivity();
  }, [callback, refreshActivity]);
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The connector, or résumé id, whose card is asking "are you sure?".
  const [confirming, setConfirming] = useState<string | null>(null);
  // Facts picked on a chart; the table lists only these while set.
  const [selection, setSelection] = useState<FactSelection | null>(null);
  // The one source the table lists, or every source when null.
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);

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
      await refreshActivity();
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

  async function removeResume(id: string) {
    setBusy(id);
    setError(null);
    try {
      await api.del(`/resumes/${id}`);
      setConfirming(null);
      setSelection(null);
      await Promise.all([resumes.reload(), evidence.reload()]);
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
      await Promise.all([resumes.reload(), refreshActivity()]);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(null);
    }
  }

  const facts = evidence.data ?? [];
  const bySource = countBy(facts, (item) => item.source);
  const shares = sourceShares(facts);
  const filtered = sourceFilter
    ? facts.filter((item) => item.source === sourceFilter)
    : facts;
  const filterName = shares.find((s) => s.source === sourceFilter)?.name;
  const picked = selection ? new Set(selection.ids) : null;
  const listed = picked
    ? filtered.filter((item) => picked.has(item.id))
    : filtered.slice(0, TABLE_ROWS);

  function filterBy(source: string | null) {
    setSourceFilter(source);
    // A place belongs to one source; picking another source drops it.
    if (selection && source !== null) {
      const ids = new Set(selection.ids);
      if (!facts.some((f) => ids.has(f.id) && f.source === source)) {
        setSelection(null);
      }
    }
  }
  const uploaded = resumes.data ?? [];
  const latestResume = uploaded[0];
  const syncing = new Set((activity?.syncing ?? []).map((work) => work.label));
  const parsing = new Set((activity?.parsing ?? []).map((work) => work.label));

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
                        kind={connection.kind}
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
                      {syncing.has(connection.kind)
                        ? "Syncing…"
                        : connection.connected
                          ? "Connected"
                          : "Not connected"}
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
                        disabled={syncing.has(connection.kind)}
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
                    ? `${latestResume.filename} — ${resumeState(latestResume, parsing)}`
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
                <Button
                  onClick={() => navigate("strengths")}
                  disabled={sourcesBusy(activity)}
                >
                  Analyze with AI
                </Button>
              </div>
            </div>

            {uploaded.length > 0 && (
              <ul className="stack" style={{ gap: 10, margin: 0, padding: 0 }}>
                {uploaded.map((resume) => (
                  <li
                    key={resume.id}
                    className="panel panel-tight"
                    style={{ listStyle: "none" }}
                  >
                    {confirming === resume.id ? (
                      <div
                        role="group"
                        aria-label={`Remove ${resume.filename}`}
                        className="stack"
                        style={{ gap: 10 }}
                      >
                        <p style={{ margin: 0, fontSize: 13.5 }}>
                          Remove {resume.filename}? This deletes the file and
                          the facts taken from it. Your analysis will be out of
                          date until you re-analyse.
                        </p>
                        <div className="row">
                          <Button
                            variant="danger"
                            busy={busy === resume.id}
                            onClick={() => void removeResume(resume.id)}
                          >
                            Remove
                          </Button>
                          <Button
                            variant="ghost"
                            disabled={busy === resume.id}
                            onClick={() => setConfirming(null)}
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div
                        className="row-between"
                        style={{ alignItems: "center" }}
                      >
                        <span style={{ fontSize: 13.5 }}>
                          {resume.filename}{" "}
                          <span className="muted">
                            · uploaded{" "}
                            {new Date(resume.uploaded_at).toLocaleDateString()}
                          </span>
                        </span>
                        <Button
                          variant="ghost"
                          onClick={() => setConfirming(resume.id)}
                        >
                          Remove
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <FollowUpQuestions onAnswered={() => void evidence.reload()} />
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
                commit or a total of many.
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
            {shares.length > 1 && (
              <div
                className="row"
                role="group"
                aria-label="Filter by source"
                style={{ margin: "4px 0 10px" }}
              >
                <PillToggle
                  small
                  pressed={sourceFilter === null}
                  onClick={() => filterBy(null)}
                >
                  All · {facts.length}
                </PillToggle>
                {shares.map((share) => (
                  <PillToggle
                    key={share.source}
                    small
                    pressed={sourceFilter === share.source}
                    onClick={() => filterBy(share.source)}
                  >
                    {share.name} · {share.count}
                  </PillToggle>
                ))}
              </div>
            )}
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
              <p className="subcopy">
                {filtered.length > TABLE_ROWS
                  ? `The first ${TABLE_ROWS} of ${factCount(filtered.length)}`
                  : `All ${factCount(filtered.length)}`}
                {filterName ? ` from ${filterName}` : ", grouped by source"}.
              </p>
            )}
            <div className="table-scroll">
              <table className="data-table" aria-label="Evidence gathered">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Fact</th>
                  </tr>
                </thead>
                <tbody>
                  {listed.map((item) => (
                    <tr key={item.id}>
                      <td className="muted" style={{ minWidth: 120 }}>
                        {item.reference}
                      </td>
                      <td>{item.fact}</td>
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

function SourceGlyph({ kind, on }: { kind: string; on: boolean }) {
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
      }}
    >
      <SourceIcon source={kind} size={22} />
    </div>
  );
}

/** Rows the table lists before a filter or a pick narrows it. */
const TABLE_ROWS = 50;

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

/** What became of an upload, in words. */
function resumeState(resume: ResumeFile, parsing: Set<string>): string {
  if (resume.parse_error) return resume.parse_error;
  if (resume.status === "parsed") return "parsed";
  return parsing.has(resume.filename) ? "reading…" : resume.status;
}
