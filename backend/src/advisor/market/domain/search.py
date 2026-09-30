"""Where a target location can be searched for candidate roles (ADR 0025).

A public job API is searched with a job title and a place. Only some target
locations are places such an API understands: a country, or "Remote". A city
is neither, so it adds no search, and its postings keep coming from company
boards.

Postings found this way are remote. One open to anyone is stored as
``WORLDWIDE_LOCATION``; one restricted to countries names them after
"Remote". ``in_search_scope`` is why a job open worldwide counts for a user
who named a country: nothing in its location says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from advisor.market.domain.posting import market_words, names_every_word

REMOTE = "Remote"
WORLDWIDE = "Worldwide"
WORLDWIDE_LOCATION = f"{REMOTE}, {WORLDWIDE}"
WORLDWIDE_WORDS = market_words(WORLDWIDE_LOCATION)

# A search with no demand is dropped: no analysis or change of locations has
# asked for it in this many weeks (ADR 0025).
SEARCH_SOURCE_IDLE_WEEKS = 8

# Job sites whose terms ask that an opening found through their API links back
# to them and names them as its source (ADR 0025), by the host of that link.
_CREDITED_HOSTS: dict[str, str] = {"himalayas.app": "Himalayas"}

# Country names as users and job boards write them, with the ISO 3166-1
# alpha-2 code a search API filters by. Several names may share a code; the
# first listed is the one the platform files the country under.
_COUNTRIES: tuple[tuple[str, str], ...] = (
    ("Argentina", "AR"),
    ("Australia", "AU"),
    ("Austria", "AT"),
    ("Belgium", "BE"),
    ("Brazil", "BR"),
    ("Canada", "CA"),
    ("Chile", "CL"),
    ("China", "CN"),
    ("Colombia", "CO"),
    ("Czechia", "CZ"),
    ("Czech Republic", "CZ"),
    ("Denmark", "DK"),
    ("Estonia", "EE"),
    ("Finland", "FI"),
    ("France", "FR"),
    ("Germany", "DE"),
    ("Greece", "GR"),
    ("Hong Kong", "HK"),
    ("Hungary", "HU"),
    ("India", "IN"),
    ("Indonesia", "ID"),
    ("Ireland", "IE"),
    ("Israel", "IL"),
    ("Italy", "IT"),
    ("Japan", "JP"),
    ("Malaysia", "MY"),
    ("Mexico", "MX"),
    ("Netherlands", "NL"),
    ("New Zealand", "NZ"),
    ("Norway", "NO"),
    ("Philippines", "PH"),
    ("Poland", "PL"),
    ("Portugal", "PT"),
    ("Romania", "RO"),
    ("Singapore", "SG"),
    ("South Africa", "ZA"),
    ("South Korea", "KR"),
    ("Korea", "KR"),
    ("Spain", "ES"),
    ("Sweden", "SE"),
    ("Switzerland", "CH"),
    ("Taiwan", "TW"),
    ("Thailand", "TH"),
    ("Turkey", "TR"),
    ("Ukraine", "UA"),
    ("United Arab Emirates", "AE"),
    ("UAE", "AE"),
    ("United Kingdom", "GB"),
    ("UK", "GB"),
    ("United States", "US"),
    ("USA", "US"),
    ("Vietnam", "VN"),
)


_LABELS: dict[str, str] = {}
for _name, _code in _COUNTRIES:
    _LABELS.setdefault(_code, _name)


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
    is remote work open to anyone. Anything that names more than that — a
    city, a region — is left to company boards: a posting stored for the
    search would not contain those words, so it would never be in scope.
    """
    words = set(market_words(location))
    if not words:
        return None
    remote = set(market_words(REMOTE))
    # The longest name first, so "South Korea" is not read as "Korea" plus a word.
    for name, code in sorted(_COUNTRIES, key=lambda entry: -len(entry[0])):
        named = set(market_words(name))
        if named <= words and words - named <= remote:
            return SearchScope(label=_LABELS[code], country_code=code)
    if words == remote:
        return SearchScope(label=REMOTE, country_code=None)
    return None


def scope_names(label: str) -> tuple[str, ...]:
    """Every name a target location may use for the place filed under
    ``label``: a country's aliases, or the label itself. A user whose location
    contains all the words of any of them may be affected by that place's
    postings changing."""
    for code, canonical in _LABELS.items():
        if canonical == label:
            return tuple(name for name, other in _COUNTRIES if other == code)
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
    """Whether a posting open worldwide counts for ``market``: it does for any
    target location a search can be scoped to, since anyone there may take it."""
    return is_open_worldwide(location) and search_scope(market) is not None


def in_market(location: str | None, market: str) -> bool:
    """Whether a posting's location falls in a market the user chose.

    Every word of the market must appear in the location, so "Berlin" takes in
    "Berlin, Germany" and "Remote" takes in "Remote, United States". Boards
    never write a location the way a user names a market, so equal strings
    almost never happen. A posting open worldwide is also in every market a
    search can be scoped to (``in_search_scope``).
    """
    return names_every_word(location, market) or in_search_scope(location, market)


def credited_source(url: str | None) -> str | None:
    """The job site an opening must be credited to wherever it is shown, or
    ``None`` when its link goes to the employer's own board."""
    host = (urlsplit(url or "").hostname or "").lower()
    for credited, name in _CREDITED_HOSTS.items():
        if host == credited or host.endswith(f".{credited}"):
            return name
    return None
