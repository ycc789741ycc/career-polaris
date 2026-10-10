import { createContext, useContext, useEffect } from "react";
import type { AiSource, Credential, Me } from "../api/types";
import type { Settled } from "./activity";
import type { AdvisorTab, Focus, Screen } from "./navigation";

/** What the sidebar and header show about the account, loaded once. */
export interface ShellStatus {
  me: Me | null;
  credential: Credential | null;
  /** Which key AI runs on (ADR 0064); absent until it has loaded. */
  aiSource?: AiSource | null;
}

/** Where a navigate() lands beyond the screen. Leaving focus out keeps it. */
export interface NavigateTo {
  tab?: AdvisorTab;
  focus?: Focus | null;
}

export interface Shell {
  status: ShellStatus;
  /** The signed-in address, which keys what this browser remembers for it. */
  account: string | null;
  navigate: (screen: Screen, to?: NavigateTo) => void;
  /** What the role map has selected, or what the Advisor is aimed at. In
   * the hash. */
  focus: Focus | null;
  /** Changes the selection without adding a history entry. */
  setFocus: (focus: Focus | null) => void;
  /** Re-reads the status, after something a screen did changed it. */
  refresh: () => Promise<void>;
  /** The header's target chip: what the plan or résumé is aimed at. */
  target: string | null;
  setTarget: (label: string | null) => void;
  /** Replaces the page heading while a screen shows a state of its own, such
   * as a waiting screen; null gives the screen's usual heading back. */
  setHeading: (heading: string | null) => void;
}

const EMPTY: ShellStatus = {
  me: null,
  credential: null,
};

export const ShellContext = createContext<Shell>({
  status: EMPTY,
  account: null,
  navigate: () => {},
  focus: null,
  setFocus: () => {},
  refresh: async () => {},
  target: null,
  setTarget: () => {},
  setHeading: () => {},
});

export function useShell(): Shell {
  return useContext(ShellContext);
}

/** Shows `heading` as the page heading while it is set, and gives the
 * screen's own back when it is not, or when the screen goes. */
export function useHeading(heading: string | null): void {
  const { setHeading } = useShell();
  useEffect(() => {
    setHeading(heading);
    return () => setHeading(null);
  }, [heading, setHeading]);
}

/** Whether the user's AI runs on CareerPolaris's key rather than their own. */
export function isOnPlatform(status: ShellStatus): boolean {
  return status.aiSource?.source === "platform";
}

/** Whether there is any AI to run the user's work on: their own key, or
 * CareerPolaris's once they chose it. */
export function hasAi(status: ShellStatus): boolean {
  return isOnPlatform(status) || status.credential !== null;
}

/** What the platform's AI is called wherever it is named. Its model never is
 * (ADR 0066). */
export const PLATFORM_AI = "CareerPolaris AI";

/** The model a screen names in its copy: the user's own, or "CareerPolaris
 * AI" while their work runs on the platform. */
export function modelName(status: ShellStatus): string {
  if (isOnPlatform(status)) return PLATFORM_AI;
  return status.credential?.model ?? "your model";
}

/** The model an estimate names. An estimate prices a run on the current
 * source, so on the platform it is "CareerPolaris AI", never its model. */
export function getShownModel(
  status: ShellStatus,
  modelId: string | null,
): string | null {
  return isOnPlatform(status) ? PLATFORM_AI : modelId;
}

/** Who pays, as a run's copy says it: "your own key on claude-opus-5", or
 * "CareerPolaris AI". */
export function chargedTo(status: ShellStatus): string {
  return isOnPlatform(status)
    ? PLATFORM_AI
    : `your own key on ${modelName(status)}`;
}

/** This month's quota on CareerPolaris's key. */
export type PlatformQuota = NonNullable<AiSource["platform_quota"]>;

/** The share of this month's quota spent, 0–100. Pure. */
export function getQuotaPercent(quota: PlatformQuota): number {
  const allowed = Number(quota.allowed_usd);
  if (!(allowed > 0)) return 100;
  return Math.min(100, Math.max(0, (Number(quota.spent_usd) / allowed) * 100));
}

/** The quota as users see it: whole percentages used and left, which always
 * add up to 100. Never dollars: those are the operator's. Pure. */
export function getQuotaLabel(quota: PlatformQuota): {
  used: number;
  left: number;
} {
  const used = Math.round(getQuotaPercent(quota));
  return { used, left: 100 - used };
}

/** The quota while the user's work runs on CareerPolaris's key, or null. */
export function getPlatformQuota(status: ShellStatus): PlatformQuota | null {
  return isOnPlatform(status)
    ? (status.aiSource?.platform_quota ?? null)
    : null;
}

/** How many runs that spend AI have finished: when it moves, the quota
 * has. Pure. */
export function getAiRunsSettled(settled: Settled): number {
  return settled.analysis + settled.roleMap + settled.advisor;
}
