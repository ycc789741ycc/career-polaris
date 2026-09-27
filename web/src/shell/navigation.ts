/**
 * Which screen is showing, kept in the URL hash.
 *
 * The sidebar numbers the journey 01–04 (the prototype's six, with Questions
 * folded into Sources and the gap plan and résumé merged into the Advisor)
 * and keeps the model settings apart as "system configuration". The hash
 * (`#/advisor/plan?role=…`) lets a reload or the back button land on the same
 * screen, tab and role, without a router dependency.
 *
 * What the Advisor aims at is whatever the role map has selected — a role, or
 * a JD the user pasted — so that selection lives here too, not in either
 * screen.
 */

export type Screen =
  | "sources"
  | "strengths"
  | "roles"
  | "advisor"
  | "model";

/** The Advisor's two tabs. */
export type AdvisorTab = "plan" | "resume";

/** What the role map has selected: a role, or a JD the user pasted. */
export type Focus = { kind: "role"; id: string } | { kind: "jd"; id: string };

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

export const DEFAULT_TAB: AdvisorTab = "plan";

const FOCUS_PARAMS = { role: "role", jd: "jd" } as const;

/** What a hash names; the defaults for anything it does not. Pure. */
export function placeFromHash(hash: string): Place {
  const [path = "", query = ""] = hash.replace(/^#\/?/, "").split("?", 2);
  const [id = "", tabPart] = path.split("/");
  const screen = ALL.some((item) => item.id === id)
    ? (id as Screen)
    : DEFAULT_SCREEN;
  const tab: AdvisorTab = tabPart === "resume" ? "resume" : DEFAULT_TAB;
  const params = new URLSearchParams(query);
  const role = params.get(FOCUS_PARAMS.role);
  const jd = params.get(FOCUS_PARAMS.jd);
  const focus: Focus | null = role
    ? { kind: "role", id: role }
    : jd
      ? { kind: "jd", id: jd }
      : null;
  return { screen, tab, focus };
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
  const query = focus
    ? `?${new URLSearchParams({ [FOCUS_PARAMS[focus.kind]]: focus.id })}`
    : "";
  return `#/${path}${query}`;
}
