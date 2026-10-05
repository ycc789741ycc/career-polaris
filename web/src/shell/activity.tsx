import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { Activity, RunStatus } from "../api/types";
import { useToast } from "./toast";

/** How often the shell asks what is running while something is. */
export const POLL_MS = 2000;
/** How often it asks while the processing machine is away, so the notice
 * clears soon after it is back (ADR 0052). */
export const AWAY_POLL_MS = 30000;

/**
 * Bumped each time a stage goes from busy to idle, so a screen can reload
 * what that stage just wrote by listing the counter as a dependency.
 */
export interface Settled {
  sources: number;
  analysis: number;
  roleMap: number;
  /** An Advisor job finished, failed or was cancelled (ADR 0042). */
  advisor: number;
}

export interface ActivityState {
  /** What is running, or null before the first answer. */
  activity: Activity | null;
  /** Asks again now: call it right after starting any background work. */
  refresh: () => Promise<void>;
  settled: Settled;
}

const IDLE: ActivityState = {
  activity: null,
  refresh: async () => {},
  settled: { sources: 0, analysis: 0, roleMap: 0, advisor: 0 },
};

export const ActivityContext = createContext<ActivityState>(IDLE);

export function useActivity(): ActivityState {
  return useContext(ActivityContext);
}

/** An analysis or build still to finish: running, or waiting to start. */
export function isBusy(run: RunStatus | null | undefined): boolean {
  return run?.status === "running" || run?.status === "waiting";
}

/** Stage 01 is still syncing a source or parsing a résumé. */
export function sourcesBusy(activity: Activity | null): boolean {
  return (
    activity !== null &&
    (activity.syncing.length > 0 || activity.parsing.length > 0)
  );
}

/**
 * The machine that runs background work is off (ADR 0051, 0052): what the
 * user starts is queued, and runs when it is back.
 */
export function isProcessingAway(activity: Activity | null): boolean {
  return activity !== null && !activity.processing.is_worker_online;
}

/** What to tell the user, before they start work, while it is away. */
export const AWAY_NOTICE = "Processing is offline; this starts when it is back";

function anythingBusy(activity: Activity | null): boolean {
  return (
    sourcesBusy(activity) ||
    isBusy(activity?.analysis) ||
    isBusy(activity?.role_map) ||
    (activity?.advisor_jobs.length ?? 0) > 0
  );
}

/** An Advisor job that was running is no longer: done, failed or cancelled. */
function advisorJobEnded(before: Activity, next: Activity): boolean {
  const running = new Set(next.advisor_jobs.map((job) => job.id));
  return before.advisor_jobs.some((job) => !running.has(job.id));
}

const SOURCE_NAMES: Record<string, string> = { github: "GitHub", jira: "Jira" };

/** One line per piece of work in progress, in journey order. */
export function describe(activity: Activity | null, model: string): string[] {
  if (activity === null) return [];
  const lines = [
    ...activity.syncing.map(
      (work) => `Syncing ${SOURCE_NAMES[work.label] ?? work.label}`,
    ),
    ...activity.parsing.map((work) => `Reading ${work.label}`),
  ];
  const away = isProcessingAway(activity);
  if (away && lines.length + busyRuns(activity) > 0) {
    lines.unshift("Waiting for the processing machine to come back");
  }
  if (activity.analysis?.status === "running") {
    lines.push(`Analysing your strengths on ${model}`);
  }
  if (activity.role_map?.status === "running") {
    lines.push(`Building your role map on ${model}`);
  } else if (activity.role_map?.status === "waiting") {
    const market = activity.role_map.waiting_for === "market";
    lines.push(
      market && !activity.processing.is_crawler_online
        ? "Role map waiting for the market search to come back online"
        : market
          ? "Searching the market for your recommended roles"
          : "Role map waiting for the analysis to finish",
    );
  }
  return lines;
}

/** Analyses, builds and Advisor jobs still to finish. */
function busyRuns(activity: Activity): number {
  return (
    (isBusy(activity.analysis) ? 1 : 0) +
    (isBusy(activity.role_map) ? 1 : 0) +
    activity.advisor_jobs.length
  );
}

function outcome(what: string, run: RunStatus | null): string {
  if (run?.status === "ready") return `${what} finished.`;
  const why = run?.error?.message ?? "it stopped before finishing";
  return `${what} failed — ${why}`;
}

/**
 * Polls `/activity` while anything is running and stops when nothing is
 * (ADR 0006, ADR 0018). Screens read it through `useActivity()`; the shell
 * shows it in the running bar and the sidebar.
 */
export function ActivityProvider({ children }: { children: ReactNode }) {
  const flash = useToast();
  const [activity, setActivity] = useState<Activity | null>(null);
  const [settled, setSettled] = useState<Settled>(IDLE.settled);
  const previous = useRef<Activity | null>(null);

  const refresh = useCallback(async () => {
    let next: Activity;
    try {
      next = await api.get<Activity>("/activity");
    } catch {
      // A failed poll keeps the last answer on screen rather than claiming
      // nothing runs; the next refresh, or the next start, asks again.
      return;
    }
    const before = previous.current;
    previous.current = next;
    setActivity(next);
    if (before === null) return;

    const sourcesDone = sourcesBusy(before) && !sourcesBusy(next);
    const analysisDone = isBusy(before.analysis) && !isBusy(next.analysis);
    const roleMapDone = isBusy(before.role_map) && !isBusy(next.role_map);
    const advisorDone = advisorJobEnded(before, next);
    if (sourcesDone || analysisDone || roleMapDone || advisorDone) {
      setSettled((count) => ({
        sources: count.sources + (sourcesDone ? 1 : 0),
        analysis: count.analysis + (analysisDone ? 1 : 0),
        roleMap: count.roleMap + (roleMapDone ? 1 : 0),
        advisor: count.advisor + (advisorDone ? 1 : 0),
      }));
    }
    // One toast at a time: the latest stage to finish is the one to mention.
    if (roleMapDone) flash(outcome("Role map", next.role_map));
    else if (analysisDone) flash(outcome("Analysis", next.analysis));
    else if (sourcesDone) flash("Your sources are up to date.");
  }, [flash]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    // While the machine is away nothing moves, so ask rarely; still ask, so
    // the notice goes once it is back.
    const delay = isProcessingAway(activity)
      ? AWAY_POLL_MS
      : anythingBusy(activity)
        ? POLL_MS
        : null;
    if (delay === null) return;
    const timer = setTimeout(() => void refresh(), delay);
    return () => clearTimeout(timer);
  }, [activity, refresh]);

  const value = useMemo(
    () => ({ activity, refresh, settled }),
    [activity, refresh, settled],
  );
  return (
    <ActivityContext.Provider value={value}>
      {children}
    </ActivityContext.Provider>
  );
}
