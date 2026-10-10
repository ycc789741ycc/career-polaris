import { useState } from "react";
import { api } from "../api/client";
import type { AiSource } from "../api/types";
import {
  AutoGrid,
  ErrorNote,
  Eyebrow,
  Loading,
  ProgressBar,
} from "../components/ui";
import {
  getQuotaLabel,
  getQuotaPercent,
  type PlatformQuota,
  PLATFORM_AI,
  useShell,
} from "../shell/ShellContext";
import { MonthlyBudget } from "./MonthlyBudget";
import { OwnProviderForm } from "./OwnProviderForm";
import { messageOf, useAsync } from "./useAsync";

type Source = "own" | "platform";

// The prototype's "What runs on your key", with questions written per gap of
// the target role rather than for uncertain scores (domain decision 27).
const USES = [
  {
    title: "Questions",
    note: "Written for the gaps between your evidence and the role you target, in Fill the gap.",
  },
  {
    title: "Skill analysis",
    note: "Reads your evidence into your own dimensions, citing each fact, and recommends the roles they point to.",
  },
  {
    title: "Role map",
    note: "Names the recommended roles that have real openings, reads out what they require, and scores your fit.",
  },
  {
    title: "Advisor",
    note: "Drafts a gap plan for the role you select on the map, and writes a résumé for it from cited work.",
  },
];

/** Where the user's evidence goes on CareerPolaris AI, said where they use it. */
export const PLATFORM_NOTICE =
  "Your evidence (résumé lines, GitHub and Jira facts, your answers) goes to CareerPolaris's AI provider to run your work.";

/**
 * The AI settings screen: first which AI runs the user's work, then only what
 * that one needs (ADR 0066).
 *
 * - **CareerPolaris AI**: this month's free quota, as a percentage. No key,
 *   no budget, and never the model.
 * - **Your own provider**: the key form and the monthly budget. A key kept
 *   from before stays stored while the platform runs, so switching back needs
 *   nothing typed again.
 *
 * An eligible account runs on CareerPolaris AI until it picks otherwise.
 * Picking it switches at once; picking one's own provider with no key shows
 * the form, and saving the key switches.
 */
export function AiSettings() {
  const { refresh } = useShell();
  const choice = useAsync<AiSource>(() => api.get("/ai-source"), []);
  const [picked, setPicked] = useState<Source | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const data = choice.data;
  if (choice.loading && !data) return <Loading what="your AI settings" />;
  const selected = getSelectedSource(data, picked);

  async function reload() {
    setPicked(null);
    await Promise.all([choice.reload(), refresh()]);
  }

  async function pick(next: Source) {
    setPicked(next);
    setError(null);
    // One's own provider with no key yet: show the form; saving switches.
    if (next === data?.source || (next === "own" && !data?.has_credential)) {
      return;
    }
    setBusy(true);
    try {
      await api.put("/ai-source", { source: next });
      await reload();
    } catch (caught) {
      setPicked(null);
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 24 }}>
      {data?.is_platform_on && (
        <AiSourceChooser
          data={data}
          selected={selected}
          busy={busy}
          onPick={(next) => void pick(next)}
        />
      )}
      <ErrorNote error={error ?? choice.error} />

      {selected === "platform" && data ? (
        <AutoGrid col={340}>
          <PlatformQuotaPanel quota={data.platform_quota} />
          <WhatRunsCallout heading={`What runs on ${PLATFORM_AI}`} />
        </AutoGrid>
      ) : (
        <AutoGrid col={340}>
          <OwnProviderForm onSaved={reload} />
          <div className="stack" style={{ gap: 20 }}>
            <MonthlyBudget />
            <WhatRunsCallout heading="What runs on your key" />
          </div>
        </AutoGrid>
      )}
    </div>
  );
}

/** Which card shows as picked: the one just clicked, else the source in use,
 * else one's own provider. Pure. */
export function getSelectedSource(
  data: AiSource | null,
  picked: Source | null,
): Source {
  if (picked) return picked;
  return data?.source === "platform" ? "platform" : "own";
}

