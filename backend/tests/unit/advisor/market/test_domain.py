"""Dedup keys, expiry and salary bands. Pure — no crawler, no database."""

from __future__ import annotations

from datetime import date

import pytest

from advisor.market.domain import (
    ACCENT_FOLDS,
    COUNTRIES,
    MAX_CANONICAL_KEY,
    MAX_LOCATION,
    MAX_TARGET_LOCATIONS,
    REGIONS,
    NormalizedPosting,
    PlaceKind,
    SalaryRange,
    SearchScope,
    SourceKind,
    TargetLocationError,
    TargetLocationOption,
    band_from,
    canonical_key,
    chosen_target_locations,
    clip,
    credited_source,
    expired_keys,
    in_market,
    is_open_worldwide,
    market_words,
    names_every_word,
    normalize,
    normalize_title,
    place_names,
    regions_of,
    remote_location,
    scope_names,
    search_scope,
    target_location_option,
    target_location_options,
)


def key(company: str, title: str, location: str | None) -> str:
    return canonical_key(company=company, title=title, location=location)


def test_the_same_job_from_two_sources_collapses_to_one_key() -> None:
    board = key("Northwind Pay", "Senior Backend Engineer", "Berlin")
    career_page = key("northwind pay", "Senior  Backend  Engineer", "berlin")
    assert board == career_page


def test_gender_and_arrangement_decoration_does_not_split_a_job() -> None:
    assert key("Acme", "Senior Backend Engineer (m/f/d)", "Berlin") == key(
        "Acme", "Senior Backend Engineer", "Berlin"
    )
    assert key("Acme", "Backend Engineer (Remote)", "Berlin") == key(
        "Acme", "Backend Engineer", "Berlin"
    )


def test_accents_and_punctuation_do_not_split_a_job() -> None:
    assert key("Café Co", "Ingénieur Back-End", "Zürich") == key(
        "Cafe Co", "Ingenieur Back End", "Zurich"
    )


def test_genuinely_different_jobs_keep_different_keys() -> None:
    assert key("Acme", "Senior Backend Engineer", "Berlin") != key(
        "Acme", "Staff Backend Engineer", "Berlin"
    )
    assert key("Acme", "Senior Backend Engineer", "Berlin") != key(
        "Acme", "Senior Backend Engineer", "Munich"
    )
    assert key("Acme", "Senior Backend Engineer", "Berlin") != key(
        "Globex", "Senior Backend Engineer", "Berlin"
    )


def test_a_missing_location_is_still_a_stable_key() -> None:
    assert key("Acme", "Engineer", None) == key("Acme", "Engineer", None)
    assert key("Acme", "Engineer", None) != key("Acme", "Engineer", "Berlin")


def test_title_normalisation_keeps_meaningful_words() -> None:
    assert normalize_title("Senior Backend Engineer (m/f/d)") == "senior backend engineer"


def test_postings_missing_from_a_crawl_are_expired_not_deleted() -> None:
    known_open = {"a", "b", "c"}
    assert expired_keys(seen_now={"a", "c"}, known_open=known_open) == {"b"}


def test_a_crawl_that_sees_everything_expires_nothing() -> None:
    assert expired_keys(seen_now={"a", "b"}, known_open={"a", "b"}) == set()


def test_a_new_posting_does_not_expire_anything() -> None:
    assert expired_keys(seen_now={"a", "b", "new"}, known_open={"a", "b"}) == set()


def test_a_salary_range_cannot_be_inverted() -> None:
    with pytest.raises(ValueError, match="cannot start above"):
        SalaryRange(min_amount=200, max_amount=100, currency="EUR")


def test_a_band_needs_at_least_one_posting_with_pay() -> None:
    assert band_from([]) is None


def test_a_thin_band_is_still_shown_but_flagged() -> None:
    """A role is never hidden from the map just because the market is thin."""
    band = band_from([(80_000, 100_000, "EUR"), (90_000, 110_000, "EUR")])
    assert band is not None
    assert not band.is_confident
    assert band.currency == "EUR"


