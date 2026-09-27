import type { Evidence } from "../api/types";

/**
 * The Sources timeline: when the work behind the evidence happened.
 *
 * Only single pieces of work are counted — one pull request, one issue. A
 * summary ("12 merged pull requests in x") tallies items that are already on
 * the chart, and its date is only the latest of them. Only sources whose date
 * is when the work happened get a row: a résumé line has no date, and an
 * answer's date is when it was given.
 */
export const TIMELINE_SOURCES = [
  {
    source: "github",
    label: "GitHub PRs",
    noun: ["pull request", "pull requests"],
  },
  { source: "jira", label: "Jira issues", noun: ["issue", "issues"] },
] as const;

export type TimelineRange = "year" | "all";

/** Below this many dated facts a grid is mostly empty; dots read better. */
export const SPARSE_BELOW = 10;

const WEEKS_IN_YEAR = 52;
const DAY_MS = 86_400_000;

export interface TimelineWeek {
  /** Monday of the week, YYYY-MM-DD. */
  start: string;
  facts: Evidence[];
}

export interface TimelineRow {
  source: string;
  label: string;
  noun: readonly [string, string];
  weeks: TimelineWeek[];
  total: number;
}

export interface Timeline {
  /** Monday of every week shown, oldest first. */
  weeks: string[];
  rows: TimelineRow[];
  /** Dated facts inside the range. */
  dated: number;
  /** Dated facts older than the range, which "all" would show. */
  older: number;
  /** Single facts with no work date: résumé lines, answers. */
  undated: number;
  busiestMonths: { month: string; count: number }[];
}

export function buildTimeline(
  facts: Evidence[],
  { today, range }: { today: string; range: TimelineRange },
): Timeline {
  const plotted = new Set<string>(TIMELINE_SOURCES.map((s) => s.source));
  const items = facts.filter((f) => f.granularity === "item");
  const dated = items.filter(
    (f) => plotted.has(f.source) && f.observed_on !== null,
  );
  const lastWeek = weekStart(today);

  let firstWeek = addDays(lastWeek, -7 * (WEEKS_IN_YEAR - 1));
  if (range === "all") {
    for (const fact of dated) {
      const week = weekStart(fact.observed_on as string);
      if (week < firstWeek) firstWeek = week;
    }
  }
  const weeks: string[] = [];
  for (let week = firstWeek; week <= lastWeek; week = addDays(week, 7)) {
    weeks.push(week);
  }

  const inRange = dated.filter((f) => {
    const week = weekStart(f.observed_on as string);
    // A date after this week is a clock the source got wrong; it is not work
    // still to come, so it sits in the latest week rather than vanishing.
    return week >= firstWeek;
  });

  const rows = TIMELINE_SOURCES.map(({ source, label, noun }) => {
    const byWeek = new Map<string, Evidence[]>();
    for (const fact of inRange) {
      if (fact.source !== source) continue;
      const week = minString(weekStart(fact.observed_on as string), lastWeek);
      byWeek.set(week, [...(byWeek.get(week) ?? []), fact]);
    }
    const cells = weeks.map((start) => ({
      start,
      facts: byWeek.get(start) ?? [],
    }));
    return {
      source,
      label,
      noun,
      weeks: cells,
      total: cells.reduce((sum, week) => sum + week.facts.length, 0),
    };
  });

  const byMonth = new Map<string, number>();
  for (const fact of inRange) {
    const month = (fact.observed_on as string).slice(0, 7);
    byMonth.set(month, (byMonth.get(month) ?? 0) + 1);
  }
  const busiestMonths = [...byMonth.entries()]
    .map(([month, count]) => ({ month, count }))
    // Most facts first; on a tie, the more recent month.
    .sort((a, b) => b.count - a.count || b.month.localeCompare(a.month))
    .slice(0, 2);

  return {
    weeks,
    rows,
    dated: inRange.length,
    older: dated.length - inRange.length,
    undated: items.length - dated.length,
    busiestMonths,
  };
}

/** 0 for none, then 1, 2–3 and 4 or more. */
export function heatLevel(count: number): 0 | 1 | 2 | 3 {
  if (count === 0) return 0;
  if (count === 1) return 1;
  if (count <= 3) return 2;
  return 3;
}

/** The Monday on or before a YYYY-MM-DD date, in UTC. */
export function weekStart(day: string): string {
  const date = parseDay(day);
  const sinceMonday = (date.getUTCDay() + 6) % 7;
  return formatDay(new Date(date.getTime() - sinceMonday * DAY_MS));
}

/** Where a day falls between two others, from 0 to 1. */
export function position(day: string, from: string, to: string): number {
  const span = parseDay(to).getTime() - parseDay(from).getTime();
  if (span <= 0) return 0;
  const offset = parseDay(day).getTime() - parseDay(from).getTime();
  return Math.min(1, Math.max(0, offset / span));
}

export function addDays(day: string, days: number): string {
  return formatDay(new Date(parseDay(day).getTime() + days * DAY_MS));
}

/** "12 May 2026", read in UTC so a date never shifts by the viewer's zone. */
export function formatDate(day: string): string {
  return parseDay(day).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** "May 2026" from "2026-05". */
export function formatMonth(month: string): string {
  return parseDay(`${month}-01`).toLocaleDateString(undefined, {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function todayUtc(): string {
  return formatDay(new Date());
}

function parseDay(day: string): Date {
  return new Date(`${day.slice(0, 10)}T00:00:00Z`);
}

function formatDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function minString(a: string, b: string): string {
  return a < b ? a : b;
}
