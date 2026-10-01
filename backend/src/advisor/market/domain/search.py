"""Where a target location can be searched for candidate roles (ADR 0025).

A public job API is searched with a job title and a place. Only some target
locations are places such an API understands: a country, or "Remote". A region
is neither (ADR 0026), so it adds no search, and its postings come from
company boards and from the searches of its member countries.

Postings found this way are remote. One open to anyone is stored as
``WORLDWIDE_LOCATION``; one restricted to countries names them after
"Remote". ``in_search_scope`` is why a job open worldwide counts for a user
who named a country: nothing in its location says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from advisor.market.domain.places import (
    COUNTRIES,
    REMOTE,
    country_named,
    names_a_place,
    regions_of,
    target_location_option,
)
from advisor.market.domain.posting import market_words

WORLDWIDE = "Worldwide"
WORLDWIDE_LOCATION = f"{REMOTE}, {WORLDWIDE}"
WORLDWIDE_WORDS = market_words(WORLDWIDE_LOCATION)

# A search with no demand is dropped: no analysis or change of locations has
# asked for it in this many weeks (ADR 0025).
SEARCH_SOURCE_IDLE_WEEKS = 8

# Job sites whose terms ask that an opening found through their API links back
# to them and names them as its source (ADR 0025), by the host of that link.
_CREDITED_HOSTS: dict[str, str] = {"himalayas.app": "Himalayas"}


@dataclass(frozen=True, slots=True)
class SearchScope:
    """One place a search API can be asked about.

    ``label`` is the place as the platform names it, the same for every user
    whose target location means it: the country, or "Remote". It is what a
    search source is filed under and what ``PostingsChanged`` announces.
    ``country_code`` is ``None`` for remote work open to anyone.
    """

    label: str
    country_code: str | None

    @property
    def is_worldwide(self) -> bool:
        return self.country_code is None


def search_scope(location: str) -> SearchScope | None:
    """The place to search for a target location, or ``None`` when it is not
    one a search can be scoped to.

    "Taiwan" and "Remote Taiwan" are remote work open to Taiwan; "Remote" alone
    is remote work open to anyone. A region is never searched (ADR 0026): a
    search filters by one country at a time. Anything else that names more
    than a country, such as a city, is left to company boards.
    """
    words = set(market_words(location))
    if not words:
        return None
    remote = set(market_words(REMOTE))
    # The longest name first, so "South Korea" is not read as "Korea" plus a word.
    named_countries = sorted(
        ((name, country) for country in COUNTRIES for name in country.names),
        key=lambda entry: -len(entry[0]),
    )
    for name, country in named_countries:
        named = set(market_words(name))
        if named <= words and words - named <= remote:
            return SearchScope(label=country.name, country_code=country.code)
    if words == remote:
        return SearchScope(label=REMOTE, country_code=None)
    return None


def scope_names(label: str) -> tuple[str, ...]:
    """The target locations a change to the place filed under ``label`` may
    concern: the place itself, and for a country, the regions it is in. A user
    who chose any of them may be affected by that place's postings changing."""
    if country_named(label) is not None:
        return (label, *regions_of(label))
    return (label,)


def remote_location(countries: list[str]) -> str:
    """The location a remote posting is stored with: the countries it is open
    to after "Remote", or ``WORLDWIDE_LOCATION`` when it is open to anyone."""
    named = [country.strip() for country in countries if country and country.strip()]
    if not named:
        return WORLDWIDE_LOCATION
    return ", ".join((REMOTE, *named))


def is_open_worldwide(location: str | None) -> bool:
    """Whether a posting says it is remote work open to anyone, anywhere."""
    return set(WORLDWIDE_WORDS) <= set(market_words(location or ""))


def in_search_scope(location: str | None, market: str) -> bool:
    """Whether a posting open worldwide counts for ``market``: it does for
    every place on the list, and for any other a search can be scoped to,
    since anyone there may take it."""
    return is_open_worldwide(location) and (
        target_location_option(market) is not None or search_scope(market) is not None
    )


def in_market(location: str | None, market: str) -> bool:
    """Whether a posting's location falls in a market the user chose.

    Every word of one of the market's names must appear in the location
    (``place_names``): "Taiwan" takes in "Taipei", "Europe" takes in "Berlin,
    Germany", and "Remote" takes in "Remote, United States". Boards never
    write a location the way a user names a market, so equal strings almost
    never happen. A posting open worldwide is also in every listed place
    (``in_search_scope``).
    """
    return names_a_place(location, market) or in_search_scope(location, market)


def credited_source(url: str | None) -> str | None:
    """The job site an opening must be credited to wherever it is shown, or
    ``None`` when its link goes to the employer's own board."""
    host = (urlsplit(url or "").hostname or "").lower()
    for credited, name in _CREDITED_HOSTS.items():
        if host == credited or host.endswith(f".{credited}"):
            return name
    return None
