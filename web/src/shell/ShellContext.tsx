import { createContext, useContext, useEffect } from "react";
import type { Credential, Me } from "../api/types";
import type { AdvisorTab, Focus, Screen } from "./navigation";

/** What the sidebar and header show about the account, loaded once. */
export interface ShellStatus {
  me: Me | null;
  credential: Credential | null;
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

/** The model a screen names in its copy: the configured one, or a stand-in. */
export function modelName(credential: Credential | null): string {
  return credential?.model ?? "your model";
}
