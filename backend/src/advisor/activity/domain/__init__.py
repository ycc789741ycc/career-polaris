"""The journey's stage rules, as plain values (ADR 0018).

No I/O, no kernel: ``advisor.activity.service`` reads each stage's recorded
status through the other components and applies these.
"""

from advisor.activity.domain.stages import STALE, Staleness

__all__ = ["STALE", "Staleness"]
