import { useEffect, useRef, useState } from "react";
import { api, streamEvents } from "../api/client";
import type {
  PlanEstimate,
  ResumeContent,
  ResumeExport,
  ResumeOptions,
  ResumeSummary,
  ResumeTemplate,
  ResumeVersion,
  TailoredResume,
  TargetRef,
} from "../api/types";
import {
  AutoGrid,
  Button,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
  RoundCheck,
  VerdictBadge,
} from "../components/ui";
import { type AdvisorTarget, sameTarget, targetQuery } from "./target";
import { modelName, useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { ago } from "./time";
import { messageOf } from "./useAsync";

type Ref = TargetRef;

const POLL_MS = 2000;

const TEMPLATES: {
  id: ResumeTemplate;
  name: string;
  note: string;
  swatch: string;
  color: string;
  rule: string;
}[] = [
  {
    id: "warm",
    name: "Warm",
    note: "Rounded, terracotta rule.",
    swatch: "#c67139",
    color: "#8a4a20",
    rule: "3px solid #c67139",
  },
  {
    id: "plain",
    name: "Plain",
    note: "ATS-safe, no ornament.",
    swatch: "#9b9691",
    color: "#201e1d",
    rule: "1px solid #cfcac5",
  },
  {
    id: "brief",
    name: "Brief",
    note: "One page, evidence first.",
    swatch: "#7a8a5e",
    color: "#4d5a35",
    rule: "3px solid #7a8a5e",
  },
];

const OPTION_LABELS: { key: keyof ResumeOptions; label: string }[] = [
  { key: "metrics", label: "Quantify bullets with data from Jira and GitHub" },
  { key: "reorder", label: "Reorder skills by what this role screens for" },
  { key: "trim", label: "Trim to one page" },
];

const SUGGESTIONS = [
  "Make the summary shorter",
  "Quantify every bullet",
  "Answer their top requirement first",
];

interface Exchange {
  request: string;
  reply: string;
  revisionId: string | null;
  hasProposal: boolean;
  applied: boolean;
  error: string | null;
  streaming: boolean;
}

/**
 * The Advisor's résumé tab: written for the one Target the Advisor is aimed at.
 *
 * The first version is written on the user's key from their cited evidence;
 * the tab polls it while it is being written (ADR 0006). The page is then
 * edited in place, saved as versions, revised through a streamed chat whose
 * proposals apply only on request, and exported as a PDF. Opening a résumé
 * kept for another Target moves the Advisor there.
 */
export function Resume({
  target,
  saved,
  onChanged,
  onRevisit,
}: {
  target: AdvisorTarget;
  /** Every tailored résumé, newest first — loaded by the Advisor. */
  saved: ResumeSummary[];
  /** A résumé was written or saved: the list is out of date. */
  onChanged: () => void;
  /** Open a résumé kept for another Target. */
  onRevisit: (entry: ResumeSummary) => void;
}) {
  const { status, navigate } = useShell();
  const flash = useToast();
  const model = modelName(status.credential);
  const ref: Ref = target.ref;

  // Opens with this Target's résumé, if it has one.
  const [resumeId, setResumeId] = useState<string | null>(
    () => saved.find((r) => sameTarget(r.target, ref))?.id ?? null,
  );
  const [resume, setResume] = useState<TailoredResume | null>(null);
  const [draft, setDraft] = useState<ResumeContent | null>(null);
  const [estimate, setEstimate] = useState<{
    ref: Ref;
    label: string;
    cost: PlanEstimate;
  } | null>(null);
  const [template, setTemplate] = useState<ResumeTemplate>("warm");
  const [options, setOptions] = useState<ResumeOptions>({
    metrics: true,
    reorder: true,
    trim: false,
  });
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [exporting, setExporting] = useState<ResumeExport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wasDrafting = useRef(false);

  const dirty =
    !!draft &&
    !!resume?.content &&
    JSON.stringify(draft) !== JSON.stringify(resume.content);

  // Read the open résumé, and keep re-reading it while it is being written.
  useEffect(() => {
    if (!resumeId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const next = await api.get<TailoredResume>(
          `/tailored-resumes/${resumeId}`,
        );
        if (cancelled) return;
        show(next);
        if (next.status === "drafting") {
          wasDrafting.current = true;
          timer = setTimeout(load, POLL_MS);
        } else if (wasDrafting.current) {
          wasDrafting.current = false;
          onChanged();
          flash(
            next.status === "ready"
              ? `Written for ${next.label}.`
              : "Writing failed — the reason is on the page.",
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId]);

  function show(next: TailoredResume) {
    setResume(next);
    setDraft(next.content);
    setTemplate(next.template);
    setOptions(next.options);
    setExchanges(
      next.revisions.map((r) => ({
        request: r.request,
        reply: r.reply,
        revisionId: r.id,
        hasProposal: r.has_proposal,
        applied: r.applied_version_id !== null,
        error: null,
        streaming: false,
      })),
    );
  }

  async function price(priced: Ref, label: string) {
    if (!status.credential) {
      flash("Writing runs on your model — add a key.");
      navigate("model");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const cost = await api.get<PlanEstimate>(
        `/tailored-resumes/cost-estimate?${targetQuery(priced)}`,
      );
      setEstimate({ ref: priced, label, cost });
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function write() {
    if (!estimate) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.post<ResumeSummary>("/tailored-resumes", {
        ...estimate.ref,
        template,
        options,
      });
      setEstimate(null);
      setResume(null);
      setDraft(null);
      setExchanges([]);
      setResumeId(created.id);
      onChanged();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function saveVersion() {
    if (!resume || !draft) return;
    setBusy(true);
    setError(null);
    try {
      const version = await api.post<ResumeVersion>(
        `/tailored-resumes/${resume.id}/versions`,
        { content: draft },
      );
      show(await api.get<TailoredResume>(`/tailored-resumes/${resume.id}`));
      onChanged();
      flash(`Saved version ${version.number} of “${resume.label}”.`);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function changeSettings(
    nextTemplate: ResumeTemplate,
    nextOptions: ResumeOptions,
  ) {
    setTemplate(nextTemplate);
    setOptions(nextOptions);
    if (!resume || resume.status !== "ready") return;
    try {
      await api.put(`/tailored-resumes/${resume.id}/settings`, {
        template: nextTemplate,
        options: nextOptions,
      });
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function exportPdf() {
    if (!resume?.version) return;
    setError(null);
    try {
      let job = await api.post<ResumeExport>(
        `/tailored-resumes/${resume.id}/exports`,
        { version: resume.version.number },
      );
      setExporting(job);
      while (job.status === "rendering") {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        job = await api.get<ResumeExport>(`/resume-exports/${job.id}`);
        setExporting(job);
      }
      if (job.status === "ready" && job.download_url) {
        flash(`Exported — ${resume.label}, ${template} template.`);
      }
    } catch (caught) {
      setError(messageOf(caught));
      setExporting(null);
    }
  }

  async function send(message: string) {
    if (!resume || !draft || !message.trim()) return;
    const index = exchanges.length;
    setExchanges((all) => [
      ...all,
      {
        request: message,
        reply: "",
        revisionId: null,
        hasProposal: false,
        applied: false,
        error: null,
        streaming: true,
      },
    ]);
    const update = (change: Partial<Exchange>) =>
      setExchanges((all) =>
        all.map((e, i) => (i === index ? { ...e, ...change } : e)),
      );
    try {
      await streamEvents(
        `/tailored-resumes/${resume.id}/revisions`,
        { message, content: draft },
        (event) => {
          const data = JSON.parse(event.data) as Record<string, unknown>;
          if (event.event === "text") {
            setExchanges((all) =>
              all.map((e, i) =>
                i === index ? { ...e, reply: e.reply + String(data.text) } : e,
              ),
            );
          } else if (event.event === "proposal") {
            update({
              revisionId: String(data.revision_id),
              hasProposal: data.proposal !== null,
              reply: String(data.reply),
            });
          } else if (event.event === "error") {
            update({ error: String(data.message) });
          }
        },
      );
    } catch (caught) {
      update({ error: messageOf(caught) });
    } finally {
      update({ streaming: false });
    }
  }

  async function apply(revisionId: string) {
    if (!resume) return;
    try {
      const version = await api.post<ResumeVersion>(
        `/tailored-resumes/${resume.id}/revisions/${revisionId}/apply`,
      );
      show(await api.get<TailoredResume>(`/tailored-resumes/${resume.id}`));
      onChanged();
      flash(`Applied as version ${version.number}.`);
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  function open(entry: ResumeSummary) {
    if (!sameTarget(entry.target, ref)) {
      onRevisit(entry);
      return;
    }
    if (entry.id !== resumeId) {
      setResume(null);
      setDraft(null);
      setExchanges([]);
      setResumeId(entry.id);
    }
    flash(`Opened “${entry.label}”.`);
  }

  return (
    <section>
      <div className="panel panel-tight" style={{ marginBottom: 20 }}>
        <Eyebrow>Write for</Eyebrow>
        <div
          style={{
            fontFamily: "var(--font-heading)",
            fontSize: 20,
            marginTop: 4,
          }}
        >
          {resume
            ? `${resume.label}${resume.snapshot?.fit != null ? ` · ${resume.snapshot.fit}% fit` : ""}`
            : `${target.label}${target.fit !== null ? ` · ${target.fit}% fit` : ""}`}
        </div>
        {!resumeId && (
          <div className="row" style={{ marginTop: 14 }}>
            <Button busy={busy} onClick={() => void price(ref, target.label)}>
              Write résumé for {target.roleName}
            </Button>
            <span className="subcopy">
              Written on your model from your own evidence; every line cites its
              source.
            </span>
          </div>
        )}
        <ErrorNote error={error} />
      </div>

      {estimate && (
        <CostConfirm
          busy={busy}
          onConfirm={() => void write()}
          onCancel={() => setEstimate(null)}
        >
          Writing a résumé for <strong>{estimate.label}</strong> costs about{" "}
          <strong>${estimate.cost.cost_usd}</strong> on {estimate.cost.model_id}
          , charged to your own provider.
          {estimate.cost.rate_is_published === false &&
            " We have no published price for that model, so this is a deliberately high guess."}
        </CostConfirm>
      )}

      <AutoGrid col={320} gap={20}>
        <div className="stack" style={{ gap: 18 }}>
          <div className="panel panel-tight">
            <Eyebrow style={{ marginBottom: 12 }}>Saved résumés</Eyebrow>
            {saved.length === 0 ? (
              <p className="subcopy" style={{ marginTop: 0 }}>
                None yet. Each one you write is kept here, with every version.
              </p>
            ) : (
              saved.map((entry) => (
                <div
                  key={entry.id}
                  className="history-row inset"
                  aria-current={entry.id === resumeId ? "true" : undefined}
                  style={{ marginBottom: 6 }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="history-name">{entry.label}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {entry.status === "drafting"
                        ? "Writing…"
                        : entry.status === "failed"
                          ? "Writing failed"
                          : `Saved ${ago(entry.updated_at)} · v${entry.latest_version ?? 1}`}
                    </div>
                  </div>
                  <Button variant="ghost" onClick={() => open(entry)}>
                    Open
                  </Button>
                </div>
              ))
            )}
            <Button
              variant="secondary"
              busy={busy}
              disabled={!dirty}
              onClick={() => void saveVersion()}
            >
              Save this version
            </Button>
            {dirty && (
              <p className="subcopy" style={{ fontSize: 12.5, marginTop: 8 }}>
                You have unsaved edits.
              </p>
            )}
          </div>

          <div className="panel panel-tight">
            <Eyebrow style={{ marginBottom: 12 }}>Template</Eyebrow>
            <div className="stack" style={{ gap: 10 }}>
              {TEMPLATES.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className="template-pick"
                  aria-pressed={template === t.id}
                  onClick={() => void changeSettings(t.id, options)}
                >
                  <span className="template-thumb" aria-hidden="true">
                    <span
                      style={{ height: 5, background: t.swatch, width: "100%" }}
                    />
                    <span />
                    <span />
                    <span style={{ width: "70%" }} />
                  </span>
                  <span>
                    <span
                      style={{
                        display: "block",
                        fontFamily: "var(--font-heading)",
                        fontSize: 15,
                      }}
                    >
                      {t.name}
                    </span>
                    <span className="subcopy" style={{ fontSize: 12.5 }}>
                      {t.note}
                    </span>
                  </span>
                </button>
              ))}
            </div>
            <div className="stack" style={{ gap: 10, marginTop: 16 }}>
              {OPTION_LABELS.map(({ key, label }) => (
                <RoundCheck
                  key={key}
                  checked={options[key]}
                  onChange={(on) =>
                    void changeSettings(template, { ...options, [key]: on })
                  }
                >
                  {label}
                </RoundCheck>
              ))}
            </div>
            <Button
              block
              busy={exporting?.status === "rendering"}
              disabled={!resume?.version || dirty}
              onClick={() => void exportPdf()}
            >
              Export as PDF
            </Button>
            {exporting?.status === "ready" && exporting.download_url && (
              <p style={{ fontSize: 13, margin: "10px 0 0" }}>
                <a
                  href={exporting.download_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download the PDF
                </a>{" "}
                <span className="muted">(the link expires shortly)</span>
              </p>
            )}
            {exporting?.status === "failed" && (
              <ErrorNote error={exporting.error?.message ?? "Export failed."} />
            )}
            <p className="subcopy" style={{ fontSize: 12.5, marginTop: 10 }}>
              {dirty
                ? "Save this version first — the export is of a saved version."
                : resume?.snapshot
                  ? `Highlighted lines were rewritten for ${resume.snapshot.role_name ?? resume.snapshot.title} at ${resume.snapshot.company}, from the sources cited under each bullet.`
                  : "The export is a white, printable page in the template you pick."}
            </p>
          </div>
        </div>

        <div>
          {!resume ? (
            resumeId ? (
              <Loading what="the résumé" />
            ) : (
              <EmptyState title="No résumé for this target yet">
                Write one above. The first version is customised to{" "}
                {target.label}.
              </EmptyState>
            )
          ) : resume.status === "drafting" ? (
            <div className="resume-page" role="status">
              <span className="model-pill">
                Writing on {model} for {resume.label}…
              </span>
              <p className="subcopy" style={{ marginTop: 12 }}>
                Reading your evidence against their requirements. The page
                updates itself when it is done.
              </p>
            </div>
          ) : resume.status === "failed" ? (
            <div className="panel">
              <h3>This résumé could not be written</h3>
              <ErrorNote error={resume.error?.message ?? "Writing failed."} />
              {(resume.error?.code?.startsWith("ai_credential") ||
                resume.error?.code === "ai_budget_exceeded") && (
                <Button variant="ghost" onClick={() => navigate("model")}>
                  Open AI &amp; model
                </Button>
              )}
            </div>
          ) : draft ? (
            <ResumePage
              key={resume.version?.id}
              content={draft}
              evidence={resume.evidence}
              template={
                TEMPLATES.find((t) => t.id === template) ?? TEMPLATES[0]!
              }
              reorder={options.reorder}
              onChange={setDraft}
            />
          ) : null}
        </div>

        <div className="stack" style={{ gap: 18 }}>
          <div className="callout" style={{ padding: 22 }}>
            <Eyebrow>Their requirements → your evidence</Eyebrow>
            {!resume || resume.coverage.length === 0 ? (
              <p
                className="callout-note"
                style={{ fontSize: 13, margin: "10px 0 0" }}
              >
                Once a résumé is written, each of their requirements shows here
                as covered, partial or a gap, with the work that backs it.
              </p>
            ) : (
              <div className="divided">
                {resume.coverage.map((row) => (
                  <div key={row.requirement}>
                    <div
                      className="row"
                      style={{
                        gap: 8,
                        flexWrap: "nowrap",
                        alignItems: "baseline",
                      }}
                    >
                      <VerdictBadge verdict={row.verdict} />
                      <span style={{ fontSize: 13.5, fontWeight: 700 }}>
                        {row.requirement}
                      </span>
                    </div>
                    <div
                      className="callout-note"
                      style={{ fontSize: 12.5, marginTop: 5 }}
                    >
                      {row.evidence.length > 0
                        ? row.evidence
                            .map((e) => `${e.reference} — ${e.fact}`)
                            .join(" · ")
                        : "Nothing in your sources speaks to this yet."}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <ChatPanel
            model={model}
            target={
              resume?.snapshot?.role_name ?? resume?.snapshot?.title ?? null
            }
            enabled={resume?.status === "ready" && !!draft}
            exchanges={exchanges}
            onSend={(message) => void send(message)}
            onApply={(revisionId) => void apply(revisionId)}
            onDismiss={(index) =>
              setExchanges((all) =>
                all.map((e, i) =>
                  i === index ? { ...e, hasProposal: false } : e,
                ),
              )
            }
          />
        </div>
      </AutoGrid>
    </section>
  );
}

function ResumePage({
  content,
  evidence,
  template,
  reorder,
  onChange,
}: {
  content: ResumeContent;
  evidence: TailoredResume["evidence"];
  template: (typeof TEMPLATES)[number];
  reorder: boolean;
  onChange: (next: ResumeContent) => void;
}) {
  const edit = (patch: Partial<ResumeContent>) =>
    onChange({ ...content, ...patch });

  const editBullet = (p: number, b: number, text: string) =>
    onChange({
      ...content,
      experience: content.experience.map((position, pi) =>
        pi !== p
          ? position
          : {
              ...position,
              bullets: position.bullets.map((bullet, bi) =>
                bi === b ? { ...bullet, text } : bullet,
              ),
            },
      ),
    });

  return (
    <article className="resume-page" aria-label="Résumé">
      <header
        style={{
          borderBottom: template.rule,
          paddingBottom: 14,
          marginBottom: 20,
        }}
      >
        <div
          className="resume-name"
          style={{ color: template.color }}
          contentEditable
          suppressContentEditableWarning
          aria-label="Name"
          onBlur={(event) =>
            edit({ name: event.currentTarget.textContent ?? "" })
          }
        >
          {content.name}
        </div>
        <div className="resume-contact">
          {[content.headline, content.contact].filter(Boolean).join(" · ")}
        </div>
      </header>

      <div
        className="resume-section"
        style={{ color: template.color, marginBottom: 6 }}
      >
        Summary
      </div>
      <p
        style={{ fontSize: 14, lineHeight: 1.65, margin: "0 0 22px" }}
        contentEditable
        suppressContentEditableWarning
        aria-label="Summary"
        onBlur={(event) =>
          edit({ summary: event.currentTarget.textContent ?? "" })
        }
      >
        {content.summary}
      </p>

      <div
        className="resume-section"
        style={{ color: template.color, marginBottom: 10 }}
      >
        Experience
      </div>
      {content.experience.map((position, p) => (
        <div key={`${position.title}-${p}`} style={{ marginBottom: 20 }}>
          <div className="row-between">
            <span className="resume-job-title">
              {position.title}
              {position.org ? ` — ${position.org}` : ""}
            </span>
            <span className="resume-when">{position.when}</span>
          </div>
          {position.bullets.map((bullet, b) => (
            <div key={b} className="resume-bullet">
              <span
                className="resume-bullet-dot"
                style={{ background: template.swatch }}
                aria-hidden="true"
              />
              <div style={{ flex: 1 }}>
                <span
                  className="resume-bullet-text"
                  data-rewritten={bullet.answers !== null}
                  contentEditable
                  suppressContentEditableWarning
                  onBlur={(event) =>
                    editBullet(p, b, event.currentTarget.textContent ?? "")
                  }
                >
                  {bullet.text}
                </span>
                <div className="resume-cite">{citeLine(bullet, evidence)}</div>
              </div>
            </div>
          ))}
        </div>
      ))}

      <div
        className="resume-section"
        style={{ color: template.color, marginBottom: 10 }}
      >
        Skills{reorder ? ", ordered for this role" : ""}
      </div>
      <div className="row" style={{ gap: 8 }}>
        {content.skills.map((skill, index) => (
          <span
            key={skill}
            className="resume-skill"
            data-lead={reorder && index < 3}
          >
            {skill}
          </span>
        ))}
      </div>

      <p
        style={{
          fontSize: 12,
          color: "#8a847e",
          marginTop: 24,
          marginBottom: 0,
        }}
      >
        Click any line to edit it directly. Grey notes show the source each line
        was written from.
      </p>
    </article>
  );
}

/** The grey note under a line: where it came from, and what it answers. */
export function citeLine(
  bullet: ResumeContent["experience"][number]["bullets"][number],
  evidence: TailoredResume["evidence"],
): string {
  const sources = bullet.evidence_ids
    .map((id) => evidence[id])
    .filter((note) => note !== undefined)
    .map((note) => note.reference);
  if (sources.length === 0) {
    return bullet.origin === "yours"
      ? "Your edit — no source cited"
      : "Source no longer in your profile";
  }
  const answers = bullet.answers ? ` — answers “${bullet.answers}”` : "";
  const edited = bullet.origin === "yours" ? " · edited by you" : "";
  return `${sources.join(" + ")}${answers}${edited}`;
}

function ChatPanel({
  model,
  target,
  enabled,
  exchanges,
  onSend,
  onApply,
  onDismiss,
}: {
  model: string;
  target: string | null;
  enabled: boolean;
  exchanges: Exchange[];
  onSend: (message: string) => void;
  onApply: (revisionId: string) => void;
  onDismiss: (index: number) => void;
}) {
  const [message, setMessage] = useState("");
  const streaming = exchanges.some((e) => e.streaming);
  const submit = (text: string) => {
    if (!text.trim() || streaming || !enabled) return;
    onSend(text.trim());
    setMessage("");
  };

  return (
    <div
      className="panel panel-tight"
      style={{ display: "flex", flexDirection: "column", minHeight: 420 }}
    >
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <span className="ai-badge" aria-hidden="true">
          AI
        </span>
        <div>
          <div style={{ fontSize: 14.5, fontWeight: 700 }}>
            Revise with {model}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            Writes from your sources to fit {target ?? "the role you pick"}
          </div>
        </div>
      </div>

      <div className="chat-log" aria-live="polite">
        <div className="bubble bubble-ai">
          {enabled
            ? `I have your profile and the bar for ${target ?? "this role"}. Ask me to rewrite anything — or use a suggestion below.`
            : "Write a résumé first; then ask me to rewrite anything in it."}
        </div>
        {exchanges.map((exchange, index) => (
          <div key={index} className="stack" style={{ gap: 10 }}>
            <div className="bubble bubble-mine">{exchange.request}</div>
            <div className="bubble bubble-ai">
              {exchange.reply || (exchange.streaming ? "…" : "")}
              {exchange.error && (
                <span
                  role="alert"
                  style={{
                    display: "block",
                    color: "var(--status-critical)",
                    fontWeight: 600,
                    marginTop: exchange.reply ? 8 : 0,
                  }}
                >
                  <span aria-hidden="true">⚠</span> {exchange.error}
                </span>
              )}
              {exchange.hasProposal &&
                exchange.revisionId &&
                !exchange.applied && (
                  <span className="row" style={{ marginTop: 10 }}>
                    <Button onClick={() => onApply(exchange.revisionId!)}>
                      Apply
                    </Button>
                    <Button variant="ghost" onClick={() => onDismiss(index)}>
                      Dismiss
                    </Button>
                  </span>
                )}
              {exchange.applied && (
                <span
                  className="muted"
                  style={{ display: "block", fontSize: 12, marginTop: 6 }}
                >
                  Applied as a new version.
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="row" style={{ gap: 6, marginBottom: 10 }}>
        {SUGGESTIONS.map((suggestion) => (
          <PillToggle
            key={suggestion}
            small
            pressed={false}
            disabled={!enabled || streaming}
            onClick={() => submit(suggestion)}
          >
            {suggestion}
          </PillToggle>
        ))}
      </div>
      <form
        className="row"
        style={{ flexWrap: "nowrap" }}
        onSubmit={(event) => {
          event.preventDefault();
          submit(message);
        }}
      >
        <input
          className="input"
          aria-label="Ask for a change"
          placeholder="Ask for a change…"
          value={message}
          disabled={!enabled}
          onChange={(event) => setMessage(event.target.value)}
        />
        <Button
          type="submit"
          disabled={!enabled || streaming || !message.trim()}
        >
          Send
        </Button>
      </form>
    </div>
  );
}
