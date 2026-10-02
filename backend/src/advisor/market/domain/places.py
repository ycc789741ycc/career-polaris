"""The places a user can choose to work in (domain decision 21, ADR 0026).

A target location is one of a fixed list: "Remote", a region, or a country.
Each kind has a known way to be matched against a posting's location, and,
where it can be, searched on a public job API (ADR 0025):

* **Remote**: remote work open to anyone. Searched worldwide.
* **A country**: its names and its main cities, since company boards often
  write only the city ("Taipei"). Searched by its ISO 3166-1 alpha-2 code.
* **A region**: a named set of countries, matched by any member's names and
  cities. Never searched: a job API filters by one country at a time, so a
  region would be one search per member country for every candidate title.

The tables here are data reviewed like code. Adding a country, a city or a
region to them adds it to the list the user picks from.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from advisor.market.domain.posting import market_words, normalize

REMOTE = "Remote"


class PlaceKind(StrEnum):
    REMOTE = "remote"
    REGION = "region"
    COUNTRY = "country"


@dataclass(frozen=True, slots=True)
class Country:
    """A country: ``name`` is the one the platform files it under, ``aliases``
    the other ways users and boards write it, ``cities`` the places a board may
    name instead of it."""

    name: str
    code: str
    aliases: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True, slots=True)
class Region:
    """A named set of countries. ``aliases`` are how a posting may name the
    region itself ("Remote - EMEA")."""

    name: str
    country_codes: tuple[str, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TargetLocationOption:
    """One place on the list the user picks from."""

    name: str
    kind: PlaceKind


# Cities are a country's main hiring places. A missing one quietly drops that
# city's board postings for the country, so grow the list from the locations
# the crawler actually sees. A city that is also a country elsewhere, or a
# common word, stays out ("Cambridge", "Washington", "Santiago").
COUNTRIES: tuple[Country, ...] = (
    Country("Argentina", "AR", cities=("Buenos Aires", "Cordoba", "Rosario")),
    Country(
        "Australia",
        "AU",
        cities=("Sydney", "Melbourne", "Brisbane", "Perth", "Canberra", "Adelaide"),
    ),
    Country("Austria", "AT", cities=("Vienna", "Wien", "Graz", "Linz")),
    Country("Belgium", "BE", cities=("Brussels", "Antwerp", "Ghent")),
    Country(
        "Brazil",
        "BR",
        aliases=("Brasil",),
        cities=("Sao Paulo", "Rio de Janeiro", "Belo Horizonte", "Florianopolis", "Curitiba"),
    ),
    Country(
        "Canada",
        "CA",
        cities=("Toronto", "Vancouver", "Montreal", "Ottawa", "Calgary", "Waterloo"),
    ),
    Country("Chile", "CL"),
    Country("China", "CN", cities=("Beijing", "Shanghai", "Shenzhen", "Hangzhou", "Guangzhou")),
    Country("Colombia", "CO", cities=("Bogota", "Medellin")),
    Country("Czechia", "CZ", aliases=("Czech Republic",), cities=("Prague", "Brno")),
    Country("Denmark", "DK", cities=("Copenhagen", "Aarhus")),
    Country("Estonia", "EE", cities=("Tallinn", "Tartu")),
    Country("Finland", "FI", cities=("Helsinki", "Espoo", "Tampere")),
    Country(
        "France", "FR", cities=("Paris", "Lyon", "Toulouse", "Nantes", "Bordeaux", "Marseille")
    ),
    Country(
        "Germany",
        "DE",
        aliases=("Deutschland",),
        cities=(
            "Berlin",
            "Munich",
            "Munchen",
            "Hamburg",
            "Frankfurt",
            "Cologne",
            "Stuttgart",
            "Dusseldorf",
        ),
    ),
    Country("Greece", "GR", cities=("Athens", "Thessaloniki")),
    Country("Hong Kong", "HK", cities=("Kowloon",)),
    Country("Hungary", "HU", cities=("Budapest",)),
    Country(
        "India",
        "IN",
        cities=(
            "Bengaluru",
            "Bangalore",
            "Hyderabad",
            "Pune",
            "Mumbai",
            "Chennai",
            "Delhi",
            "Gurugram",
            "Gurgaon",
            "Noida",
        ),
    ),
    Country("Indonesia", "ID", cities=("Jakarta", "Bandung")),
    Country("Ireland", "IE", cities=("Dublin", "Cork", "Galway")),
    Country("Israel", "IL", cities=("Tel Aviv", "Jerusalem", "Haifa", "Herzliya")),
    Country("Italy", "IT", cities=("Milan", "Rome", "Turin", "Bologna")),
    Country("Japan", "JP", cities=("Tokyo", "Osaka", "Kyoto", "Fukuoka", "Yokohama")),
    Country("Malaysia", "MY", cities=("Kuala Lumpur", "Penang", "Cyberjaya")),
    Country("Mexico", "MX", cities=("Guadalajara", "Monterrey")),
    Country(
        "Netherlands",
        "NL",
        aliases=("The Netherlands",),
        cities=("Amsterdam", "Rotterdam", "Utrecht", "The Hague", "Eindhoven"),
    ),
    Country("New Zealand", "NZ", cities=("Auckland", "Wellington", "Christchurch")),
    Country("Norway", "NO", cities=("Oslo", "Bergen", "Trondheim")),
    Country("Philippines", "PH", cities=("Manila", "Makati", "Taguig", "Cebu")),
    Country("Poland", "PL", cities=("Warsaw", "Krakow", "Wroclaw", "Gdansk", "Poznan")),
    Country("Portugal", "PT", cities=("Lisbon", "Porto", "Braga")),
    Country("Romania", "RO", cities=("Bucharest", "Cluj Napoca", "Iasi")),
    Country("Singapore", "SG"),
    Country("South Africa", "ZA", cities=("Cape Town", "Johannesburg", "Durban", "Pretoria")),
    Country("South Korea", "KR", aliases=("Korea",), cities=("Seoul", "Busan", "Pangyo")),
    Country("Spain", "ES", cities=("Madrid", "Barcelona", "Valencia", "Malaga", "Seville")),
    Country("Sweden", "SE", cities=("Stockholm", "Gothenburg", "Malmo")),
    Country("Switzerland", "CH", cities=("Zurich", "Geneva", "Basel", "Lausanne", "Bern", "Zug")),
    Country(
        "Taiwan",
        "TW",
        cities=("Taipei", "Hsinchu", "Taichung", "Kaohsiung", "Tainan", "Taoyuan"),
    ),
    Country("Thailand", "TH", cities=("Bangkok", "Chiang Mai")),
    Country("Turkey", "TR", aliases=("Turkiye",), cities=("Istanbul", "Ankara", "Izmir")),
    Country("Ukraine", "UA", cities=("Kyiv", "Kiev", "Lviv", "Kharkiv")),
    Country("United Arab Emirates", "AE", aliases=("UAE",), cities=("Dubai", "Abu Dhabi")),
    Country(
        "United Kingdom",
        "GB",
        aliases=("UK", "Great Britain", "England", "Scotland"),
        cities=("London", "Manchester", "Edinburgh", "Bristol", "Glasgow", "Belfast", "Leeds"),
    ),
    Country(
        "United States",
        "US",
        aliases=("USA", "US"),
        cities=(
            "New York",
            "San Francisco",
            "Seattle",
            "Austin",
            "Boston",
            "Los Angeles",
            "Chicago",
            "Denver",
            "Atlanta",
            "Mountain View",
            "Palo Alto",
            "Sunnyvale",
            "San Diego",
            "Miami",
            "Dallas",
            "Houston",
        ),
    ),
    Country("Vietnam", "VN", aliases=("Viet Nam",), cities=("Ho Chi Minh", "Hanoi", "Da Nang")),
)

# Every country belongs to at least one region, so any market a country user
# sees, a region user can choose too.
REGIONS: tuple[Region, ...] = (
    Region(
        "Asia-Pacific",
        (
            "AU",
            "CN",
            "HK",
            "ID",
            "IN",
            "JP",
            "KR",
            "MY",
            "NZ",
            "PH",
            "SG",
            "TH",
            "TW",
            "VN",
        ),
        aliases=("APAC", "Asia Pacific"),
    ),
    Region(
        "Europe",
        (
            "AT",
            "BE",
            "CH",
            "CZ",
            "DE",
            "DK",
            "EE",
            "ES",
            "FI",
            "FR",
            "GB",
            "GR",
            "HU",
            "IE",
            "IT",
            "NL",
            "NO",
            "PL",
            "PT",
            "RO",
            "SE",
            "TR",
            "UA",
        ),
        aliases=("EU", "EMEA"),
    ),
    Region("Latin America", ("AR", "BR", "CL", "CO", "MX"), aliases=("LATAM",)),
    Region("Middle East & Africa", ("AE", "IL", "ZA"), aliases=("EMEA",)),
    Region("North America", ("CA", "MX", "US")),
)

_BY_CODE: dict[str, Country] = {country.code: country for country in COUNTRIES}
_BY_NAME: dict[str, TargetLocationOption] = {}


def target_location_options() -> tuple[TargetLocationOption, ...]:
    """ "Remote", then the regions, then the countries, each group A to Z."""
    return (
        TargetLocationOption(REMOTE, PlaceKind.REMOTE),
        *(
            TargetLocationOption(region.name, PlaceKind.REGION)
            for region in sorted(REGIONS, key=lambda r: r.name)
        ),
        *(
            TargetLocationOption(country.name, PlaceKind.COUNTRY)
            for country in sorted(COUNTRIES, key=lambda c: c.name)
        ),
    )


for _option in target_location_options():
    _BY_NAME[normalize(_option.name)] = _option


def target_location_option(value: str) -> TargetLocationOption | None:
    """The option ``value`` names, ignoring case and accents, or ``None`` when
    it is not on the list."""
    return _BY_NAME.get(normalize(value))


def country_named(name: str) -> Country | None:
    """The country filed under ``name``, or ``None``."""
    option = target_location_option(name)
    if option is None or option.kind is not PlaceKind.COUNTRY:
        return None
    return next(country for country in COUNTRIES if country.name == option.name)


def region_named(name: str) -> Region | None:
    """The region filed under ``name``, or ``None``."""
    option = target_location_option(name)
    if option is None or option.kind is not PlaceKind.REGION:
        return None
    return next(region for region in REGIONS if region.name == option.name)


def place_names(market: str) -> tuple[str, ...]:
    """Every name a posting's location may use for ``market``: a country's
    names and cities; for a region, its own names and every member's; for
    "Remote", itself. Anything not on the list is only its own name."""
    if (country := country_named(market)) is not None:
        return (*country.names, *country.cities)
    if (region := region_named(market)) is not None:
        names: list[str] = [region.name, *region.aliases]
        for code in region.country_codes:
            member = _BY_CODE[code]
            names += [*member.names, *member.cities]
        return tuple(dict.fromkeys(names))
    option = target_location_option(market)
    return (option.name,) if option is not None else (market,)


def regions_of(country_name: str) -> tuple[str, ...]:
    """The regions a country belongs to, A to Z."""
    country = country_named(country_name)
    if country is None:
        return ()
    return tuple(sorted(region.name for region in REGIONS if country.code in region.country_codes))


def names_a_place(location: str | None, market: str) -> bool:
    """Whether ``location`` contains every word of one of ``market``'s names."""
    found = set(market_words(location or ""))
    return any(
        (words := set(market_words(name))) and words <= found for name in place_names(market)
    )
