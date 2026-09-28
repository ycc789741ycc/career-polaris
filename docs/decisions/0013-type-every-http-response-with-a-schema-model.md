# 0013. Type every HTTP response with a schema model built from a component's view

**Status:** Accepted — 2026-09-28.

## Context

Data crosses three boundaries on its way to the browser, and until now only
two of them were typed.

1. **Database ↔ domain.** `infra/mappers.py` turns ORM rows into entities and
   back (ADR 0011).
2. **Component ↔ its callers.** Each `service.py` returns frozen `*View`
   dataclasses (`ConnectionView`, `PlanView`, `ProfileSnapshot`, …), never
   entities. No record said why. The reasons are in the code:
   - Entities carry what must not leave the component. `SourceConnection`
     holds encrypted OAuth tokens and `owner_id`.
   - Entities are mutable and carry rules, so a caller holding one could
     change it outside the service's unit of work.
   - Entities live in the private `domain/` behind the `*-public-surface`
     import contracts (ADR 0009).
   - Views are also where read models are put together. `ProfileSnapshot`
     combines evidence, positions and a version, and it is what `assessment`
     reads.
3. **API ↔ SPA.** About 40 handlers built `dict[str, object]` by hand, each
   mapping view fields to keys and calling `.isoformat()` and `str()` itself.
   FastAPI published those responses as `{"type": "object"}`. The generated
   `schema.d.ts` therefore held 35 `Record<string, unknown>` types.
   - The SPA did not use them. It typed its calls against 35 interfaces
     written by hand in `web/src/api/types.ts`.
   - CI's drift check (`make gen-client`, then `git diff schema.d.ts`) passed
     whatever a handler sent. A renamed field reached a screen as `undefined`.

## Decision

- **Every JSON response is a Pydantic model** in `api/schemas/<component>.py`,
  next to `api/routes/<component>.py`.
  - A handler's return annotation names the model. The existing identity
    routes already did this, rather than using `response_model=`.
  - The only exception is `/ai-providers`. It returns `dict[str, list[str]]`,
    which OpenAPI can already describe.
  - The revision chat's Server-Sent Events are built from models in the same
    module. OpenAPI cannot describe a stream, so they stay out of the
    document.
- **Schemas map from views, never from entities.** Each response model has a
  `from_view` classmethod, which replaces the per-route `_…_body` helpers. So
  the layering is: entity (inside the component) → view (the component's
  contract) → schema (the wire's contract).
- **Responses and requests have different base models.**
  - Responses derive from `ApiModel`, which is frozen with `extra="forbid"`,
    so a route that builds a body with a stray field fails in tests.
  - Requests derive from `RequestModel`, which still ignores unknown fields
    so an older client is not refused.
- **The wire format did not change.**
  - `Timestamp` serialises with `isoformat()`, keeping `+00:00` where
    Pydantic's default would write `Z`.
  - Money stays a decimal string.
  - Stored JSON (salary bands, fit gaps, plan projects, résumé content) is
    validated on its way out, so a stored shape that drifts fails loudly
    instead of going out unchecked.
- **Enumerated strings on the wire are `Literal`s**, not the domain's
  `StrEnum`s. Renaming a domain enum member then does not silently change
  the contract.
- **Every router declares the error envelope** (`ErrorEnvelope`) for 422,
  4XX and 5XX, so the generated client knows what a failure carries.
- **The SPA's types are aliases** over `components["schemas"]` in
  `web/src/api/types.ts` and `web/src/auth/session.ts`. They keep the names
  call sites already used.
- **Two import-linter contracts** (Rule 13) enforce the boundary:
  - `api.schemas` imports no kernel, framework or composition root.
  - Only `api.routes` and `api.main` import `api.schemas`.
- **A unit test** fails if any `/api/v1` response is published as a bare
  object.

## Consequences

Easier:

- The contract is checked from end to end. A renamed or dropped field now
  fails `make typecheck` in `web/` at the line that reads it, once
  `make gen-client` has run, and CI fails if it hasn't.
- One place per resource says what goes over the wire. Serialisation is done
  once, by Pydantic, instead of by hand in every handler.
- The OpenAPI document is accurate, including errors, for any other client.

Harder:

- Each resource now has three shapes to keep: entity, view and schema. A new
  field touches the view, the schema and its `from_view`, then needs
  `make gen-client`.
- The `Literal`s repeat the enum values. Adding a status means adding it in
  both places, or the response fails validation (a 500) until you do.
- Stored JSON is validated on every read. An old row with a missing key used
  to reach the client quietly; now it is a 500 until the row or the schema
  is fixed. We prefer that, but it is a new way for a read to fail.
- `CostEstimate` split into three models, one per run:
  - `CostEstimate` for the first analysis;
  - `RoleMapEstimate` for the role map;
  - `TargetEstimate` for gap plans and résumés.
  The role map's estimate used to share the SPA's `CostEstimate` type; it now
  has its own.
- Two request fields stay untyped: the résumé `content` on `VersionRequest`
  and `RevisionRequest`. Typing them would make requests stricter than the
  domain's `ResumeContent.from_dict`, which tolerates missing keys. That is a
  separate change to make deliberately.

## Alternatives considered

- **Services return entities and schemas map from those.** This drops the
  view and so one shape per resource. It lost because it hands `api/` the
  encrypted tokens and mutable entities. It would also loosen every
  `*-public-surface` contract, and read models like `ProfileSnapshot` would
  still need a type of their own.
- **Make the views Pydantic models and return them directly.** One shape
  fewer. It lost because a view's job is to be what *other components*
  consume. Tying it to the public wire means an internal change to
  `ProfileSnapshot` for `assessment` becomes an API change for the SPA, and
  the other way round.
- **Serialise the view dataclasses directly** (FastAPI accepts dataclasses).
  It lost because every view field would become public, including ones that
  exist for other components (`CoverageView.dimension_key`,
  `FitView.target_profile`). It would also keep domain enums on the wire.
- **Keep the dicts and the hand-written TypeScript types.** It lost because
  nothing checks them against each other, and that was the problem.
- **`response_model=` on the decorator instead of the return annotation.**
  It does the same thing, but it would be inconsistent with the identity
  routes, and mypy could no longer check that a handler returns what it
  declares.
