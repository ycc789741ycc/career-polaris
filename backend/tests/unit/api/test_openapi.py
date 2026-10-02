"""The OpenAPI document describes every response, not just that one exists.

A handler returning a plain ``dict`` publishes ``{"type": "object"}``, which the
generated client turns into ``Record<string, unknown>`` — the contract check in
CI then passes whatever the handler sends (ADR 0013).
"""

from __future__ import annotations

from typing import Any

import pytest


def _untyped(schema: dict[str, Any], components: dict[str, Any]) -> bool:
    """True when a schema says "some object" without saying which."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return _untyped(components[name], components)
    if "anyOf" in schema:
        return any(_untyped(s, components) for s in schema["anyOf"])
    if schema.get("type") == "array":
        return _untyped(schema.get("items", {}), components)
    if schema.get("type") == "object" and "properties" not in schema:
        values = schema.get("additionalProperties", True)
        return values in (True, {}) or _untyped(values, components)
    return False


def _json_responses(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    found = []
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            for status, response in operation.get("responses", {}).items():
                if not status.startswith("2"):
                    continue
                schema = response.get("content", {}).get("application/json", {}).get("schema")
                if schema is not None:
                    found.append((f"{method.upper()} {path} {status}", schema))
    return found


@pytest.fixture
def document(clean_env: None) -> dict[str, Any]:
    # Imported here: api.main builds its app on import, which reads settings.
    from api.main import create_app

    return create_app().openapi()


def test_every_api_response_names_its_fields(document: dict[str, Any]) -> None:
    components = document["components"]["schemas"]
    untyped = [
        where
        for where, schema in _json_responses(document)
        if where.split()[1].startswith("/api/v1") and _untyped(schema, components)
    ]
    assert untyped == [], f"responses published as a bare object: {untyped}"


def test_failures_are_published_in_the_error_envelope(document: dict[str, Any]) -> None:
    operation = document["paths"]["/api/v1/me"]["get"]
    for status in ("4XX", "5XX"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorEnvelope"}


def test_the_guard_catches_a_plain_dict() -> None:
    """The check above is only worth having if it fails on what it is for."""
    assert _untyped({"type": "object", "additionalProperties": True}, {})
    assert _untyped({"type": "array", "items": {"type": "object"}}, {})
    assert not _untyped({"type": "object", "additionalProperties": {"type": "string"}}, {})


def test_every_list_is_a_page_with_the_same_two_parameters(document: dict[str, Any]) -> None:
    """One envelope and one pair of paging parameters on every list (ADR 0014)."""
    components = document["components"]["schemas"]
    for path, operations in document["paths"].items():
        get = operations.get("get")
        if not path.startswith("/api/v1") or get is None:
            continue
        schema = (
            get["responses"].get("200", {}).get("content", {}).get("application/json", {})
        ).get("schema", {})
        resolved = components[schema["$ref"].rsplit("/", 1)[-1]] if "$ref" in schema else schema
        is_page = "$ref" in schema and schema["$ref"].endswith("Page")
        assert resolved.get("type") != "array", f"GET {path} returns a bare array"
        if is_page:
            assert set(resolved["required"]) == {"items", "page", "page_size", "total"}
            names = {p["name"] for p in get.get("parameters", []) if p["in"] == "query"}
            assert {"page", "page_size"} <= names, f"GET {path} pages without the parameters"


def test_signed_in_routes_declare_the_bearer_scheme(document: dict[str, Any]) -> None:
    """Swagger UI's Authorize button holds the token for every route that declares it."""
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    me = document["paths"]["/api/v1/me"]["get"]
    assert me["security"] == [{"HTTPBearer": []}]
    assert "authorization" not in {p["name"] for p in me.get("parameters", [])}
    assert "security" not in document["paths"]["/api/v1/auth/sign-in"]["post"]
