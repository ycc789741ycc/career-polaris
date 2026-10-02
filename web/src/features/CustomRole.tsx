import { useState } from "react";
import { api } from "../api/client";
import type { CustomRoleEstimate, Role } from "../api/types";
import { Button, ErrorNote } from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { CostConfirm } from "./CostConfirm";
import { messageOf } from "./useAsync";

type Draft = { title: string; company: string; jd: string };

const EMPTY: Draft = { title: "", company: "", jd: "" };

/**
 * "Add a role of your own" (ADR 0021): a role the recommendation missed,
 * placed on the map beside the recommended ones. A title is enough; a company narrows the
 * search for its postings, and a pasted JD, which stays private, is what its
 * requirements are read from. The cost is shown before anything is spent.
 */
export function CustomRoleForm({
  onAdded,
}: {
  /** The role was added: reload the map and select it. */
  onAdded: (role: Role) => Promise<void>;
}) {
  const { status } = useShell();
  const model = modelName(status.credential);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [estimate, setEstimate] = useState<CustomRoleEstimate | null>(null);
  const [added, setAdded] = useState<Role | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function body() {
    return {
      title: draft.title.trim(),
      company_name: draft.company.trim() || null,
      job_description: draft.jd.trim() || null,
    };
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
      if (!draft.title.trim()) {
        setError("Give the role a job title first.");
        return;
      }
      setAdded(null);
      setEstimate(
        await api.post<CustomRoleEstimate>(
          "/roles/custom/cost-estimate",
          body(),
        ),
      );
    });

  const add = () =>
    run(async () => {
      const role = await api.post<Role>("/roles/custom", body());
      setEstimate(null);
      setDraft(EMPTY);
      setAdded(role);
      await onAdded(role);
    });

  return (
    <div className="panel" style={{ marginTop: 20 }}>
      <h3>Add a role of your own</h3>
      <p className="subcopy">
        Not seeing a role you want? Add it and it is analysed against your
        strengths, then placed on the map beside the recommended ones. A pasted
        JD stays private to you.
      </p>
      {estimate && (
        <CostConfirm
          busy={busy}
          onConfirm={() => void add()}
          onCancel={() => setEstimate(null)}
        >
          {estimate.matches > 0
            ? `It takes in ${estimate.matches} open ${estimate.matches === 1 ? "posting" : "postings"} in your locations. `
            : "No open posting in your locations matches it yet, so it is read from its JD alone. "}
          Reading what it requires, then scoring your fit against every role on
          the map, will cost about <strong>${estimate.cost_usd}</strong>
          {estimate.model_id ? ` on ${estimate.model_id}` : ""}, charged to your
          own provider.
        </CostConfirm>
      )}
      <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 200px" }}>
          <label className="field-label" htmlFor="custom-role-title">
            Job title
          </label>
          <input
            id="custom-role-title"
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
          <label className="field-label" htmlFor="custom-role-company">
            Company name <span className="muted">(optional)</span>
          </label>
          <input
            id="custom-role-company"
            className="input"
            placeholder="e.g. Halden Labs"
            value={draft.company}
            onChange={(event) =>
              setDraft({ ...draft, company: event.target.value })
            }
          />
        </div>
      </div>
      <label
        className="field-label"
        htmlFor="custom-role-jd"
        style={{ marginTop: 10 }}
      >
        Job description{" "}
        <span className="muted">(optional, sharpens the analysis)</span>
      </label>
      <textarea
        id="custom-role-jd"
        className="input"
        rows={4}
        placeholder={`Paste the full posting — ${model} reads its requirements.`}
        value={draft.jd}
        onChange={(event) => setDraft({ ...draft, jd: event.target.value })}
      />
      <div className="row" style={{ marginTop: 10 }}>
        <Button
          busy={busy}
          disabled={!draft.title.trim()}
          onClick={() => void askForEstimate()}
        >
          Add to Role Map
        </Button>
        {added && (
          <span className="muted" style={{ fontSize: 13 }}>
            On the map:{" "}
            <strong>
              {added.name}
              {added.company_name ? ` · ${added.company_name}` : ""}
            </strong>
          </span>
        )}
      </div>
      <ErrorNote error={error} />
    </div>
  );
}
