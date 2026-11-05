"""Validation feedback identifies constraints without copying personal data."""

from __future__ import annotations

import json
import traceback
from typing import Literal

import pytest
from pydantic import BaseModel, Field, field_validator

from kernel.ai_gateway.gateway import _parse, _with_repair_note
from kernel.ai_gateway.output_validation import get_schema_diagnostics
from kernel.ai_gateway.pricing import REPAIR_NOTE_TOKENS, estimate_tokens
from kernel.ai_gateway.providers import Request
from kernel.errors import OutputInvalidError

PRIVATE = "private-person@example.test"


class Line(BaseModel):
    text: str = Field(min_length=1, max_length=10)
    evidence_ids: list[str] = Field(max_length=8)


class Draft(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    bullets: list[Line]


def test_nested_constraints_are_reported_without_the_rejected_values() -> None:
    with pytest.raises(OutputInvalidError) as caught:
        _parse(
            json.dumps(
                {"name": "A", "bullets": [{"text": PRIVATE, "evidence_ids": [PRIVATE] * 9}]}
            ),
            Draft,
        )

    error = caught.value
    assert error.context == {
        "category": "schema_validation",
        "error_count": 2,
        "violations": [
            {"path": "bullets[0].text", "type": "string_too_long", "max_length": 10},
            {"path": "bullets[0].evidence_ids", "type": "too_long", "max_length": 8},
        ],
        "diagnostics_truncated": False,
    }
    assert PRIVATE not in json.dumps(error.context)
    assert PRIVATE not in str(error)
    assert PRIVATE not in "".join(traceback.format_exception(error))


class DynamicFields(BaseModel):
    values: dict[str, int]
    numeric_keys: dict[int, int]


def test_dictionary_keys_including_numeric_keys_are_not_field_paths() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as caught:
        DynamicFields.model_validate(
            {"values": {PRIVATE: PRIVATE}, "numeric_keys": {15551234567: PRIVATE}}
        )

    diagnostics = get_schema_diagnostics(caught.value, DynamicFields)
    assert [v["path"] for v in diagnostics["violations"]] == ["values.*", "numeric_keys.*"]
    assert PRIVATE not in json.dumps(diagnostics)
    assert "15551234567" not in json.dumps(diagnostics)


class CustomMessage(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def reject(cls, value: str) -> str:
        raise ValueError(value)


def test_custom_validator_messages_and_context_are_not_feedback() -> None:
    with pytest.raises(OutputInvalidError) as caught:
        _parse(json.dumps({"text": PRIVATE}), CustomMessage)
    assert caught.value.context["violations"] == [{"path": "text", "type": "value_error"}]
    assert PRIVATE not in json.dumps(caught.value.context)


class UnionFields(BaseModel):
    line: Line | None
    kind: Literal["summary", "experience"]


def test_nullable_references_and_enum_errors_keep_safe_locations() -> None:
    with pytest.raises(OutputInvalidError) as caught:
        _parse(
            json.dumps({"line": {"text": PRIVATE, "evidence_ids": []}, "kind": PRIVATE}),
            UnionFields,
        )
    assert [v["path"] for v in caught.value.context["violations"]] == ["line.text", "kind"]
    assert PRIVATE not in json.dumps(caught.value.context)


def test_many_errors_produce_bounded_complete_feedback_with_a_count() -> None:
    with pytest.raises(OutputInvalidError) as caught:
        _parse(
            json.dumps({"name": "A", "bullets": [{"text": PRIVATE, "evidence_ids": []}] * 30}),
            Draft,
        )
    diagnostics = caught.value.context
    assert diagnostics["error_count"] == 30
    assert len(diagnostics["violations"]) == 8
    assert diagnostics["diagnostics_truncated"] is True
    encoded = json.dumps(diagnostics, ensure_ascii=True)
    assert len(encoded) <= 1_800
    request = Request("key", "model", "https://llm.example", "Return JSON.", "Original", 4096)
    repaired = _with_repair_note(request, encoded)
    assert encoded in repaired.user
    assert estimate_tokens(repaired.user.removeprefix(request.user)) <= REPAIR_NOTE_TOKENS


@pytest.mark.parametrize("text", ["", "{", '"' + PRIVATE, PRIVATE])
def test_malformed_json_has_a_category_without_content(text: str) -> None:
    with pytest.raises(OutputInvalidError) as caught:
        _parse(text, Draft)
    assert caught.value.context == {"category": "json_parse"}
    assert PRIVATE not in str(caught.value)


def test_a_repaired_draft_retains_its_evidence_ids() -> None:
    draft = _parse(
        '{"name":"A","bullets":[{"text":"Built APIs","evidence_ids":["E1","E2"]}]}', Draft
    )
    assert draft.bullets[0].evidence_ids == ["E1", "E2"]
