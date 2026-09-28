"""Worker handlers for the assessment. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from advisor.assessment.domain import QuestionRoundTrigger
from kernel.logging import get_logger

log = get_logger(__name__)


async def run(deps: Any, *, owner_id: str, run_id: str) -> str | None:
    """Analyse for one recorded run, then open a question round for whatever
    came back thin.

    Returns the round for the caller to queue, since this module does not know
    the job runner. A run that ended without a result opens no round.
    """
    owner = uuid.UUID(owner_id)
    assessment = await deps.assessment.analyse(owner, uuid.UUID(run_id))
    if assessment is None:
        return None
    log.info(
        "assessment.completed",
        dimensions=len(assessment.dimensions),
        model_id=assessment.model_id,
    )
    round_id = await deps.assessment.request_questions(
        owner, trigger=QuestionRoundTrigger.ASSESSMENT
    )
    return str(round_id) if round_id else None


async def generate_questions(deps: Any, *, owner_id: str, round_id: str) -> None:
    # A failure the round can explain is recorded on it, not raised.
    await deps.assessment.generate_questions(uuid.UUID(owner_id), uuid.UUID(round_id))
    log.info("assessment.questions_finished", round_id=round_id)


async def compute_fits(deps: Any, *, owner_id: str) -> None:
    fits = await deps.assessment.compute_fits(uuid.UUID(owner_id))
    log.info("assessment.fits_computed", fits=len(fits))
