import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  OwnPosting,
  OwnPostingEstimate,
  OwnPostingPage,
} from "../api/types";
import { Button, ErrorNote, Eyebrow, FitBadge } from "../components/ui";
import { useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { dayLabel } from "./time";
import { messageOf } from "./useAsync";

const POLL_MS = 2000;

/** What the file input offers; the server checks the type again. */
export const JD_FILE_TYPES = ".pdf,.docx,.txt";

export type Draft = {
  title: string;
  company: string;
  /** What the role asks for, one requirement per line. */
  requirements: string;
  file: File | null;
};

const EMPTY: Draft = { title: "", company: "", requirements: "", file: null };

/**
 * The roles the user brought themselves (ADR 0034), re-read while one is
 * being read and scored, as Fill the gap is while it writes (ADR 0006).
 */
export function useOwnPostings(): {
  data: OwnPosting[] | null;
  error: string | null;
  reload: () => Promise<void>;
} {
  const [data, setData] = useState<OwnPosting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(async () => {
    try {
      setData(await api.items<OwnPostingPage>("/own-postings"));
      setError(null);
    } catch (caught) {
      setError(messageOf(caught));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, tick]);

  const running = (data ?? []).some((posting) => posting.status === "running");
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => setTick((n) => n + 1), POLL_MS);
    return () => clearTimeout(timer);
  }, [running, data]);

  return { data, error, reload };
}

/**
 * "Aim the Advisor at your own role" (the prototype's CustomTarget): a job
 * the role map does not show, brought by uploading its description or by
 * filling it in. Adding one spends nothing and puts nothing on the role map;
 * "Set as target" reads it and scores the fit, at a cost shown first, then
 * opens Fill the gap for it.
 */
export function OwnRole({
  own,
  currentTarget,
}: {
  /** The Advisor's own list, so a role set as target here is the one it
   * finds when Fill the gap opens. */
  own: { data: OwnPosting[] | null; reload: () => Promise<void> };
  /** What the Advisor is aimed at now, which setting another replaces. */
  currentTarget: string | null;
}) {
  const { navigate } = useShell();

  return (
    <section className="stack" style={{ gap: 20 }}>
      <div>
        <button
          type="button"
          className="link-button"
          style={{ fontSize: 14, fontWeight: 600 }}
          onClick={() => navigate("advisor", { tab: "gaps" })}
        >
          ← Back to the Advisor
        </button>
      </div>

      <section className="panel" aria-labelledby="own-intro-h">
        <Eyebrow style={{ color: "var(--color-accent-700)" }}>
          Not on your role map?
        </Eyebrow>
        <h2 id="own-intro-h" className="run-progress-heading">
          Bring the job yourself
        </h2>
        <p className="run-progress-subline" style={{ maxWidth: 760 }}>
          Add roles you found yourself to your own list. They are not added to
          the role map. Pick one as your Advisor target and the Advisor compares
          it with your strengths, then asks its follow-up questions in Fill the
          gap.
        </p>
      </section>

      <OwnRoleForm onAdded={own.reload} />
      <MyRoles
        postings={own.data ?? []}
        currentTarget={currentTarget}
        onChanged={own.reload}
      />
    </section>
  );
}

/**
 * "Your role": upload the job description, or fill the role in. One is
 * enough. Adding it calls no model, so there is no cost to confirm.
 */
