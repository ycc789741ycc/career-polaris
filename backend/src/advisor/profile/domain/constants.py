"""The profile's named values.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- connection ----------------------------------------------------------------

# A token this close to expiring is refreshed before a sync uses it, so it
# cannot run out halfway through one. Atlassian's last an hour.
TOKEN_REFRESH_MARGIN_SECONDS = 300

# --- account_report (ADR 0061) ---------------------------------------------------

# How often Atlassian expects each account reported, unless its reply names
# another period in a Cycle-Period header.
REPORT_CYCLE_SECONDS = 7 * 24 * 60 * 60

# Each report runs up to this much later than its cycle, so reports do not
# bunch up at the times they started, as Atlassian asks.
REPORT_JITTER_SECONDS = 15 * 60

# A report that could not be sent, or was not configured, is tried again
# after this long rather than dropped: the chain must not end on a bad day.
REPORT_RETRY_SECONDS = 24 * 60 * 60
