import { type ReactNode, useEffect, useRef, useState } from "react";
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
 * What they decide is market scope: which postings the role map is built from
 * and which salary bands it shows. So they sit on 03 Roles, above the map and
 * its Build button (ADR 0071). Each change saves the whole set; the role map
 * then says the locations changed, and is rebuilt on them when the user asks
 * (ADR 0027). A country or "Remote" is also searched for the roles an analysis
 * recommends; a region is not.
 *
 * One line, no panel: the label, the chosen places as chips, "+ Add" and the
 * `note`. The list opens as a dropdown under "+ Add", over the page, so the
 * map does not move; picking a place saves and closes it, and Escape or a
 * click outside closes it without saving. What the places mean is behind the
 * ⓘ. `isReadOnly` keeps the set as it is while a build reads it.
 */
export function TargetLocations({
  note,
  isReadOnly = false,
  onSaved,
}: {
  // What the chosen places take in, at the end of the line.
  note?: ReactNode;
  isReadOnly?: boolean;
  onSaved?: (locations: string[]) => void;
} = {}) {
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
  const [isListOpen, setIsListOpen] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const addRef = useRef<HTMLDivElement>(null);
  const aboutRef = useRef<HTMLDivElement>(null);

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
  const isListShown = isListOpen && !isReadOnly && !isFull;

  // Escape or a click outside closes whichever popover is open.
  useEffect(() => {
    if (!isListShown && !isAboutOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setIsListOpen(false);
      setIsAboutOpen(false);
      setFilter("");
    }
    function onPointer(event: PointerEvent) {
      const target = event.target as Node;
      if (!addRef.current?.contains(target)) {
        setIsListOpen(false);
        setFilter("");
      }
      if (!aboutRef.current?.contains(target)) setIsAboutOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [isListShown, isAboutOpen]);

  async function save(locations: string[]) {
    setBusy(true);
    setError(null);
    try {
      const stored = await api.put<string[]>("/target-locations", {
        locations,
      });
      setAnswered(stored);
      onSaved?.(stored);
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
    if (await save([...chosen, name])) {
      setFilter("");
      setIsListOpen(false);
    }
  }

  return (
    <section className="location-line" aria-label="Where you want to work">
      <span className="location-line-label">Where you want to work</span>
      {saved.loading || options.loading ? (
        <Loading what="your locations" />
      ) : (
        <>
          {chosen.length === 0 ? (
            <span className="muted">
              {isReadOnly
                ? "Anywhere (the platform's baseline postings)"
                : "Anywhere (newest baseline postings)"}
            </span>
          ) : (
            chosen.map((location) => (
              <span key={location} className="chip location-chip">
                {location}
                {kindOf.get(location) === "region" && (
                  <span className="location-chip-kind">region</span>
                )}
                {!isReadOnly && (
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
                )}
              </span>
            ))
          )}
          {!isReadOnly && !isFull && (
            <div className="location-add" ref={addRef}>
              <button
                type="button"
                className="location-add-button"
                aria-expanded={isListShown}
                aria-haspopup="dialog"
                disabled={busy}
                onClick={() => {
                  setIsListOpen((open) => !open);
                  setFilter("");
                }}
              >
                + Add
              </button>
              {isListShown && (
                <div
                  className="location-dropdown"
                  role="dialog"
                  aria-label="Add a place"
                >
                  <input
                    className="input"
                    aria-label="Find a place"
                    value={filter}
                    placeholder="Type to filter: a country, a region or Remote…"
                    autoFocus
                    onChange={(event) => setFilter(event.target.value)}
                  />
                  <div className="location-options">
                    {GROUPS.map(({ kind, label }) => {
                      const inGroup = shown.filter(
                        (option) => option.kind === kind,
                      );
                      if (inGroup.length === 0) return null;
                      return (
                        <div key={kind} role="group" aria-label={label}>
                          <div className="location-options-heading">
                            {label}
                          </div>
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
                </div>
              )}
            </div>
          )}
          {note && <span className="muted location-line-note">{note}</span>}
          <div className="location-about" ref={aboutRef}>
            <button
              type="button"
              className="location-about-button"
              aria-label="About where you want to work"
              aria-expanded={isAboutOpen}
              onClick={() => setIsAboutOpen((open) => !open)}
            >
              ⓘ
            </button>
            {isAboutOpen && (
              <div className="location-about-popover" role="note">
                <p>
                  Pick up to {MAX_TARGET_LOCATIONS} places. Your role map is
                  built from postings in these places, and salary bands are
                  shown for them.
                </p>
                <p>
                  {isFull
                    ? `At ${MAX_TARGET_LOCATIONS}, remove one to add another.`
                    : chosen.length === 0
                      ? "None chosen: your map uses the platform's newest baseline postings."
                      : `${left} ${left === 1 ? "slot" : "slots"} left. At ${MAX_TARGET_LOCATIONS}, remove one to add another.`}
                </p>
                {hasRegion && (
                  <p>
                    Regions use the postings we already have. Pick a country for
                    a fresh search of your recommended roles.
                  </p>
                )}
              </div>
            )}
          </div>
        </>
      )}
      <ErrorNote error={error ?? options.error} />
    </section>
  );
}
