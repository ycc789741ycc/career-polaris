import { useState } from "react";
import { api } from "../api/client";
import type { StringPage } from "../api/types";
import { Button, ErrorNote, Loading } from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

// The cap the market enforces (domain decision 21). The api is the authority;
// this only keeps the input from offering a fourth it would refuse.
export const MAX_TARGET_LOCATIONS = 3;

/**
 * "Where you want to work": the user's one to three target locations.
 *
 * They are stated about the user, so they sit in 01 Sources, but what they
 * decide is market scope: which postings the role map groups and which salary
 * bands it shows. Each change saves the whole set, and a role map the user
 * already has is rebuilt on the new scope.
 */
export function TargetLocations() {
  const saved = useAsync<string[]>(
    () => api.items<StringPage>("/target-locations"),
    [],
  );
  // What the last save answered with; it is the saved set from then on.
  const [answered, setAnswered] = useState<string[] | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chosen = answered ?? saved.data ?? [];
  const isFull = chosen.length >= MAX_TARGET_LOCATIONS;
  const left = MAX_TARGET_LOCATIONS - chosen.length;

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

  async function add() {
    const value = draft.trim();
    if (!value || isFull) return;
    if (await save([...chosen, value])) setDraft("");
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
        Pick up to {MAX_TARGET_LOCATIONS} locations. The role map only searches
        postings in these places, and salary bands are shown for them.
      </p>
      {saved.loading ? (
        <Loading what="your locations" />
      ) : (
        <>
          {chosen.length > 0 && (
            <div className="row" style={{ gap: 8, margin: "10px 0" }}>
              {chosen.map((location) => (
                <span key={location} className="chip location-chip">
                  {location}
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
          <form
            className="row"
            style={{ flexWrap: "nowrap", marginTop: 10 }}
            onSubmit={(event) => {
              event.preventDefault();
              void add();
            }}
          >
            <input
              className="input"
              aria-label="Add a location"
              value={draft}
              placeholder="City, country or Remote region…"
              disabled={isFull}
              onChange={(event) => setDraft(event.target.value)}
            />
            <Button
              type="submit"
              variant="secondary"
              busy={busy}
              disabled={isFull || !draft.trim()}
            >
              Add
            </Button>
          </form>
          <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
            {isFull
              ? `At ${MAX_TARGET_LOCATIONS}, remove one to add another.`
              : chosen.length === 0
                ? "None chosen yet: the role map uses the platform's baseline postings."
                : `${left} ${left === 1 ? "slot" : "slots"} left. At ${MAX_TARGET_LOCATIONS}, remove one to add another.`}
          </p>
        </>
      )}
      <ErrorNote error={error} />
    </section>
  );
}
