import { useState } from "react";
import { api } from "../api/client";
import type { TargetOption } from "../api/types";
import { AutoGrid, Button, ErrorNote, Eyebrow } from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { messageOf } from "./useAsync";

const SAMPLE_JD = {
  title: "Staff Platform Engineer",
  company: "Meridian Labs",
  text: "Staff Platform Engineer at Meridian Labs — set technical direction across three product teams, own the reliability roadmap and its SLOs, mentor senior engineers. Requires demonstrated org-level influence.",
};

/**
 * JDs the user pastes: the one kind of Target that is not a role on the map.
 * Picking one selects it, like picking a bubble; the role map's single
 * Advisor target bar is what then aims the Advisor at it. A pasted JD stays
 * private, and its requirements are read on the user's model the first time
 * the Advisor prices something for it.
 */
export function OwnJdPanel({
  pasted,
  selectedId,
  error: loadError,
  onSelect,
  onAdded,
}: {
  pasted: TargetOption[];
  selectedId: string | null;
  error: string | null;
  onSelect: (id: string) => void;
  /** A new JD was saved: re-read the list and select it. */
  onAdded: (id: string) => Promise<void>;
}) {
  const { status } = useShell();
  const model = modelName(status.credential);
  const [jd, setJd] = useState({ text: "", title: "", company: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add() {
    if (!jd.text.trim()) {
      setError("Paste the job description first.");
      return;
    }
    if (!jd.title.trim() || !jd.company.trim()) {
      setError("Give the posting a title and a company first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const posting = await api.post<{ id: string }>("/job-descriptions", {
        company_name: jd.company.trim(),
        title: jd.title.trim(),
        location: null,
        description: jd.text,
      });
      setJd({ text: "", title: "", company: "" });
      await onAdded(posting.id);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel" style={{ marginTop: 20 }}>
      <h3>My own JD</h3>
      <p className="subcopy">
        A posting that is not on the map. Pick it and the Advisor plans and
        writes against its own requirements instead of a role&apos;s.
      </p>
      <AutoGrid col={300} gap={18} style={{ marginTop: 12 }}>
        <div>
          <textarea
            className="input"
            rows={6}
            aria-label="Job description"
            value={jd.text}
            placeholder={`Paste the full job description — ${model} reads its requirements when the Advisor first uses it.`}
            onChange={(event) => setJd({ ...jd, text: event.target.value })}
          />
          <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
            <input
              className="input"
              aria-label="Job title"
              placeholder="Job title"
              style={{ flex: "1 1 150px", width: "auto" }}
              value={jd.title}
              onChange={(event) => setJd({ ...jd, title: event.target.value })}
            />
            <input
              className="input"
              aria-label="Company"
              placeholder="Company"
              style={{ flex: "1 1 150px", width: "auto" }}
              value={jd.company}
              onChange={(event) =>
                setJd({ ...jd, company: event.target.value })
              }
            />
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <Button variant="secondary" busy={busy} onClick={() => void add()}>
              Add JD
            </Button>
            <Button variant="ghost" onClick={() => setJd({ ...SAMPLE_JD })}>
              Use a sample
            </Button>
          </div>
          <ErrorNote error={error ?? loadError} />
        </div>

        <div className="inset" style={{ padding: 18 }}>
          <Eyebrow style={{ marginBottom: 8 }}>Your pasted JDs</Eyebrow>
          {pasted.length === 0 ? (
            <p className="subcopy" style={{ margin: 0 }}>
              None yet. A JD you paste stays private to you.
            </p>
          ) : (
            <div className="stack" style={{ gap: 8 }}>
              {pasted.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className="target-chip"
                  aria-pressed={selectedId === option.id}
                  onClick={() => onSelect(option.id)}
                >
                  <b>{option.title}</b>
                  <span className="target-chip-company">
                    {option.company_name}
                  </span>
                  {option.fit !== null && (
                    <span className="target-chip-fit">{option.fit}%</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </AutoGrid>
    </div>
  );
}
