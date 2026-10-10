import { useState } from "react";
import { api } from "../api/client";
import type { AiSource } from "../api/types";
import {
  ErrorNote,
  PillToggle,
  ProgressBar,
  RoundCheck,
} from "../components/ui";
import {
  getQuotaLabel,
  getQuotaPercent,
  useShell,
} from "../shell/ShellContext";
import { messageOf, useAsync } from "./useAsync";

/** What the user accepts before their first switch to CareerPolaris's key. */
export const PLATFORM_TERMS =
  "Your evidence (résumé lines, GitHub and Jira facts, your answers) is sent to CareerPolaris's AI provider, under CareerPolaris's account and its terms, not yours.";

/**
 * Which key the user's AI runs on: their own, or CareerPolaris's under a
 * monthly quota (ADR 0064). Switching is free and takes effect from the next
 * run; nothing falls back from one to the other. Shown only while
 * CareerPolaris offers its key.
 */
export function AiSourcePanel() {
  const { refresh } = useShell();
  const choice = useAsync<AiSource>(() => api.get("/ai-source"), []);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const data = choice.data;
  if (!data?.is_platform_on) return null;

  async function use(source: "own" | "platform") {
    setBusy(true);
    setError(null);
    try {
      await api.put("/ai-source", {
        source,
        accept_platform_terms: source === "platform" && accepted,
      });
      await Promise.all([choice.reload(), refresh()]);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  const quota = data.platform_quota;
  const onPlatform = data.source === "platform";
  const needsTerms = !data.has_accepted_platform_terms;

  return (
    <div className="panel">
      <h3>Which AI runs your work</h3>
      <div
        className="row"
        style={{ gap: 8, margin: "4px 0 14px" }}
        role="group"
        aria-label="Which AI runs your work"
      >
        <PillToggle
          pressed={data.source === "own"}
          disabled={busy || !data.has_credential}
          onClick={() => void use("own")}
        >
          Your own key
        </PillToggle>
        <PillToggle
          pressed={onPlatform}
          disabled={
            busy || !data.is_eligible || (needsTerms && !accepted) || onPlatform
          }
          onClick={() => void use("platform")}
        >
          CareerPolaris&apos;s AI
        </PillToggle>
      </div>

      <p className="subcopy">{getSourceNote(data)}</p>

      {data.is_eligible && quota && (
        <div style={{ margin: "12px 0" }}>
          <ProgressBar
            percent={getQuotaPercent(quota)}
            label={`Free quota used: ${getQuotaLabel(quota).used}%`}
          />
          <p className="subcopy" style={{ fontSize: 13, marginTop: 6 }}>
            {getQuotaLine(quota, data.platform_model)}
          </p>
        </div>
      )}

      {data.is_eligible && needsTerms && !onPlatform && (
        <RoundCheck checked={accepted} onChange={setAccepted}>
          {PLATFORM_TERMS}
        </RoundCheck>
      )}

      <ErrorNote error={error ?? choice.error} />
    </div>
  );
}

/** What the panel says under the choice. Pure. */
export function getSourceNote(data: AiSource): string {
  if (!data.is_eligible) {
    return "CareerPolaris's AI is for accounts signed in with Google. Sign in with Google to use it, or add a key of your own below.";
  }
  if (data.source === "platform") {
    return `Your work runs on CareerPolaris's AI (${data.platform_model}) until this month's quota is used. Switch back to your own key at any time.`;
  }
  if (data.source === "own") {
    return "Your work runs on your own key. You can switch to CareerPolaris's AI, with a monthly quota, at any time.";
  }
  return "Nothing is set up to run your work yet: use CareerPolaris's AI, with a monthly quota, or add a key of your own below.";
}

/** "38% of this month's free quota used · 62% left. On claude-haiku-4-5. It
 * starts again on the 1st." In percentages only. Pure. */
export function getQuotaLine(
  quota: NonNullable<AiSource["platform_quota"]>,
  model: string | null,
): string {
  const { used, left } = getQuotaLabel(quota);
  if (used >= 100) {
    return "This month's free quota is used up. It starts again on the 1st, or switch to your own key.";
  }
  const on = model ? ` On ${model}.` : "";
  return `${used}% of this month's free quota used · ${left}% left.${on} It starts again on the 1st.`;
}
