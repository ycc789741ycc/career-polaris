"""The market's named values: limits, thresholds and fixed names.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- target_locations --------------------------------------------------------

# A user works toward one to three places from a fixed list: "Remote", a
# region or a country (domain decision 21, ADR 0026). The cap keeps a first
# role map affordable and the map legible.
MAX_TARGET_LOCATIONS = 3

MAX_TARGET_LOCATION = 128


# --- pay_text ----------------------------------------------------------------

# Below this a figure is an hourly rate or not pay at all; above it, not a salary.
MIN_YEARLY_AMOUNT = 10_000

MAX_YEARLY_AMOUNT = 100_000_000


# --- places ------------------------------------------------------------------

REMOTE = "Remote"


# --- posting -----------------------------------------------------------------

# The longest text a posting keeps. A board can list every office an opening is
# open in as its "location"; the posting keeps the start of it rather than
# failing to store at all.
MAX_COMPANY_NAME = 255

MAX_TITLE = 512

MAX_LOCATION = 255

MAX_CANONICAL_KEY = 768


# --- salary ------------------------------------------------------------------

# Below this many postings a band is shown, but flagged: a role is not hidden
# from a user's map just because their market is thin (domain section 2.5).
CONFIDENT_SAMPLE_SIZE = 5


# --- search ------------------------------------------------------------------

WORLDWIDE = "Worldwide"

WORLDWIDE_LOCATION = f"{REMOTE}, {WORLDWIDE}"
