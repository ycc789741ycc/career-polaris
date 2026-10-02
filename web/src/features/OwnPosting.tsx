import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  OwnPosting,
  OwnPostingEstimate,
  OwnPostingPage,
} from "../api/types";
import { Button, ErrorNote, FitBadge, PillToggle } from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { messageOf } from "./useAsync";

const POLL_MS = 2000;

export type Draft = {
  title: string;
  company: string;
  jd: string;
  file: File | null;
};

const EMPTY: Draft = { title: "", company: "", jd: "", file: null };

/** How the JD arrives: pasted as text, or uploaded as a file. */
export type JdMode = "paste" | "upload";

/** What a file input offers; the server checks the type again. */
export const JD_FILE_TYPES = ".pdf,.docx,.txt";

/**
 * The postings the user brought themselves (Phase 8), re-read while one is
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
 * "Aim at a posting of your own": a job the role map does not show, pasted
 * or uploaded as a file here to plan for (ADR 0033). Its JD, which stays
 * private, is what its requirements are read from, and the user's fit is
 * scored against them. A file is read by the worker, never in the browser.
 * Nothing is added to the role map, and nothing is spent before the cost is
 * confirmed.
 */
export function OwnPostingForm({
  onAdded,
}: {
  /** The posting was added: reload the list. It is scored in the background. */
  onAdded: (posting: OwnPosting) => Promise<void>;
}) {
  const { status } = useShell();
  const model = modelName(status.credential);
  const [mode, setMode] = useState<JdMode>("paste");
  // Bumped after a posting is added, to clear the file input it came from.
  const [resets, setResets] = useState(0);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [estimate, setEstimate] = useState<OwnPostingEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = draftIsReady(draft, mode);

  function named() {
    return {
      title: draft.title.trim(),
      company_name: draft.company.trim() || null,
    };
  }

  function body() {
    return { ...named(), job_description: draft.jd.trim() };
  }

  function choose(next: JdMode) {
    setMode(next);
    setEstimate(null);
    setError(null);
  }

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

  const askForEstimate = () =>
    run(async () => {
      if (!ready) {
        setError(
          mode === "paste"
            ? "Give it a job title and paste its job description first."
            : "Give it a job title and choose the file with its job description first.",
        );
        return;
      }
      setEstimate(
        mode === "paste"
          ? await api.post<OwnPostingEstimate>(
              "/own-postings/cost-estimate",
              body(),
            )
          : await api.post<OwnPostingEstimate>(
              "/own-postings/upload-estimate",
              named(),
            ),
      );
    });

  const add = () =>
    run(async () => {
      const posting =
        mode === "upload" && draft.file
          ? await api.upload<OwnPosting>(
              "/own-postings/upload",
              draft.file,
              named(),
            )
          : await api.post<OwnPosting>("/own-postings", body());
      setEstimate(null);
      setDraft(EMPTY);
      setResets((n) => n + 1);
      await onAdded(posting);
    });

  return (
    <div className="panel" style={{ marginTop: 20 }}>
      <h3>Aim at a posting of your own</h3>
      <p className="subcopy">
        Found a job the role map doesn&apos;t show? Paste its description or
        upload it as a file, and plan for it. It is never added to the map. The
        JD stays private to you.
      </p>
      <div
        className="row"
        role="group"
        aria-label="How to add the job description"
        style={{ marginTop: 10, gap: 6 }}
      >
        <PillToggle
          small
          pressed={mode === "paste"}
          onClick={() => choose("paste")}
        >
          Paste it
        </PillToggle>
        <PillToggle
          small
          pressed={mode === "upload"}
          onClick={() => choose("upload")}
        >
          Upload a file
        </PillToggle>
      </div>
      {estimate && (
        <CostConfirm
          busy={busy}
          onConfirm={() => void add()}
          onCancel={() => setEstimate(null)}
        >
          Reading what it requires, then scoring your fit against it, will cost
          {mode === "upload" ? " at most" : " about"}{" "}
          <strong>${estimate.cost_usd}</strong>
          {estimate.model_id ? ` on ${estimate.model_id}` : ""}, charged to your
          own provider.
        </CostConfirm>
      )}
      <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 200px" }}>
          <label className="field-label" htmlFor="own-posting-title">
            Job title
          </label>
          <input
            id="own-posting-title"
            className="input"
            required
            placeholder="e.g. Principal Engineer"
            value={draft.title}
            onChange={(event) =>
              setDraft({ ...draft, title: event.target.value })
            }
          />
        </div>
        <div style={{ flex: "1 1 200px" }}>
          <label className="field-label" htmlFor="own-posting-company">
            Company name <span className="muted">(optional)</span>
          </label>
          <input
            id="own-posting-company"
            className="input"
            placeholder="e.g. Halden Labs"
            value={draft.company}
            onChange={(event) =>
              setDraft({ ...draft, company: event.target.value })
            }
          />
        </div>
      </div>
      {mode === "paste" ? (
        <>
          <label
            className="field-label"
            htmlFor="own-posting-jd"
            style={{ marginTop: 10 }}
          >
            Job description
          </label>
          <textarea
            id="own-posting-jd"
            className="input"
            rows={4}
            required
            placeholder={`Paste the full posting — ${model} reads its requirements.`}
            value={draft.jd}
            onChange={(event) => setDraft({ ...draft, jd: event.target.value })}
          />
        </>
      ) : (
        <>
          <label
            className="field-label"
            htmlFor="own-posting-file"
            style={{ marginTop: 10 }}
          >
            Job description file
          </label>
          <input
            key={resets}
            id="own-posting-file"
            className="input"
            type="file"
            accept={JD_FILE_TYPES}
            required
            onChange={(event) => {
              setDraft({ ...draft, file: event.target.files?.[0] ?? null });
              setEstimate(null);
            }}
          />
          <p className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
            A PDF, a Word file or plain text. {model} reads it once it is
            uploaded; the file is deleted after.
          </p>
        </>
      )}
      <div className="row" style={{ marginTop: 10 }}>
        <Button
          busy={busy}
          disabled={!ready}
          onClick={() => void askForEstimate()}
        >
          Read and score it
        </Button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}

/**
 * The postings the user brought, each with where reading and scoring it
 * stands: aim at one once it is scored, rescore one scored against earlier
 * strengths (never unasked), or remove it.
 */
export function OwnPostingList({
  postings,
  onAim,
  onChanged,
}: {
  postings: OwnPosting[];
  onAim: (posting: OwnPosting) => void;
  onChanged: () => Promise<void>;
}) {
  const flash = useToast();
  const [pricing, setPricing] = useState<{
    posting: OwnPosting;
    estimate: OwnPostingEstimate;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (postings.length === 0) return null;

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

  const price = (posting: OwnPosting) =>
    run(async () => {
      const estimate = await api.get<OwnPostingEstimate>(
        `/own-postings/${posting.private_job_posting_id}/rescore-estimate`,
      );
      setPricing({ posting, estimate });
    });

  const rescore = (posting: OwnPosting) =>
    run(async () => {
      await api.post<OwnPosting>(
        `/own-postings/${posting.private_job_posting_id}/rescore`,
        {},
      );
      setPricing(null);
      await onChanged();
    });

  const remove = (posting: OwnPosting) =>
    run(async () => {
      await api.del(`/own-postings/${posting.private_job_posting_id}`);
      flash(`${posting.title} removed.`);
      await onChanged();
    });

  return (
    <div className="panel" style={{ marginTop: 20 }}>
      <h3>Your postings</h3>
      {pricing && (
        <CostConfirm
          busy={busy}
          onConfirm={() => void rescore(pricing.posting)}
          onCancel={() => setPricing(null)}
        >
          Scoring your fit to {pricing.posting.title} again, against your latest
          strengths, will cost about{" "}
          <strong>${pricing.estimate.cost_usd}</strong>
          {pricing.estimate.model_id ? ` on ${pricing.estimate.model_id}` : ""},
          charged to your own provider. Its requirements are kept.
        </CostConfirm>
      )}
      <ul
        aria-label="Your postings"
        style={{ listStyle: "none", padding: 0, margin: 0 }}
      >
        {postings.map((posting) => (
          <li
            key={posting.private_job_posting_id}
            className="row-between"
            style={{ padding: "10px 0", flexWrap: "wrap", gap: 10 }}
          >
            <div style={{ minWidth: 0 }}>
              <strong>{posting.title}</strong>
              {posting.company_name && (
                <span className="muted"> · {posting.company_name}</span>
              )}
              <div className="muted" style={{ fontSize: 12.5 }}>
                {statusLine(posting)}
              </div>
            </div>
            <div className="row" style={{ gap: 8 }}>
              {posting.fit !== null && <FitBadge fit={posting.fit} />}
              {posting.fit !== null && (
                <Button onClick={() => onAim(posting)}>
                  Aim the Advisor at it
                </Button>
              )}
              {posting.status !== "running" &&
                (posting.is_stale || posting.status === "failed") && (
                  <Button
                    variant="ghost"
                    busy={busy}
                    onClick={() => void price(posting)}
                  >
                    {posting.status === "failed" ? "Try again" : "Rescore"}
                  </Button>
                )}
              <Button
                variant="ghost"
                busy={busy}
                onClick={() => void remove(posting)}
              >
                Remove
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <ErrorNote error={error} />
    </div>
  );
}

/** Whether the form has what the chosen way of adding a JD needs. Pure. */
export function draftIsReady(draft: Draft, mode: JdMode): boolean {
  if (!draft.title.trim()) return false;
  return mode === "paste" ? Boolean(draft.jd.trim()) : draft.file !== null;
}

/** What a posting's row says about where reading and scoring it stands. Pure. */
export function statusLine(posting: OwnPosting): string {
  if (posting.status === "running") {
    return posting.source === "uploaded"
      ? `Reading ${posting.filename ?? "the file"}, then scoring it…`
      : "Reading and scoring it…";
  }
  if (posting.status === "failed") {
    return posting.error_message ?? "Scoring it failed.";
  }
  if (posting.is_stale) {
    return "Scored against an earlier analysis of your strengths.";
  }
  return posting.fit !== null
    ? "Scored against your strengths."
    : "Not scored yet.";
}
