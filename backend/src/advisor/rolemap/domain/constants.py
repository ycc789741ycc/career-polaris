"""The role map's named values: limits, thresholds and counts.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- role --------------------------------------------------------------------

# A role's title, as an analysis recommends it and a build names it.
MAX_ROLE_TITLE = 255

# The most requirements one role is read out with. A fit is projected over them,
# so it also bounds what scoring a role's fit can cost.
MAX_ROLE_REQUIREMENTS = 20


# --- candidate ---------------------------------------------------------------

# The most dimensions an analysis hands over with its candidates. A fit is
# projected over them, so with the requirements they bound what scoring one
# role can cost, priced before any dimension exists.
MAX_STRENGTHS = 10


# --- fit -----------------------------------------------------------------------

# How much an opening's stress on a requirement moves that requirement's weight
# for the opening: its weight is scaled by 1 + this x the requirement's
# similarity to the opening, less its mean over the role's openings (Phase 8).
OPENING_EMPHASIS = 4.0

# The least an opening's weight on a requirement can be scaled by before it
# counts the requirement as not asked for, and the most it can be scaled by.
OPENING_WEIGHT_FLOOR = 0.25

OPENING_WEIGHT_CEILING = 2.0


# --- hiring_bar --------------------------------------------------------------

# Below this many distinct reporters a company+title figure could be traced
# back to one person, so the estimate is used instead.
MIN_REPORTERS = 3


# --- lineage -----------------------------------------------------------------

# Below this overlap, two groups of postings are not the same role.
SAME_ROLE_THRESHOLD = 0.5


# --- matches -----------------------------------------------------------------

MIN_MATCHES = 1

MAX_MATCHES = 50

DEFAULT_MATCHES = 10


# --- selection ---------------------------------------------------------------

# Below this, a candidate has no openings worth naming a role after.
MIN_POSTINGS_FOR_A_ROLE = 3

# The least cosine at which a posting counts as an opening for a candidate it
# does not name by title. Set for all-MiniLM-L6-v2 over a candidate's title and
# description against a posting's title and description.
CANDIDATE_MATCH_THRESHOLD = 0.40

# How much a dimension a candidate does not rest on counts in its estimate,
# beside the ones the analysis said it rests on (ADR 0027).
UNCITED_DIMENSION_WEIGHT = 0.25
