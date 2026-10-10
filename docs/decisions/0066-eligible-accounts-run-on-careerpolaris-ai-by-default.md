# 0066. Eligible accounts run on CareerPolaris AI by default, and its model is never named

**Status:** Accepted — 2026-10-11. Amends 0064.

## Context

ADR 0064 offered CareerPolaris's own AI key to Google-verified accounts. To
use it, the user had to switch to it in AI settings and accept a data notice
the first time. With no choice made, their own key ran if they had stored one,
and nothing ran if they hadn't.

That made the free option the hard one to reach. A new user signing in with
Google, who is exactly the person it was meant for, met a settings page about
API keys before anything worked. The page also showed the key form and a
dollar budget to people on the platform's key, which neither applied to. And
it named the platform's model, which is an operator's detail that can change
under them.

## Decision

- **With no choice made, an eligible account runs on CareerPolaris AI** while
  the platform is on (`get_source_in_use`). Otherwise it runs on the user's
  own key, if they stored one.
- **No terms step.** Choosing CareerPolaris AI switches at once.
  `accept_platform_terms`, `has_accepted_platform_terms` and
  `ai_source_choice.platform_terms_accepted_at` are gone. Where the user's
  evidence goes is said where they use it, as a standing line under the
  quota in AI settings.
- **Storing a key chooses it.** `set_credential` sets the source to `own`.
  Migration 0053 gives every account that stored a key before this, and made
  no choice, an `own` choice, so no one is moved off their key by the new
  default.
- **AI settings asks first which AI runs the work**, then shows only what
  that one needs:
  - for CareerPolaris AI, the free quota as a percentage;
  - for their own provider, the key form and the monthly budget.
  
  A stored key stays stored while the platform runs, so switching back needs
  nothing typed again.
- **The platform's model is never named.** It isn't sent to the client
  (`AiSourceBody` has no `platform_model`). AI settings, the sidebar, the
  header, the running bar and every cost estimate say "CareerPolaris AI"
  (`modelName`, `getShownModel`, `chargedTo`). Work already finished keeps
  the model id it recorded.

## Consequences

Easier:

- A Google user can analyse their evidence straight after signing in, with
  nothing to set up.
- Each user sees settings for the AI they actually use, and no dollar budget
  that doesn't bind them.
- The operator can change the platform's model without users seeing their
  tool change.

Harder:

- **More of the operator's money is spent by default.** Every eligible
  account draws on the quota until it brings its own key, so the ceilings
  (ADR 0064) matter more, and `make platform-ai-usage` deserves a look after
  launch.
- **Users no longer explicitly agree where their evidence goes.** They are
  told, on the settings page and in the privacy policy. They don't tick a
  box.
- **A finished plan or résumé can still name the platform's model** in its
  "Drafted by …" line, because it recorded the model id. Hiding that too would
  mean recording on every artifact which key paid.

## Alternatives considered

- **Keep the opt-in with the terms checkbox (ADR 0064 as it was).** It is the
  most explicit about data, but it puts setup in front of the free path for
  the very users the free path is for.
- **Default every account to the platform, including existing key holders.**
  That would quietly move people off the key they chose to store. Migration
  0053 gives them an explicit `own` choice instead.
- **Hide the model on finished work too.** That needs a funding column on
  every artifact and its own migrations. The settings, shell and estimates
  are where a user decides; finished work only reports history.
