# 0025. Search Himalayas for the analysis's candidate roles, as ownerless demand sources

**Status:** Proposed — 2026-09-30.

## Context

Since ADR 0024 the role map is built from the roles an analysis recommends.
A build finds each candidate's openings among the postings already crawled,
and the crawler only reads sources it was given: the baseline list of company
boards, and boards discovered for a company named on a custom role. Nothing
ever looks for a candidate's jobs. A candidate whose jobs are not in that
corpus is left unplaced ("From your strengths, not on your market yet"), even
when the jobs exist.

The users this is being built for want to work in **Taiwan**, **Singapore**
and **remotely**. The baseline has almost nothing there. What could fill it
was checked on 2026-09-30:

| Source | Keyword search | What the check found |
|---|---|---|
| Himalayas (`himalayas.app/jobs/api/search`) | `q`, plus `country`, `worldwide`, `timezone` | No key. Full HTML descriptions. Remote jobs open to Taiwan: 2,716; to Singapore: 3,293; "data engineer" open to Taiwan: 224. Terms: link back to the Himalayas URL and name Himalayas as the source; do not pass the jobs on to Jooble, Neuvoo, Google Jobs or LinkedIn Jobs. Rate-limited (429). |
| Remotive (`remotive.com/api/remote-jobs`) | `search` | No key. At most four calls a day, listings delayed 24 hours, the same attribution terms. Remote only, no country filter. |
| Adzuna (`/jobs/sg/search`) | `what`, `where` | Covers Singapore, not Taiwan. Needs a key. Returns a snippet of the description, not the text. 250 calls a day. Commercial use past a 14-day trial needs a licence. |
| MyCareersFuture (`api.mycareersfuture.gov.sg/v2/jobs`) | `search`, by third-party reports | Singapore's government board, on-site jobs. No published API documentation or terms were found, and the endpoint answered 504 to every request during the check. |
| Taiwan MOL open data (`apiservice.mol.gov.tw`, dataset 44062) | No: filters on fields only | Government Open Data Licence. In a sample of 1,000 postings, 59 were engineering of any kind and about 20 were software or IT; the median description was 97 characters. |
| 104, Cake, Yourator | — | No public API. Where Taiwan's software jobs actually are. |

Two rules already in place shape the choice. The crawler holds no secrets and
reads no user data. And a crawl source records why it is crawled, never who
asked (`CrawlSource.origin`, domain decision 15); it already has a `market`
column and a `publicApi` source kind that nothing uses yet.

## Decision

- **Himalayas is the first public-API source**, for remote work: remote jobs
  anyone may take, and remote jobs open to the country a user named. It has a
  keyword search, needs no key, returns whole descriptions and allows this
  use with attribution.
- **A search is an ownerless demand source.** When an analysis's candidates
  are stored, the worker asks `market` to make sure a crawl source exists for
  each (candidate title, target location) pair: `kind = himalayas`,
  `origin = demand`, `market` set to the location, and the search URL as its
  endpoint. `(kind, endpoint)` is already unique, so two users whose analyses
  recommend the same title in the same place share one source, and the row
  says nothing about either. Only the title is sent, never the candidate's
  description or anything from the profile.
- **Locations map to Himalayas filters in `market`'s domain.** A target
  location that names a country searches with that country's code; "Remote"
  searches `worldwide`. A location that is neither (a city) adds no source.
  A posting is stored with a location that names both "Remote" and the
  countries it is open to, so the existing word rule puts it in scope for a
  user who chose either.
- **The crawler runs the searches, with a new adapter** under
  `market/crawling/adapters/`, through the existing fetch, politeness and
  ingest path: at most `HIMALAYAS_PAGES_PER_SEARCH` (3, sixty postings) per
  source per crawl, and a 429 ends that source's crawl for the week rather
  than retrying. It needs no key, so the crawler still holds no secret.
- **A new source is crawled within minutes, not at the next weekly crawl.**
  Between weekly runs the crawler polls for sources never fetched and crawls
  those. `PostingsChanged` then rebuilds the role map as any market change
  does, which is when a candidate the first build left unplaced is placed.
