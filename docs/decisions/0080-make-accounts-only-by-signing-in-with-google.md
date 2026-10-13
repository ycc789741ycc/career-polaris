# 0080. Make accounts only by signing in with Google, and offer a password only while Google is off

**Status:** Accepted — 2026-10-13. Amends [0001](0001-run-our-own-email-password-sign-in.md), [0008](0008-sign-in-with-google-by-our-own-oidc-exchange.md) and [0054](0054-limit-each-account-and-each-sign-up-address-in-postgres.md).

## Context

Anyone could make an account with an email address and a password
(`POST /auth/register`, ADR 0001). Those addresses are never verified, because
there is no email delivery, and a forgotten password cannot be reset. A
password account also cannot use CareerPolaris AI, which needs a Google
identity (ADR 0064). Google already proves the address, takes over a password
account at it (ADR 0008), and is what new users are steered to. Only the
per-address sign-up limit (ADR 0054) stood between a script and as many
unverified accounts as it liked.

## Decision

- **No account is made with a password.** `POST /auth/register`,
  `AuthService.register`, the password-strength policy
  (`assert_acceptable`, `MIN_PASSWORD_LENGTH`) and the "Create an account"
  mode of the sign-in screen are gone. Signing in with Google is the only way
  an account is made.
- **The password form shows only while Google is off.** `GET /auth/methods`
  says `password: true` only when `GOOGLE_OAUTH_CLIENT_ID` is blank; the
  sign-in screen then shows the email form and no Google button, and
  otherwise Google alone. It offers nothing until `/auth/methods` answers.
- **`POST /auth/sign-in` still answers on every machine.** Hiding the form is
  the SPA's choice, not a refusal: an account made before this keeps its
  password, its lockout and its sessions until its owner continues with Google
  at the same address, which removes the password (ADR 0008).
- **No sign-up limit.** `SIGNUPS_PER_ADDRESS_PER_DAY` and the `signups` limit
  are removed, because no request makes an account without Google.

## Consequences

- Easier: every new account has an address Google verified and can use
  CareerPolaris AI; there is no password to forget for anyone new, and one
  fewer limit and setting to run.
- Harder: a machine without a Google client — the droplet until it has a
  domain, or a fresh local checkout — can make no account at all; only
  accounts that exist sign in there. A developer needs a Google OAuth client
  with the localhost redirect (`.env.example`) to make one.
- Harder: a person without a Google account cannot use CareerPolaris.
- Harder: Google sign-in now makes accounts with no per-address limit of our
  own; we rely on Google's own account checks, and the edge's per-address
  request limits (ADR 0053), to slow a script.
- The password tables, hashing and lockout stay for the accounts that still
  have one, and are not reachable from the screen while Google is on.

## Alternatives considered

- **Remove password sign-in too.** Locks out every existing password account
  on a machine where Google is off, which is the droplet today. Lost.
- **Refuse `POST /auth/sign-in` while Google is on.** Forces existing users to
  Google at once, but the user asked only that the form be hidden, and the
  takeover already moves them over the first time they continue with Google.
  Lost.
- **Make Google configuration required at start.** Keeps the code simpler, but
  the droplet cannot run until there is a domain. Lost.
- **Keep registration behind a setting.** One more mode to test and explain,
  for a path no deployment should use. Lost.