def test_a_well_sampled_band_is_confident() -> None:
    ranges = [(80_000 + i * 1_000, 100_000 + i * 1_000, "EUR") for i in range(6)]
    band = band_from(ranges)
    assert band is not None and band.is_confident
    assert band.low <= band.mid <= band.high


def test_a_band_ignores_postings_in_another_currency() -> None:
    band = band_from([(80_000, 100_000, "EUR"), (200_000, 240_000, "USD")])
    assert band is not None
    assert band.currency == "EUR" and band.sample_size == 1


def test_embedding_text_leads_with_the_title() -> None:
    posting = NormalizedPosting(
        external_id="1",
        company_name="Acme",
        title="Senior Backend Engineer",
        location="Berlin",
        description="You will build services.",
        url="https://acme.test/jobs/1",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=None,
    )
    assert posting.embedding_text.startswith("Senior Backend Engineer")
    assert "You will build services." in posting.embedding_text


# --- storage bounds --------------------------------------------------------


def _long_posting(location: str) -> NormalizedPosting:
    return NormalizedPosting(
        external_id="1",
        company_name="Datadog",
        title="Staff Application Security Engineer",
        location=location,
        description="Secure things.",
        url="https://boards.test/1",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=None,
        salary=None,
    )


EVERY_OFFICE = "; ".join(f"Remote, US State {n}" for n in range(60))


def test_a_location_listing_every_office_is_kept_to_what_storage_holds() -> None:
    posting = _long_posting(EVERY_OFFICE)

    assert posting.location is not None
    assert len(posting.location) == MAX_LOCATION
    assert posting.location.endswith("…")
    assert posting.location.startswith("Remote, US State 0")


def test_short_text_is_left_alone() -> None:
    assert clip("Berlin", MAX_LOCATION) == "Berlin"
    assert _long_posting("Berlin").location == "Berlin"


def test_an_overlong_key_is_bounded_stable_and_still_distinct() -> None:
    long_title = "engineer " * 120
    first = canonical_key(company="Acme", title=long_title + "one", location=None)
    second = canonical_key(company="Acme", title=long_title + "two", location=None)

    assert len(first) <= MAX_CANONICAL_KEY and len(second) <= MAX_CANONICAL_KEY
    assert first != second
    assert first == canonical_key(company="Acme", title=long_title + "one", location=None)
    # A key within bounds is unchanged, so every stored posting keeps its key.
    assert canonical_key(company="Acme", title="Engineer", location="Berlin") == (
        "acme|engineer|berlin"
    )


# -- markets -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "market"),
    [
        ("Berlin, Germany", "Berlin"),
        ("berlin", "Berlin"),
        ("Remote, United States", "Remote"),
        ("New York, NY", "New York"),
        ("Remote - EU", "Remote EU"),
        ("Zürich, Switzerland", "Zurich"),
        ("Zurich, Switzerland", "Zürich"),
    ],
)
def test_a_location_is_in_a_market_when_it_names_every_word_of_it(
    location: str, market: str
) -> None:
    assert in_market(location, market)


@pytest.mark.parametrize(
    ("location", "market"),
    [
        ("Berlin, Germany", "Munich"),
        ("York, UK", "New York"),
        (None, "Berlin"),
        ("Berlin", ""),
    ],
)
def test_a_location_missing_any_word_of_the_market_is_outside_it(
    location: str | None, market: str
) -> None:
    assert not in_market(location, market)


def test_market_words_are_plain_ascii_and_each_appears_once() -> None:
    assert market_words("  São Paulo / são-paulo ") == ("sao", "paulo")
    assert market_words("---") == ()


def test_the_database_folds_accents_exactly_as_normalize_does() -> None:
    accented, plain = ACCENT_FOLDS
    assert len(accented) == len(plain) and "ü" in accented and "é" in accented
    assert all(normalize(a) == p for a, p in zip(accented, plain, strict=True))


def test_target_locations_are_stored_under_their_names_on_the_list_each_once() -> None:
    assert chosen_target_locations([" germany ", "remote", "GERMANY", "Asia-Pacific"]) == (
        "Germany",
        "Remote",
        "Asia-Pacific",
    )


