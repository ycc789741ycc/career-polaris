"""How the market reads words: names, titles and places normalised the same
way everywhere, so they can be compared.

Accents are folded to ASCII, case and punctuation dropped, and decoration that
says nothing about which job it is ("(m/f/d)", "(remote)") stripped from
titles. Companies, postings, places and searches all compare through these
rules, which is why they live in a concept of their own rather than in any one
of them.
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_NOISE = re.compile(r"[^a-z0-9 ]+")

# Decoration that carries no information about which job this is. Stripped so
# "Senior Backend Engineer (m/f/d)" and "Senior Backend Engineer" are one job.
_TITLE_NOISE = (
    r"\(m/f/d\)",
    r"\(m/w/d\)",
    r"\(f/m/d\)",
    r"\(all genders\)",
    r"\(remote\)",
    r"\(hybrid\)",
    r"\(onsite\)",
    r"\(full[- ]time\)",
    r"\(part[- ]time\)",
    r"\(contract\)",
    r"\(intern\)",
)
_TITLE_NOISE_RE = re.compile("|".join(_TITLE_NOISE), re.IGNORECASE)


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _WHITESPACE.sub(" ", _NOISE.sub(" ", folded.lower())).strip()


def normalize_title(title: str) -> str:
    return normalize(_TITLE_NOISE_RE.sub(" ", title))


def names_every_word(text: str | None, phrase: str) -> bool:
    """Whether ``text`` contains every word of ``phrase``, accent-folded and in
    any order. The one word rule for a location in a market and for a posting
    matching a role the user named ("Staff Backend" takes in "Backend Engineer,
    Staff")."""
    wanted = set(market_words(phrase))
    return bool(wanted) and wanted <= set(normalize(text or "").split())


def market_words(market: str) -> tuple[str, ...]:
    """The words a location must contain to be in ``market``: lowercase ASCII
    letters and digits only, so they are safe inside a database pattern."""
    return tuple(dict.fromkeys(normalize(market).split()))


def _accent_folds() -> tuple[str, str]:
    """Each lowercase accented Latin letter and the ASCII letter ``normalize``
    turns it into, for a database to fold a location the same way."""
    accented, plain = [], []
    for code in range(0xC0, 0x250):
        char = chr(code)
        if char != char.lower():
            continue
        folded = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
        if len(folded) == 1 and folded.isalpha():
            accented.append(char)
            plain.append(folded.lower())
    return "".join(accented), "".join(plain)


# ("àáâ…", "aaa…"): what SQL's translate() needs to match ``market_words``.
ACCENT_FOLDS = _accent_folds()


def clip(text: str, limit: int) -> str:
    """Text cut to at most ``limit`` characters, marked with an ellipsis when cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
