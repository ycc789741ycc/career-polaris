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

# The sections a résumé shows at once (ADR 0039, ADR 0043).
MAX_SECTIONS = 9

MAX_CUSTOM_SECTIONS = 3

# Every section a résumé holds, shown or hidden: one of each of the eight
# built-in kinds, and the user's own (ADR 0043).
MAX_HELD_SECTIONS = 8 + MAX_CUSTOM_SECTIONS

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
TEMPLATE_FONTS = (
    "Caprasimo",
    "Figtree",
    "DejaVu Serif",
    "DejaVu Sans Mono",
    "Inter",
    "Lato",
    "Source Serif 4",
    "Merriweather",
    "EB Garamond",
    "IBM Plex Mono",
)

# Type sizes a template may set, in points: (smallest, largest).
NAME_PT_RANGE = (16.0, 30.0)

HEADING_PT_RANGE = (7.0, 11.0)

BODY_PT_RANGE = (8.5, 11.5)

# The name and the text against the white page, WCAG AA for normal text.
MIN_CONTRAST = 4.5

MAX_TEMPLATE_NAME = 60

# --- tailored_resume -----------------------------------------------------------

# Each stage's share of writing a résumé or a section, (start, end) of 0 to 1
# (ADR 0042).
RESUME_STAGE_SHARES = {
    "reading": (0.0, 0.1),
    "writing": (0.1, 0.85),
    "checking": (0.85, 0.95),
    "saving": (0.95, 1.0),
}

# --- template_reading ----------------------------------------------------------

# A column is a share of the page's runs starting at one x: at least this.
SIDEBAR_MIN_SHARE = 0.15

# Two columns' starts at least this share of the page's width apart.
SIDEBAR_MIN_GAP = 0.25

# Runs whose starts lie within this share of the page's width are one column:
# an icon before a line (a contact detail's) moves its text this far at most.
COLUMN_BAND = 0.04

# A reading never saved as a template is forgotten after a day (ADR 0041).
TEMPLATE_READING_KEEP_SECONDS = 86_400

# --- contact details (ADR 0048) ------------------------------------------------

MAX_CONTACTS = 8

MAX_CONTACT = 200

# Each contact kind's icon, as the path of a 24-unit square SVG, drawn inline
# by the PDF and the preview alike so nothing is fetched. The GitHub and
# LinkedIn marks are from Simple Icons (CC0); the rest from Material Icons
# (Apache 2.0).
CONTACT_ICONS: dict[str, str] = {
    "email": (
        "M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2z"
        "m0 4l-8 5-8-5V6l8 5 8-5v2z"
    ),
    "phone": (
        "M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 "
        "1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 "
        "0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 "
        "1.02l-2.2 2.2z"
    ),
    "github": (
        "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258"
        ".82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 "
        "3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 "
        "1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-"
        "5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 "
        "0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 "
        "2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 "
        "1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 "
        "2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627"
        "-5.373-12-12-12"
    ),
    "linkedin": (
        "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 "
        "1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 "
        "3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 "
        "0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-"
        "2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 "
        "1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 "
        ".774 23.2 0 22.222 0h.003z"
    ),
    "website": (
        "M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 "
        "11.99 2zm6.93 6h-2.95c-.32-1.25-.78-2.45-1.38-3.56 1.84.63 3.37 1.91 4.33 3.56z"
        "M12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 "
        "14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2 0 .68.06 "
        "1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56-1.84-.63-3.37-1.9-4.33-3.56z"
        "m2.95-8H5.08c.96-1.66 2.49-2.93 4.33-3.56C8.81 5.55 8.35 6.75 8.03 8zM12 19.96c"
        "-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c"
        "-.09-.66-.16-1.32-.16-2 0-.68.07-1.35.16-2h4.68c.09.65.16 1.32.16 2 0 .68-.07 "
        "1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95c-.96 1.65-2.49 2.93-4.33 "
        "3.56zM16.36 14c.08-.66.14-1.32.14-2 0-.68-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 "
        "2s-.1 1.36-.26 2h-3.38z"
    ),
    "location": (
        "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c"
        "-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"
    ),
}
