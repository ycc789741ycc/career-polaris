"""The activity component.

What background work is running across the journey, and the rules for when
the next stage may start (ADR 0018). It has no tables.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``activity-public-surface``).
"""

from advisor.activity.service import ActivityService, ActivityView, PendingView, RunStatusView
from kernel.progress import RunningJobView

# ``RunningJobView`` is the kernel's: each Advisor component reports its
# running jobs in it, and the route gathers them (ADR 0042).
__all__ = ["ActivityService", "ActivityView", "PendingView", "RunStatusView", "RunningJobView"]
