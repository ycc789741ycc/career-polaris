"""Cost estimation.

Two places need this: the budget check before every call, and the
"show cost before spending" confirmation on a user's first analysis and first
role map (domain decision in section 2.8).

The estimate is an estimate. Token counts here come from a character
heuristic that knows Chinese, Japanese and Korean run near a token a
character, and the rate for a model we have no published price for is
deliberately pessimistic, so the user is never surprised by a larger bill than
the number they approved. What a call really cost is the provider's own count,
priced at the rate of the model we asked for.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

_PRICING_FILE = Path(__file__).parent / "pricing.json"

# Han, kana, Hangul and full-width forms: each character is near a token.
_CJK = re.compile(
    "["
    "\u3040-\u30ff"  # hiragana and katakana
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"  # Han
    "\uac00-\ud7af"  # Hangul
    "\uff00-\uffef"  # full-width forms
    "]"
)
# A snapshot a provider answers an alias with: claude-haiku-4-5-20251001,
# gpt-5-mini-2025-08-07.
_SNAPSHOT_DATE = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$")
# What a retry's repair note adds to the prompt, at most: the note itself and
# the validation error it quotes.
REPAIR_NOTE_TOKENS = 1_000


@dataclass(frozen=True, slots=True)
class Rate:
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    is_published: bool


@dataclass(frozen=True, slots=True)
class CostEstimate:
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    # False when we had no published rate and used the conservative fallback.
    rate_is_published: bool


@lru_cache(maxsize=1)
def _table() -> dict[str, object]:
    return dict(json.loads(_PRICING_FILE.read_text(encoding="utf-8")))


def rate_for(model: str) -> Rate:
    """The published rate for ``model``, or for the model a dated snapshot
    id names, or the pessimistic fallback."""
    models: dict[str, dict[str, float]] = _table()["models"]  # type: ignore[assignment]
    entry = models.get(model) or models.get(_SNAPSHOT_DATE.sub("", model))
    if entry is not None:
        return Rate(
            input_per_mtok=Decimal(str(entry["input_per_mtok"])),
            output_per_mtok=Decimal(str(entry["output_per_mtok"])),
            is_published=True,
        )
    fallback: dict[str, float] = _table()["unknown_model_rate"]  # type: ignore[assignment]
    return Rate(
        input_per_mtok=Decimal(str(fallback["input_per_mtok"])),
        output_per_mtok=Decimal(str(fallback["output_per_mtok"])),
        is_published=False,
    )


def estimate_tokens(text: str) -> int:
    counting: dict[str, float] = _table()["token_counting"]  # type: ignore[assignment]
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    tokens = other / counting["chars_per_token"] + cjk * counting["tokens_per_cjk_char"]
    return max(1, math.ceil(tokens))


def cost_of(model: str, *, input_tokens: int, output_tokens: int) -> Decimal:
    rate = rate_for(model)
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * rate.input_per_mtok / million
        + Decimal(output_tokens) * rate.output_per_mtok / million
    )


def estimate(model: str, *, prompt: str, expected_output_tokens: int) -> CostEstimate:
    input_tokens = estimate_tokens(prompt)
    rate = rate_for(model)
    return CostEstimate(
        input_tokens=input_tokens,
        output_tokens=expected_output_tokens,
        cost_usd=cost_of(model, input_tokens=input_tokens, output_tokens=expected_output_tokens),
        rate_is_published=rate.is_published,
    )


def estimate_ceiling(
    model: str, *, prompt: str, max_output_tokens: int, attempts: int
) -> CostEstimate:
    """The most a call can cost: every attempt, each re-sending the prompt
    with a repair note and writing to its output limit.

    Money that is not the user's is reserved against this, never against the
    typical case.
    """
    input_tokens = attempts * estimate_tokens(prompt) + (attempts - 1) * REPAIR_NOTE_TOKENS
    output_tokens = attempts * max_output_tokens
    rate = rate_for(model)
    return CostEstimate(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_of(model, input_tokens=input_tokens, output_tokens=output_tokens),
        rate_is_published=rate.is_published,
    )
