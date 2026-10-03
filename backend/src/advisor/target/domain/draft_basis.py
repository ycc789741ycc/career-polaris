"""What a gap plan or a tailored résumé was drafted from (Phase 9, ADR 0035).

A draft reads two things: the user's evidence, as one version of their
profile, and the Target, as a snapshot of what it requires and how the user
measures up. Each draft records both. When either has moved on since, the
draft is outdated, and the Advisor says so and offers to regenerate it — it
never rewrites one by itself, because rewriting spends the user's key.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from advisor.target.domain.snapshot import TargetSnapshot


class OutdatedReason(StrEnum):
    # The user's evidence changed: a sync, an upload, an answer.
    EVIDENCE = "evidence"
    # What the Target asks for, or the user's fit to it, changed.
    TARGET = "target"


@dataclass(frozen=True, slots=True)
class DraftBasis:
    profile_version: int
    target_digest: str

    def get_outdated_reasons(self, current: DraftBasis) -> tuple[OutdatedReason, ...]:
        """Why a draft made from this basis no longer matches ``current``,
        evidence first; empty when it still does."""
        reasons: list[OutdatedReason] = []
        if current.profile_version != self.profile_version:
            reasons.append(OutdatedReason.EVIDENCE)
        if current.target_digest != self.target_digest:
            reasons.append(OutdatedReason.TARGET)
        return tuple(reasons)


def get_target_digest(snapshot: TargetSnapshot) -> str:
    """A hash of everything a draft reads from the Target.

    The requirements (statement, weight, expected level), the basis they came
    from, the fit, the dimension gaps and the uncovered requirements. Not
    ``taken_at``, not the label, and not the order anything was loaded in: a
    snapshot taken again of an unchanged Target hashes the same.
    """
    material = {
        "requirements": sorted(
            [r.statement, r.weight, r.expected_level] for r in snapshot.requirements
        ),
        "basis": str(snapshot.basis),
        "fit_score": snapshot.fit_score,
        "dimensions": sorted(
            [d.dimension_key, d.user_score, d.target_score, d.lift] for d in snapshot.dimensions
        ),
        "uncovered": sorted([u.statement, u.weight, u.lift] for u in snapshot.uncovered),
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
