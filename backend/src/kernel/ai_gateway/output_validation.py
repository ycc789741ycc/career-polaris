"""Bounded validation diagnostics, containing no model-written values.

Pydantic locations can include dictionary keys chosen by the model, and
messages and context can contain user data even with ``include_input=False``.
Only schema-defined field names, array indices, standard error types and
numeric length limits cross this boundary.
"""

from __future__ import annotations

import json
from typing import Any, get_args

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorType

_ERROR_TYPES = frozenset(get_args(ErrorType))
_MAX_ERRORS = 8
_MAX_PATH_PARTS = 12
_MAX_PATH_CHARS = 160
_MAX_DIAGNOSTIC_CHARS = 1_800


def _variants(node: dict[str, Any], root: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve local references and unions to locate a static field."""
    if "$ref" in node:
        target: Any = root
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
    choices = node.get("anyOf") or node.get("oneOf")
    if choices:
        return [variant for choice in choices for variant in _variants(choice, root)]
    return [node]


def _field_path(location: tuple[Any, ...], root: dict[str, Any]) -> str:
    path = ""
    nodes = [root]
    for part in location[:_MAX_PATH_PARTS]:
        variants = [variant for node in nodes for variant in _variants(node, root)]
        fields = [
            node["properties"][part]
            for node in variants
            if isinstance(part, str) and part in node.get("properties", {})
        ]
        arrays = [node["items"] for node in variants if isinstance(node.get("items"), dict)]
        if fields:
            path += ("." if path else "") + part
            nodes = fields
        elif type(part) is int and arrays:
            path += f"[{part}]"
            nodes = arrays
        else:
            # Dictionary keys (including numeric keys) and union tags may
            # be supplied by the model. Keep the value schema, not the key.
            path += ("." if path else "") + "*"
            nodes = [
                node["additionalProperties"]
                for node in variants
                if isinstance(node.get("additionalProperties"), dict)
            ]
    if len(location) > _MAX_PATH_PARTS:
        path += ".*"
    return (path or "$")[:_MAX_PATH_CHARS]


def get_schema_diagnostics(error: ValidationError, schema: type[BaseModel]) -> dict[str, Any]:
    """A safe summary for both operator logs and the next model attempt.

    Keep JSON small enough to fit the gateway's repair allowance without
    slicing through a field's diagnostics. Unknown/custom error messages,
    enum values, input values and dynamic dictionary keys are never copied.
    """
    root = schema.model_json_schema()
    diagnostics: dict[str, Any] = {
        "category": "schema_validation",
        "error_count": error.error_count(),
        "violations": [],
        "diagnostics_truncated": False,
    }
    errors = error.errors(include_input=False, include_url=False)
    for item in errors[:_MAX_ERRORS]:
        violation: dict[str, Any] = {
            "path": _field_path(item["loc"], root),
            "type": item["type"] if item["type"] in _ERROR_TYPES else "value_error",
        }
        context = item.get("ctx", {})
        for key in ("min_length", "max_length"):
            value = context.get(key)
            if type(value) is int:
                violation[key] = value
        diagnostics["violations"].append(violation)
        if len(json.dumps(diagnostics, ensure_ascii=True)) > _MAX_DIAGNOSTIC_CHARS:
            diagnostics["violations"].pop()
            break
    diagnostics["diagnostics_truncated"] = len(diagnostics["violations"]) < len(errors)
    return diagnostics
