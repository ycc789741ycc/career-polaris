# 0034. Add a role of your own without spending anything, and evaluate it when it is set as the target

**Status:** Accepted — 2026-10-07. Amends [0030](0030-aim-at-a-posting-of-your-own-instead-of-adding-a-custom-role.md) and [0033](0033-keep-a-posting-of-your-own-in-target.md).

## Context

ADR 0030 and ADR 0033 made a posting of the user's own a Target. In both, the
user adds it with a title, an optional company and a required JD, pasted or
uploaded. Adding it shows a cost, and the confirmation queues the run that
reads the JD's requirements and scores the fit. "Aim the Advisor at it" is a
second step, after the run.

The 3 Oct 2026 prototype (`prototype/screens/CustomTarget.dc.html`, domain
spec §6.0) changes this flow:

- "Your role" offers two ways in, side by side: upload the job description
  (a file drop zone only), or fill the role in by hand. Filling in takes a
  job title, an optional company and an optional list of what the role asks
  for. With nothing listed, the Advisor infers typical requirements for the
  title and marks them as estimates.
- "Add to my roles" only adds the role to a list. It runs no analysis.
- "Set as target" compares the role with the user's strengths, at a cost
  shown first. It replaces the current target and opens Fill the gap.

So money is spent only on a role the user actually aims at. A user who keeps
a few roles in the list pays for none of them until they choose one.

## Decision

Adding a posting of the user's own stores it and spends nothing. Setting it
as the target evaluates it.

- **Two ways in.**
  - `POST /own-postings` takes `{title, company_name?, requirements: []}`:
    a role filled in by hand, `source = 'filled_in'`. What it asks for is
    stored as its JD, one requirement per line. With none listed,
    `job_description` is null and `has_estimated_requirements` is set.
  - `POST /own-postings/upload` takes the file, with `title` now optional.
    Without one, the posting is named after its file (`has_placeholder_title`).
    When the file is read, it takes the job title the requirement extraction
    reads out of it.
  - Pasting a JD is no longer taken. Pasted postings already stored keep
    `source = 'pasted'` and work as before.
- **Nothing is queued on add.** Neither route prices anything or records a
  `PostingEvaluation`, and neither needs an analysis.
- **Set as target.** The cost is shown first. It records the run that
  reads, if not read yet, and scores, and the SPA then opens Fill the gap
  aimed at the posting.
  - `GET /own-postings/{id}/target-estimate` prices it. The price is the
    projection, plus reading the requirements when none are stored yet. An
    unread file is priced as a ceiling, as before.
  - `POST /own-postings/{id}/target` records the run.
  - When the fit is current — scored, and not stale against the latest
    analysis — the estimate is `0`, nothing is queued, and the SPA aims at
    the posting without asking. A run already going is joined. This
    replaces `/rescore` and `/rescore-estimate`: a stale fit is rescored by
    setting the posting as the target again.
- **Estimated requirements.** A role with nothing listed has its
  requirements estimated from its title. This is one call on the user's key,
  through the role map's fit kit: `RoleMapService.infer_requirements`, with a
  new template `typical_requirements.v1`. It has the same output schema as
  `role_extraction` and the title is fenced as untrusted. The Advisor's
  banner says the requirements are estimated.
  `RoleMapService.extract_requirements` now also returns the name the model
  read (`RequirementsReadView`), which an untitled upload takes.
- Migration 0032 adds `has_placeholder_title` and
  `has_estimated_requirements` (both default false), allows
  `source = 'filled_in'`, and lets a filled-in posting with estimated
  requirements have no JD. Rows already stored are untouched.
- In the SPA, "Use your own role" is an Advisor tab of its own
  (`#/advisor/own`), reachable with or without a target. The "Your target
  role" banner offers it beside "Pick from role map".

## Consequences

Easier:

- Nothing is spent on a role until the user aims at it. Adding several roles
  to compare later costs nothing.
- A user with only a job title can still plan for it. No JD needs to be
  found and pasted first.
- One endpoint makes a posting ready to aim at, whether it was never read,
  is stale, or failed. A current one costs nothing and asks nothing.

Harder:

- Aiming at a role of your own takes one more wait. The read and score run
  after "Set as target", so Fill the gap opens on a "Reading and scoring…"
  state instead of straight away.
- Estimated requirements are only as good as the model's idea of a typical
  posting for the title. Plans and résumés measured against them say less
  than ones measured against a real JD. The banner says so, but nothing else
  in the plan or résumé does.
- An uploaded file is unnamed until it is read. Until then the list shows
  its file's name, which may say nothing about the job.
- Pasting a JD as text is gone. A user who has the text but no file has to
  save it as a `.txt` first, or list its requirements by hand.
- Clients of the removed routes break: `POST /own-postings` with
  `job_description`, `/own-postings/cost-estimate`, `/upload-estimate`,
  `/rescore-estimate` and `/rescore`. The SPA is the only client.

## Alternatives considered

- **Keep evaluating on add.** This was simplest, and the flow ADR 0030
  shipped. It lost because it spends the user's key on every role they add,
  aimed at or not, and it contradicts the prototype, where adding runs
  nothing.
- **Keep the JD required, and only defer the evaluation.** This avoids
  estimated requirements and the new prompt. It lost because the prototype
  lets a user plan for a role they can only name. Requiring a JD would turn
  away exactly the user who has no posting to paste.
- **Have the user type a title for an upload.** This avoids taking the name
  from the extraction. It lost because the prototype's upload side is a drop
  zone only, "one is enough". The extraction already reads a name, so taking
  it costs nothing extra.
- **Keep pasting beside uploading.** It lost because the prototype has no
  paste box: its fill-in side lists requirements instead, which covers the
  same need without asking for a whole posting.
