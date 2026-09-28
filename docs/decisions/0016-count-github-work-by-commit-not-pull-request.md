# 0016. Count GitHub work by commit, not by pull request

**Status:** Accepted — 2026-09-28.

## Context

The GitHub connector made its evidence from pull requests. Two searches on
`/search/issues` supplied everything: merged pull requests the user authored
(`is:pr author:{login} is:merged`) and pull requests they reviewed. It tallied
the first page of merged pull requests by repository and kept 25 of their
titles as items.

Work that never went through a pull request left no evidence. That covers
commits pushed straight to a branch, which is how most solo and personal
projects work, and how many teams handle small changes. The profile then
understated exactly the people whose work is least visible anywhere else. Only
one page, 100 pull requests, was ever read, so the per-repository tallies also
stopped at 100 however much someone had shipped.

## Decision

**The connector counts commits.** It reads `/search/commits` with
`author:{login} merge:false`, sorted by author date, newest first, and pages
through the results, up to the 1000 that GitHub's search will return.

- Per repository, for the ten busiest: a summary, `github:commits:{repo}`,
  `"{n} commits authored in {repo}."`, with `n` as its tally.
- The 25 newest commits, as items: `github:commit:{sha}`, cited as
  `GitHub · {repo}@{short sha}`, stating the first line of the message, dated
  by the author date.
- Merge commits are left out. They join work that was already done, and would
  count it a second time.

A squash-merged or rebased pull request still counts, because the commit that
lands on the default branch carries its author.

**Reviews stay.** Reviewing is work a commit cannot show, so the
`github:reviews` summary from `/search/issues` is unchanged, except that it now
pages the same way.

**A sync deletes the facts a connector no longer writes.** A connector declares
the `external_ref` prefixes it has retired, and `ProfileService.sync_connection`
deletes the source's facts under them in the same transaction that writes the
new ones. GitHub retires `github:merged:` and `github:pr:`. Without this, a user
who synced before the change would have the same work counted once as merged
pull requests and again as commits. The deletion bumps the profile version like
any other change, so earlier reports are marked out of date (ADR 0015).

## Consequences

- Easier: work pushed without a pull request counts, and a repository's tally
  now reaches 1000 commits instead of stopping at 100 pull requests.
- Easier: a commit's short sha is a citation anyone with access can check.
- Harder: GitHub's commit search reads only default branches. Work on a branch
  that was never merged, or that was merged into a fork's default branch
  instead, still leaves no evidence.
- Harder: it finds only commits whose author email is linked to the GitHub
  account. Commits made from an unlinked work address are missed until the user
  adds that address to GitHub.
- Harder: the scopes are unchanged (`read:user`, `repo:status`, `public_repo`),
  and none of them reads private repositories. Reaching private work needs the
  `repo` scope, which also grants write access. That is a consent decision of
  its own, not part of this one.
- Harder: commits are a noisier unit than pull requests. One pull request can be
  twenty "fix typo" commits, so a tally measures activity rather than size.
  That is why the tally is shown per repository and the items keep the message.
- Harder: a sync makes up to ten search calls for commits, where it used to make
  one. GitHub allows 30 search requests a minute per user, so a user can sync
  about twice a minute before being rate-limited.
- Every GitHub fact an earlier report cites is deleted at the next sync, so
  those citations go stale at once. The out-of-date notice from ADR 0015 covers
  this.

## Alternatives considered

- **Count both pull requests and commits.** Lost because a squash-merged pull
  request is also a commit by the same author, so most reviewed work would be
  counted twice.
- **List the user's repositories and read each one's commits**
  (`/user/repos`, then `/repos/{repo}/commits?author=`). Lost because it only
  sees repositories the user owns or belongs to, which leaves out contributions
  to other people's projects, and it costs one call per repository.
- **The GraphQL `contributionsCollection`.** It counts commits per repository,
  including private ones where the user allows it. Lost because it gives counts
  without messages or shas, so there would be nothing specific to cite, and it
  covers at most one year per query.
- **The events API** (`/users/{login}/events`). Lost because it reaches back
  only 90 days and 300 events.
- **Delete the old shapes in a migration.** Lost because a migration does not
  bump anyone's profile version, so earlier reports would go on citing deleted
  facts without being marked out of date.
