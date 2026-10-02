"""Target's named values: what a posting of the user's own may hold.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- own_posting -------------------------------------------------------------

# A posting of the user's own's job title, as long as a role's title.
MAX_TITLE = 255

MAX_COMPANY_NAME = 255

# The most of a JD that is stored: a JD longer than this is not a JD.
MAX_JOB_DESCRIPTION = 50_000
