/**
 * Which screen is showing, kept in the URL hash.
 *
 * The sidebar numbers the journey 01–04 (the prototype's six, with Questions
 * folded into Sources and the gap plan and résumé merged into the Advisor)
 * and keeps the model settings apart as "system configuration". The hash
 * (`#/advisor/plan?role=…`) lets a reload or the back button land on the same
 * screen, tab and role, without a router dependency.
 *
 * What the Advisor aims at is whatever the role map has selected — a role,
 * and optionally one opening in it (ADR 0022) — or a posting the user brought
 * themselves (Phase 8), so that selection lives here too, not in any screen.
 */

export type Screen = "sources" | "strengths" | "roles" | "advisor" | "model";

/**
 * The Advisor's tabs: first Fill the gap, then either the plan or the résumé;
 * and "own", where the user brings a role of their own to aim at (ADR 0034).
 */
export type AdvisorTab = "gaps" | "plan" | "resume" | "own";

/** What the role map has selected: a role, and optionally one opening in it. */
export interface RoleFocus {
  role: string;
  opening?: string | undefined;
}

/** A posting the user brought themselves, picked in the Advisor (Phase 8). */
export interface PostingFocus {
  posting: string;
}

/** What the Advisor is aimed at: a role selection, or a posting of your own. */
export type Focus = RoleFocus | PostingFocus;

/** The role selection a focus names, if it names one. Pure. */
export function roleFocus(focus: Focus | null): RoleFocus | null {
  return focus && "role" in focus ? focus : null;
}

/** Everything the hash says. */
export interface Place {
  screen: Screen;
  tab: AdvisorTab;
  focus: Focus | null;
}

export interface ScreenMeta {
  id: Screen;
  /** Shown before the label in the sidebar; absent for settings. */
  num?: string;
  label: string;
  /** The page heading. */
  title: string;
  kicker: string;
}

/** The numbered journey, in order. */
export const JOURNEY: readonly ScreenMeta[] = [
  {
    id: "sources",
    num: "01",
    label: "Sources",
    title: "Bring in your real work",
    kicker: "Profile",
  },
  {
    id: "strengths",
    num: "02",
    label: "Strengths",
    title: "Where you actually stand",
    kicker: "Report",
  },
  {
    id: "roles",
    num: "03",
    label: "Role map",
    title: "The roles worth your next six months",
    kicker: "Report",
  },
  {
    id: "advisor",
    num: "04",
    label: "Advisor",
    title: "Closing the distance to one role",
    kicker: "Plan & résumé",
  },
];

export const MODEL_SCREEN: ScreenMeta = {
  id: "model",
  label: "AI & model",
  title: "Bring your own model",
  kicker: "System configuration",
};

const ALL: readonly ScreenMeta[] = [...JOURNEY, MODEL_SCREEN];

export const DEFAULT_SCREEN: Screen = "sources";

export function metaOf(screen: Screen): ScreenMeta {
  return ALL.find((item) => item.id === screen) ?? JOURNEY[0]!;
}

export const DEFAULT_TAB: AdvisorTab = "gaps";

/** What a hash names; the defaults for anything it does not. Pure. */
export function placeFromHash(hash: string): Place {
  const [path = "", query = ""] = hash.replace(/^#\/?/, "").split("?", 2);
  const [id = "", tabPart] = path.split("/");
  const screen = ALL.some((item) => item.id === id)
    ? (id as Screen)
    : DEFAULT_SCREEN;
  const tab: AdvisorTab =
    tabPart === "plan" || tabPart === "resume" || tabPart === "own"
      ? tabPart
      : DEFAULT_TAB;
  const params = new URLSearchParams(query);
  const role = params.get("role");
  const opening = params.get("opening");
  const posting = params.get("posting");
  const focus: Focus | null = role
    ? opening
      ? { role, opening }
      : { role }
    : posting
      ? { posting }
      : null;
  return { screen, tab, focus };
}

/**
 * The selection a navigate() lands with. One it names wins; otherwise it
 * stays with the screen, except that entering the Advisor from elsewhere —
 * the sidebar, the header — opens the Target last set there, or none, and
 * never the role map's selection: a bubble picked is not a Target until
 * "Target this role" makes it one. Pure.
 */
export function getArrivalFocus(
  from: Place,
  next: Screen,
  named: Focus | null | undefined,
  storedTarget: Focus | null,
): Focus | null {
  if (named !== undefined) return named;
  if (next === "advisor" && from.screen !== "advisor") return storedTarget;
  return from.focus;
}

/** The hash for a location; the tab shows only on the Advisor. */
export function hashFor({
  screen,
  tab = DEFAULT_TAB,
  focus = null,
}: {
  screen: Screen;
  tab?: AdvisorTab;
  focus?: Focus | null;
}): string {
  const path = screen === "advisor" ? `${screen}/${tab}` : screen;
  const params = new URLSearchParams();
  if (focus && "role" in focus) {
    params.set("role", focus.role);
    if (focus.opening) params.set("opening", focus.opening);
  } else if (focus) {
    params.set("posting", focus.posting);
  }
  const query = focus ? `?${params}` : "";
  return `#/${path}${query}`;
}
