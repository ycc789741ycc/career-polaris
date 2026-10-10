# 0064. Google-verified accounts may run AI on the platform's key, under a quota

**Status:** Accepted — 2026-10-10.

## Context

Every AI call has run on the user's own provider key since the start
(`CLAUDE.md`: "All AI runs on the user's own provider key"). That keeps the
operator's bill at zero, but it also means nobody can see what the product
does until they have opened an account with a model provider and pasted a key.

Offering the operator's own key changes who pays. Three things follow from
that:

- **Our sign-up proves nothing.** Addresses are not verified (ADR 0001), and
  `SIGNUPS_PER_ADDRESS_PER_DAY` (ADR 0054) only slows a script down. A quota
  per account is worthless if accounts are free to make.
- **The ledger was not good enough to meter money.** Streamed calls were
  recorded from character counts, and dated model ids were priced at the
  fallback rate. Phase 13's first step fixed that before anything here was
  built.
- **Check-then-record overshoots.** Two jobs running at once can both pass a
  check, and one check covered up to three attempts. That is tolerable when
  the money is the user's and the cap is theirs, but not when it is ours.

## Decision

- **Two ways to pay, chosen per account.** A call runs on the user's own key
  or the platform's (`Funding.OWN`, `Funding.PLATFORM`), and the user may
  switch between them at any time in Settings. Funding is decided per call,
  so a running job whose user switches finishes on the new source. A failed
  key never falls back to the other source.
- **The gateway holds the platform's key.** `CredentialStore.load` returns
  either the user's encrypted credential or a `PlatformCredential` marker.
  The gateway then takes the provider, the model and the key from settings
  (`PLATFORM_AI_PROVIDER`, `PLATFORM_AI_MODEL`, `PLATFORM_AI_API_KEY`). A blank
  key turns the feature off.
- **One model, priced.** The operator picks the model and users cannot. It
  must have a published rate in `pricing.json`, or the api and worker refuse
  to start, because a guessed rate would make every quota wrong.
- **Only Google-verified accounts are eligible.** An account qualifies if it
  has a Google identity (`identity.federated_identity`). That is checked on
  every call, not just when the user switches.
- **Our key failing is not the user's fault.** A provider refusing the
  platform's key logs `ai.platform_key_failed` and answers
  `ai_platform_unavailable` (503). The user's credential, their paused-jobs
  flag and their budget are left alone.
- **Every ledger row says who paid** (`identity.ai_usage_ledger.funding`,
  migration 0048). The user's monthly cap counts only `own` rows: it guards
  their money, not ours.
- **The platform's spend is reserved, then settled** (Phase 13, step 3).
  - The reservation is a ceiling: every retry at its full output limit.
  - It is held per account per month, and for the whole platform per UTC
    day and per month, in `limits`.
  - A call whose ceiling exceeds `PLATFORM_AI_MAX_CALL_USD` is refused
    outright.
- **The provider's own spend limit is the last line of defence.** The key
  comes from a provider project of its own, with a hard monthly limit set
  there (`docs/deploy.md`).

## Consequences

Easier:

- Someone can try the product without a provider account, and decide later
  whether to bring a key.
- The ledger now holds real figures and who paid them, so spend can be
  reported per task and per source.

Harder:

- **The operator pays for AI, and abuse can run up the bill.** The ceilings
  cap the loss; per-account quotas don't, because Google accounts are free
  to make too.
- **User data reaches a provider under the operator's terms.** Evidence,
  résumés and Jira issues go to the operator's provider account, not the
  user's. Settings says so before the first switch, and the user has to
  accept.
- **There is a second key to rotate, on two machines.** The api (for the
  résumé chat) and the worker both hold `PLATFORM_AI_API_KEY`. Rotating it
  means editing `.env` in both places and restarting.
- **Google sign-in now gates a feature.** It is off until there is a domain
  (Phase 12), so nobody is eligible until then.
- **A job can change source part-way through.** That happens if the user
  switches while it runs. Each ledger row says which source paid for it,
  which is how the operator can tell.

## Alternatives considered

- **A free trial for every new account.** Without verified addresses, it
  invites scripted farming of accounts.
- **Storing the platform's key encrypted in the database, edited from an
  admin console.** That would give rotation without a restart. But it adds
  an admin role, an internet-facing surface and a way around row-level
  security, all for one operator. Settings in `.env` match how every other
  secret here is held.
- **Pinning a job's source when it starts.** This would store the funding on
  every job row in every component. Deciding per call and recording it on
  the ledger answers the same question at one place.
- **Keeping check-then-record and adding a safety margin.** Any margin is a
  guess. A reservation of the ceiling is exact, and settling returns what
  the call didn't use.
- **Letting the user's own cap cover platform calls as well.** The cap is a
  limit the user sets on their own money. Spending against it from our key
  would make their own calls fail early for no reason they could see.
