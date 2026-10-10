import { createContext, useContext, useEffect } from "react";
import type { AiSource, Credential, Me } from "../api/types";
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

/** The model a screen names in its copy: the one in use, or a stand-in. */
export function modelName(status: ShellStatus): string {
  if (isOnPlatform(status)) {
    return status.aiSource?.platform_model ?? "CareerPolaris's model";
  }
  return status.credential?.model ?? "your model";
}

/** Who pays, as a run's copy says it: "your own key on claude-opus-5", or
 * "CareerPolaris's AI (claude-haiku-4-5)". */
export function chargedTo(status: ShellStatus): string {
  return isOnPlatform(status)
    ? `CareerPolaris's AI (${modelName(status)})`
    : `your own key on ${modelName(status)}`;
}