@pytest.mark.parametrize("place", ["Berlin", "Remote EU", "Taipei", "Atlantis", "UK"])
def test_a_place_not_on_the_list_is_refused(place: str) -> None:
    """Only names on the list are taken: a city, an alias or a free-text
    region is refused rather than silently matching nothing (ADR 0026)."""
    with pytest.raises(TargetLocationError):
        chosen_target_locations(["Germany", place])


def test_no_target_location_is_a_valid_choice() -> None:
    assert chosen_target_locations([]) == ()


def test_at_most_three_target_locations_are_chosen() -> None:
    assert MAX_TARGET_LOCATIONS == 3
    with pytest.raises(TargetLocationError):
        chosen_target_locations(["Germany", "Portugal", "France", "Remote"])


def test_a_blank_target_location_is_refused() -> None:
    with pytest.raises(TargetLocationError):
        chosen_target_locations(["Germany", "  "])


def test_a_role_title_takes_in_a_posting_naming_each_of_its_words_in_any_order() -> None:
    assert names_every_word("Backend Engineer, Staff", "Staff Backend")
    assert names_every_word("Ingénieur Backend", "ingenieur")
    assert not names_every_word("Staff Designer", "Staff Backend")
    assert not names_every_word("Anything", "  ")


# -- places a job API can be searched for (ADR 0025) --------------------------


@pytest.mark.parametrize(
    ("location", "label", "code"),
    [
        ("Taiwan", "Taiwan", "TW"),
        ("taiwan", "Taiwan", "TW"),
        ("Remote Taiwan", "Taiwan", "TW"),
        ("Singapore", "Singapore", "SG"),
        ("UK", "United Kingdom", "GB"),
        ("United Kingdom", "United Kingdom", "GB"),
        ("South Korea", "South Korea", "KR"),
        ("Remote", "Remote", None),
        ("remote", "Remote", None),
    ],
)
def test_a_country_or_remote_is_a_place_a_search_can_be_scoped_to(
    location: str, label: str, code: str | None
) -> None:
    scope = search_scope(location)

    assert scope == SearchScope(label=label, country_code=code)
    assert scope.is_worldwide == (code is None)


@pytest.mark.parametrize(
    "location", ["Taipei", "Taipei, Taiwan", "Remote EU", "Europe", "Asia-Pacific", "Berlin", ""]
)
def test_a_city_or_a_region_adds_no_search(location: str) -> None:
    """A posting stored for the search would not contain those words, so it
    would never be in that user's scope."""
    assert search_scope(location) is None


def test_a_change_to_a_country_reaches_the_users_of_its_regions_too() -> None:
    assert scope_names("United Kingdom") == ("United Kingdom", "Europe")
    assert scope_names("Taiwan") == ("Taiwan", "Asia-Pacific")
    assert scope_names("Mexico") == ("Mexico", "Latin America", "North America")
    assert scope_names("Remote") == ("Remote",)
    # A market that is not a search's place is only ever its own name.
    assert scope_names("Berlin") == ("Berlin",)


def test_a_remote_posting_names_the_countries_it_is_open_to() -> None:
    assert remote_location(["Taiwan", " Japan ", ""]) == "Remote, Taiwan, Japan"
    assert remote_location([]) == "Remote, Worldwide"


@pytest.mark.parametrize(
    "market", ["Taiwan", "Remote Taiwan", "Singapore", "Remote", "Europe", "Asia-Pacific"]
)
def test_remote_work_open_to_anyone_is_in_every_place_a_search_covers(market: str) -> None:
    assert in_market("Remote, Worldwide", market)


@pytest.mark.parametrize("market", ["Taipei", "Berlin", "Remote EU"])
def test_remote_work_open_to_anyone_is_not_in_a_place_no_search_covers(market: str) -> None:
    assert not in_market("Remote, Worldwide", market)


