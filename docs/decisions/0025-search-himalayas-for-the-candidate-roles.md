# 0025. Search Himalayas for the analysis's candidate roles, as ownerless demand sources

**Status:** Accepted — 2026-09-30. Amended by 0026.

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
| Himalayas (`himalayas.app/jobs/api/search`) | `q`, plus `country`, `worldwide`, `timezone` | No key. Full HTML descriptions. Remote jobs open to Taiwan: 2,716; to Singapore: 3,293; "data engineer" open to Taiwan: 224. A country search also returns jobs open to anyone, with no country listed. Terms: link back to the Himalayas URL and name Himalayas as the source; do not pass the jobs on to Jooble, Neuvoo, Google Jobs or LinkedIn Jobs. Rate-limited (429). Its robots.txt disallows `/jobs*&page=`, which takes in a paged search. |
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
- **A search is an ownerless demand source.** `rolemap` announces a new set of
  candidates as `RoleCandidatesReplaced`, with their titles. The dispatcher
  reads the user's target locations and queues `market.request_searches` with
  titles and places only. That job makes sure a crawl source exists for each
  (title, place) pair: `kind = himalayas`, `origin = demand`, no company, and
  the search URL as its endpoint. `(kind, endpoint)` is already unique, so two
  users whose analyses recommend the same title in the same place share one
  source, and the row says nothing about either. Only the title is sent,
  folded to plain lowercase words, never the candidate's description or
  anything else from the profile. A change of target locations searches the
  last analysis's candidates in the new places the same way.
- **Places map to Himalayas filters in `market`'s domain** (`search_scope`).
  A target location that names a country, with or without "Remote", searches
  with that country's code; "Remote" alone searches `worldwide`. Anything
  that names more (a city, a region) adds no source. A search is filed under
  one name for its place (`CrawlSource.market`: "Taiwan", "Remote"), whatever
  the user typed.
- **How a found posting is in scope.** It is stored with the countries it is
  open to after "Remote" ("Remote, Taiwan, Japan"), so the existing word rule
  puts it in scope for "Taiwan" and for "Remote". One open to anyone is
  "Remote, Worldwide", and `in_market` gains one rule for it: remote work
  open worldwide is in every target location a search can be scoped to. A
  city is not one, so it is not in "Taipei".
- **The crawler runs the searches, with a new adapter** under
  `market/crawling/adapters/`, through the existing fetch, politeness and
  ingest path. It reads the first page only, the twenty most relevant
  openings: robots.txt disallows paging. A 429 is recorded on the source and
  it waits for the next weekly crawl. It needs no key, so the crawler still
  holds no secret.
- **A new source is crawled within minutes, not at the next weekly crawl.**
  Between weekly runs the crawler looks every two minutes for active sources
  never fetched (`crawl_new`) and crawls only those. A board that discovery
  just found benefits too.
- **A place is announced once per crawl, and only when it changed.** A
  search's postings are stored without `PostingsChanged`
  (`record_search_crawl`). After the run, each place where an opening
  appeared or went is announced once (`announce_markets`), which is one
  role-map rebuild per user there, not one per search. That rebuild is when a
  candidate the first build left unplaced is placed. The dispatcher's fan-out
  now finds users by any name for the place ("Remote Taiwan" and "taiwan"
  both name "Taiwan"; "UK" names "United Kingdom"), not by an equal string.
- **A search nobody asks for is retired.** Each request marks its sources
  (`last_requested_at`, migration 0020). Before a weekly crawl, a search not
  asked for in `SEARCH_SOURCE_IDLE_WEEKS` (8) is retired and what it found is
  expired, since no crawl is left to notice those postings closing. Asking
  again revives it. Requests come from an analysis and from a change of
  target locations.
- **Attribution is shown.** Every opening from this source links to its
  Himalayas URL and says "via Himalayas", in the role map's matched openings
  and on the Advisor's target (`credited_to`, decided from the link's host).
  Postings from it are never exported or syndicated. The AI & model screen
  says that recommended job titles are searched there, and that nothing else
  is sent.
- **On-site Taiwan and Singapore are not solved here.** They stay on company
  boards. The baseline list gains three with openings there on the day of
  the check: Appier (40 in Taiwan), OKX (126 in Singapore) and Stripe (53 in
  Singapore, 4 in Taiwan). A custom role with a company still seeds
  discovery. MyCareersFuture is revisited when its terms can be read and the
  endpoint answers.

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
- Himalayas lists jobs that company boards list too, under a different
  location, so the dedup key (company, title, location) does not collapse
  them and one opening can count twice towards a role. Not solved here.
- Twenty openings per search is a narrow window. An opening that drops out
  of the first page is expired though it may still be open, and returns if
  it ranks again.
- A user who never re-analyses and never changes locations stops asking, so
  after eight weeks their searches retire and those roles thin out until
  they analyse again.
- A weekly crawl that changes a place rebuilds the role map of everyone
  there, and scores their fits again on their keys. It is one rebuild per
  place, and none when nothing changed, but it is a recurring spend the user
  did not confirm each time.
- Up to 20 candidates times three locations is sixty searches per user, and
  the crawler gains a polling loop beside its weekly one. Both need limits
  that hold when many users analyse at once.
- "Remote EU" and other regions get no search: Himalayas filters by country.
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