function AiSourceChooser({
  data,
  selected,
  busy,
  onPick,
}: {
  data: AiSource;
  selected: Source;
  busy: boolean;
  onPick: (source: Source) => void;
}) {
  return (
    <div className="panel">
      <h3 id="ai-source-heading">How your AI runs</h3>
      <div
        className="source-cards"
        role="radiogroup"
        aria-labelledby="ai-source-heading"
      >
        <SourceCard
          source="platform"
          title={PLATFORM_AI}
          note={
            data.is_eligible
              ? "Free monthly quota. Nothing to set up."
              : "For accounts signed in with Google. Sign in with Google to use it."
          }
          checked={selected === "platform"}
          disabled={busy || !data.is_eligible}
          onPick={onPick}
        />
        <SourceCard
          source="own"
          title="Your own provider"
          note={
            data.has_credential
              ? "Use your key from Anthropic, OpenAI or Google. It is kept: switch back any time."
              : "Use a key from Anthropic, OpenAI or Google."
          }
          checked={selected === "own"}
          disabled={busy}
          onPick={onPick}
        />
      </div>
    </div>
  );
}

function SourceCard({
  source,
  title,
  note,
  checked,
  disabled,
  onPick,
}: {
  source: Source;
  title: string;
  note: string;
  checked: boolean;
  disabled: boolean;
  onPick: (source: Source) => void;
}) {
  return (
    <label className="source-card radio" data-checked={checked || undefined}>
      <input
        type="radio"
        name="ai-source"
        value={source}
        checked={checked}
        disabled={disabled}
        onChange={() => onPick(source)}
      />
      <span className="dot" aria-hidden="true" />
      <span>
        <span className="source-card-title">{title}</span>
        <span className="source-card-note">{note}</span>
      </span>
    </label>
  );
}

function PlatformQuotaPanel({ quota }: { quota: PlatformQuota | null }) {
  return (
    <div className="panel">
      <h3>This month&apos;s free quota</h3>
      {quota ? (
        <>
          <ProgressBar
            percent={getQuotaPercent(quota)}
            label={`Free quota used: ${getQuotaLabel(quota).used}%`}
          />
          <p className="subcopy" style={{ fontSize: 13.5, marginTop: 8 }}>
            {getQuotaLine(quota)}
          </p>
        </>
      ) : (
        <p className="subcopy">The quota could not be read just now.</p>
      )}
      <p className="subcopy" style={{ fontSize: 12.5, marginTop: 14 }}>
        {PLATFORM_NOTICE}
      </p>
    </div>
  );
}

function WhatRunsCallout({ heading }: { heading: string }) {
  return (
    <div className="callout">
      <Eyebrow style={{ marginBottom: 6 }}>{heading}</Eyebrow>
      <div className="divided">
        {USES.map((use) => (
          <div key={use.title}>
            <div style={{ fontSize: 14.5, fontWeight: 700 }}>{use.title}</div>
            <div
              className="callout-note"
              style={{ fontSize: 13, lineHeight: 1.55, marginTop: 3 }}
            >
              {use.note}
            </div>
          </div>
        ))}
      </div>
      <p
        className="callout-note"
        style={{ fontSize: 12.5, lineHeight: 1.55, margin: "14px 0 0" }}
      >
        Crawling, parsing, embedding and matching run on our side and need no
        model.
      </p>
      <p
        className="callout-note"
        style={{ fontSize: 12.5, lineHeight: 1.55, margin: "8px 0 0" }}
      >
        To find openings, the job titles your analysis recommends are searched
        on Himalayas, a public remote-jobs site, for the places you want to
        work. Only the title and the place are sent: nothing else from your
        profile, and nothing that says it is you.
      </p>
    </div>
  );
}

/** "38% of this month's free quota used · 62% left. It starts again on the
 * 1st." In percentages only, and never the model. Pure. */
export function getQuotaLine(quota: PlatformQuota): string {
  const { used, left } = getQuotaLabel(quota);
  if (used >= 100) {
    return "This month's free quota is used up. It starts again on the 1st, or switch to your own provider.";
  }
  return `${used}% of this month's free quota used · ${left}% left. It starts again on the 1st.`;
}