export function OwnRoleForm({ onAdded }: { onAdded: () => Promise<void> }) {
  const flash = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = draftIsReady(draft);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const fields = {
        title: draft.title.trim() || null,
        company_name: draft.company.trim() || null,
      };
      const added = draft.file
        ? await api.upload<OwnPosting>(
            "/own-postings/upload",
            draft.file,
            fields,
          )
        : await api.post<OwnPosting>("/own-postings", {
            ...fields,
            requirements: requirementLines(draft.requirements),
          });
      setDraft(EMPTY);
      if (fileInput.current) fileInput.current.value = "";
      flash(`${added.title} added to your roles.`);
      await onAdded();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  function choose(file: File | null) {
    setDraft((current) => ({ ...current, file }));
  }

  return (
    <section className="panel" aria-labelledby="own-role-h">
      <h3 id="own-role-h" style={{ margin: 0 }}>
        Your role
      </h3>
      <p className="subcopy" style={{ margin: "4px 0 16px" }}>
        Upload the job description, or fill in the role yourself. One is enough.
      </p>
      <div className="own-role-ways">
        <div>
          <Eyebrow>Upload the job description</Eyebrow>
          <div
            className={`drop-zone${dragging ? " drop-zone-active" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              choose(event.dataTransfer.files[0] ?? null);
            }}
          >
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--color-accent-700)"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
            </svg>
            <div style={{ fontWeight: 700, marginTop: 8 }}>
              {draft.file ? draft.file.name : "Drop a PDF, DOCX or TXT"}
            </div>
            <div
              className="subcopy"
              style={{ fontSize: 12.5, margin: "4px 0 12px" }}
            >
              {draft.file
                ? "Read when you set it as your target, then deleted."
                : "Requirements are read straight from the posting"}
            </div>
            <input
              ref={fileInput}
              id="own-role-file"
              type="file"
              accept={JD_FILE_TYPES}
              aria-label="Job description file"
              style={{ display: "none" }}
              onChange={(event) => choose(event.target.files?.[0] ?? null)}
            />
            <div className="row" style={{ justifyContent: "center", gap: 8 }}>
              <Button
                variant="secondary"
                onClick={() => fileInput.current?.click()}
              >
                {draft.file ? "Choose another file" : "Choose file"}
              </Button>
              {draft.file && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    choose(null);
                    if (fileInput.current) fileInput.current.value = "";
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
          </div>
        </div>

        <div className="own-role-or" aria-hidden="true">
          <span />
          <span>or</span>
          <span />
        </div>

        <div>
          <Eyebrow>Fill it in yourself</Eyebrow>
          <label className="field-label" htmlFor="own-role-title">
            Job title
            {draft.file && (
              <span className="muted"> (optional with a file)</span>
            )}
          </label>
          <input
            id="own-role-title"
            className="input"
            required={!draft.file}
            placeholder="e.g. Principal Engineer"
            value={draft.title}
            onChange={(event) =>
              setDraft({ ...draft, title: event.target.value })
            }
          />
          <label className="field-label" htmlFor="own-role-company">
            Company <span className="muted">(optional)</span>
          </label>
          <input
            id="own-role-company"
            className="input"
            placeholder="e.g. Halden Labs"
            value={draft.company}
            onChange={(event) =>
              setDraft({ ...draft, company: event.target.value })
            }
          />
          <label className="field-label" htmlFor="own-role-requirements">
            What the role asks for <span className="muted">(optional)</span>
          </label>
          <textarea
            id="own-role-requirements"
            className="input"
            rows={4}
            disabled={draft.file !== null}
            placeholder="One requirement per line, e.g. Leads architecture across teams"
            value={draft.requirements}
            onChange={(event) =>
              setDraft({ ...draft, requirements: event.target.value })
            }
          />
          <p className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
            {draft.file
              ? "With a file, what the role asks for is read from it."
              : "Leave requirements empty and the Advisor infers typical ones for this title, marked as estimates."}
          </p>
        </div>
      </div>
      <div className="row" style={{ marginTop: 16 }}>
        <Button busy={busy} disabled={!ready} onClick={() => void add()}>
          Add to my roles
        </Button>
      </div>
      <ErrorNote error={error} />
    </section>
  );
}

/**
 * "My roles": each with how it was added, and "Set as target", which reads
 * and scores it at a cost shown first — nothing when its fit is current — and
 * opens Fill the gap for it.
 */
export function MyRoles({
  postings,
  currentTarget,
  onChanged,
}: {
  postings: OwnPosting[];
  currentTarget: string | null;
  onChanged: () => Promise<void>;
}) {
  const { navigate } = useShell();
  const flash = useToast();
  const [pricing, setPricing] = useState<{
    posting: OwnPosting;
    estimate: OwnPostingEstimate;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const aim = (posting: OwnPosting) =>
    run(async () => {
      await api.post<OwnPosting>(
        `/own-postings/${posting.private_job_posting_id}/target`,
        {},
      );
      setPricing(null);
      await onChanged();
      navigate("advisor", {
        tab: "gaps",
        focus: { posting: posting.private_job_posting_id },
      });
    });

  const price = (posting: OwnPosting) =>
    run(async () => {
      const estimate = await api.get<OwnPostingEstimate>(
        `/own-postings/${posting.private_job_posting_id}/target-estimate`,
      );
      if (Number(estimate.cost_usd) === 0) {
        // Its fit is current: nothing to spend, so nothing to confirm.
        await aim(posting);
        return;
      }
      setPricing({ posting, estimate });
    });

  const remove = (posting: OwnPosting) =>
    run(async () => {
      await api.del(`/own-postings/${posting.private_job_posting_id}`);
      flash(`${posting.title} removed.`);
      await onChanged();
    });

  return (
    <section className="panel" aria-labelledby="my-roles-h">
      <div className="row-between" style={{ alignItems: "baseline" }}>
        <h3 id="my-roles-h" style={{ margin: 0 }}>
          My roles
        </h3>
        <span className="muted" style={{ fontSize: 13 }}>
          {postings.length} {postings.length === 1 ? "role" : "roles"}
        </span>
      </div>
      <p className="subcopy" style={{ margin: "4px 0 12px" }}>
        Setting a role as target compares it with your strengths, at a cost
        shown first on your key.
        {currentTarget ? ` It replaces ${currentTarget} as your target.` : ""}
      </p>
      {pricing && (
        <CostConfirm
          busy={busy}
          onConfirm={() => void aim(pricing.posting)}
          onCancel={() => setPricing(null)}
        >
          Reading what {pricing.posting.title} asks for and scoring your fit to
          it will cost about <strong>${pricing.estimate.cost_usd}</strong>
          {pricing.estimate.model_id ? ` on ${pricing.estimate.model_id}` : ""},
          charged to your own provider
          {pricing.posting.status === null &&
          pricing.posting.source === "uploaded"
            ? " — at most, since its file is not read yet"
            : ""}
          . Fill the gap then writes its questions.
        </CostConfirm>
      )}
      {postings.length === 0 ? (
        <p className="muted" style={{ fontSize: 13.5 }}>
          No roles yet. Add one above.
        </p>
      ) : (
        <ul aria-label="My roles" className="own-role-list">
          {postings.map((posting) => (
            <li key={posting.private_job_posting_id} className="own-role-row">
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700 }}>
                  {posting.company_name
                    ? `${posting.title} · ${posting.company_name}`
                    : posting.title}
                </div>
                <div className="muted" style={{ fontSize: 12.5 }}>
                  {roleLine(posting)}
                </div>
              </div>
              <div className="row" style={{ gap: 8, flex: "0 0 auto" }}>
                {posting.fit !== null && !posting.is_stale && (
                  <FitBadge fit={posting.fit} />
                )}
                <Button
                  busy={busy}
                  disabled={posting.status === "running"}
                  onClick={() => void price(posting)}
                >
                  Set as target
                </Button>
                <Button
                  variant="ghost"
                  busy={busy}
                  aria-label={`Remove ${posting.title}`}
                  onClick={() => void remove(posting)}
                >
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <ErrorNote error={error} />
    </section>
  );
}

/** Whether the form has enough to add a role: a file, or a title. Pure. */
export function draftIsReady(draft: Draft): boolean {
  return draft.file !== null || Boolean(draft.title.trim());
}

/** The requirements typed one per line, blank lines dropped. Pure. */
export function requirementLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * How a role came and where it stands: "Uploaded JD · added 12 Sep 2026", or
 * "Filled in · no company · requirements estimated · added 1 Oct 2026", then
 * what reading and scoring it is doing. Pure.
 */
export function roleLine(posting: OwnPosting): string {
  const parts = [
    posting.source === "uploaded"
      ? "Uploaded JD"
      : posting.source === "filled_in"
        ? "Filled in"
        : "Pasted JD",
  ];
  if (posting.source === "filled_in" && !posting.company_name) {
    parts.push("no company");
  }
  if (posting.has_estimated_requirements) parts.push("requirements estimated");
  if (posting.created_at) parts.push(`added ${dayLabel(posting.created_at)}`);
  const status = statusLine(posting);
  if (status) parts.push(status);
  return parts.join(" · ");
}

/** Where reading and scoring a role stands, if anywhere. Pure. */
export function statusLine(posting: OwnPosting): string | null {
  if (posting.status === "running") {
    return posting.source === "uploaded" && posting.filename
      ? `reading ${posting.filename}, then scoring it…`
      : "reading and scoring it…";
  }
  if (posting.status === "failed") {
    return posting.error_message ?? "scoring it failed";
  }
  if (posting.fit !== null && posting.is_stale) {
    return "scored against an earlier analysis";
  }
  return null;
}
