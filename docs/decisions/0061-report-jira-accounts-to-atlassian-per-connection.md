# 0061. Each Jira connection reports its Atlassian account, with the app owner's token

**Status:** Accepted — 2026-10-09.

## Context

A Jira connection stores personal data from Atlassian:

- the person's name and email, as the connection's account;
- the issues and epics they finished, as evidence on their profile.

To let anyone other than its owner authorise the Jira OAuth 2.0 (3LO) app,
Atlassian requires the app to be shared and its personal data declared. An app
that declares it stores personal data must implement the **personal data
reporting API** (Atlassian's user privacy guide for app developers):

- **What a report sends.** Each account we hold data about is named by its
  `accountId`, with when we last fetched its data, to
  `POST https://api.atlassian.com/app/report-accounts/`. Up to 90 accounts go
  in one request.
- **How often.** Once a cycle: 7 days, unless a `Cycle-Period` header names
  another. Never more often than that per account.
- **What comes back.** 204 means nothing to do. 200 lists the accounts that
  were `closed` or `updated`, and a closed account's data must be erased.
- **Which token sends it.** Atlassian recommends the token of the account that
  owns the app.

Two things in this codebase shape how it can be done:

- **Row-level security.** Every connection lives in an owner-zone table under
  row-level security. No job can list every user's Jira connection, by design.
- **Tokens expire.** Atlassian's access tokens last an hour, and the refresh
  tokens rotate. They had never been refreshed, so the same change fixes that
  first.

## Decision

**Each Jira connection reports itself.** `profile.report_jira_account(owner_id)`
runs on the worker's `sync` queue, as that owner.

1. It reads the user's connection, which now keeps the Atlassian `accountId`
   (`external_account_id`, migration 0046) from `/myself` at connect and at
   every sync.
2. It reads the Jira connection of the account named by
   `JIRA_REPORTING_OWNER_ID`, the operator's own CareerPolaris account
   connected with the Atlassian account that owns the app. It refreshes that
   token if it is about to expire.
3. It sends one account: `{accountId, updatedAt}`, where `updatedAt` is the
   connection's `last_synced_at`.
4. It acts on the reply:

   | Reply | Action |
   |---|---|
   | `closed` | `disconnect`: the tokens and every Jira fact go, and the reports end. |
   | `updated` | A sync, which costs no AI and replaces our copy. |
   | 204 | Nothing. |
   | 429 | The next report waits for `Retry-After`. |

5. It queues the next report after the cycle (`Cycle-Period` when it is a
   number of seconds, otherwise 7 days), plus up to 15 minutes of jitter.

**The chain is hard to lose.**

- Every Jira sync also queues a report a cycle out. A queueing lock per user
  (`profile.report_jira_account:<owner_id>`) refuses a second while one waits,
  so connecting starts the chain and a lost chain is re-armed at the next sync.
- A report that cannot be sent is tried again a day later, never dropped.
  That covers Atlassian failing, the operator's connection missing or
  refused, or a connection made before the `accountId` was kept. Each such
  case logs a WARN or an ERROR.
- Only a connection that is gone ends its reports.

**`JIRA_REPORTING_OWNER_ID` is optional.** Blank turns reporting off: each
report logs `account_report.off` and tries again a day later. That way the
release can ship before the operator has an account in production to name.
The worker needs it; the api does not read it.

The reporting kit lives in `profile`:

- `domain/account_report.py` holds the rules from reply to decision.
- `infra/account_report.py` holds the HTTP client.
- `wiring/queue.py` queues the next step, as it does for `rolemap.await_market`.

## Consequences

Easier:

- **The app can be shared truthfully.** It declares the personal data it
  stores and meets Atlassian's terms for it.
- **A closed Atlassian account's data leaves.** It goes within a cycle, along
  the existing disconnect path, which is already tested.
- **Nothing crosses users.** RLS stays as it is: every read is one owner's,
  in that owner's transaction.
- **No new deployable, port or credential store.** Everything runs in the
  worker on the compute machine.

Harder:

- **One request per account, not 90.** At this scale that is a few requests a
  day. Thousands of Jira users would want batching, which needs a way to list
  accounts across owners that RLS deliberately does not give.
- **Every report depends on one person's connection.** The operator's Jira
  connection is a single point of failure. If it is disconnected, revoked or
  left unused until its refresh token expires, every report fails, logging
  `account_report.no_reporting_connection` or `account_report.failed` daily,
  until it is reconnected. Reports are retried, not lost, but nothing is
  reported meanwhile.
- **That person's account is special.** Deleting it, or disconnecting its
  Jira, stops reporting for everyone. Nothing in the UI says so; this record
  and `docs/deploy.md` do.
- **A queueing lock is a Procrastinate feature.** Moving off Procrastinate
  means finding another way to keep one report waiting per user.
- **Each connect and sync makes two more Jira calls.** The accessible
  resources and `/myself` are read once more, for the `accountId`.
- **The `Cycle-Period` format is a guess.** Atlassian does not document it. A
  value that is not a number of seconds falls back to 7 days, which may be
  more often than asked, never less.

## Alternatives considered

- **Declare that we store no personal data,** after dropping the name and email
  from the account. Lost: the issues and epics are information about an
  identified person, and Atlassian's definition of personal data is that
  broad. The declaration would be untrue.
- **One periodic job that batches every account.** Lost: it must read every
  user's connection. That means a role that bypasses RLS, or a security-definer
  function exposing owners and accountIds across users, to save requests we
  do not yet need to save.
- **Report with each user's own token.** Lost: Atlassian recommends the app
  owner's. A closed account's token stops working, so it could never be told
  that account was closed.
- **A separate platform credential with its own sign-in flow.** Lost for now:
  it needs a second OAuth callback, a new secret store and a screen to drive
  it. The operator's ordinary Jira connection does the same job. It is worth
  revisiting if the single point of failure above starts to bite.