- **A search nobody's candidates name is retired.** Replacing a user's
  candidates leaves their old searches in place; a demand search source whose
  last crawl found nothing new for `SEARCH_SOURCE_IDLE_WEEKS` (4) is set
  inactive, as a baseline entry is when it leaves the list.
- **Attribution is shown.** Every opening from this source links to its
  Himalayas URL and says "via Himalayas", in the role map's matched openings
  and on the Advisor's target. Postings from it are never exported or
  syndicated.
- **On-site Taiwan and Singapore are not solved here.** They stay on company
  boards: the baseline list gains companies that hire in Taiwan and
  Singapore on Greenhouse, Lever and Ashby, and a custom role with a company
  still seeds discovery. MyCareersFuture is revisited when its terms can be
  read and the endpoint answers.

## Consequences

Easier:
- A candidate for remote work, or remote work open to Taiwan or Singapore, is
  looked for instead of waiting for a company someone happened to name.
- It reuses what exists: a crawl source, an adapter, the ingest and dedup
  path, `PostingsChanged` and the rebuild. No new deployable, queue or table.
- The crawler's two rules hold. It gets no secret and no user data; a search
  is a job title and a country.

Harder:
- A job title derived from a user's profile leaves the platform, to a third
  party. It is a generic title with nothing attached, sent from the crawler,
  but it is the first time anything derived from a profile is sent anywhere
  but the user's own AI provider. The privacy note has to say so.
- The map now depends on one company's free API and its terms. If Himalayas
  rate-limits harder, changes its terms or closes the API, remote candidates
  go back to unplaced. Postings already stored stay until they expire.
- The rebuild that places a candidate happens after the build the user
  confirmed, and spends their key on naming the new role and scoring its fit
  without a second confirmation. ADR 0020 already allows that for a market
  change, and the Analyse estimate is already a ceiling for ten roles, but
  the spend now arrives minutes later instead of a week later.
- Himalayas lists jobs that company boards list too. The posting dedup key
  has to match across sources, or one opening counts twice towards a role.
- Up to 20 candidates times three locations is sixty searches per user, and
  the crawler gains a polling loop beside its weekly one. Both need limits
  that hold when many users analyse at once.
- "Remote" in Himalayas means remote. A user who wants an office in Taipei or
  Singapore gets little from this, and the role map has to say which openings
  are remote.
- Attribution is a user-interface requirement that a later redesign can
  break without any test failing, unless one is written for it.

## Alternatives considered

- **Pull everything Himalayas has for a country each week, and let the local
  matching do the searching.** Lost: about 2,700 postings per country at
  twenty a page is some 140 requests per country per crawl against a
  rate-limited free API, most of it for roles nobody's analysis named.
- **Adzuna for Singapore.** Lost for now: its key would be the crawler's
  first secret, a snippet is too little to read requirements from, and using
  it past a 14-day trial needs a licence agreement. Worth reopening if that
  agreement is wanted.
- **MyCareersFuture for Singapore.** Not rejected, but not adoptable today:
  no published terms or documentation could be found for the API, and it
  could not be reached to confirm what it returns.
- **Taiwan's MOL open data.** Lost: no keyword search, about 2% software
  roles in the sample, and descriptions too short to extract requirements
  from. Its licence is the most permissive of any source here, so it stays
  the fallback if breadth ever matters more than fit.
- **Read 104, Cake or Yourator.** Lost: none offers a public API, and
  reading their pages without one is the scraping domain decision 6 rules
  out.
- **Query from the worker while the build runs**, so the first build already
  has the postings. Lost: it puts outbound fetching of third-party content in
  the process that holds users' keys and data, which is what the crawler
  exists to keep apart, and a slow API would hold a build open.
- **Remotive as well.** Deferred: four calls a day allows only a bulk pull,
  it has no country filter, and its listings are a day old. It adds little
  once Himalayas is in.
