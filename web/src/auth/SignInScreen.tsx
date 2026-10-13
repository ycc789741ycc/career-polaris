import { useEffect, useState, type FormEvent } from "react";
import { AppIcon } from "../components/AppIcon";
import { PRIVACY_PATH } from "../features/PrivacyPolicy";
import { Button, ErrorNote, Field } from "../components/ui";
import { useAuth } from "./AuthProvider";
import { googleStartUrl, signInMethods, type SignInMethods } from "./session";
import { SignInIllustration } from "./SignInIllustration";
import { readSignInError, withoutSignInError } from "./signInError";

/** If the server cannot be asked: Google off, so a password is the way in. */
const PASSWORD_ONLY: SignInMethods = {
  password: true,
  google: false,
  platform_ai: false,
};

/**
 * Sign in. Accounts are made only by signing in with Google (ADR 0080); the
 * email form is for accounts from before then, offered only while Google is
 * off.
 */
export function SignInScreen() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  // A Google sign-in that did not finish comes back with its reason in the
  // URL. Read purely here; the effect below removes it.
  const [error, setError] = useState<string | null>(() =>
    readSignInError(window.location.search),
  );
  // Null until the server answers: nothing is offered, so a form never
  // flashes up and goes.
  const [methods, setMethods] = useState<SignInMethods | null>(null);

  useEffect(() => {
    const { pathname, search } = window.location;
    if (readSignInError(search) !== null) {
      window.history.replaceState(
        null,
        "",
        withoutSignInError(pathname, search),
      );
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    signInMethods()
      .then((offered) => !cancelled && setMethods(offered))
      .catch(() => !cancelled && setMethods(PASSWORD_ONLY));
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Something went wrong.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sign-in">
      <div className="brand sign-in-brand">
        <AppIcon size={32} />
        CareerPolaris
      </div>

      <div className="sign-in-pitch">
        <SignInIllustration />
        <div>
          <h1 className="sign-in-headline">
            Know your strengths. Find your next role. Tailor your résumé to it.
          </h1>
          <p className="lead sign-in-lead">
            CareerPolaris reads your evidence from GitHub, Jira and your past
            résumé, then backs every strength, role match and résumé line with
            it.
          </p>
        </div>
      </div>

      <div className="sign-in-aside">
        <div className="sign-in-card">
          <form onSubmit={submit} style={{ display: "grid", gap: 4 }}>
            <h2 className="sign-in-heading">Sign in to CareerPolaris</h2>

            {methods?.google && (
              /* A link, not a fetch: the browser itself goes to Google. */
              <a
                className="btn btn-secondary sign-in-google"
                href={googleStartUrl()}
              >
                Continue with Google
              </a>
            )}

            {methods?.google && methods.password && (
              <div className="sign-in-divider">or with email</div>
            )}

            {methods?.password && (
              <>
                <Field label="Email">
                  <input
                    className="input"
                    type="email"
                    value={email}
                    autoComplete="email"
                    placeholder="you@work.com"
                    required
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </Field>

                <Field label="Password">
                  <input
                    className="input"
                    type="password"
                    value={password}
                    autoComplete="current-password"
                    required
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </Field>
              </>
            )}

            <ErrorNote error={error} />

            {methods?.password && (
              <Button
                type="submit"
                busy={busy}
                disabled={!email || !password}
                block
              >
                Sign in
              </Button>
            )}

            {/* Said plainly rather than discovered later. */}
            <p className="sign-in-footnote">
              {methods?.platform_ai
                ? "Sign in with Google to start on CareerPolaris AI's free monthly quota, or add your own AI provider and key after signing in."
                : "After signing in you add your own AI provider and key; nothing is analysed until you do."}{" "}
              {methods?.google &&
                "New to CareerPolaris? Continuing with Google makes your account. Had a password here? Continue with Google at the same address: the account is linked to Google, and any password on it stops working."}
              {methods?.password &&
                !methods.google &&
                "Accounts are made with Google, which is not set up here, so only an existing account can sign in. No password reset yet."}{" "}
              <a href={PRIVACY_PATH}>Privacy policy</a>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
