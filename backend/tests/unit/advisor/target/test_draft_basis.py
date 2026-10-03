"""What a plan or a résumé was drafted from, and when that has moved on (ADR
0035): the Target's digest, the outdated rule, and the service call that
compares a recorded basis with the Target as it stands now."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from advisor.target import DraftBasis, OutdatedReason, TargetRef, TargetService, TargetSnapshot
from advisor.target.domain import (
    DimensionGap,
    Requirement,
    RequirementBasis,
    UncoveredGap,
    get_target_digest,
)
from kernel.errors import NotFoundError, TargetUnusableError

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
REF = TargetRef(str(uuid.uuid4()))


def _snapshot(**changes: object) -> TargetSnapshot:
    snapshot = TargetSnapshot(
        ref=REF,
        title="Staff Backend Engineer",
        company="Northwind Pay",
        role_id=REF.role_id,
        role_name="Staff Backend Engineer",
        requirements=(
            Requirement("Owns production reliability", 0.9, "senior"),
            Requirement("Designs payment systems", 0.6, "senior"),
        ),
        basis=RequirementBasis.ROLE,
        fit_score=72,
        dimensions=(DimensionGap("incidents", "Incidents", 40, 70, 9),),
        uncovered=(UncoveredGap("Multi-region capacity planning", 0.4, 4),),
        requirement_map={},
        taken_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    return replace(snapshot, **changes)  # type: ignore[arg-type]


def test_a_target_taken_again_unchanged_hashes_the_same() -> None:
    first = _snapshot()
    later = _snapshot(
        taken_at=first.taken_at + timedelta(days=3),
        title="Renamed",
        requirements=tuple(reversed(first.requirements)),
    )

    assert get_target_digest(first) == get_target_digest(later)


@pytest.mark.parametrize(
    "changes",
    [
        {"requirements": (Requirement("Owns production reliability", 0.9, "senior"),)},
        {
            "requirements": (
                Requirement("Owns production reliability", 0.5, "senior"),
                Requirement("Designs payment systems", 0.6, "senior"),
            )
        },
        {"basis": RequirementBasis.OPENING},
        {"fit_score": 75},
        {"dimensions": (DimensionGap("incidents", "Incidents", 55, 70, 5),)},
        {"uncovered": ()},
    ],
)
def test_anything_a_draft_reads_changes_the_digest(changes: dict[str, object]) -> None:
    assert get_target_digest(_snapshot(**changes)) != get_target_digest(_snapshot())


@pytest.mark.parametrize(
    ("version", "digest", "reasons"),
    [
        (3, "d1", ()),
        (4, "d1", (OutdatedReason.EVIDENCE,)),
        (3, "d2", (OutdatedReason.TARGET,)),
        (4, "d2", (OutdatedReason.EVIDENCE, OutdatedReason.TARGET)),
    ],
)
def test_a_draft_is_outdated_by_whatever_moved_on(
    version: int, digest: str, reasons: tuple[OutdatedReason, ...]
) -> None:
    recorded = DraftBasis(profile_version=3, target_digest="d1")

    assert recorded.get_outdated_reasons(DraftBasis(version, digest)) == reasons


class _Snapshots(TargetService):
    """The service with its snapshot stood in for: the Target as it is now,
    or the error resolving it raises."""

    def __init__(self, now: TargetSnapshot | Exception) -> None:
        self.now = now

    async def snapshot(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetSnapshot:
        if isinstance(self.now, Exception):
            raise self.now
        return self.now


async def test_the_service_compares_a_recorded_basis_with_the_target_now() -> None:
    now = _snapshot()
    recorded = DraftBasis(profile_version=3, target_digest=get_target_digest(now))
    service = _Snapshots(now)

    current = await service.get_outdated_reasons(OWNER, REF, recorded=recorded, profile_version=3)
    assert current == ()
    assert await service.get_outdated_reasons(OWNER, REF, recorded=recorded, profile_version=4) == (
        OutdatedReason.EVIDENCE,
    )


async def test_a_draft_with_no_recorded_basis_is_never_outdated() -> None:
    service = _Snapshots(TargetUnusableError("not scored yet"))

    assert await service.get_outdated_reasons(OWNER, REF, recorded=None, profile_version=9) == ()


@pytest.mark.parametrize(
    "error", [TargetUnusableError("not scored since the rebuild"), NotFoundError("role gone")]
)
async def test_a_target_that_cannot_be_resolved_now_counts_as_changed(error: Exception) -> None:
    recorded = DraftBasis(profile_version=3, target_digest=get_target_digest(_snapshot()))

    assert await _Snapshots(error).get_outdated_reasons(
        OWNER, REF, recorded=recorded, profile_version=3
    ) == (OutdatedReason.TARGET,)
