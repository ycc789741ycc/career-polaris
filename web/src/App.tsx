import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api/client";
import type { Credential, Me } from "./api/types";
import { useAuth } from "./auth/AuthProvider";
import { SignInScreen } from "./auth/SignInScreen";
import { Loading } from "./components/ui";
import { AiSettings } from "./features/AiSettings";
import { Advisor } from "./features/Advisor";
import { Connect } from "./features/Connect";
import {
  completeCallback,
  type CallbackOutcome,
} from "./features/oauthCallback";
import { Roles } from "./features/Roles";
import { Strengths } from "./features/Strengths";
import {
  hashFor,
  metaOf,
  placeFromHash,
  type Focus,
  type Place,
  type Screen,
} from "./shell/navigation";
import { ActivityProvider } from "./shell/activity";
import { ActivityBar } from "./shell/ActivityBar";
import { PageHeader } from "./shell/PageHeader";
import {
  ShellContext,
  type NavigateTo,
  type ShellStatus,
} from "./shell/ShellContext";
import { Sidebar } from "./shell/Sidebar";
import { ToastProvider } from "./shell/toast";

export function App() {
  const { status } = useAuth();

  if (status === "loading") {
    // The refresh cookie is being exchanged; a reload should not flash the
    // sign-in screen while that happens.
    return (
      <div
        style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}
      >
        <Loading what="your session" />
      </div>
    );
  }
  return status === "signed-in" ? (
    <ToastProvider>
      <ActivityProvider>
        <Shell />
      </ActivityProvider>
    </ToastProvider>
  ) : (
    <SignInScreen />
  );
}

/** What the sidebar and header need. Pieces fail independently. */
export async function loadStatus(): Promise<ShellStatus> {
  const [me, credential] = await Promise.all([
    api.get<Me>("/me").catch(() => null),
    api.get<Credential | null>("/ai-credential").catch(() => null),
  ]);
  return { me, credential };
}

function Shell() {
  const { email, signOut } = useAuth();
  const [place, setPlace] = useState<Place>(() =>
    placeFromHash(window.location.hash),
  );
  // navigate() builds on the latest place without re-creating itself.
  const current = useRef(place);
  useEffect(() => {
    current.current = place;
  }, [place]);
  const { screen, tab, focus } = place;
  const [status, setStatus] = useState<ShellStatus>({
    me: null,
    credential: null,
  });
  const [target, setTarget] = useState<string | null>(null);
  const [heading, setHeading] = useState<string | null>(null);
  const [callback, setCallback] = useState<CallbackOutcome | null>(null);
  const handled = useRef(false);

  const navigate = useCallback((next: Screen, to: NavigateTo = {}) => {
    const from = current.current;
    const place: Place = {
      screen: next,
      tab: to.tab ?? from.tab,
      focus: to.focus === undefined ? from.focus : to.focus,
    };
    current.current = place;
    setPlace(place);
    if (window.location.hash !== hashFor(place)) {
      window.history.pushState(null, "", hashFor(place));
    }
  }, []);

  // A new selection on the same screen replaces the entry rather than adding
  // one, so clicking through bubbles does not fill the back button.
  const setFocus = useCallback((next: Focus | null) => {
    const place: Place = { ...current.current, focus: next };
    current.current = place;
    setPlace(place);
    window.history.replaceState(null, "", hashFor(place));
  }, []);

  // Back and forward move between screens like any other page.
  useEffect(() => {
    const onHash = () => setPlace(placeFromHash(window.location.hash));
    window.addEventListener("popstate", onHash);
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("popstate", onHash);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  // Returning from GitHub or Jira lands on /connections/{kind}/callback.
  // Handled once per page load: the code it carries is single-use.
  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    void completeCallback(window.location, (url) =>
      window.history.replaceState(null, "", url),
    ).then((outcome) => {
      if (outcome) {
        navigate("sources");
        setCallback(outcome);
      }
    });
  }, [navigate]);

  const refresh = useCallback(async () => {
    setStatus(await loadStatus());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const shell = useMemo(
    () => ({
      status,
      navigate,
      focus,
      setFocus,
      refresh,
      target,
      setTarget,
      setHeading,
    }),
    [status, navigate, focus, setFocus, refresh, target],
  );
  const me = status.me;

  return (
    <ShellContext.Provider value={shell}>
      <div className="app">
        <Sidebar current={screen} status={status} onNavigate={navigate} />
        <main className="main">
          <PageHeader
            meta={
              heading ? { ...metaOf(screen), title: heading } : metaOf(screen)
            }
            status={status}
            target={target}
            email={me?.email ?? email}
            onSignOut={() => void signOut()}
          />
          <ActivityBar />
          <div className="page-body" key={screen}>
            {me?.background_jobs_paused && (
              <p
                role="alert"
                className="inset"
                style={{
                  color: "var(--status-critical)",
                  fontSize: 13.5,
                  fontWeight: 600,
                  marginTop: 0,
                }}
              >
                <span aria-hidden="true">⚠</span> Background work is paused:{" "}
                {me.paused_reason}. Your reports will go out of date until this
                is fixed under “AI &amp; model”.
              </p>
            )}
            {screen === "sources" && <Connect callback={callback} />}
            {screen === "strengths" && <Strengths />}
            {screen === "roles" && <Roles />}
            {screen === "advisor" && <Advisor tab={tab} />}
            {screen === "model" && <AiSettings />}
          </div>
        </main>
      </div>
    </ShellContext.Provider>
  );
}
