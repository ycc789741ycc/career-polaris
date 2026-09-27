import type { Evidence } from "../api/types";
import type { FactSelection } from "./selection";
import { SOURCES } from "./SourceMix";

/** What a bar on this chart counts, per source. */
const GROUPS = [
  { source: "github", title: "Merged pull requests by repository" },
  { source: "jira", title: "Issues by Jira project" },
] as const;

export interface Place {
  source: string;
  subject: string;
  count: number;
  /** Every fact about this repository or project: the tally and its items. */
  ids: string[];
}

export interface PlaceGroup {
  source: string;
  title: string;
  places: Place[];
}

/**
 * Bars come from each source's own per-place tallies ("12 merged pull
 * requests in acme/ledger"), not from counting items: a sync keeps only the
 * latest few items, but its tallies cover everything it read.
 */
export function placeGroups(facts: Evidence[]): PlaceGroup[] {
  return GROUPS.map(({ source, title }) => {
    const places = facts
      .filter(
        (f) =>
          f.source === source &&
          f.granularity === "summary" &&
          f.subject !== null &&
          f.tally !== null,
      )
      .map((tally) => ({
        source,
        subject: tally.subject as string,
        count: tally.tally as number,
        ids: facts
          .filter((f) => f.source === source && f.subject === tally.subject)
          .map((f) => f.id),
      }))
      .sort((a, b) => b.count - a.count || a.subject.localeCompare(b.subject));
    return { source, title, places };
  }).filter((group) => group.places.length > 0);
}

export function placeKey(place: Place): string {
  return `place:${place.source}:${place.subject}`;
}

/**
 * Where the work lives: one bar per repository or project.
 *
 * Each source gets its own scale, because a merged pull request and a Jira
 * issue are not the same unit and one axis would invite comparing them.
 */
export function WorkPlaces({
  facts,
  selectedKey = null,
  onSelect,
}: {
  facts: Evidence[];
  selectedKey?: string | null;
  onSelect: (selection: FactSelection | null) => void;
}) {
  const groups = placeGroups(facts);
  if (groups.length === 0) return null;

  return (
    <div className="panel">
      <h3 style={{ margin: 0 }}>Where the work lives</h3>
      <p className="subcopy" style={{ fontSize: 13 }}>
        The places each source counted most. Click one to list its facts below.
      </p>
      {groups.map((group) => {
        const most = Math.max(...group.places.map((p) => p.count), 1);
        const colour = SOURCES[group.source]?.colour ?? "var(--axis)";
        return (
          <section key={group.source} className="places">
            <h4 className="places-title">{group.title}</h4>
            <ul className="places-list">
              {group.places.map((place) => {
                const key = placeKey(place);
                const isSelected = key === selectedKey;
                return (
                  <li key={key}>
                    <button
                      type="button"
                      className="place"
                      aria-pressed={isSelected}
                      aria-label={`${place.subject}: ${place.count}`}
                      onClick={() =>
                        onSelect(
                          isSelected
                            ? null
                            : { key, label: place.subject, ids: place.ids },
                        )
                      }
                    >
                      <span className="place-name" title={place.subject}>
                        {place.subject}
                      </span>
                      <span className="place-track" aria-hidden="true">
                        <span
                          className="place-bar"
                          style={{
                            width: `${(place.count / most) * 100}%`,
                            background: colour,
                          }}
                        />
                      </span>
                      <span className="place-count">{place.count}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
