import { useState } from "react";
import { api } from "../api/client";
import type { TargetOption } from "../api/types";
import { AutoGrid, Button, ErrorNote, Eyebrow } from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { messageOf, useAsync } from "./useAsync";

const SAMPLE_JD = {
  title: "Staff Platform Engineer",
  company: "Meridian Labs",
  text: "Staff Platform Engineer at Meridian Labs — set technical direction across three product teams, own the reliability roadmap and its SLOs, mentor senior engineers. Requires demonstrated org-level influence.",
};

/**
 * A JD the user pastes: the one thing the Advisor can aim at that is not a
 * role on the map. Selecting it here is what the Advisor then plans and
 * writes for. It stays private to the user, and its requirements are read on
 * their model the first time the Advisor prices something for it.
 */
export function OwnJdPanel() {
  const { status, focus, setFocus, navigate } = useShell();
  const model = modelName(status.credential);
  const targets = useAsync<TargetOption[]>(() => api.get("/targets"), []);
  const [jd, setJd] = useState({ text: "", title: "", company: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pasted = (targets.data ?? []).filter(
    (o) => o.kind === "privatePosting",
  );
  const selected = pasted.find(
    (o) => focus?.kind === "jd" && focus.id === o.id,
  );

  async function save() {
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
      await targets.reload();
      setFocus({ kind: "jd", id: posting.id });
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
        A posting that is not on the map. Select it here and the Advisor plans
        and writes against its own requirements instead of a role&apos;s.
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
            <Button busy={busy} onClick={() => void save()}>
              Save &amp; select
            </Button>
            <Button variant="ghost" onClick={() => setJd({ ...SAMPLE_JD })}>
              Use a sample
            </Button>
          </div>
          <ErrorNote error={error ?? targets.error} />
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
                  aria-pressed={selected?.id === option.id}
                  onClick={() => setFocus({ kind: "jd", id: option.id })}
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
          {selected && (
            <div className="row" style={{ marginTop: 14 }}>
              <Button
                onClick={() =>
                  navigate("advisor", {
                    tab: "plan",
                    focus: { kind: "jd", id: selected.id },
                  })
                }
              >
                Plan a route
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  navigate("advisor", {
                    tab: "resume",
                    focus: { kind: "jd", id: selected.id },
                  })
                }
              >
                Tailor résumé
              </Button>
            </div>
          )}
        </div>
      </AutoGrid>
    </div>
  );
}
