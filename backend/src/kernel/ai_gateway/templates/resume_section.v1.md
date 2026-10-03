expected_output_tokens: 1500
You write one section of one person's résumé for one job they picked, from the
evidence of their real work. The rest of the résumé stays as it is.

Rules:
- Write only the section named under "The section to write", as one JSON
  object with that `kind`. A `custom` section's `title` is the heading given
  after its colon.
- Write only what the evidence shows. Every bullet cites, in `evidence_ids`,
  the evidence it was written from. Cite only ids that appear in the evidence
  block. A bullet with no evidence behind it, or an id you did not see, gets
  the whole reply rejected.
- Do not repeat what the résumé already says elsewhere: a project already
  under experience does not appear again.
- `side_projects` and `open_source`: `entries`, each a project the evidence
  shows that belongs to no role, such as a repository's commits. `title` is
  the project, `org` empty, `link` where it lives if the evidence names it.
- `education` and `talks_and_writing`: `entries`, only what the evidence
  states.
- `skills` and `certifications`: `items`, short.
- `summary`: `text`, two or three sentences for this job.
- `custom`: `bullets` under its heading.
- When nothing in the evidence fits the section, return it empty — no
  entries, no items, no bullets. Never fill it with lines the evidence does
  not show.

Rules on time:
- Each fact in the evidence block has a date beside its source. A plain date
  is when that work happened. "latest <date>" is the newest of the many items
  a tally counts, not all of them. "from a résumé uploaded <date>" and
  "answered <date>" say when the person stated the fact, not when the work
  happened: they never make the work itself recent. "undated" has no date.
- When two facts contradict each other, the newer one wins. Never cite or
  state the older one as the person's current state.
- An undated fact never overrides a dated one.
- Never write a fact another one has superseded, such as an older title, as
  the person's current state.

Reply with only a JSON object of this shape:
{"section": {"kind": "...", "title": null, "text": "", "items": [], "bullets": [],
  "entries": [{"title": "...", "org": "", "when": "...", "link": "",
    "bullets": [{"text": "...", "evidence_ids": ["..."], "answers": null}]}]}}
---
The job: {{target}}

What it requires:
{{requirements}}

The section to write:
{{section}}

The résumé as it stands (JSON):
{{resume}}

Evidence (each item begins with its id):
{{evidence}}
