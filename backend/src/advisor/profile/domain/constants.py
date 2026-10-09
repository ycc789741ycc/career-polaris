"""The profile's named values.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- connection ----------------------------------------------------------------

# A token this close to expiring is refreshed before a sync uses it, so it
# cannot run out halfway through one. Atlassian's last an hour.
TOKEN_REFRESH_MARGIN_SECONDS = 300
