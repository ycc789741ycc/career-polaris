"""The résumé's named values: how long and how many.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- content -----------------------------------------------------------------

MAX_ROLES = 6

MAX_BULLETS_PER_ROLE = 8

MAX_SKILLS = 30

MAX_TEXT = 600

# A dimension this far below the Target's bar still counts as partly covered.
# The prototype's threshold.
PARTIAL_WITHIN = 14
