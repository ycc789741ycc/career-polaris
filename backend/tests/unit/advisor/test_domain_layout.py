"""Each component's domain is split by concept (Phase 7, the design guideline's
"Modules in the domain: one per concept").

A module is named for the concept it holds, never for a kind of code. Only
``repositories.py``, ``events.py`` and ``constants.py`` are split by kind, and
``constants.py`` is a leaf that imports nothing but the standard library.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import advisor

ADVISOR = Path(advisor.__file__).parent
DOMAINS = sorted(path for path in ADVISOR.glob("*/domain") if path.is_dir())
NAMED_FOR_A_KIND = {"entities", "models", "value_objects", "rules", "types", "helpers"}


def test_every_component_has_a_domain_to_check() -> None:
    assert len(DOMAINS) >= 10


def test_no_domain_module_is_named_for_a_kind_of_code() -> None:
    named_for_a_kind = [
        str(module.relative_to(ADVISOR))
        for domain in DOMAINS
        for module in domain.glob("*.py")
        if module.stem in NAMED_FOR_A_KIND
    ]

    assert named_for_a_kind == []


def test_constants_import_only_the_standard_library() -> None:
    outside = []
    for constants in (domain / "constants.py" for domain in DOMAINS):
        if not constants.exists():
            continue
        for node in ast.walk(ast.parse(constants.read_text())):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top != "__future__" and top not in sys.stdlib_module_names:
                    outside.append(f"{constants.relative_to(ADVISOR)}: {module}")

    assert outside == []
