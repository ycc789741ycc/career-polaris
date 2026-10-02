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

/**
 * Bumped each time a stage goes from busy to idle, so a screen can reload
 * what that stage just wrote by listing the counter as a dependency.
 */
export interface Settled {
  sources: number;
  analysis: number;
  roleMap: number;
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
  settled: { sources: 0, analysis: 0, roleMap: 0 },
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

function anythingBusy(activity: Activity | null): boolean {
  return (
    sourcesBusy(activity) ||
    isBusy(activity?.analysis) ||
    isBusy(activity?.role_map)
  );
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
  if (activity.analysis?.status === "running") {
    lines.push(`Analysing your strengths on ${model}`);
  }
  if (activity.role_map?.status === "running") {
    lines.push(`Building your role map on ${model}`);
  } else if (activity.role_map?.status === "waiting") {
    lines.push(
      activity.role_map.waiting_for === "market"
        ? "Searching the market for your recommended roles"
        : "Role map waiting for the analysis to finish",
    );
  }
  return lines;
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
    if (sourcesDone || analysisDone || roleMapDone) {
      setSettled((count) => ({
        sources: count.sources + (sourcesDone ? 1 : 0),
        analysis: count.analysis + (analysisDone ? 1 : 0),
        roleMap: count.roleMap + (roleMapDone ? 1 : 0),
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
    if (!anythingBusy(activity)) return;
    const timer = setTimeout(() => void refresh(), POLL_MS);
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
