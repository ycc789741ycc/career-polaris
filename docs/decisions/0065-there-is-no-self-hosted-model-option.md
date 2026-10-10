# 0065. There is no self-hosted model option; only an OpenAI key may name a base URL

**Status:** Accepted — 2026-10-11.

## Context

AI settings offered four providers: Anthropic, OpenAI, Google and "Local", a
model the user runs themselves at a base URL they supply. The idea was a
model on the user's own hardware, at no cost.

CareerPolaris is a hosted service. Every AI call is made by the api or the
worker, on the droplet or the operator's machine, never from the user's
browser. A model on the user's laptop or home network cannot be reached from
there, and the SSRF guard (`kernel.fetch`) refuses private addresses on
purpose. So "Local" worked only if the user exposed their model on the public
internet, which few would do and none should be nudged into.

It also had costs:

- **A provider we can't price.** Every local call fell back to the
  pessimistic rate, so it inflated the user's own cap.
- **Special cases in the code.** Its adapter didn't ask for stream usage, so
  every call was recorded as an estimate. It needed a "required base URL"
  rule, and an empty suggested-models list.

A base URL still has a real use: an OpenAI-compatible cloud (Azure OpenAI,
Groq, Together) speaks OpenAI's wire format at an endpoint of its own.

## Decision

- **Three providers: Anthropic, OpenAI and Google.** `Provider.LOCAL`,
  `LocalProvider` and the rule that a local credential needs a base URL are
  gone. `"local"` is now an unknown provider.
- **Only an OpenAI key may name a base URL** (`accepts_base_url`). It is
  optional, checked by the SSRF guard when saved and again on every call, and
  shown in AI settings only for OpenAI. A base URL for any other provider is
  refused.
- **Migration 0051 enforces both in the database.** It deletes stored `local`
  credentials, clears any base URL on a non-OpenAI credential, and adds
  `ck_provider_credential_provider` and `ck_provider_credential_base_url`.

## Consequences

Easier:

- Every provider we offer is one we can call and price, and the settings
  screen offers nothing that can't work.
- The OpenAI adapter always asks for stream usage, so its calls are recorded
  with the provider's counts.

Harder:

- **Users with a local credential lose it.** They are asked for a key again,
  as before they first set one. Their AI settings say no key is set, and work
  that needs AI says to add one.
- **A self-hosted model is out of reach,** even for someone willing to expose
  it publicly. They can still reach one through an OpenAI-compatible endpoint
  on a public URL, under the OpenAI provider.
- **Models behind an OpenAI-compatible cloud are usually unpriced.** Their
  calls take the unpriced-model path.

## Alternatives considered

- **Keep "Local" for models exposed on the public internet.** That's an
  OpenAI-compatible base URL under another name. Keeping both would mean two
  ways to say the same thing, and a label that promises something the service
  can't do.
- **Drop the base URL as well.** That would be the smallest surface, with no
  user-chosen URL our servers call. But it would shut out the
  OpenAI-compatible clouds, which are a real use.
- **Call the user's model from their browser.** Every call runs in the
  worker, often as a background job while the user is away, and goes through
  the gateway's budget, ledger and output validation. A browser-side path
  would bypass all of that.
