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

# --- section -----------------------------------------------------------------

# Every section a résumé can have at once: one of each kind, and a few of the
# user's own (ADR 0039).
MAX_SECTIONS = 9

MAX_CUSTOM_SECTIONS = 3

# A custom section's heading, the user's own words.
MAX_SECTION_TITLE = 60

MAX_SUMMARY = 1200

# A list item: one skill or one certification.
MAX_ITEM = 120

# A side project's or an open-source project's link, shown as text.
MAX_LINK = 200

# A dimension this far below the Target's bar still counts as partly covered.
# The prototype's threshold.
PARTIAL_WITHIN = 14

# --- template_spec: the built-in sizes -------------------------------------

# One page is what "trim" means; these keep a résumé on it. The preview drops
# what the PDF drops, by these same numbers (ADR 0038).
TRIMMED_BULLETS = 3

TRIMMED_SKILLS = 12

# The exported page, which the preview is laid out as: A4 and its margins.
PAGE_WIDTH_MM = 210

PAGE_HEIGHT_MM = 297

PAGE_MARGIN_TOP_MM = 18

PAGE_MARGIN_SIDE_MM = 17

# The built-in templates' type sizes, in points. An entry's title, the
# contact line and small print follow the body size (``get_derived_pt``).
NAME_PT = 22.0

BODY_PT = 10.0

HEADING_PT = 8.5

# The design system's families, bundled in the worker image and hosted by the
# SPA. DejaVu, which the image also carries, sets anything outside their Latin
# subset.
HEADING_FONT = "Caprasimo"

BODY_FONT = "Figtree"

FALLBACK_FONT = "DejaVu Sans"

# --- template_spec -----------------------------------------------------------

# Every font a template may name: bundled in the worker image and hosted by
# the SPA, so the PDF and the preview set the same type (ADR 0040).
TEMPLATE_FONTS = ("Caprasimo", "Figtree", "DejaVu Serif", "DejaVu Sans Mono")

# Type sizes a template may set, in points: (smallest, largest).
NAME_PT_RANGE = (16.0, 30.0)

HEADING_PT_RANGE = (7.0, 11.0)

BODY_PT_RANGE = (8.5, 11.5)

# The name and the text against the white page, WCAG AA for normal text.
MIN_CONTRAST = 4.5

MAX_TEMPLATE_NAME = 60
