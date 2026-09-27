import type { Evidence } from "../api/types";

/** Chart order, names and colours per source; unknown sources go last. */
export const SOURCES: Record<string, { name: string; colour: string }> = {
  github: { name: "GitHub", colour: "var(--source-github)" },
  jira: { name: "Jira", colour: "var(--source-jira)" },
  resume: { name: "Résumé", colour: "var(--source-resume)" },
  self_reported: {
    name: "Your answers",
    colour: "var(--source-self-reported)",
  },
};

export interface SourceShare {
  source: string;
  name: string;
  colour: string;
  count: number;
  /** Whole percent; the shares add up to 100. */
  percent: number;
}

export function sourceShares(facts: Evidence[]): SourceShare[] {
  const counts = new Map<string, number>();
  for (const fact of facts) {
    counts.set(fact.source, (counts.get(fact.source) ?? 0) + 1);
  }
  const order = Object.keys(SOURCES);
  const rank = (source: string) =>
    order.includes(source) ? order.indexOf(source) : order.length;
  const shares = [...counts.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([source, count]) => ({
      source,
      name: SOURCES[source]?.name ?? source,
      colour: SOURCES[source]?.colour ?? "var(--axis)",
      count,
      percent: 0,
    }));
  return withWholePercents(shares, facts.length);
}

/**
 * How the evidence splits by source, as one stacked bar.
 *
 * It shares out facts, not work: one fact can be a single pull request or a
 * total of a hundred, so the note under the bar says so rather than let the
 * widths be read as effort.
 */
export function SourceMix({ facts }: { facts: Evidence[] }) {
  const shares = sourceShares(facts);
  if (shares.length === 0) return null;
  const description = shares
    .map((s) => `${s.name} ${s.count} (${s.percent}%)`)
    .join(", ");

  return (
    <div>
      <div
        className="source-mix"
        role="img"
        aria-label={`Facts by source: ${description}`}
      >
        {shares.map((share) => (
          <span
            key={share.source}
            className="source-mix-segment"
            style={{ flexGrow: share.count, background: share.colour }}
          />
        ))}
      </div>
      <ul className="source-mix-legend" aria-hidden="true">
        {shares.map((share) => (
          <li key={share.source}>
            <span
              className="source-mix-swatch"
              style={{ background: share.colour }}
            />
            <span>{share.name}</span>
            <strong>{share.count}</strong>
            <span className="muted">{share.percent}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Rounds each share down, then hands the leftover points to the largest
 * remainders, so the legend never adds up to 99% or 101%.
 */
function withWholePercents(
  shares: SourceShare[],
  total: number,
): SourceShare[] {
  if (total === 0) return shares;
  const exact = shares.map((s) => (s.count * 100) / total);
  const floors = exact.map(Math.floor);
  let left = 100 - floors.reduce((sum, n) => sum + n, 0);
  const byRemainder = exact
    .map((value, index) => ({ index, remainder: value - Math.floor(value) }))
    .sort((a, b) => b.remainder - a.remainder);
  for (const { index } of byRemainder) {
    if (left === 0) break;
    floors[index] = (floors[index] as number) + 1;
    left -= 1;
  }
  return shares.map((s, i) => ({ ...s, percent: floors[i] as number }));
}
