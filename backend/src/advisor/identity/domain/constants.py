"""Identity's named values: password, lockout and token limits.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

from datetime import timedelta

# --- password ----------------------------------------------------------------

MIN_PASSWORD_LENGTH = 12

MAX_PASSWORD_LENGTH = 200

MAX_FAILED_ATTEMPTS = 5

LOCKOUT_WINDOW = timedelta(minutes=15)


# --- tokens ------------------------------------------------------------------

# Long enough that guessing is hopeless; opaque, so it carries no claims.
REFRESH_TOKEN_BYTES = 32
