# 0022. Make a Target a role, plus an optional opening in it

**Status:** Accepted — 2026-09-29. Amends [0005](0005-resolve-targets-in-their-own-module.md). Amended by [0030](0030-aim-at-a-posting-of-your-own-instead-of-adding-a-custom-role.md).

## Context

ADR 0005 put Targets in their own `target` module. A Target was a kind plus one
reference: a matched posting, a subscribed role (removed by ADR 0019), or a
pasted JD. `gapplan.plan` and `resume.resume` stored the kind and one of several
reference columns. `TargetService.options()` listed every Target for pickers,
and the Advisor offered a row of chips, one per opening in the selected role.

The v3 design (domain decision 26) opens every Advisor page with "Your target
role": one role, "at {company} · {location} · {posting}" when an opening was
picked, and a "Change role" link back to the role map, the only picker. A pasted
JD is no longer a Target of its own: it belongs to the custom role it came with
(ADR 0021).

## Decision

- **`TargetRef(role_id, job_posting_id=None)`** in `target/domain/snapshot.py`.
  The role is one of the user's roles, recommended or custom; the opening is a
  shared posting in it. `TargetKind` is gone.
- **Requirements come from the most specific source the Target has.** A custom
  role with a JD is measured against that JD, `basis = "posting"`. Any other
  role is measured against the role's requirements, `basis = "role"`. Both are
  read by the role-map build, and the fit is the role's. So resolving a Target
  never spends the user's key, and the lazy scoring of a pasted JD in
  `assessment` is removed (`fit_for_private_posting`, `estimate_private_fit`, the
  `posting_requirements` template), along with `includes_scoring` on the
  estimate.
- **An opening narrows the title, company and fit shown**, but not the
  requirements. Reading a single posting's own requirements is not built. It
  would need a fit stored per posting. This deviates from the order domain
  decision 26 lists, and is recorded here rather than faked.
- **`TargetService.options()` and `GET /targets` go.** `GET /matched-postings`
  takes `role_id`, which gives the openings the Advisor can name in a role.
- **Storage.** Plans and résumés hold `role_id` (not null, indexed) and a
  nullable `job_posting_id`, with the snapshot's reference in the same shape.
  Migration 0016 moves every row: an opening keeps its posting and takes the
  role its snapshot was frozen from; a pasted JD points at the custom role
  migration 0015 made from it. Rows whose role cannot be found are deleted, and
  the migration logs how many. `PlanDrafted` and `ResumeTailored` carry
  `role_id` instead of a kind.
- **The SPA.** The hash carries only `?role=` and an optional `&opening=`;
  `?jd=` is gone. Picking a row of "Top matched openings" selects that opening,
  and the sticky bar reads "Target this opening". The Advisor shows the "Your
  target role" banner with fit, band and "Change role", and no chips. Plan
  history and saved résumés are listed by their labels, role · company, and
  revisiting one moves the Advisor to its role and opening.

## Consequences

Easier:
- One picker, on the role map, and one thing every Advisor number is about.
- Resolving a Target is free: whatever was read or scored, the build paid for.
- A plan or résumé survives a posting expiring: its role remains, and so does
  its snapshot.

Harder:
- An opening is measured against its role's requirements, not its own, so two
  openings in one role share a fit breakdown until per-posting requirements are
  built.
- A Target for a role the user removes, or one that reclustering retires,
  cannot be resolved again. Its plans and résumés keep their snapshots but
  cannot be regenerated until the user picks a role on the map.
- Old plans aimed at a posting whose snapshot was never taken (a failed draft)
  are deleted by the migration.

## Alternatives considered

- **Keep `kind` and add `role` as a third kind.** Lost: two ways to name the
  same Target, and the Advisor would still need a picker to choose between
  them.
- **Read each opening's own requirements when it is targeted.** Lost for now:
  it spends the key at aim time, needs a fit stored per posting, and the
  prototype shows the opening's fit, not a separate breakdown. It stays open
  as a later step.
- **Store the opening only, and derive the role from it.** Lost: a custom role
  often has no opening at all, and an opening can move between roles on a
  recluster.
