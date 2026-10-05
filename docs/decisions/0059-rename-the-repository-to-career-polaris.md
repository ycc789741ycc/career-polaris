# 0059. The Git repository is called `career-polaris`

**Status:** Accepted — 2026-10-05. Amends [0056](0056-rename-everything-inside-to-careerpolaris.md).

## Context

ADR 0056 renamed everything inside the code base to CareerPolaris but kept the
Git repository's name, `job-searching-advisor`, since renaming it belongs to
GitHub and to every clone's remote rather than to the code base. That left the
one name a person meets first, the repository, still the old one.

## Decision

The repository is renamed to `career-polaris`, on GitHub
(`ycc789741ycc/career-polaris`) and in the local checkout's directory. This
replaces 0056's "The Git repository keeps its name"; the rest of 0056 stands.

- **The README and `CLAUDE.md` no longer name an exception:** the old name
  survives only in history.
- **History keeps the names it was written with,** as 0056 says: accepted
  ADRs, past phases in `docs/plan.md` and the drawings still say
  `job-searching-advisor`.

## Consequences

Easier:

- One name everywhere, the repository included, with no exception to explain.

Harder:

- **Every other clone must update its remote** with
  `git remote set-url origin git@github.com:ycc789741ycc/career-polaris.git`.
  GitHub redirects the old URL for now, but the redirect ends the day anyone
  creates a new repository named `job-searching-advisor` under the account.
- **Links to the old URL** in places outside the repo (bookmarks, notes,
  issues elsewhere) rely on that same redirect.

## Alternatives considered

- **Keep the old repository name (0056 as written).** Lost because the
  repository has in fact been renamed; the docs would describe a state that
  no longer exists.
