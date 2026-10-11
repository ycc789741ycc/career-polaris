# 0076. Quantify a résumé's lines only from numbers their facts state, and flag the rest

**Status:** Accepted — 2026-10-12.

## Context

"Quantify bullets with data from Jira and GitHub" was one line in the write
prompt's options — "Quantify bullets with numbers the evidence gives" — and
did little:

- The connectors gave few numbers. GitHub wrote one commit count per
  repository and one review count overall; Jira one throughput count per site
  and one per epic. None said over how long, and the 50 single commits and
  issues, which most lines cite, carry no number at all.
- Nothing said a tally was the number to use, or to cite it beside the single
  facts a line rests on.
- Only a full write read the option. The revision chat, whose own suggestion
  is "Quantify every bullet", and "Fill from your sources" never saw it.
- Turning the option on changed nothing until the next priced write, and the
  card did not say so.
- When nothing is connected, as on a profile built from an uploaded résumé
  alone, there is no GitHub or Jira number to draw on, and the option's label
  promised one.

Nothing checked a number in a written line against what the line cites, so
pushing the model harder alone would invite invented figures, the claim this
product exists to avoid.

## Decision

- **More numbers, said plainly.** Each GitHub and Jira tally says over how
  long its work ran ("142 commits authored in acme/ledger between Mar 2025
  and Sep 2026."). GitHub also counts reviews per repository, for its five
  busiest (`github:reviews:<repo>`, replaced on each sync); Jira counts a
  site's finished issues by type. All are in the fact text and `tally`; no
  schema change. They arrive with the next sync.
- **One rule on numbers in every résumé prompt.** `resume_write` v6,
  `resume_revise` v6 and `resume_section` v2 say: every number in a written
  line appears in a fact it cites, never rounded up or carried from another
  fact; a tally counts the work its subject names and may be stated with its
  span. Each reads the résumé's options (`_options_block`): with Quantify
  on, every line whose work a fact counts or measures gets that number;
  off, a number stays only where a cited fact words it so.
- **Checked, and flagged rather than dropped.** `get_unbacked_lines` finds the
  model's lines that state a number none of their cited facts states, ignoring
  separators and `%`/`+`. After every write, proposal and filled section the
  count is logged (`resume.unbacked_number`, WARN). The line is kept:
  `GET /tailored-resumes/{id}` lists them as `unbacked_lines`, and the page
  notes each under the line, never printed, for the user to check or reword.
  A line the user wrote is theirs and is never flagged.
- **The card says what the option can do.** Under Quantify, the Layout card
  says which of GitHub and Jira are connected, or that neither is and numbers
  then come only from the résumé and answers. Changing an option says it
  applies when the résumé is next written, with Regenerate beside it.

## Consequences

Easier:

- A line can carry a real, dated count from GitHub or Jira, and say over how
  long.
- An invented figure is visible to the user on the page, and countable in the
  logs, instead of silent.
- The chat and a filled section follow the same rule as a full write.

Harder:

- The check is lexical. A number restated in other words ("two" for "2"), or
  derived (a percentage worked out from two counts), is flagged although it is
  honest; a number that happens to appear in a cited fact for another reason
  passes. It flags; it does not prove.
- Old prompt versions stay on disk for the records that name them, and the
  ledger's per-prompt calibration starts again for v6/v2.
- Facts change wording on the next sync, which marks plans and résumés
  outdated by evidence once (ADR 0035).

## Alternatives considered

- **Reject a reply with an unbacked number**, as for an uncited line. Lost: it
  throws away a whole paid write over one figure, and the check is lexical, so
  it would reject honest lines too.
- **Strip the number from the line.** Lost: what is left often reads wrong,
  and the user cannot see what was claimed.
- **Count merged pull requests again.** Lost: work is counted by commit on
  purpose (squash merges, pushes without review), and a second count of the
  same work would double it.
- **Compute numbers for the model** (lines changed, cycle times). Not now: it
  needs more API calls and scopes per sync; the spans and types come from
  what is already fetched.
