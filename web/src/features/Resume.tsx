import { type CSSProperties, useEffect, useRef, useState } from "react";
import { api, streamEvents } from "../api/client";
import type {
  PlanEstimate,
  ResumeBullet,
  ResumeContact,
  ResumeContent,
  ResumeExport,
  ResumeSection,
  ResumeSectionSlot,
  ResumeOptions,
  ResumeSummary,
  ResumeTemplate,
  ResumeTemplateLimits,
  ResumeTemplateLook,
  ResumeTemplatePage,
  ResumeTemplateSpec,
  ResumeVersion,
  TailoredResume,
  TargetRef,
} from "../api/types";
import {
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
import { hasAi, modelName, useShell } from "../shell/ShellContext";
import { useActivity } from "../shell/activity";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { startDownload } from "./download";
import {
  isEmptySection,
  SECTION_HEADINGS,
  sectionHeading,
  SectionsPanel,
} from "./ResumeSections";
import { EvidenceDisclosure } from "./EvidenceDisclosure";
import { OutdatedBanner } from "./OutdatedBanner";
import { TemplateEditor, withSpec } from "./ResumeTemplates";
import { dayLabel } from "./time";
import { messageOf } from "./useAsync";

type Ref = TargetRef;

const POLL_MS = 2000;

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
 *
 * The preview is the PDF's page: its template, sizes, margins and trim come
 * from GET /resume-templates, the definition the renderer uses, and Export
 * downloads the file the moment it is rendered (ADR 0038). "Make your own"
 * keeps a template of the user's own, previewed on the page as it is edited
 * (ADR 0040).
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
  // A job just started: the shell polls it, and the tab shows its card.
  const { refresh: refreshActivity } = useActivity();
  const model = modelName(status);
  const ref: Ref = target.ref;

  // Opens with this Target's résumé, if it has one.
  const [resumeId, setResumeId] = useState<string | null>(
    () => saved.find((r) => sameTarget(r.target, ref))?.id ?? null,
  );
  const [resume, setResume] = useState<TailoredResume | null>(null);
  const [draft, setDraft] = useState<ResumeContent | null>(null);
  // The drafts before each unsaved edit, newest last, for Undo. Saving or
  // opening another résumé starts it again.
  const [undoStack, setUndoStack] = useState<ResumeContent[]>([]);
  const [estimate, setEstimate] = useState<{
    ref: Ref;
    label: string;
    cost: PlanEstimate;
    /** Set when the estimate is for writing this résumé again (ADR 0035). */
    regenerates: string | null;
    /** Set when the estimate is for filling a new section (ADR 0039). */
    section?: ResumeSectionSlot;
  } | null>(null);
  // Sections added in this visit, marked "New" in the panel.
  const [added, setAdded] = useState<string[]>([]);
  // Bumped to re-read the open résumé after asking for it to be written again.
  const [reloads, setReloads] = useState(0);
  const [template, setTemplate] = useState<ResumeTemplate>("organic");
  const [options, setOptions] = useState<ResumeOptions>({
    metrics: true,
    reorder: true,
    trim: false,
  });
  // This résumé's own fonts over its template's; null keeps the template's
  // (ADR 0047).
  const [fonts, setFonts] = useState<ResumeFonts>(NO_FONTS);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [exporting, setExporting] = useState<ResumeExport | null>(null);
  const [templates, setTemplates] = useState<ResumeTemplateLook[]>([]);
  const [limits, setLimits] = useState<ResumeTemplateLimits | null>(null);
  // The template being made or changed, and its spec as it stands.
  const [editor, setEditor] = useState<{
    from: ResumeTemplateLook;
    editing: boolean;
  } | null>(null);
  const [preview, setPreview] = useState<ResumeTemplateSpec | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wasDrafting = useRef(false);

  const chosen =
    templates.find((t) => t.id === template) ?? templates[0] ?? null;
  // While a template is being edited, the page previews it; otherwise the
  // chosen one, in the résumé's own fonts.
  const look =
    editor && preview
      ? withSpec(editor.from, preview)
      : chosen && (fonts.heading_font || fonts.body_font)
        ? withSpec(chosen, {
            ...chosen.spec,
            heading_font: fonts.heading_font ?? chosen.spec.heading_font,
            body_font: fonts.body_font ?? chosen.spec.body_font,
          })
        : chosen;

  // What writing it again costs, priced up front for the Write-for card.
  const [regenerateCost, setRegenerateCost] = useState<PlanEstimate | null>(
    null,
  );
  const nextVersion = (resume?.versions[0]?.number ?? 0) + 1;
  useEffect(() => {
    if (resume?.status !== "ready") return;
    let cancelled = false;
    api
      .get<PlanEstimate>(
        `/tailored-resumes/cost-estimate?${targetQuery(resume.target)}`,
      )
      .then((cost) => {
        if (!cancelled) setRegenerateCost(cost);
      })
      // The line just leaves the price out; Regenerate prices it again.
      .catch(() => setRegenerateCost(null));
    return () => {
      cancelled = true;
    };
  }, [resume?.id, resume?.status]); // eslint-disable-line react-hooks/exhaustive-deps

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
        if (next.status === "drafting" || next.status === "filling") {
          wasDrafting.current = true;
          timer = setTimeout(load, POLL_MS);
        } else if (wasDrafting.current) {
          wasDrafting.current = false;
          onChanged();
          flash(
            next.status === "ready"
              ? next.error
                ? "That section could not be filled — the reason is on the page."
                : `Written for ${next.label}.`
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
  }, [resumeId, reloads]);

  // Every template, as the renderer draws it: the picker and the page read it.
  useEffect(() => {
    api
      .items<ResumeTemplatePage>("/resume-templates")
      .then(setTemplates)
      .catch((caught: unknown) => setError(messageOf(caught)));
    api
      .get<ResumeTemplateLimits>("/resume-templates/limits")
      .then(setLimits)
      .catch((caught: unknown) => setError(messageOf(caught)));
  }, []);

  function openEditor(from: ResumeTemplateLook, editing: boolean) {
    setEditor({ from, editing });
    setPreview(from.spec);
  }

  function closeEditor() {
    setEditor(null);
    setPreview(null);
  }

  function templateSaved(saved: ResumeTemplateLook) {
    setTemplates((all) =>
      all.some((t) => t.id === saved.id)
        ? all.map((t) => (t.id === saved.id ? saved : t))
        : [...all, saved],
    );
    closeEditor();
    void changeSettings(saved.id, options);
    flash(`Saved — ${saved.name}.`);
  }

  function templateDeleted(id: string) {
    setTemplates((all) => all.filter((t) => t.id !== id));
    closeEditor();
    // The server moved every résumé set in it to Organic.
    if (template === id) setTemplate("organic");
    flash("Template deleted.");
  }

  /** An edit to the draft, remembered so Undo can take it back. */
  function editDraft(next: ResumeContent) {
    if (draft && !isSameContent(draft, next)) {
      setUndoStack((stack) => getStackWith(stack, draft));
    }
    setDraft(next);
  }

  /** Back to the draft before the last unsaved edit. */
  function undo() {
    const previous = undoStack[undoStack.length - 1];
    if (!previous) return;
    setUndoStack((stack) => stack.slice(0, -1));
    setDraft(previous);
  }

  // Cmd/Ctrl+Z undoes the last edit while no field is being typed in: a line
  // being edited keeps the browser's own undo.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "z" || event.shiftKey) return;
      if (!(event.metaKey || event.ctrlKey)) return;
      const at = document.activeElement as HTMLElement | null;
      if (
        at &&
        (at.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(at.tagName))
      ) {
        return;
      }
      if (undoStack.length === 0) return;
      event.preventDefault();
      undo();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  function show(next: TailoredResume) {
    setResume(next);
    setDraft(next.content);
    setUndoStack([]);
    setTemplate(next.template);
    setOptions(next.options);
    setFonts({ heading_font: next.heading_font, body_font: next.body_font });
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

  async function price(
    priced: Ref,
    label: string,
    regenerates: string | null = null,
  ) {
    if (!hasAi(status)) {
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
      setEstimate({ ref: priced, label, cost, regenerates });
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function priceSection(slot: ResumeSectionSlot) {
    if (!resume) return;
    if (dirty) {
      // A section is filled into the saved version, so unsaved changes
      // would be written over when it lands.
      setError(
        "Save your changes first: a section is filled into the saved version.",
      );
      return;
    }
    if (!hasAi(status)) {
      flash("Sections are filled on your model — add a key.");
      navigate("model");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const query = new URLSearchParams({ kind: slot.kind });
      if (slot.title) query.set("title", slot.title);
      const cost = await api.get<PlanEstimate>(
        `/tailored-resumes/${resume.id}/sections/estimate?${query.toString()}`,
      );
      setEstimate({
        ref: resume.target,
        label: sectionHeading(slot),
        cost,
        regenerates: null,
        section: slot,
      });
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
      if (estimate.section && resume) {
        // Shown, or added, then filled from the sources as the next version.
        await api.post<ResumeSummary>(
          `/tailored-resumes/${resume.id}/sections`,
          { kind: estimate.section.kind, title: estimate.section.title },
        );
        setAdded((all) => [
          ...all,
          `${estimate.section!.kind}:${estimate.section!.title ?? ""}`,
        ]);
        setEstimate(null);
        setReloads((n) => n + 1);
        void refreshActivity();
        return;
      }
      if (estimate.regenerates) {
        // The same résumé, written again as its next version.
        await api.post<ResumeSummary>(
          `/tailored-resumes/${estimate.regenerates}/regenerate`,
        );
        setEstimate(null);
        setReloads((n) => n + 1);
        onChanged();
        void refreshActivity();
        return;
      }
      const created = await api.post<ResumeSummary>("/tailored-resumes", {
        ...estimate.ref,
        template,
        options,
      });
      setEstimate(null);
      setResume(null);
      setDraft(null);
      setUndoStack([]);
      setExchanges([]);
      setResumeId(created.id);
      onChanged();
      void refreshActivity();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function saveVersion(content: ResumeContent | null = draft) {
    if (!resume || !content) return;
    setBusy(true);
    setError(null);
    try {
      const version = await api.post<ResumeVersion>(
        `/tailored-resumes/${resume.id}/versions`,
        { content },
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
    nextFonts: ResumeFonts = fonts,
  ) {
    setTemplate(nextTemplate);
    setOptions(nextOptions);
    setFonts(nextFonts);
    if (!resume || resume.status !== "ready") return;
    try {
      await api.put(`/tailored-resumes/${resume.id}/settings`, {
        template: nextTemplate,
        options: nextOptions,
        ...nextFonts,
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
        // Signed just now, so it is used before it can expire.
        startDownload(job.download_url);
        flash(`Downloaded — ${resume.label}, ${chosen?.name ?? template}.`);
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
      setUndoStack([]);
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
        {saved.length > 0 && (
          <label className="row resume-version" style={{ marginTop: 12 }}>
            <span className="field-label" style={{ margin: 0 }}>
              Version
            </span>
            <select
              className="input"
              value={resumeId ?? ""}
              onChange={(event) => {
                const entry = saved.find((r) => r.id === event.target.value);
                if (entry) open(entry);
              }}
            >
              {!resumeId && <option value="">None for this target yet</option>}
              {saved.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {savedLine(entry)}
                </option>
              ))}
            </select>
          </label>
        )}
        {resume?.status === "ready" && (
          <div className="row" style={{ marginTop: 14, gap: 12 }}>
            <Button
              busy={busy}
              onClick={() => void price(resume.target, resume.label, resume.id)}
            >
              Regenerate résumé
            </Button>
            <span className="subcopy" style={{ fontSize: 12.5 }}>
              {lastGeneratedLine(resume, regenerateCost)}
            </span>
          </div>
        )}
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
          {estimate.section
            ? "Filling"
            : estimate.regenerates
              ? "Writing the résumé again for"
              : "Writing a résumé for"}{" "}
          <strong>{estimate.label}</strong>
          {estimate.section ? " from your sources" : ""} costs about{" "}
          <strong>${estimate.cost.cost_usd}</strong> on {estimate.cost.model_id}
          , charged to your own provider.
          {estimate.cost.rate_is_published === false &&
            " We have no published price for that model, so this is a high guess, and it won't count toward your monthly cap."}
        </CostConfirm>
      )}

      {resume?.status === "ready" && (
        <OutdatedBanner
          reasons={resume.outdated_by}
          busy={busy}
          onRegenerate={() =>
            void price(resume.target, resume.label, resume.id)
          }
        />
      )}

      <div className="resume-layout">
        <aside className="stack resume-col-tools" aria-label="Résumé tools">
          <details className="tool-card" open>
            <summary>
              <span>Layout</span>
              <span className="tool-card-status">
                {layoutStatus(chosen?.name ?? null, draft)}
              </span>
            </summary>
            <div className="tool-card-body">
              <div className="field-label" style={{ marginBottom: 8 }}>
                Template
              </div>
              <div className="template-grid">
                {templates.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className="template-pick"
                    aria-pressed={template === t.id}
                    onClick={() => void changeSettings(t.id, options)}
                  >
                    <span className="template-thumb" aria-hidden="true">
                      <span
                        style={{
                          height: 5,
                          background: t.spec.accent_color,
                          width: "100%",
                        }}
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
                        {t.is_built_in ? t.note : "Your own."}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
              {editor && limits ? (
                <TemplateEditor
                  key={`${editor.from.id}:${editor.editing}`}
                  limits={limits}
                  from={editor.from}
                  editing={editor.editing}
                  onPreview={setPreview}
                  onSaved={templateSaved}
                  onDeleted={templateDeleted}
                  onClose={closeEditor}
                />
              ) : (
                chosen &&
                limits && (
                  <div className="row" style={{ gap: 4, marginTop: 8 }}>
                    {!chosen.is_built_in && (
                      <Button
                        variant="ghost"
                        onClick={() => openEditor(chosen, true)}
                      >
                        Change {chosen.name}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      disabled={
                        templates.filter((t) => !t.is_built_in).length >=
                        limits.max_templates
                      }
                      onClick={() => openEditor(chosen, false)}
                    >
                      Make your own
                    </Button>
                  </div>
                )
              )}
              {chosen && limits && !editor && (
                <div className="row" style={{ gap: 8, marginTop: 12 }}>
                  {FONT_PICKERS.map(({ key, label }) => (
                    <label key={key} className="font-picker">
                      <span className="field-label">{label}</span>
                      <select
                        className="input"
                        value={fonts[key] ?? ""}
                        disabled={resume?.status !== "ready"}
                        onChange={(event) =>
                          void changeSettings(template, options, {
                            ...fonts,
                            [key]: (event.target.value ||
                              null) as ResumeFonts["heading_font"],
                          })
                        }
                      >
                        <option value="">
                          Template&apos;s ({chosen.spec[key]})
                        </option>
                        {limits.fonts.map((font) => (
                          <option key={font} value={font}>
                            {font}
                          </option>
                        ))}
                      </select>
                    </label>
                  ))}
                </div>
              )}
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
              {draft &&
                resume &&
                (resume.status === "ready" || resume.status === "filling") && (
                  <SectionsPanel
                    content={draft}
                    added={added}
                    filling={
                      resume.status === "filling"
                        ? // The one being filled is shown in the plan and still
                          // empty in the content.
                          (resume.section_plan.find(
                            (slot) =>
                              slot.is_shown &&
                              !resume.content?.sections.some(
                                (s) =>
                                  s.kind === slot.kind &&
                                  (s.title ?? null) === (slot.title ?? null) &&
                                  !isEmptySection(s),
                              ),
                          ) ?? null)
                        : null
                    }
                    busy={busy || resume.status === "filling"}
                    // Show, hide, move and remove change the draft only; the
                    // user saves the version when it reads as they want.
                    onChange={editDraft}
                    onAdd={(slot) => void priceSection(slot)}
                  />
                )}
            </div>
          </details>
          <details className="tool-card" open>
            <summary>
              <span>Revise with AI</span>
              <span className="tool-card-status">
                {reviseStatus(exchanges, model)}
              </span>
            </summary>
            <div className="tool-card-body">
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
          </details>
          <details className="tool-card tool-card-coverage">
            <summary>
              <span>Coverage</span>
              <span className="tool-card-status">
                {coverageStatus(resume?.coverage ?? [])}
              </span>
            </summary>
            <div className="tool-card-body">
              {!resume || resume.coverage.length === 0 ? (
                <p
                  className="callout-note"
                  style={{ fontSize: 13, margin: "10px 0 0" }}
                >
                  Once a résumé is written, each of their requirements shows
                  here as covered, partial or a gap, with the work that backs
                  it.
                </p>
              ) : (
                <>
                  <p
                    className="callout-note"
                    style={{ fontSize: 13, margin: "6px 0 10px" }}
                  >
                    Open a requirement to see the evidence behind it.
                  </p>
                  <div className="divided">
                    {resume.coverage.map((row) => (
                      <div key={row.requirement} className="requirement-row">
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
                          {row.verdict === "gap" && row.answers.length > 0 && (
                            // Still a gap until a re-analysis counts it; the
                            // page may claim it from the answer (ADR 0044).
                            <span className="chip">Answered by you</span>
                          )}
                        </div>
                        <EvidenceDisclosure
                          compact
                          evidence={[...row.evidence, ...row.answers]}
                          empty="Nothing in your sources speaks to this yet."
                        />
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </details>
        </aside>

        <div className="resume-col-page">
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
              <div className="row" style={{ marginTop: 12, gap: 8 }}>
                {/* Written again as the same résumé, priced first. */}
                <Button
                  busy={busy}
                  onClick={() =>
                    void price(resume.target, resume.label, resume.id)
                  }
                >
                  Try again
                </Button>
                {(resume.error?.code?.startsWith("ai_credential") ||
                  resume.error?.code?.startsWith("ai_platform") ||
                  resume.error?.code === "ai_budget_exceeded") && (
                  <Button variant="ghost" onClick={() => navigate("model")}>
                    Open AI &amp; model
                  </Button>
                )}
              </div>
            </div>
          ) : draft && look ? (
            <>
              {resume.status === "filling" && (
                <p className="resume-annotation" role="status">
                  Filling a section from your sources on {model}… The rest of
                  the page stays as it is.
                </p>
              )}
              {resume.status === "ready" && resume.error && (
                <ErrorNote error={resume.error.message} />
              )}
              <div
                className="row-between"
                style={{ marginBottom: 10, flexWrap: "wrap", gap: 8 }}
              >
                <RoundCheck checked={showSources} onChange={setShowSources}>
                  Show where each line came from
                </RoundCheck>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {trimmedNote(draft, options, look)}
                </span>
              </div>
              {options.reorder && (
                <p className="resume-annotation">
                  Skills are ordered for this role.
                </p>
              )}
              <ResumePage
                key={resume.version?.id}
                content={draft}
                evidence={resume.evidence}
                look={look}
                icons={limits?.contact_icons ?? null}
                trim={options.trim}
                reorder={options.reorder}
                showSources={showSources}
                onChange={editDraft}
              />
              <div className="resume-page-actions">
                <Button
                  busy={busy}
                  disabled={!dirty}
                  onClick={() => void saveVersion(draft)}
                >
                  Save as v{nextVersion}
                </Button>
                <Button
                  variant="ghost"
                  disabled={undoStack.length === 0}
                  onClick={undo}
                  aria-label={
                    undoStack.length > 0
                      ? `Undo (${undoStack.length} unsaved ${undoStack.length === 1 ? "edit" : "edits"})`
                      : "Undo"
                  }
                >
                  ↶ Undo
                </Button>
                <Button
                  variant="secondary"
                  busy={exporting?.status === "rendering"}
                  disabled={!resume.version || dirty}
                  onClick={() => void exportPdf()}
                >
                  {exporting?.status === "rendering"
                    ? "Rendering…"
                    : "Export as PDF"}
                </Button>
                <span className="resume-annotation resume-page-note">
                  {dirty
                    ? "You have unsaved edits. Save this version first — the export is of a saved version."
                    : "Click any line to edit it in place."}
                </span>
              </div>
              {exporting?.status === "failed" && (
                <ErrorNote
                  error={exporting.error?.message ?? "Export failed."}
                />
              )}
            </>
          ) : draft ? (
            <Loading what="the template" />
          ) : null}
        </div>
      </div>
    </section>
  );
}

/** How many edits Undo can take back. */
const UNDO_LIMIT = 50;

/** The undo stack with one more draft on top, the oldest dropped past the
 * limit. Pure. */
export function getStackWith(
  stack: ResumeContent[],
  draft: ResumeContent,
): ResumeContent[] {
  return [...stack, draft].slice(-UNDO_LIMIT);
}

/** Whether two drafts read the same. Pure. */
function isSameContent(a: ResumeContent, b: ResumeContent): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** "Northwind Pay · v3 · edited 27 Sep 2026", one saved résumé in the
 * Version list. Pure. */
export function savedLine(entry: ResumeSummary): string {
  if (entry.status === "drafting") return `${entry.label} · writing…`;
  if (entry.status === "failed") return `${entry.label} · writing failed`;
  return `${entry.label} · v${entry.latest_version ?? 1} · edited ${dayLabel(entry.updated_at)}`;
}

/** "Organic · 4 sections": the Layout card's summary. Pure. */
export function layoutStatus(
  templateName: string | null,
  content: ResumeContent | null,
): string {
  const shown = content?.sections.filter((s) => s.is_shown).length ?? 0;
  return [
    templateName,
    content ? `${shown} ${shown === 1 ? "section" : "sections"}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** "1 proposal waiting", or the model the chat writes on. Pure. */
export function reviseStatus(exchanges: Exchange[], model: string): string {
  const waiting = exchanges.filter(
    (e) => e.hasProposal && e.revisionId && !e.applied,
  ).length;
  if (waiting === 0) return model;
  return `${waiting} ${waiting === 1 ? "proposal" : "proposals"} waiting`;
}

/** "1 covered · 1 partial · 1 gap": the Coverage card's summary. Pure. */
export function coverageStatus(
  coverage: readonly { verdict: string }[],
): string {
  if (coverage.length === 0) return "Once written";
  const count = (verdict: string) =>
    coverage.filter((row) => row.verdict === verdict).length;
  const gaps = count("gap");
  return `${count("covered")} covered · ${count("partial")} partial · ${gaps} ${
    gaps === 1 ? "gap" : "gaps"
  }`;
}

/** The page's custom properties, from the template as the renderer draws
 * it: sizes in points, margins as a share of the page's width. Pure. */
export function pageStyle(look: ResumeTemplateLook): Record<string, string> {
  const share = (mm: number) => `${(mm / look.page_width_mm) * 100}cqw`;
  const spec = look.spec;
  return {
    "--page-ratio": String(look.page_height_mm / look.page_width_mm),
    "--margin-top": share(look.margin_top_mm),
    "--margin-side": share(look.margin_side_mm),
    "--name-pt": String(spec.name_pt),
    "--title-pt": String(look.title_pt),
    "--body-pt": String(spec.body_pt),
    "--contact-pt": String(look.contact_pt),
    "--small-pt": String(look.small_pt),
    "--heading-pt": String(spec.heading_pt),
    "--rule": look.rule,
    "--band-color": look.band_color,
    "--name-color": spec.name_color,
    "--text-color": spec.text_color,
    "--dot-color": spec.accent_color,
    "--heading-case": spec.heading_case === "upper" ? "uppercase" : "none",
    "--bullet": BULLETS[spec.bullet],
    "--heading-font": `"${spec.heading_font}"`,
    "--body-font": `"${spec.body_font}"`,
  };
}

/** Each bullet style as a CSS list-style, as the renderer sets it. */
const BULLETS: Record<ResumeTemplateSpec["bullet"], string> = {
  dot: "disc",
  dash: '"\\2013  "',
  none: "none",
};

/** What "Trim to one page" leaves out of the PDF, and so of the page. Pure. */
export function trimmedNote(
  content: ResumeContent,
  options: ResumeOptions,
  look: ResumeTemplateLook,
): string {
  if (!options.trim) return "As it will print, A4.";
  const over = (count: number, limit: number) => Math.max(0, count - limit);
  let lines = 0;
  let items = 0;
  for (const section of content.sections) {
    if (!section.is_shown) continue;
    for (const entry of section.entries) {
      lines += over(entry.bullets.length, look.trimmed_bullets);
    }
    lines += over(section.bullets.length, look.trimmed_bullets);
    items += over(section.items.length, look.trimmed_skills);
  }
  if (lines === 0 && items === 0)
    return "Trimmed to one page; nothing left out.";
  const parts = [
    lines ? `${lines} line${lines === 1 ? "" : "s"}` : null,
    items ? `${items} item${items === 1 ? "" : "s"}` : null,
  ].filter(Boolean);
  return `Trimmed to one page: ${parts.join(" and ")} left out of the PDF.`;
}

function ResumePage({
  content,
  evidence,
  look,
  icons,
  trim,
  reorder,
  showSources,
  onChange,
}: {
  content: ResumeContent;
  evidence: TailoredResume["evidence"];
  look: ResumeTemplateLook;
  /** Each contact kind's icon path, as the PDF draws it (ADR 0048). */
  icons: Record<string, string> | null;
  trim: boolean;
  reorder: boolean;
  showSources: boolean;
  onChange: (next: ResumeContent) => void;
}) {
  const edit = (patch: Partial<ResumeContent>) =>
    onChange({ ...content, ...patch });
  const editSection = (at: number, next: ResumeSection) =>
    onChange({
      ...content,
      sections: content.sections.map((s, i) => (i === at ? next : s)),
    });
  const editEntry = (
    at: number,
    section: ResumeSection,
    index: number,
    patch: Partial<ResumeSection["entries"][number]>,
  ) =>
    editSection(at, {
      ...section,
      entries: section.entries.map((it, i) =>
        i === index ? { ...it, ...patch } : it,
      ),
    });

  const lines = (bullets: ResumeBullet[]) =>
    trim ? bullets.slice(0, look.trimmed_bullets) : bullets;

  const bulletList = (
    bullets: ResumeBullet[],
    onLines: (next: ResumeBullet[]) => void,
  ) => (
    <ul className="resume-bullets">
      {lines(bullets).map((bullet, b) => (
        <li key={b}>
          <span
            className="resume-bullet-text"
            data-rewritten={showSources && bullet.answers !== null}
            contentEditable
            suppressContentEditableWarning
            onBlur={(event) =>
              onLines(
                bullets.map((line, i) =>
                  i === b
                    ? { ...line, text: event.currentTarget.textContent ?? "" }
                    : line,
                ),
              )
            }
          >
            {bullet.text}
          </span>
          <div className="resume-cite" hidden={!showSources}>
            {citeLine(bullet, evidence)}
          </div>
        </li>
      ))}
    </ul>
  );

  const newLine: ResumeBullet = {
    text: "New line",
    evidence_ids: [],
    origin: "yours",
    answers: null,
  };

  const spec = look.spec;
  const hasSidebar =
    spec.layout === "sidebar_left" || spec.layout === "sidebar_right";
  const inSidebar = (section: ResumeSection) =>
    hasSidebar && (spec.sidebar_kinds as string[]).includes(section.kind);
  const editContact = (at: number, patch: Partial<ResumeContact>) =>
    edit({
      contacts: content.contacts.map((c, i) =>
        i === at ? { ...c, ...patch } : c,
      ),
    });
  const contact = (
    <div className="resume-contact">
      <Editable
        className="resume-headline"
        value={content.headline}
        label="Headline"
        placeholder="Headline"
        onChange={(headline) => edit({ headline })}
      />
      {content.contacts.map((item, at) => (
        <span key={at} className="resume-contact-item">
          <span className="resume-contact-kind">
            <ContactIcon kind={item.kind} icons={icons} />
            {/* The icon is the menu: an invisible select laid over it. */}
            <select
              aria-label={`Kind of ${item.value || "contact"}`}
              value={item.kind}
              onChange={(event) =>
                editContact(at, {
                  kind: event.target.value as ResumeContact["kind"],
                })
              }
            >
              {CONTACT_KINDS.map(({ kind, label }) => (
                <option key={kind} value={kind}>
                  {label}
                </option>
              ))}
            </select>
          </span>
          <Editable
            value={item.value}
            label={`${CONTACT_LABELS[item.kind]} contact`}
            placeholder={CONTACT_LABELS[item.kind]}
            onChange={(value) =>
              // Cleared to nothing, it goes.
              value
                ? editContact(at, { value })
                : edit({
                    contacts: content.contacts.filter((_, i) => i !== at),
                  })
            }
          />
        </span>
      ))}
      {content.contacts.length < MAX_CONTACTS && (
        <button
          type="button"
          className="resume-add-line"
          onClick={() =>
            edit({
              contacts: [
                ...content.contacts,
                { kind: "email", value: "you@example.com" },
              ],
            })
          }
        >
          + Add contact
        </button>
      )}
    </div>
  );
  // A hidden section is kept and never printed (ADR 0043).
  const sectionsWhere = (side: boolean) =>
    content.sections.map((section, at) =>
      section.is_shown && inSidebar(section) === side
        ? sectionAt(section, at)
        : null,
    );

  function sectionAt(section: ResumeSection, at: number) {
    const heading = sectionHeading(section);
    const key = `${section.kind}:${section.title ?? ""}`;
    if (isEmptySection(section)) {
      // Nothing prints for it; the app says so and offers a first line.
      return (
        <div
          key={key}
          className="resume-annotation"
          style={{ margin: "8px 0" }}
        >
          Nothing in your sources for {heading} yet; add lines in place.{" "}
          <button
            type="button"
            className="resume-add-line"
            onClick={() => editSection(at, startSection(section, newLine))}
          >
            + Add to {heading}
          </button>
        </div>
      );
    }
    return (
      <section key={key} aria-label={heading}>
        <Editable
          as="div"
          className="resume-section"
          value={heading}
          label={`Heading of ${heading}`}
          onChange={(next) =>
            editSection(at, {
              ...section,
              // Cleared, or back to the kind's own: no override. A section of
              // the user's own keeps a heading.
              title:
                !next || next === SECTION_HEADINGS[section.kind]
                  ? section.kind === "custom"
                    ? section.title
                    : null
                  : next,
            })
          }
        />
        {section.kind === "summary" && (
          <p
            className="resume-summary"
            contentEditable
            suppressContentEditableWarning
            aria-label="Summary"
            onBlur={(event) =>
              editSection(at, {
                ...section,
                text: event.currentTarget.textContent ?? "",
              })
            }
          >
            {section.text}
          </p>
        )}
        {section.entries.map((entry, e) => (
          <section key={`${entry.title}-${e}`} className="resume-job">
            {/* Takes the whole entry off the page, from the margin left of its
                title, so the title stays where the PDF prints it. Gone once the
                version is saved. Never printed. */}
            <button
              type="button"
              className="resume-remove-entry"
              aria-label={`Remove ${entry.title} from ${heading}`}
              title="Remove this entry"
              onClick={() =>
                editSection(at, {
                  ...section,
                  entries: section.entries.filter((_, i) => i !== e),
                })
              }
            >
              ×
            </button>
            <div className="resume-job-head">
              <span className="resume-job-title">
                <Editable
                  value={entry.title}
                  label="Title"
                  placeholder="Title"
                  onChange={(title) =>
                    // An entry always has a title; clearing it keeps the old.
                    title && editEntry(at, section, e, { title })
                  }
                />
                {entry.org ? " — " : " "}
                <Editable
                  value={entry.org}
                  label="Organisation"
                  placeholder="Organisation"
                  onChange={(org) => editEntry(at, section, e, { org })}
                />
              </span>
              <Editable
                className="resume-when"
                value={entry.when}
                label="When"
                placeholder="When"
                onChange={(when) => editEntry(at, section, e, { when })}
              />
            </div>
            <Editable
              as="div"
              className="resume-when"
              value={entry.link}
              label="Link"
              placeholder="Link"
              onChange={(link) => editEntry(at, section, e, { link })}
            />
            {bulletList(entry.bullets, (next) =>
              editSection(at, {
                ...section,
                entries: section.entries.map((it, i) =>
                  i === e ? { ...it, bullets: next } : it,
                ),
              }),
            )}
          </section>
        ))}
        {section.items.length > 0 && (
          <div className="resume-skills">
            {(trim
              ? section.items.slice(0, look.trimmed_skills)
              : section.items
            ).map((item, index) => (
              <Editable
                key={`${index}-${item}`}
                className="resume-skill"
                value={item}
                label={`${heading} item`}
                lead={
                  showSources &&
                  reorder &&
                  section.kind === "skills" &&
                  index < 3
                }
                onChange={(next) =>
                  editSection(at, {
                    ...section,
                    // Cleared to nothing, it goes.
                    items: next
                      ? section.items.map((it, i) => (i === index ? next : it))
                      : section.items.filter((_, i) => i !== index),
                  })
                }
              />
            ))}
            <button
              type="button"
              className="resume-add-line"
              onClick={() =>
                editSection(at, {
                  ...section,
                  items: [...section.items, "New item"],
                })
              }
            >
              + Add
            </button>
          </div>
        )}
        {section.bullets.length > 0 &&
          bulletList(section.bullets, (next) =>
            editSection(at, { ...section, bullets: next }),
          )}
      </section>
    );
  }

  // Laid out as the renderer lays it out: a sidebar holds the contact line
  // and the lists the template names, and comes first only on the left.
  const side = (
    <div className="resume-side">
      {contact}
      {sectionsWhere(true)}
    </div>
  );
  const main = <div className="resume-main">{sectionsWhere(false)}</div>;

  return (
    <div className="resume-sheet">
      <article
        className="resume-page"
        aria-label="Résumé"
        data-layout={spec.layout}
        style={pageStyle(look) as CSSProperties}
      >
        <header className={spec.layout === "header_band" ? "band" : undefined}>
          <div
            className="resume-name"
            contentEditable
            suppressContentEditableWarning
            aria-label="Name"
            onBlur={(event) =>
              edit({ name: event.currentTarget.textContent ?? "" })
            }
          >
            {content.name}
          </div>
          {!hasSidebar && contact}
        </header>
        {hasSidebar ? (
          <div className="resume-columns">
            {spec.layout === "sidebar_left" ? (
              <>
                {side}
                {main}
              </>
            ) : (
              <>
                {main}
                {side}
              </>
            )}
          </div>
        ) : (
          sectionsWhere(false)
        )}
      </article>
      <p className="resume-annotation" style={{ marginTop: 10 }}>
        The page is laid out as the PDF prints it; the line across it marks
        where an A4 page ends.
      </p>
    </div>
  );
}

/** An empty section with a first line, entry or item to edit. Pure. */
function startSection(
  section: ResumeSection,
  line: ResumeBullet,
): ResumeSection {
  switch (section.kind) {
    case "summary":
      return { ...section, text: "A sentence about you." };
    case "skills":
    case "certifications":
      return { ...section, items: ["New item"] };
    case "custom":
      return { ...section, bullets: [line] };
    default:
      return {
        ...section,
        entries: [
          { title: "New entry", org: "", when: "", link: "", bullets: [line] },
        ],
      };
  }
}

/** The grey note under a line: where it came from, and what it answers. */
export function citeLine(
  bullet: ResumeBullet,
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
      role="region"
      aria-label={`Revise with ${model}`}
      style={{ display: "flex", flexDirection: "column" }}
    >
      <div className="muted" style={{ fontSize: 12 }}>
        {model} · writes from your sources to fit{" "}
        {target ?? "the role you pick"}; proposals apply only when you say so
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
          style={{ flex: 1, minWidth: 0 }}
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

/** "Last generated 27 Sep 2026 · about $0.04 on your key · saved as a new
 * version". Pure. */
export function lastGeneratedLine(
  resume: TailoredResume,
  cost: PlanEstimate | null,
): string {
  const generated = resume.versions.find((v) => v.source !== "manual");
  const when = generated
    ? new Date(generated.created_at).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : null;
  return [
    when ? `Last generated ${when}` : null,
    cost ? `about $${Number(cost.cost_usd).toFixed(2)} on your key` : null,
    "saved as a new version",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Text edited in place on the page: saved on blur when it changed, trimmed.
 * Empty, it shows its placeholder, which the page never prints. */
function Editable({
  as: Tag = "span",
  value,
  label,
  placeholder,
  className,
  lead,
  onChange,
}: {
  as?: "span" | "div";
  value: string;
  label: string;
  placeholder?: string;
  className?: string;
  lead?: boolean;
  onChange: (next: string) => void;
}) {
  return (
    <Tag
      className={className}
      contentEditable
      suppressContentEditableWarning
      aria-label={label}
      data-placeholder={placeholder}
      data-lead={lead}
      onBlur={(event) => {
        const next = (event.currentTarget.textContent ?? "").trim();
        if (next !== value) onChange(next);
      }}
    >
      {value}
    </Tag>
  );
}

type ResumeFonts = Pick<TailoredResume, "heading_font" | "body_font">;

const NO_FONTS: ResumeFonts = { heading_font: null, body_font: null };

/** The two fonts a résumé can set over its template's (ADR 0047). */
const FONT_PICKERS: { key: keyof ResumeFonts; label: string }[] = [
  { key: "heading_font", label: "Titles in" },
  { key: "body_font", label: "Text in" },
];

const MAX_CONTACTS = 8;

/** The contact kinds, as the kind menu offers them. */
const CONTACT_KINDS: { kind: ResumeContact["kind"]; label: string }[] = [
  { kind: "email", label: "Email" },
  { kind: "phone", label: "Phone" },
  { kind: "github", label: "GitHub" },
  { kind: "linkedin", label: "LinkedIn" },
  { kind: "website", label: "Website" },
  { kind: "location", label: "Location" },
];

const CONTACT_LABELS = Object.fromEntries(
  CONTACT_KINDS.map(({ kind, label }) => [kind, label]),
) as Record<ResumeContact["kind"], string>;

/** A contact kind's icon, drawn from the same path the PDF draws. */
function ContactIcon({
  kind,
  icons,
}: {
  kind: ResumeContact["kind"];
  icons: Record<string, string> | null;
}) {
  const path = icons?.[kind];
  if (!path) return null;
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="resume-contact-icon">
      <path d={path} />
    </svg>
  );
}
