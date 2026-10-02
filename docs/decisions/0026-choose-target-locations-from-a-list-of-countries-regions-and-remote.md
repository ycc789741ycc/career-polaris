# 0026. Choose target locations from a list of countries, regions and Remote

**Status:** Accepted — 2026-10-02.

## Context

"Where you want to work" in 01 Sources was a free-text box (domain decision
21). Whatever the user typed was matched against posting locations word by
word, and since ADR 0025 a location is also searched on Himalayas for the
roles an analysis recommends, but only when it names a country or is "Remote".

Free text failed quietly in three ways:

- A city ("Taipei") matched the boards that wrote the city, but got no search,
  and nothing on the screen said so.
- A region ("Remote EU", "APAC") matched only postings that happened to write
  the same words, and got no search either.
- A typo or an unusual spelling matched nothing at all, and the role map was
  built from an empty market without saying why.

At the same time, matching by the country's name alone misses most board
postings for it: company boards often write only the city ("Taipei",
"Berlin").

## Decision

- **A target location is one of a fixed list**, in `market`'s domain
  (`advisor/market/domain/places.py`): "Remote", then the regions, then the
  countries, each group A to Z. `GET /target-location-options` serves it as a
  page with each place's kind (`remote`, `region`, `country`), and the SPA
  keeps no copy. 01 Sources picks from it with a filterable list.
- **Only listed places are stored.** `chosen_target_locations` stores each
  under its name on the list ("united kingdom" is "United Kingdom") and
  refuses anything else, so `PUT /target-locations` answers 422 for a city or
  a free-text region. The cap of three stays.
- **A country takes in its cities.** Each country has its other names ("UK",
  "USA") and its main hiring cities. `in_market`, the scope query's SQL and
  the fan-out all read them, so a board posting in Taipei is in scope for
  "Taiwan". The Himalayas search is unchanged: it is asked by country code.
- **A region is a named set of countries, matched and never searched.** Asia-
  Pacific, Europe, Latin America, Middle East & Africa and North America to
  start with; every country is in at least one. A posting is in a region when
  it names the region itself ("EMEA", "APAC") or any member country, alias or
  city. A region adds no search: Himalayas filters by one country at a time,
  so "Europe" would be one search per member country for each candidate
  title, about 500 for one analysis. A change announced for a country also
  reaches the users of its regions. The screen says once, under the list, that
  a region uses the postings already stored.
- **Remote work open to anyone is in every listed place**, as it already was
  for every place a search covers.
- **Stored locations move onto the list.** Migration 0021 rewrites each row to
  the place it names ("UK" → "United Kingdom", "Remote Taiwan" → "Taiwan",
  "Remote EU" → "Europe") and deletes rows that name no place on the list,
  such as a city, and duplicates. It records no event, so it rebuilds nobody's
  role map; the next build uses the new scope. Its mapping is frozen in the
  migration, not read from the list.

This amends domain decision 21 (a target location was "a city, a country or a
remote region") and ADR 0025, where a region simply added no source; it is now
a rule.

## Consequences

Easier:

- Every place a user picks has a known way to be matched, and, for a country
  or "Remote", to be searched. Nothing fails silently on a spelling.
- One search is shared by everyone who picks the same country: the label a
  search is filed under is the name the user chose.
- Board postings that write only a city now count for the country, and for its
  regions.

Harder:

- A user can no longer narrow to one city. "Taiwan" takes in all of Taiwan,
  and a user who only wants Taipei sees Kaohsiung too.
- A region's searched postings depend on what other users chose: a user who
  picks only "Europe" gets board postings, worldwide remote work and the
  searches some other user's country asked for, but their own recommended
  roles are never searched for on their behalf.
- The fan-out widens: a change to one country also reaches its regions'
  users, so "Europe" users rebuild when any member country moves.
- The city names per country and the countries per region are lists someone
  keeps up. A missing city quietly drops that city's board postings for its
  country. Short aliases ("US", "EU") match the word wherever a board writes
  it.
- Users who had typed a city lost that location in the migration, with no
  notice on the screen.
- Integration tests can no longer isolate themselves in the shared development
  database with a made-up place through the service; they store one directly
  (`tests/integration/places.py`).

## Alternatives considered

- **Keep free text, and tell the user what each location will do.** Lost:
  the screen would have to explain matching and searching per entry, and a
  typo would still save. A list makes the explanation unnecessary.
- **Map a city to its country in the migration** instead of deleting it.
  Lost: it widens a user's scope to a whole country they did not choose. The
  user can pick the country in one click.
- **Search a region through every member country.** Lost: about 500 requests
  per analysis to one rate-limited API, well past what a build can wait for.
  Searching a few "representative" members was rejected as a judgement the
  user cannot see.
- **Include cities on the list.** Lost: a city gets no search and, to be
  matched well, needs its own aliases and suburbs. Countries already take in
  their cities.
