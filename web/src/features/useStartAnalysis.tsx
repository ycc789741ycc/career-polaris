import { useState } from "react";
import { api } from "../api/client";
import type { CostEstimate } from "../api/types";
import { useActivity } from "../shell/activity";
import { getShownModel, useShell } from "../shell/ShellContext";
import { CostConfirm } from "./CostConfirm";
import { messageOf } from "./useAsync";

/**
 * Starting a strength analysis, from Sources ("Analyze with AI") or from
 * Strengths ("Re-analyse"): ask what it costs, wait for a yes, then start it.
 * Nothing is spent before the yes.
 */
export function useStartAnalysis({
  onStarted,
}: { onStarted?: () => void } = {}) {
  const { refresh: refreshActivity } = useActivity();
  const { status } = useShell();
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
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
    let started = false;
    try {
      await api.post("/assessments");
      setEstimate(null);
      started = true;
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
      // Refused or started, the running bar should say why.
      await refreshActivity();
    }
    if (started) onStarted?.();
  }

  const confirmation = estimate ? (
    <CostConfirm
      busy={busy}
      onConfirm={() => void confirm()}
      onCancel={() => setEstimate(null)}
    >
      This analysis will cost about <strong>${estimate.cost_usd}</strong> on{" "}
      {getShownModel(status, estimate.model_id)}, charged to your own provider.
      It scores your strengths and recommends roles; your role map is built only
      when you ask for it on Roles.
      {estimate.rate_is_published === false && (
        <>
          {" "}
          We have no published price for that model, so this is a high guess,
          and it won&apos;t count toward your monthly cap.
        </>
      )}
    </CostConfirm>
  ) : null;

  return { ask, busy, error, confirmation };
}
