# 0017. Group Jira work by epic, not by project

**Status:** Accepted — 2026-09-28.

## Context

The Jira connector tallied the user's assigned issues per project, keyed
`jira:{site}:project:{KEY}`, and named each issue's project as its `subject`.
The "Where the work lives" chart drew one bar per project.

A project says where a team files its tickets, not what was built. One project
usually holds years of unrelated work, and one initiative often spans several
projects. So "84 issues in PAY" says nothing about the size of any one thing the
user shipped, which is the scope evidence a résumé loses and this connector
exists to recover. An epic names the thing that was shipped.

The connector also read only the first page of the search, 100 issues.

## Decision

**Issues are grouped by the epic they belong to.** The search now also asks for
each issue's `issuetype` and `parent`, and an issue's epic is:

- the issue itself, when it is an epic assigned to the user, since owning an
  epic is work on it;
- its parent, when the parent is an epic, which is the case for stories, tasks
  and bugs;
- its parent's parent, for a subtask. Those stories are read in one more search,
  `key in (…)`, up to 100 keys per call.

An issue is an epic when its type's `hierarchyLevel` is 1. Where Jira leaves the
level out, the type's name `Epic` decides. An issue under no epic is left out of
the epic tallies, but it still counts toward the site's throughput.

For the ten epics with the most issues there is a summary,
`jira:{site}:epic:{KEY}`, stating `"{n} issues worked in the epic {KEY}: {summary}."`.
Its `subject` is `"{KEY} {summary}"`, so a chart bar reads as the thing that was
built. Each issue item carries the same `subject` as its epic, so clicking a
bar lists the tally and its issues.

**The search pages** by `nextPageToken`, up to 1000 issues per site.

**The project tallies are retired.** ADR 0016 had connectors declare retired
`external_ref` shapes as prefixes. Jira's project tallies carry the site id
between the source and the shape (`jira:{site}:project:{KEY}`), which a prefix
cannot express. So retired shapes are now glob patterns (`jira:*:project:*`,
`github:pr:*`), matched with `fnmatchcase`. Everything else ADR 0016 decided
about retiring holds: the next sync deletes the facts in the same transaction
that writes the new ones, and the version bump marks earlier reports out of date.

**Only a key shaped like a Jira key goes into JQL.** A parent key comes from
Jira's response, and is untrusted like everything else fetched. A key that is
not `PROJECT-123` is never written into a query, so the lookup of subtasks'
stories cannot be turned into a different search.

## Consequences

- Easier: a tally measures one initiative, so "31 issues worked in the epic
  PAY-1: Ledger rewrite" says how large the thing was.
- Easier: an epic that spans projects is counted once, across all of them.
- Harder: teams that do not use epics get no per-epic tallies at all. Their
  work still counts toward throughput and as items, but the chart shows no Jira
  bars for them. The project view, which every issue had, is gone.
- Harder: a sync makes more calls. It pages up to ten times per site, plus one
  lookup per 100 distinct subtask parents.
- Harder: an epic's summary is part of the `subject`. When an epic is renamed,
  the next sync restates its facts under the new name. Earlier reports cite the
  old wording until they are re-run.
- Harder: glob patterns are broader than prefixes. A careless pattern such as
  `jira:*` would delete every Jira fact at the next sync. Each connector's
  patterns are covered by a unit test for that reason.

## Alternatives considered

- **Keep projects and add epics.** Lost because each issue would be counted in
  two tallies, and the chart would put two unlike groupings on one scale.
- **Group by the `Epic Link` custom field.** Lost because Atlassian replaced it
  with `parent` across Jira Cloud, and its field id differs from site to site.
- **Fetch every epic's children from the epic's side.** Lost because it needs one
  search per epic, and reaches issues the user did not work on.
- **Keep prefixes, and list every site's project refs as retired.** Lost because
  the connector would have to know which sites a user once synced, which only
  their stored facts record.
