import { createContext, useContext } from "react";
import type { Credential, Me } from "../api/types";
import type { AdvisorTab, Focus, Screen } from "./navigation";

/** What the sidebar and header show about the account, loaded once. */
export interface ShellStatus {
  me: Me | null;
  credential: Credential | null;
  /** Follow-up questions still waiting for an answer. */
  openQuestions: number;
  /** Mean dimension confidence of the latest analysis, 0–100, or null. */
  confidence: number | null;
}

/** Where a navigate() lands beyond the screen. Leaving focus out keeps it. */
export interface NavigateTo {
  tab?: AdvisorTab;
  focus?: Focus | null;
}

export interface Shell {
  status: ShellStatus;
  navigate: (screen: Screen, to?: NavigateTo) => void;
  /** What the role map has selected, and the Advisor aims at. In the hash. */
  focus: Focus | null;
  /** Changes the selection without adding a history entry. */
  setFocus: (focus: Focus | null) => void;
  /** Re-reads the status, after something a screen did changed it. */
  refresh: () => Promise<void>;
  /** The header's target chip: what the plan or résumé is aimed at. */
  target: string | null;
  setTarget: (label: string | null) => void;
}

const EMPTY: ShellStatus = {
  me: null,
  credential: null,
  openQuestions: 0,
  confidence: null,
};

export const ShellContext = createContext<Shell>({
  status: EMPTY,
  navigate: () => {},
  focus: null,
  setFocus: () => {},
  refresh: async () => {},
  target: null,
  setTarget: () => {},
});

export function useShell(): Shell {
  return useContext(ShellContext);
}

/** The model a screen names in its copy: the configured one, or a stand-in. */
export function modelName(credential: Credential | null): string {
  return credential?.model ?? "your model";
}
