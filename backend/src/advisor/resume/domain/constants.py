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

# --- template_look -----------------------------------------------------------

# One page is what "trim" means; these keep a résumé on it. The preview drops
# what the PDF drops, by these same numbers (ADR 0038).
TRIMMED_BULLETS = 3

TRIMMED_SKILLS = 12

# The exported page, which the preview is laid out as: A4 and its margins.
PAGE_WIDTH_MM = 210

PAGE_HEIGHT_MM = 297

PAGE_MARGIN_TOP_MM = 18

PAGE_MARGIN_SIDE_MM = 17

# Type sizes on the page, in points.
NAME_PT = 22.0

TITLE_PT = 11.0

BODY_PT = 10.0

CONTACT_PT = 9.5

SMALL_PT = 9.0

HEADING_PT = 8.5

# The design system's families, bundled in the worker image and hosted by the
# SPA. DejaVu, which the image also carries, sets anything outside their Latin
# subset.
HEADING_FONT = "Caprasimo"

BODY_FONT = "Figtree"

FALLBACK_FONT = "DejaVu Sans"