def test_remote_work_open_to_other_countries_is_not_in_this_one() -> None:
    assert not in_market("Remote, Argentina", "Taiwan")
    assert in_market("Remote, Taiwan, Japan", "Taiwan")
    assert in_market("Remote, Taiwan, Japan", "Remote Taiwan")


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Remote, Worldwide", True),
        ("Worldwide (remote)", True),
        ("Remote, Taiwan", False),
        (None, False),
    ],
)
def test_a_posting_says_when_it_is_open_worldwide(location: str | None, expected: bool) -> None:
    assert is_open_worldwide(location) is expected


@pytest.mark.parametrize(
    ("url", "credit"),
    [
        ("https://himalayas.app/companies/acme/jobs/engineer", "Himalayas"),
        ("https://www.himalayas.app/companies/acme/jobs/engineer", "Himalayas"),
        ("https://boards.greenhouse.io/acme/jobs/1", None),
        ("https://nothimalayas.app/jobs/1", None),
        ("", None),
        (None, None),
    ],
)
def test_an_opening_found_through_a_job_site_is_credited_to_it(
    url: str | None, credit: str | None
) -> None:
    assert credited_source(url) == credit


# -- the list of places (ADR 0026) ---------------------------------------------


def test_the_list_is_remote_then_regions_then_countries_each_a_to_z() -> None:
    options = target_location_options()
    kinds = [option.kind for option in options]

    assert options[0] == TargetLocationOption("Remote", PlaceKind.REMOTE)
    assert kinds == sorted(kinds, key=[PlaceKind.REMOTE, PlaceKind.REGION, PlaceKind.COUNTRY].index)
    for kind in (PlaceKind.REGION, PlaceKind.COUNTRY):
        names = [option.name for option in options if option.kind is kind]
        assert names == sorted(names)
    assert len({option.name for option in options}) == len(options)


def test_every_country_is_listed_once_under_one_name() -> None:
    countries = [o.name for o in target_location_options() if o.kind is PlaceKind.COUNTRY]
    assert len(countries) == len(COUNTRIES) == len({c.code for c in COUNTRIES})
    assert "United Kingdom" in countries and "UK" not in countries


def test_every_country_is_in_at_least_one_region() -> None:
    in_a_region = {code for region in REGIONS for code in region.country_codes}
    assert {country.code for country in COUNTRIES} <= in_a_region
    assert regions_of("Taiwan") == ("Asia-Pacific",)


def test_a_place_on_the_list_is_found_whatever_its_case() -> None:
    assert target_location_option("united kingdom") == TargetLocationOption(
        "United Kingdom", PlaceKind.COUNTRY
    )
    assert target_location_option("Taipei") is None


@pytest.mark.parametrize(
    ("location", "market"),
    [
        ("Taipei", "Taiwan"),
        ("Hsinchu, TW", "Taiwan"),
        ("London, England", "United Kingdom"),
        ("Remote - UK", "United Kingdom"),
        ("Berlin, Germany", "Europe"),
        ("Lisbon", "Europe"),
        ("Remote, EMEA", "Europe"),
        ("Singapore", "Asia-Pacific"),
        ("Taipei", "Asia-Pacific"),
        ("Austin, TX, US", "North America"),
        ("Remote, Worldwide", "Latin America"),
    ],
)
def test_a_country_takes_in_its_cities_and_a_region_its_countries(
    location: str, market: str
) -> None:
    assert in_market(location, market)


@pytest.mark.parametrize(
    ("location", "market"),
    [
        ("Tokyo", "Taiwan"),
        ("Taipei", "Europe"),
        ("Berlin, Germany", "Asia-Pacific"),
        ("Remote, Argentina", "Europe"),
    ],
)
def test_a_place_does_not_take_in_another_places_cities(location: str, market: str) -> None:
    assert not in_market(location, market)


def test_a_region_names_itself_its_countries_and_their_cities() -> None:
    names = place_names("Asia-Pacific")

    assert names[:3] == ("Asia-Pacific", "APAC", "Asia Pacific")
    assert {"Taiwan", "Taipei", "Singapore", "Japan", "Tokyo"} <= set(names)
    assert len(names) == len(set(names))
    assert place_names("Taiwan")[:1] == ("Taiwan",) and "Kaohsiung" in place_names("Taiwan")
    assert place_names("Remote") == ("Remote",)
