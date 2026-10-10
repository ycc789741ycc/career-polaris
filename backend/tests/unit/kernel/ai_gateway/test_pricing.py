"""Cost estimation, including the case where we have no published rate."""

from __future__ import annotations

from decimal import Decimal

from kernel.ai_gateway import pricing


def test_a_published_model_uses_its_real_rate() -> None:
    rate = pricing.rate_for("claude-opus-5")
    assert rate.is_published
    assert rate.input_per_mtok == Decimal("5.0")
    assert rate.output_per_mtok == Decimal("25.0")


def test_an_unknown_model_falls_back_conservatively() -> None:
    """A user must never be surprised by a bill larger than what they approved."""
    unknown = pricing.rate_for("some-model-we-have-no-price-for")
    opus = pricing.rate_for("claude-opus-5")
    assert not unknown.is_published
    assert unknown.input_per_mtok > opus.input_per_mtok
    assert unknown.output_per_mtok > opus.output_per_mtok


def test_cost_scales_with_both_directions_of_tokens() -> None:
    cheap = pricing.cost_of("claude-opus-5", input_tokens=1_000, output_tokens=100)
    dear = pricing.cost_of("claude-opus-5", input_tokens=1_000, output_tokens=10_000)
    assert dear > cheap


def test_one_million_input_tokens_costs_the_published_input_rate() -> None:
    assert pricing.cost_of("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0) == Decimal(
        "2.0"
    )


def test_estimate_reports_whether_the_rate_was_published() -> None:
    known = pricing.estimate("claude-haiku-4-5", prompt="x" * 400, expected_output_tokens=500)
    assert known.rate_is_published
    assert known.input_tokens == 100

    guessed = pricing.estimate("mystery-model", prompt="x" * 400, expected_output_tokens=500)
    assert not guessed.rate_is_published
    assert guessed.cost_usd > known.cost_usd


def test_a_dated_snapshot_is_priced_as_the_model_it_names() -> None:
    """Providers answer an alias with a dated id; it must not cost the fallback."""
    for snapshot in ("claude-haiku-4-5-20251001", "claude-haiku-4-5-2025-10-01"):
        rate = pricing.rate_for(snapshot)
        assert rate.is_published
        assert rate == pricing.rate_for("claude-haiku-4-5")


def test_chinese_and_japanese_count_near_a_token_a_character() -> None:
    chinese = "負責後端服務的設計與維運並帶領五人團隊完成支付系統重構"
    japanese = "バックエンドの設計と運用を担当しました"
    assert pricing.estimate_tokens(chinese) == len(chinese)
    assert pricing.estimate_tokens(japanese) == len(japanese)


def test_english_counts_four_characters_a_token() -> None:
    assert pricing.estimate_tokens("x" * 400) == 100


def test_mixed_text_counts_each_script_its_own_way() -> None:
    text = "Led the 支付 rewrite"  # 16 other characters, 2 Han
    assert pricing.estimate_tokens(text) == 6  # 16 / 4 + 2


def test_the_ceiling_prices_every_attempt_at_its_output_limit() -> None:
    typical = pricing.estimate("claude-haiku-4-5", prompt="x" * 4_000, expected_output_tokens=500)
    ceiling = pricing.estimate_ceiling(
        "claude-haiku-4-5", prompt="x" * 4_000, max_output_tokens=4_096, attempts=3
    )

    assert ceiling.output_tokens == 3 * 4_096
    assert ceiling.input_tokens == 3 * 1_000 + 2 * pricing.REPAIR_NOTE_TOKENS
    assert ceiling.cost_usd > 3 * typical.cost_usd
