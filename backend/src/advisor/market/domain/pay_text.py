"""Pay written into a posting's text.

Most boards leave their structured compensation fields empty, yet pay-
transparency laws mean many descriptions state a range outright — "United
States Salary Range $139,200 — $235,200 USD". This reads that range, so a role
still gets a salary band when the board gave none in its own fields.

Every amount the market keeps is a year's pay, because that is what a band
compares and what the role map says it shows. ``yearly_range`` holds that rule
for pay a board published in its own fields too.

Only a range with a currency counts, and only a yearly one: a single figure,
an hourly or monthly rate, or "$100M-$200M raised" is left alone. A wrong
salary is worse than none, because it moves a whole band.
"""

from __future__ import annotations

import html
import re

from advisor.market.domain.constants import MAX_YEARLY_AMOUNT, MIN_YEARLY_AMOUNT
from advisor.market.domain.posting import SalaryRange

_CODES = ("USD", "EUR", "GBP", "CAD", "AUD", "CHF", "SEK", "NOK", "DKK", "PLN", "SGD", "NZD")
# Longest first, so "CA$" is read before "$".
_SYMBOLS = {"CA$": "CAD", "C$": "CAD", "AU$": "AUD", "A$": "AUD", "US$": "USD", "$": "USD"}
_SYMBOLS |= {"€": "EUR", "£": "GBP"}

_CURRENCY_MARKERS = [re.escape(s) for s in sorted(_SYMBOLS, key=len, reverse=True)]
_CURRENCY_MARKERS += [rf"\b{code}\b" for code in _CODES]
_CUR = f"(?:{'|'.join(_CURRENCY_MARKERS)})"
_AMOUNT = r"\d[\d,.]*\d|\d"
_RANGE = re.compile(
    rf"(?P<c1>{_CUR})?\s?(?P<a1>{_AMOUNT})\s?(?P<k1>[kK]\b)?\s?(?P<c2>{_CUR})?"
    r"\s*(?:-|\u2013|\u2014|\bto\b|\band\b)\s*"
    rf"(?P<c3>{_CUR})?\s?(?P<a2>{_AMOUNT})\s?(?P<k2>[kK]\b)?\s?(?P<c4>{_CUR})?"
)
# What follows a range and makes it something other than a yearly salary.
_SCALE_AFTER = re.compile(r"\s?(?:m|mm|b|bn|million|billion)\b", re.IGNORECASE)
_NOT_YEARLY = re.compile(
    r"\b(?:hour|hourly|hr|month|monthly|week|weekly|day|daily)\b|/\s?(?:h|hr|mo|wk)\b",
    re.IGNORECASE,
)
_PERIOD_WINDOW = 30
_THOUSANDS = re.compile(r"^\d{1,3}(?:[,.]\d{3})+(?:[.,]\d{1,2})?$")
# How boards say "a year": Lever's "per-year-salary", Ashby's "1 YEAR",
# schema.org's "YEAR", Himalayas' "annual".
_YEARLY_PERIOD = re.compile(r"year|annual", re.IGNORECASE)


def yearly_range(
    low: int, high: int, currency: str, *, period: str | None = None
) -> SalaryRange | None:
    """The range as a year's pay, or ``None`` when it is not one.

    A ``period`` a board stated must be yearly: an hourly or monthly rate is
    dropped rather than converted, since converting means guessing the hours.
    With no period stated, an amount outside a plausible year's pay is dropped.
    Never raises.
    """
    if period and not _YEARLY_PERIOD.search(period):
        return None
    if low > high or low < MIN_YEARLY_AMOUNT or high > MAX_YEARLY_AMOUNT:
        return None
    return SalaryRange(min_amount=low, max_amount=high, currency=currency)


def salary_in_text(text: str) -> SalaryRange | None:
    """The first yearly pay range stated in ``text``, or ``None``. Never raises."""
    plain = " ".join(html.unescape(text or "").split())
    for match in _RANGE.finditer(plain):
        found = _range_from(match, tail=plain[match.end() : match.end() + _PERIOD_WINDOW])
        if found is not None:
            return found
    return None


def _range_from(match: re.Match[str], *, tail: str) -> SalaryRange | None:
    currency = _currency(match.group("c1", "c2", "c3", "c4"))
    if currency is None or _SCALE_AFTER.match(tail) or _NOT_YEARLY.search(tail):
        return None
    high = _amount(match["a2"], thousands=bool(match["k2"]))
    # "80-95k": a k written once scales a bare low end too, but not "$80,000-$95k".
    bare_low = match["a1"].isdigit() and int(match["a1"]) < 1000
    low = _amount(match["a1"], thousands=bool(match["k1"]) or (bool(match["k2"]) and bare_low))
    if low is None or high is None:
        return None
    return yearly_range(low, high, currency)


def _currency(markers: tuple[str | None, ...]) -> str | None:
    """An ISO code written out wins over a symbol: "$120,000 CAD" is Canadian."""
    written = [m for m in markers if m]
    for marker in written:
        if marker in _CODES:
            return marker
    return _SYMBOLS.get(written[0]) if written else None


def _amount(raw: str, *, thousands: bool) -> int | None:
    if thousands:
        try:
            return round(float(raw.replace(",", ".")) * 1000)
        except ValueError:
            return None
    if _THOUSANDS.match(raw):
        # "139,200.00" and "80.000" alike: drop cents, then the group separators.
        whole = re.sub(r"[.,]\d{1,2}$", "", raw)
        return int(re.sub(r"[,.]", "", whole))
    return int(raw) if raw.isdigit() else None
