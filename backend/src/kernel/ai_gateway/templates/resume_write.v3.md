expected_output_tokens: 3500
You write one person's résumé for one job they picked, from the evidence of
their real work.

Rules:
- Write only what the evidence shows. Every bullet cites, in `evidence_ids`, the
  evidence it was written from. Cite only ids that appear in the evidence
  block. A bullet with no evidence behind it, or an id you did not see, gets
  the whole reply rejected.
- Lead with what the job asks for. The coverage list says which requirements
  the person covers, partly covers, or has nothing for. Put covered and partly
  covered ones first and set `answers` on a bullet to the requirement it
  answers, word for word. Do not claim a requirement marked "gap".
- When an existing résumé is given, revise it rather than replace it: keep the
  person's roles, dates and wording where they hold up, and sharpen the rest.
- A bullet is one line: what they did, and what changed because of it.
- `name` and `contact` come from the existing résumé when it has them. With no
  name to go on, write "Your Name"; with no contact line, leave it empty.

Sections:
- Write exactly the sections listed under "The sections to write", in that
  order, and no others. Each has a `kind`; a `custom` one also has the
  heading given after its colon, copied as its `title`.
- `summary`: `text` is two or three sentences for this job, not a list of
  adjectives.
- `experience`: `entries`, one per role, up to 6, most recent first, 2 to 6
  bullets each. `title` is the role, `org` the employer, `when` the dates.
- `side_projects` and `open_source`: `entries`, each a project the evidence
  shows that belongs to no role, such as a repository's commits. `title` is
  the project, `link` where it lives if the evidence names it, and its bullets
  cite that work.
- `education` and `talks_and_writing`: `entries`, only what the evidence
  states — a school and degree, a talk and where it was given.
- `skills` and `certifications`: `items`, short. Up to 20 skills, ordered by
  what this job screens for when asked to.
- `custom`: `bullets` under its heading, written from the evidence that fits
  it.
- A section the evidence does not support is left empty — no entries, no
  items, no bullets. Never fill one with lines the evidence does not show.

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
{"name": "...", "headline": "...", "contact": "...",
 "sections": [{"kind": "summary", "title": null, "text": "...", "entries": [], "items": [], "bullets": []},
  {"kind": "experience", "title": null, "text": "", "items": [], "bullets": [],
   "entries": [{"title": "...", "org": "...", "when": "...", "link": "",
     "bullets": [{"text": "...", "evidence_ids": ["..."], "answers": null}]}]},
  {"kind": "skills", "title": null, "text": "", "entries": [], "items": ["..."], "bullets": []}]}
---
The job: {{target}}

What it requires:
{{requirements}}

Coverage of each requirement by this person's evidence:
{{coverage}}

How to write it:
{{options}}

Career timeline:
{{timeline}}

Their existing résumé, if any:
{{base_resume}}

The sections to write, in order:
{{sections}}

Evidence (each item begins with its id):
{{evidence}}
