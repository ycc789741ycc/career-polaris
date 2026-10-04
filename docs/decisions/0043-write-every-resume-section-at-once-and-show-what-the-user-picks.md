# 0043. A résumé writes every section at once, and the user picks which to show

**Status:** Accepted — 2026-10-12.

## Context

ADR 0039 made a résumé an ordered list of sections the user chooses. A new
résumé was written with summary, experience and skills. Any other section was a
priced `resume.fill_section` job, one section at a time, that the user had to
think to add.

A user who connected GitHub and Jira and uploaded no résumé got an empty
Experience section:

- **Nothing ever writes the career timeline.** `profile.career_position` has
  readers and no writer (ADR 0039 noted it), so the writer's `timeline` is
  always "(no positions recorded)".
- **`resume_write` v3 took roles only from an uploaded résumé.** It defined
  an experience entry as "one per role", `title` the role and `org` the
  employer. GitHub and Jira show the work but never a job title, so without
  `base_resume` the model followed "a section the evidence does not support is
  left empty" and left Experience empty.
- **The other kinds leaned on the résumé the same way.** Nothing told the model
  how to tell paid work from open source or a side project.
- **Only the plan's sections were written.** GitHub work that belonged in Open
  source or Side projects never appeared unless the user added those sections.

## Decision

A résumé holds every section, each shown or hidden, and generating writes them
all.

- **Every built-in kind, always.** `DEFAULT_PLAN` holds all eight built-in
  kinds. Summary, experience and skills (`DEFAULT_SHOWN`) are shown; the rest
  follow, hidden. `get_full_plan` appends any built-in kind a plan lacks, hidden,
  so a résumé written before this takes them on its next write.
- **Each section stores whether it is shown.** `Section.is_shown` lives in
  every saved version's content, so going back to a version brings back what
  it showed. `SectionSlot.is_shown` lives in `Resume.section_plan`. A slot's
  state takes no part in its equality: a section is the same section shown or
  hidden. Experience is always shown (`assert_plan_valid`). `MAX_SECTIONS` (9)
  limits what is shown; `MAX_HELD_SECTIONS` (the eight kinds plus three of the
  user's own) limits what is held.
- **Showing and hiding are free edits.** Each is a version saved through
  `POST /tailored-resumes/{id}/versions`, like moving a section: no AI call,
  nothing queued. A hidden section keeps its content.
- **Only shown sections print.** `render_html` and the preview draw
  `ResumeContent.get_shown()`. Coverage is decided by scores, not by the page,
  and is unaffected.
- **`resume_write` v4 writes every section from the evidence alone.**
  - It is given every slot in the plan, shown or not, and the connected
    accounts (`ProfileSnapshot.accounts`, from `SourceConnection.external_account`:
    the GitHub login and the Jira site), which are untrusted.
  - Experience comes from the timeline or an uploaded résumé when there is one.
    Otherwise it has one entry per place the work was done — a Jira site, a
    GitHub organisation — titled by the work unless the evidence states a job
    title, never an invented one.
  - Repositories owned by others are open source; ones under the user's own
    account that belong to no experience entry are side projects. Work lands in
    exactly one of the three.
  - Education, certifications, talks and writing come only from what the
    evidence states.
  - `expected_output_tokens` rises from 3,500 to 6,000.
- **`resume_revise` v4 sees every section.** Each section's state is shown in
  the résumé it reads. A reply's section carries `is_shown` only when the user
  asked to show or hide it; `null` keeps its state (`get_proposal_layout`). A
  built-in section the reply leaves out is kept: the chat hides a built-in
  section and removes only one of the user's own.
- **Filling from the sources is for empty sections only.**
  `POST /tailored-resumes/{id}/sections` fills a section the résumé holds that
  has no lines, and shows it, or adds one of the user's own. A section with
  lines is refused before anything is spent. `resume_section` v1 is unchanged.
- **The Sections panel lists every section.** Built-in sections have Show or
  Hide; Experience is "Required"; a custom one keeps Remove. An empty section
  offers "Fill from your sources", priced. "Add a section of your own" offers
  only "Custom…".
- **Migration 0039** adds `is_shown` to every stored plan, version and chat
  proposal: what was there is shown, and the missing built-in kinds are
  appended hidden and empty. Its downgrade drops the hidden sections, with
  anything written in them, and the flag.

## Consequences

Easier:

- A user with only GitHub and Jira gets Experience, Open source and Side
  projects written on the first Generate, and shows them with a click.
- Showing a section costs nothing and waits for nothing.
- Every section is written to the same evidence in the same call, so showing
  one later never mixes two writes.

Harder:

- Every Generate and Regenerate costs more: the estimate's output ceiling
  nearly doubles, for sections many users never show. The ceiling was set from
  the larger reply's shape, not measured on real profiles; measure it once
  there are some.
- An experience entry with no timeline or résumé names a place and the work,
  not a job title. That reads thinner than a résumé the user wrote, and the
  rule against inventing a title is only in the prompt.
- Telling open source from side projects from paid work rests on repository
  owners and the accounts given. Work in an organisation's repository the user
  contributed to as an outsider reads as experience.
- A hidden section is still content: the chat, every version and every reader
  of one walk it.
- Migration 0039 rewrites stored JSON again, as 0035 did, and its downgrade
  loses whatever hidden sections held.
- "Fill from your sources" is offered on any empty section, not only on one
  that predates this ADR. On a section the evidence already left empty it
  usually comes back empty again, at a price the user confirmed.

## Alternatives considered

- **Keep adding sections one at a time, and only change the prompt.** Lost: it
  fixes Experience but still leaves a user's open-source work unwritten until
  they think to add the section, and each addition is a separate spend.
- **Store the shown state only on the résumé's plan.** Lost: going back to an
  earlier version would show whatever the plan says now, not what that version
  showed.
- **Choose the shown sections from the evidence** (show Open source when GitHub
  has outside work). Lost: without a timeline every repository is "outside", as
  ADR 0039 found; the defaults stay predictable and the user decides.
- **Record the timeline first, and let Experience follow it.** Not instead of
  this: the timeline only helps users with an uploaded résumé or answers that
  state their positions. It is planned separately (Phase 10, "Record the
  career timeline").
