"""Fill the gap's named values: how many gaps, questions and choices.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- questions ---------------------------------------------------------------

# The costliest gaps of a Target are asked about, as the gap plan shows them.
ASKED_GAPS = 4

MAX_QUESTIONS_PER_GAP = 3

MIN_CHOICES = 2

MAX_CHOICES = 5

MAX_QUESTION_CHARS = 400

MAX_ANSWER_CHARS = 2000
