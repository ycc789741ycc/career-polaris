import { useState } from "react";
import { api } from "../api/client";
import type { AnalysisEstimate } from "../api/types";
import { useActivity } from "../shell/activity";
import { getShownModel, isOnPlatform, useShell } from "../shell/ShellContext";
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
  const [estimate, setEstimate] = useState<AnalysisEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      setEstimate(
        await api.get<AnalysisEstimate>("/assessments/cost-estimate"),
      );
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
      This will cost about <strong>${estimate.cost_usd}</strong> on{" "}
      {getShownModel(status, estimate.model_id)},{" "}
      {isOnPlatform(status)
        ? "from your free monthly quota"
        : "charged to your own provider"}
      : ${estimate.analysis_cost_usd} for the analysis, at most $
      {estimate.role_map_cost_usd} for the role map built after it
      {estimate.max_roles > 0
        ? `, up to ${estimate.max_roles} roles`
        : ", which has no roles to name yet"}
      , and at most ${estimate.fits_cost_usd} for scoring your fit against them.
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
