"""Connector contract.

A connector turns one authorised source into ``EvidenceDraft`` rows. It runs
only in the worker's ``sync`` queue, because that is the only place the
connector OAuth tokens can be decrypted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from advisor.profile.domain import EvidenceGranularity
from kernel.fetch import GuardedClient


@dataclass(frozen=True, slots=True)
class EvidenceDraft:
    """``external_ref`` makes a re-sync update a fact rather than duplicate it."""

    external_ref: str
    reference: str
    fact: str
    observed_on: date | None
    granularity: EvidenceGranularity = EvidenceGranularity.ITEM
    tally: int | None = None
    subject: str | None = None


class Connector(Protocol):
    kind: str
    # ``external_ref`` shapes an earlier version of this connector wrote and
    # this one no longer does, as glob patterns ("jira:*:project:*"). A sync
    # deletes the source's facts that match any of them.
    retired_refs: tuple[str, ...]
    # ``external_ref`` shapes each sync writes in full, as glob patterns. A
    # stored fact of one of these shapes that the latest sync did not return
    # is deleted, so what the source no longer backs stops counting.
    replaced_refs: tuple[str, ...]

    async def account_name(self, client: GuardedClient, access_token: str) -> str:
        """Who the token belongs to, as the user would recognise it."""
        ...

    async def fetch(self, client: GuardedClient, access_token: str) -> list[EvidenceDraft]: ...
