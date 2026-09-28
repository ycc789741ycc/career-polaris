# 0014. Page every list response, with `page`, `page_size` and `total`

**Status:** Accepted — 2026-09-28.

## Context

Every list endpoint returned a bare JSON array.

- A client could not ask for part of a list, or learn how long it was without
  fetching all of it.
- The lists that grow with use would keep growing in one response: evidence
  with every sync, assessment history with every analysis, uploads, pasted
  JDs and saved résumés.
- The design guideline asks for "one response envelope and pagination
  params across all endpoints".

ADR 0013 had just put every response behind a schema, so the envelope could
be added in one place.

## Decision

- **Every `GET` list endpoint answers with a page**:
  `{"items": [...], "page": 1, "page_size": 20, "total": 57}`.
  - `total` counts the whole list, not the page.
  - A page past the end has empty `items` and still carries the real `total`.
- **The same two query parameters on every list**, from one dependency
  (`api.dependencies.Paging`):
  - `page` is 1-based.
  - `page_size` runs from 1 to 100.
  - **An omitted `page_size` returns the whole list** on page 1, with
    `page_size: null`. Asking for page 2 of the whole list is a 422 in the
    usual envelope.
- **Each list has a named schema**, such as `RolePage(Page[Role])`. The
  OpenAPI document and the SPA then see `RolePage`, not `Page_Role_`.
- **Where the page is cut depends on how the list is made.**
  - *In the store* (`get_list` with `page`/`page_size`, then `get_count`, in
    the same transaction), for a list read straight from one repository that
    nothing else in the application reads whole. That covers evidence (a new
    `ProfileService.evidence`), assessment history and uploaded résumés.
  - *In memory, in the service* (`kernel.paging.paginate`), for a list the
    use case builds after reading. Paging in SQL would cut the wrong rows:
    - plan history keeps each Target's latest;
    - saved résumés re-sort by `updated_at`;
    - questions turn to oldest-first.
  - *In the route*, for a list other components read whole, where changing
    the service's return type would touch every caller for no gain:
    - fits, roles, watched roles, pasted JDs, matched postings and Targets;
    - connectors and markets, which the route assembles itself.
- **`/matched-postings` drops `limit` for `page_size`.** The top ten is
  `page_size=10`, and `total` is how many openings matched.
- **Requests that change a list are not list reads.** Adding or removing a
  market still answers with the saved set as a plain array.
- **The SPA reads a list through `api.items<RolePage>(path)`.** It is typed by
  the generated page, so a list call can no longer compile against the wrong
  shape.

### Deviations from the design guideline

- The guideline names the parameter `limit`. This uses **`page_size`**, the
  name the repository contract (ADR 0011) and `kernel.paging` already use,
  so a query parameter reaches `get_list` under one name.
- The guideline says "user-facing lists that grow without bound pass a
  `page_size`". This API **returns the whole list when none is given**.
  - The screens today need whole lists: the role map, the radar, the evidence
    ledger. Every one of them would otherwise have to ask for the maximum.
  - The cost is that a client can still ask for everything. `page_size` is
    capped, but its absence is not.

## Consequences

Easier:

- One shape and one pair of parameters for every list. A client can page any
  list and show "3 of 57" without fetching all 57.
- The lists that grow have a way not to. A screen that pages evidence costs
  the database one page and one count.
- `test_openapi.py` fails if a `GET` list ever returns a bare array again.

Harder:

- Every client unwraps `items`. The SPA does so in one helper, but any other
  consumer has to change.
- `total` costs a `COUNT` beside every store-paged read.
- Paging in memory or in the route still reads the whole list; it only sends
  less.
  - That is bounded per user: at most k roles, one fit per role, a handful of
    connectors.
  - It is not bounded for watched roles and pasted JDs. If those grow, they
    move to store-paging, and their internal callers change with them.
- Returning everything by default means paging is opt-in. A new screen that
  forgets `page_size` gets the whole list, as before.

## Alternatives considered

- **A default page size (20) with a maximum of 100.** Every list is bounded,
  which fits the guideline better. It lost because every current screen needs
  the whole list: each would have had to pass `page_size=100` and page past
  it if a user ever exceeded that, which is more code than the problem
  warrants today.
- **Cursor (keyset) paging.** It is stable under inserts and needs no count.
  It lost for now: the lists are per user and small, the SPA shows totals,
  and `get_list` already speaks in pages (ADR 0011).
- **Headers (`Link`, `X-Total-Count`) with the body left as an array.** This
  keeps bodies unchanged, but the generated client does not type headers, so
  `total` would be untyped again, and the guideline asks for an envelope.
- **Paging only the lists that grow.** Fewer changes, but it gives two list
  shapes, and a client has to know which list is which.
