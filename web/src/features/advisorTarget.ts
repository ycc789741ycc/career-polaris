import type {
  Fit,
  OwnPosting,
  PlanSummary,
  ResumeSummary,
  Role,
  TargetRef,
} from "../api/types";
import { sameTarget } from "./target";

/**
 * Which Target the Advisor works against, and the ones it worked against
 * before (ADR 0050).
 *
 * No Target exists until the user sets one: "Target this role" on the role
 * map, "Set as target" on a role of their own, or a previous target used
 * again. The choice is kept in this browser, per account; the server knows a
 * Target only through the answers, plans and résumés written for it, which
 * is where Previous targets also looks.
 */

/** One time a Target was worked against, as this browser remembers it. */
export interface TargetUse {
  ref: TargetRef;
  label: string;
  /** ISO time it was last opened in the Advisor. */
  usedAt: string;
}

export interface TargetStore {
  current: TargetRef | null;
  /** Newest first, at most STORED_TARGET_LIMIT. */
  history: TargetUse[];
}

/** A Target to switch back to, as Previous targets lists it. */
export interface PreviousTarget {
  ref: TargetRef;
  label: string;
  source: "role_map" | "own_role";
  /** "uploaded JD" or "filled in" for a role of your own; null otherwise. */
  detail: string | null;
  lastUsedAt: string;
  fit: number | null;
}

export const STORED_TARGET_LIMIT = 20;

const EMPTY: TargetStore = { current: null, history: [] };

function storageKey(account: string): string {
  return `careerpolaris.target.${account}`;
}

/**
 * The account's stored Targets; empty when there are none, the storage is
 * unavailable (a private window, blocked site data), or what is there is not
 * a store this code wrote.
 */
export function getStoredTargets(account: string | null): TargetStore {
  if (!account) return EMPTY;
  try {
    const raw = window.localStorage.getItem(storageKey(account));
    if (!raw) return EMPTY;
    return parseStore(JSON.parse(raw));
  } catch {
    return EMPTY;
  }
}

/**
 * Records that the Advisor now works against `ref`: it becomes the current
 * Target and the newest in the history. Storage failing loses only this
 * browser's memory of it, so it is not an error the user can act on.
 */
export function recordTargetUse(
  account: string | null,
  ref: TargetRef,
  label: string,
  now: Date = new Date(),
): void {
  if (!account) return;
  const next = getStoreWithUse(getStoredTargets(account), ref, label, now);
  try {
    window.localStorage.setItem(storageKey(account), JSON.stringify(next));
  } catch {
    // Unavailable storage: the Advisor still opens on this Target now.
  }
}

/** The store with `ref` as the current Target and newest use. Pure. */
export function getStoreWithUse(
  store: TargetStore,
  ref: TargetRef,
  label: string,
  now: Date,
): TargetStore {
  const kept = store.history.filter((use) => !sameTarget(use.ref, ref));
  return {
    current: ref,
    history: [{ ref, label, usedAt: now.toISOString() }, ...kept].slice(
      0,
      STORED_TARGET_LIMIT,
    ),
  };
}

/**
 * Every Target worth switching back to, newest first. Pure.
 *
 * The browser's history is joined with the Targets the server has plans and
 * résumés for, so a Target set on another device still shows; each is dated
 * by its latest use, plan or résumé. The current Target is left out, and so is
 * one that can no longer be aimed at: a role gone from the map, or a posting
 * of your own removed or not scored.
 */
export function getPreviousTargets({
  history,
  plans,
  resumes,
  roles,
  fits,
  own,
  current,
}: {
  history: readonly TargetUse[];
  plans: readonly PlanSummary[];
  resumes: readonly ResumeSummary[];
  roles: readonly Role[];
  fits: readonly Fit[];
  own: readonly OwnPosting[];
  current: TargetRef | null;
}): PreviousTarget[] {
  const seen: { ref: TargetRef; label: string; at: string }[] = [];
  const add = (ref: TargetRef, label: string, at: string | null) => {
    if (!at) return;
    const found = seen.find((entry) => sameTarget(entry.ref, ref));
    if (!found) {
      seen.push({ ref, label, at });
    } else if (at > found.at) {
      found.at = at;
    }
  };
  for (const use of history) add(use.ref, use.label, use.usedAt);
  for (const plan of plans) {
    add(plan.target, plan.label, plan.drafted_at ?? plan.created_at);
  }
  for (const resume of resumes) {
    add(resume.target, resume.label, resume.updated_at);
  }

  const previous: PreviousTarget[] = [];
  for (const entry of seen) {
    if (current && sameTarget(entry.ref, current)) continue;
    const ownId = entry.ref.private_job_posting_id;
    if (ownId) {
      const posting = own.find((p) => p.private_job_posting_id === ownId);
      if (!posting || posting.fit === null) continue;
      previous.push({
        ref: entry.ref,
        label: entry.label,
        source: "own_role",
        detail: posting.source === "filled_in" ? "filled in" : "uploaded JD",
        lastUsedAt: entry.at,
        fit: posting.is_stale ? null : posting.fit,
      });
      continue;
    }
    if (!roles.some((role) => role.id === entry.ref.role_id)) continue;
    previous.push({
      ref: entry.ref,
      label: entry.label,
      source: "role_map",
      detail: null,
      lastUsedAt: entry.at,
      fit: fits.find((f) => f.role_id === entry.ref.role_id)?.score ?? null,
    });
  }
  return previous.sort((a, b) => b.lastUsedAt.localeCompare(a.lastUsedAt));
}

/** "Your own role · uploaded JD · last used 12 Sep 2026". Pure. */
export function previousTargetLine(
  target: PreviousTarget,
  dayLabel: (iso: string) => string,
): string {
  return [
    target.source === "own_role" ? "Your own role" : "From the role map",
    target.detail,
    `last used ${dayLabel(target.lastUsedAt)}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** A store read back from storage, or nothing usable. */
function parseStore(value: unknown): TargetStore {
  if (!value || typeof value !== "object") return EMPTY;
  const { current, history } = value as Partial<TargetStore>;
  return {
    current: isRef(current) ? current : null,
    history: Array.isArray(history)
      ? history
          .filter(
            (use): use is TargetUse =>
              !!use &&
              isRef(use.ref) &&
              typeof use.label === "string" &&
              typeof use.usedAt === "string",
          )
          .slice(0, STORED_TARGET_LIMIT)
      : [],
  };
}

function isRef(value: unknown): value is TargetRef {
  if (!value || typeof value !== "object") return false;
  const ref = value as Partial<TargetRef>;
  return (
    typeof ref.role_id === "string" ||
    typeof ref.private_job_posting_id === "string"
  );
}
