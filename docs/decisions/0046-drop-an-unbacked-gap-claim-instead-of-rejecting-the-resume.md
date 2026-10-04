# 0046. An unbacked gap claim is dropped, not the résumé

**Status:** Accepted — 2026-10-12.

## Context

ADR 0044 let a résumé claim a requirement marked gap from the answers given
about it, and checked that in code: `assert_gap_claims_answered` rejected the
whole reply when a written line's `answers` named a gap and its citations
were anything but that gap's answers, or the gap had none.

The first real résumé written under it failed:

> the written résumé was rejected: a line claims 'Ability to design,
> implement, and maintain clean, modular architectures with strong testing
> practices, …', a gap nothing was answered about

The line was cited to the user's own evidence. Only its label — the
requirement it said it met — had nothing behind it. The model labels lines
with requirements to lead with what the job asks for, and a gap the analysis
scored a little short is easy to label. Rejecting the reply threw away a write
the user had paid for, over that label, and a regenerate could fail the same
way.

The rule guards two different things, which ADR 0044 treated alike:

- **The facts on the page.** Every written line cites the user's own
  evidence, checked by `assert_written_lines_cited` and
  `assert_citations_exist`. That is what keeps an invented fact out, and it
  still rejects the reply.
- **The claim that a line meets a requirement.** That is the `answers` label,
  which the page marks and which coverage does not read.

## Decision

A claim nothing backs is dropped; the line stays.

- `get_claims_settled(content, requirements, gaps)` clears a written line's
  `answers` when it names no requirement of the Target, or names one marked
  gap that its citations do not rest on alone — the gap's answers, at least
  one of them, and nothing else. A gap nobody answered about can be claimed
  by no line. The line's text and citations are kept as they were.
- `assert_gap_claims_answered` is gone. Writes, chat proposals and filled
  sections run `get_claims_settled` before their other checks, as before, and
  log how many claims they dropped (`resume.claims_dropped`).
- A line the user wrote keeps its claim, as under ADR 0044.
- The prompts are unchanged: `resume_write` and `resume_revise` v5 still tell
  the model a gap may be claimed only from its answers.

This amends ADR 0044's "The rule is checked, not only asked for"; the rest of
ADR 0044 stands.

## Consequences

Easier:

- A model that over-labels a cited line no longer costs the user the write,
  and a regenerate does not fail on the same label.
- What the page claims still rests on the user's answers, checked in code.

Harder:

- A line's text can still read as meeting a gap — "maintains clean, modular
  architectures" — once its label is dropped. The words were written from the
  user's own cited evidence, but the page no longer marks which requirement
  they answer, and coverage still calls it a gap.
- The model's mistake is silent to the user; it shows only in the log count.

## Alternatives considered

- **Keep rejecting, and let the user regenerate.** Lost: the same label fails
  the same way, and each attempt is a spend.
- **Drop the line instead of its label.** Lost: the line cites real evidence,
  and losing it loses true work from the page.
- **Ask the model again within the same call.** Lost: the gateway already
  re-asks only on a schema failure; adding a second round for a label doubles
  the cost of the cases where it happens.
