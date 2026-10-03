"""The gap plan's named values: how many milestones, tasks and projects.

A leaf: it imports only the standard library, so every module in the domain
can use it. Each group is headed by the module whose rules use it.
"""

from __future__ import annotations

# --- plan --------------------------------------------------------------------

# Each stage's share of drafting a plan, (start, end) of 0 to 1 (ADR 0042).
PLAN_STAGE_SHARES = {
    "reading": (0.0, 0.1),
    "drafting": (0.1, 0.85),
    "checking": (0.85, 0.95),
    "saving": (0.95, 1.0),
}

MIN_MILESTONES = 2

MAX_MILESTONES = 5

MIN_TASKS_PER_MILESTONE = 2

MAX_TASKS_PER_MILESTONE = 5

MAX_PROJECTS = 4

# The prototype's "The four things between you and …": enough to act on, few
# enough that the first one is obviously first.
SHOWN_GAPS = 4

# A gap's bar is drawn out of this many fit points, or out of the plan's
# largest lift when one is larger.
LIFT_SCALE_FLOOR = 10

# Two tasks are the same piece of work when they close a common gap and share
# this much of their wording. Regenerating rewords tasks; it should not make
# finished work look unfinished.
TASK_MATCH_THRESHOLD = 0.6

MAX_STEPPING_STONES = 3
