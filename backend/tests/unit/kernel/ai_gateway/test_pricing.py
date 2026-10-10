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


# -- keeping the table current (make sync-pricing) -------------------------------

LISTING = {
    "gpt-5.1": {
        "input_cost_per_token": 1.25e-06,
        "output_cost_per_token": 1e-05,
        "litellm_provider": "openai",
    },
    "azure/gpt-5.1": {
        "input_cost_per_token": 9e-06,
        "output_cost_per_token": 9e-05,
        "litellm_provider": "azure",
    },
    "gemini/gemini-3-flash-preview": {
        "input_cost_per_token": 5e-07,
        "output_cost_per_token": 3e-06,
        "litellm_provider": "gemini",
    },
    "vertex_ai/gemini-3-pro-preview": {
        "input_cost_per_token": 2e-06,
        "output_cost_per_token": 1.2e-05,
        "litellm_provider": "vertex_ai",
    },
    "claude-haiku-4-5": {
        "input_cost_per_token": 1e-06,
        "output_cost_per_token": 5e-06,
        "litellm_provider": "anthropic",
    },
    "deepinfra/cheap-model": {
        "input_cost_per_token": 1e-09,
        "output_cost_per_token": 1e-09,
        "litellm_provider": "deepinfra",
    },
}

TABLE = {
    "_comment": "kept",
    "token_counting": {"chars_per_token": 4, "tokens_per_cjk_char": 1.0},
    "unknown_model_rate": {"input_per_mtok": 15.0, "output_per_mtok": 75.0},
    "models": {
        "claude-haiku-4-5": {"input_per_mtok": 1.0, "output_per_mtok": 5.0},
        "gpt-5.1": {"input_per_mtok": 3.0, "output_per_mtok": 30.0},
    },
}


def test_a_listed_rate_is_read_from_the_provider_itself_per_million() -> None:
    rate = pricing.get_listed_rate(LISTING, "gpt-5.1")

    assert rate is not None
    assert (rate.input_per_mtok, rate.output_per_mtok) == (Decimal("1.25"), Decimal("10"))


def test_google_models_are_found_under_the_api_or_vertex() -> None:
    flash = pricing.get_listed_rate(LISTING, "gemini-3-flash-preview")
    pro = pricing.get_listed_rate(LISTING, "gemini-3-pro-preview")

    assert flash is not None and flash.output_per_mtok == Decimal("3")
    assert pro is not None and pro.input_per_mtok == Decimal("2")


def test_a_resellers_price_is_never_read() -> None:
    assert pricing.get_listed_rate(LISTING, "cheap-model") is None


def test_a_sync_updates_known_models_adds_suggested_ones_and_keeps_the_rest() -> None:
    synced, changes, missing = pricing.get_synced_table(
        TABLE, LISTING, also=["gemini-3-flash-preview", "not-listed-anywhere"]
    )

    models = synced["models"]
    assert isinstance(models, dict)
    assert models["gpt-5.1"] == {"input_per_mtok": 1.25, "output_per_mtok": 10.0}
    assert models["gemini-3-flash-preview"] == {"input_per_mtok": 0.5, "output_per_mtok": 3.0}
    assert "not-listed-anywhere" not in models
    assert missing == ["not-listed-anywhere"]
    assert {change.model for change in changes} == {"gpt-5.1", "gemini-3-flash-preview"}
    # Unchanged: nothing reported for Haiku, and everything but models kept.
    assert synced["_comment"] == "kept"
    assert synced["unknown_model_rate"] == TABLE["unknown_model_rate"]


def test_a_rate_more_than_halved_or_free_is_called_out() -> None:
    _, changes, _ = pricing.get_synced_table(TABLE, LISTING)
    [gpt] = [change for change in changes if change.model == "gpt-5.1"]
    assert gpt.is_suspicious  # $3 → $1.25 in: more than half off

    free = {"gpt-5.1": {**LISTING["gpt-5.1"], "input_cost_per_token": 0.0}}
    _, changes, _ = pricing.get_synced_table(TABLE, free)
    assert changes[0].is_suspicious


def test_the_summary_lists_changes_flags_and_what_was_missing() -> None:
    _, changes, missing = pricing.get_synced_table(TABLE, LISTING, also=["not-listed-anywhere"])

    summary = pricing.get_sync_summary(changes, missing)

    assert "| `gpt-5.1` | 3 → 1.25 | 30 → 10 | ⚠" in summary
    assert "`not-listed-anywhere`" in summary
    assert "E+" not in summary


def test_every_model_settings_suggests_has_a_published_rate() -> None:
    """Settings never offers a model whose spend would be guessed."""
    from advisor.identity import SUGGESTED_MODELS

    unpriced = [
        model
        for models in SUGGESTED_MODELS.values()
        for model in models
        if not pricing.rate_for(model).is_published
    ]
    assert unpriced == []
