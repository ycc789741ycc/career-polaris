import type { ReactNode } from "react";
import { AppIcon } from "../components/AppIcon";
import { loadConfig } from "../config";

/**
 * The privacy policy, public at /privacy.
 *
 * Shown without signing in, because the OAuth providers' consent screens
 * (Atlassian's in particular) link to it for people who have no account yet.
 * Every statement here describes what the code does today; a change to what is
 * collected, kept or deleted changes this page in the same pull request.
 */

export const PRIVACY_PATH = "/privacy";
export const PRIVACY_EFFECTIVE_DATE = "9 October 2026";

export function isPrivacyPath(pathname: string): boolean {
  return pathname.replace(/\/+$/, "") === PRIVACY_PATH;
}

export function PrivacyPolicy() {
  const { privacyContactEmail } = loadConfig();
  const contact = (
    <a href={`mailto:${privacyContactEmail}`}>{privacyContactEmail}</a>
  );

  return (
    <main
      style={{ maxWidth: 720, margin: "0 auto", padding: "48px 16px 72px" }}
    >
      <a
        className="brand"
        href="/"
        style={{ padding: 0, marginBottom: 28, fontSize: 18 }}
      >
        <AppIcon size={28} />
        CareerPolaris
      </a>
      <h1 style={{ fontSize: 36, marginBottom: 8 }}>Privacy policy</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Effective {PRIVACY_EFFECTIVE_DATE}
      </p>
      <p className="lead">
        CareerPolaris reads the work you have done — on GitHub, in Jira and in
        your résumé — to show where you stand and which roles are worth aiming
        at. This page says what it collects, what it does with it, and how to
        remove it. Questions or requests: {contact}.
      </p>

      <Section title="What we collect">
        <ul>
          <li>
            <strong>Your account:</strong> your email address and a salted
            Argon2id hash of your password — never the password itself. If you
            sign in with Google, the email Google confirms and Google’s
            identifier for your account.
          </li>
          <li>
            <strong>GitHub, if you connect it:</strong> your public profile,
            the commits you authored and the pull requests you reviewed —
            repository names, commit messages, counts and dates. Access is
            read-only (<code>read:user</code>, <code>repo:status</code>,{" "}
            <code>public_repo</code>).
          </li>
          <li>
            <strong>Jira, if you connect it:</strong> your Atlassian display
            name and, when your Atlassian privacy settings show it, your email;
            the name of each site you grant; and the finished issues assigned
            to you — their keys, summaries, statuses, dates and the epics they
            belong to. Access is read-only (<code>read:jira-work</code>,{" "}
            <code>read:jira-user</code>), plus <code>offline_access</code> so a
            sync can run without you signing in to Atlassian again.
          </li>
          <li>
            <strong>What you give us:</strong> résumés and job postings you
            upload and the text read from them, answers to the questions the
            Advisor asks, the places you want to work, and the plans and
            résumés generated for you.
          </li>
          <li>
            <strong>Your AI provider key:</strong> stored encrypted and never
            shown back — only its provider, model and last four characters.
          </li>
        </ul>
        <p>
          We do not use advertising, analytics or tracking scripts, and we do
          not sell or share your data with anyone for their own use.
        </p>
      </Section>

      <Section title="How we use it">
        <p>
          Only to build your strength report, role map, gap plan and tailored
          résumés, and to keep your account working. Every analysis runs on{" "}
          <strong>your own AI provider key</strong>: the evidence it needs is
          sent to the provider you chose, under that provider’s terms, and
          nowhere else. For each AI call we record its size and cost, not its
          content; what it produces is kept as your reports.
        </p>
      </Section>

      <Section title="Where it is kept and how it is protected">
        <ul>
          <li>
            Your data is stored in a database and in object storage hosted by
            DigitalOcean. Background processing — syncing your accounts and
            reading uploaded files — runs on a separate machine that reaches
            the database over an encrypted private network.
          </li>
          <li>
            Every connection to CareerPolaris is encrypted with TLS. The access
            tokens GitHub and Atlassian give us, and your AI key, are encrypted
            at rest and opened only for the call that needs them.
          </li>
          <li>
            Each account’s data is separated by row-level security in the
            database, so one account’s request cannot read another’s rows. The
            job-board crawler has no access to user data at all.
          </li>
        </ul>
      </Section>

      <Section title="How long we keep it, and how to remove it">
        <ul>
          <li>
            <strong>Disconnecting GitHub or Jira</strong> (under Sources)
            deletes its access tokens and every fact gathered from it. Reports
            already generated from those facts stay as they are until you run a
            new analysis or regenerate them. You can also revoke our access on
            GitHub or in your Atlassian account settings at any time.
          </li>
          <li>
            <strong>Deleting a résumé</strong> deletes the file and the facts
            read from it. An uploaded job posting’s file is deleted once its
            text has been read.
          </li>
          <li>
            <strong>Deleting your account:</strong> there is no button for it
            yet. Write to {contact} from your account’s address and we will
            delete your account and everything stored for it.
          </li>
          <li>
            You can also ask us at {contact} for a copy of the data we hold
            about you, or to correct it.
          </li>
        </ul>
      </Section>

      <Section title="Cookies and browser storage">
        <p>
          We set one cookie to keep you signed in (httpOnly, sent only to us),
          and a short-lived one while a Google sign-in is in progress. Your
          browser’s local storage remembers which role you are targeting in
          the Advisor. Nothing else is stored in your browser.
        </p>
      </Section>

      <Section title="Changes">
        <p>
          If this policy changes, the new version is published here with a new
          effective date.
        </p>
      </Section>
    </main>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginTop: 32 }}>
      <h2 style={{ fontSize: 22, marginBottom: 8 }}>{title}</h2>
      {children}
    </section>
  );
}
