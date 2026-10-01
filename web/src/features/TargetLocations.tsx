import { useState } from "react";
import { api } from "../api/client";
import type {
  StringPage,
  TargetLocationOption,
  TargetLocationOptionPage,
} from "../api/types";
import { ErrorNote, Loading } from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

// The cap the market enforces (domain decision 21). The api is the authority;
// this only keeps the list from offering a fourth it would refuse.
export const MAX_TARGET_LOCATIONS = 3;

const GROUPS: { kind: TargetLocationOption["kind"]; label: string }[] = [
  { kind: "remote", label: "Remote" },
  { kind: "region", label: "Regions" },
  { kind: "country", label: "Countries" },
];

/**
 * "Where you want to work": the user's one to three target locations, picked
 * from the places the platform knows how to match (ADR 0026).
 *
 * They are stated about the user, so they sit in 01 Sources, but what they
 * decide is market scope: which postings the role map is built from and which
 * salary bands it shows. Each change saves the whole set, and a role map the
 * user already has is rebuilt on the new scope. A country or "Remote" is also
 * searched for the roles an analysis recommends; a region is not.
 */
export function TargetLocations() {
  const saved = useAsync<string[]>(
    () => api.items<StringPage>("/target-locations"),
    [],
  );
  const options = useAsync<TargetLocationOption[]>(
    () => api.items<TargetLocationOptionPage>("/target-location-options"),
    [],
  );
  // What the last save answered with; it is the saved set from then on.
  const [answered, setAnswered] = useState<string[] | null>(null);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chosen = answered ?? saved.data ?? [];
  const isFull = chosen.length >= MAX_TARGET_LOCATIONS;
  const left = MAX_TARGET_LOCATIONS - chosen.length;
  const kindOf = new Map(
    (options.data ?? []).map((option) => [option.name, option.kind]),
  );
  const hasRegion = chosen.some((name) => kindOf.get(name) === "region");
  const wanted = filter.trim().toLowerCase();
  const shown = (options.data ?? []).filter((option) =>
    option.name.toLowerCase().includes(wanted),
  );

  async function save(locations: string[]) {
    setBusy(true);
    setError(null);
    try {
      setAnswered(await api.put<string[]>("/target-locations", { locations }));
      return true;
    } catch (err) {
      setError(messageOf(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add(name: string) {
    if (isFull || chosen.includes(name)) return;
    if (await save([...chosen, name])) setFilter("");
  }

  return (
    <section className="panel" aria-labelledby="target-locations-heading">
      <div className="row-between">
        <h3 id="target-locations-heading" style={{ margin: 0 }}>
          Where you want to work
        </h3>
        <span className="muted" style={{ fontSize: 12.5, fontWeight: 700 }}>
          {chosen.length} of {MAX_TARGET_LOCATIONS} chosen
        </span>
      </div>
      <p className="subcopy">
        Pick up to {MAX_TARGET_LOCATIONS} places. The role map only uses
        postings in these places, and salary bands are shown for them.
      </p>
      {saved.loading || options.loading ? (
        <Loading what="your locations" />
      ) : (
        <>
          {chosen.length > 0 && (
            <div className="row" style={{ gap: 8, margin: "10px 0" }}>
              {chosen.map((location) => (
                <span key={location} className="chip location-chip">
                  {location}
                  {kindOf.get(location) === "region" && (
                    <span className="location-chip-kind">region</span>
                  )}
                  <button
                    type="button"
                    className="location-chip-remove"
                    aria-label={`Remove ${location}`}
                    disabled={busy}
                    onClick={() =>
                      void save(chosen.filter((other) => other !== location))
                    }
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <input
            className="input"
            aria-label="Find a place"
            value={filter}
            placeholder="Type to filter: a country, a region or Remote…"
            disabled={isFull}
            onChange={(event) => setFilter(event.target.value)}
            style={{ marginTop: 10 }}
          />
          {!isFull && (
            <div className="location-options">
              {GROUPS.map(({ kind, label }) => {
                const inGroup = shown.filter((option) => option.kind === kind);
                if (inGroup.length === 0) return null;
                return (
                  <div key={kind} role="group" aria-label={label}>
                    <div className="location-options-heading">{label}</div>
                    {inGroup.map((option) => {
                      const isChosen = chosen.includes(option.name);
                      return (
                        <button
                          key={option.name}
                          type="button"
                          className="location-option"
                          disabled={busy || isChosen}
                          aria-label={
                            isChosen
                              ? `${option.name}, already chosen`
                              : `Add ${option.name}`
                          }
                          onClick={() => void add(option.name)}
                        >
                          {option.name}
                        </button>
                      );
                    })}
                  </div>
                );
              })}
              {shown.length === 0 && (
                <p className="muted" style={{ margin: 8 }}>
                  No place matches “{filter.trim()}”.
                </p>
              )}
            </div>
          )}
          <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
            {isFull
              ? `At ${MAX_TARGET_LOCATIONS}, remove one to add another.`
              : chosen.length === 0
                ? "None chosen yet: the role map uses the platform's baseline postings."
                : `${left} ${left === 1 ? "slot" : "slots"} left. At ${MAX_TARGET_LOCATIONS}, remove one to add another.`}
          </p>
          {hasRegion && (
            <p className="muted" style={{ fontSize: 12.5, margin: "6px 0 0" }}>
              Regions use the postings we already have. Pick a country for a
              fresh search of your recommended roles.
            </p>
          )}
        </>
      )}
      <ErrorNote error={error ?? options.error} />
    </section>
  );
}
