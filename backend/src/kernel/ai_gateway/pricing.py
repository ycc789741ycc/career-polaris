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
from collections.abc import Iterable, Mapping
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


# -- keeping the table current (make sync-pricing) ------------------------------

# Where a listing's rate for one of our models may be, in order: the provider's
# own id, then Google's under its API's prefix, then Google's on Vertex, which
# Google prices the same. Resellers' entries (azure/, deepinfra/, …) are never
# read: their prices are their own.
_LISTING_PROVIDERS = frozenset(
    {"anthropic", "openai", "gemini", "vertex_ai", "vertex_ai-language-models"}
)
_LISTING_KEYS = ("{model}", "gemini/{model}", "vertex_ai/{model}")
_PER_MILLION = Decimal(1_000_000)
# A listed rate that falls by more than this share is called out for review.
SUSPICIOUS_DROP = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class RateChange:
    """One model's rate before and after a sync."""

    model: str
    old: Rate | None
    new: Rate

    @property
    def is_suspicious(self) -> bool:
        """Free, or more than half off: worth a person's look before it
        meters anyone's spend."""
        if self.new.input_per_mtok <= 0 or self.new.output_per_mtok <= 0:
            return True
        if self.old is None:
            return False
        return (
            self.new.input_per_mtok < self.old.input_per_mtok * SUSPICIOUS_DROP
            or self.new.output_per_mtok < self.old.output_per_mtok * SUSPICIOUS_DROP
        )


def get_listed_rate(listing: Mapping[str, object], model: str) -> Rate | None:
    """``model``'s rate in a LiteLLM price listing, per million tokens, or
    None when the listing does not have it from the provider itself."""
    for pattern in _LISTING_KEYS:
        entry = listing.get(pattern.format(model=model))
        if not isinstance(entry, Mapping):
            continue
        if entry.get("litellm_provider") not in _LISTING_PROVIDERS:
            continue
        cost_in = entry.get("input_cost_per_token")
        cost_out = entry.get("output_cost_per_token")
        if not isinstance(cost_in, int | float) or not isinstance(cost_out, int | float):
            continue
        return Rate(
            input_per_mtok=_per_million(cost_in),
            output_per_mtok=_per_million(cost_out),
            is_published=True,
        )
    return None


def get_synced_table(
    table: Mapping[str, object], listing: Mapping[str, object], also: Iterable[str] = ()
) -> tuple[dict[str, object], list[RateChange], list[str]]:
    """The price table with every model's rate taken from ``listing``.

    Covers the models already in the table and ``also`` (the ones Settings
    suggests). A model the listing lacks keeps its rate and is named in the
    second list. Everything but ``models`` is kept as it was.
    """
    models: dict[str, dict[str, float]] = dict(table["models"])  # type: ignore[call-overload]
    changes: list[RateChange] = []
    missing: list[str] = []
    for model in sorted(set(models) | set(also)):
        listed = get_listed_rate(listing, model)
        if listed is None:
            missing.append(model)
            continue
        entry = models.get(model)
        old = (
            Rate(
                input_per_mtok=Decimal(str(entry["input_per_mtok"])),
                output_per_mtok=Decimal(str(entry["output_per_mtok"])),
                is_published=True,
            )
            if entry is not None
            else None
        )
        if old != listed:
            changes.append(RateChange(model=model, old=old, new=listed))
        models[model] = {
            "input_per_mtok": float(listed.input_per_mtok),
            "output_per_mtok": float(listed.output_per_mtok),
        }
    synced = {key: value for key, value in table.items() if key != "models"}
    synced["models"] = dict(sorted(models.items()))
    return synced, changes, missing


def get_sync_summary(changes: list[RateChange], missing: list[str]) -> str:
    """What a sync changed, as the body of the pull request that carries it."""
    lines = ["Rates per million tokens, from LiteLLM's price listing.", ""]
    if changes:
        lines += ["| Model | Input | Output | |", "|---|---|---|---|"]
        for change in changes:
            flag = (
                "⚠ free or more than half off: check before merging"
                if (change.is_suspicious)
                else ("new" if change.old is None else "")
            )
            lines.append(
                f"| `{change.model}` | {_was(change.old, 'input')}{change.new.input_per_mtok:f}"
                f" | {_was(change.old, 'output')}{change.new.output_per_mtok:f} | {flag} |"
            )
    else:
        lines.append("No rate changed.")
    if missing:
        lines += [
            "",
            "Not in the listing, so left as they were: "
            + ", ".join(f"`{model}`" for model in missing)
            + ".",
        ]
    return "\n".join(lines) + "\n"


def _per_million(cost_per_token: float) -> Decimal:
    return (Decimal(str(cost_per_token)) * _PER_MILLION).normalize()


def _was(old: Rate | None, side: str) -> str:
    if old is None:
        return ""
    value = old.input_per_mtok if side == "input" else old.output_per_mtok
    return f"{value.normalize():f} → "
