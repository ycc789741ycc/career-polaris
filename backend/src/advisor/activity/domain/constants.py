"""Activity's named values.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- stages ------------------------------------------------------------------

# The code a lost job is reported with, next to the codes a job fails with.
STALE = "stale"
