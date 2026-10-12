"""The look a résumé version keeps (ADR 0079): one template, built in or the
user's own, its own look over it and the trim, kept as a dict."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from advisor.resume import Options, OwnLook, Template
from advisor.resume.domain import TailoredResume, VersionLook

AT = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def test_a_version_look_reads_back_as_it_was_kept() -> None:
    looks = (
        VersionLook(template=Template.PLAIN),
        VersionLook(
            template=None,
            custom_template_id=uuid.uuid4(),
            own_look=OwnLook(heading_font="Inter", bold_titles=True, body_pt=10.5, name_pt=24.0),
            trim=True,
        ),
    )
    for look in looks:
        assert VersionLook.from_dict(look.to_dict()) == look


def test_a_version_look_has_one_template() -> None:
    with pytest.raises(ValueError, match="one template"):
        VersionLook(template=None)
    with pytest.raises(ValueError, match="one template"):
        VersionLook(template=Template.ORGANIC, custom_template_id=uuid.uuid4())


def test_a_resume_takes_the_look_of_the_version_saved() -> None:
    resume = TailoredResume.requested(
        owner_id=uuid.uuid4(),
        role_id=uuid.uuid4(),
        job_posting_id=None,
        label="Staff Engineer",
        template=Template.ORGANIC,
        options=Options(metrics=False, reorder=True, trim=False),
        at=AT,
    )
    look = VersionLook(
        template=Template.PLAIN, own_look=OwnLook(section_font="Lato", heading_pt=9.5), trim=True
    )

    resume.update_saved_look(look, at=AT)

    assert resume.get_version_look() == look
    # The writing options stay the résumé's own.
    assert (resume.options.metrics, resume.options.reorder) == (False, True)
