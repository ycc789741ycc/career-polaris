"""Brings the price table up to date from LiteLLM's price listing.

Reads ``pricing.json`` on stdin and writes the updated table to stdout; what
changed goes to stderr as markdown, for the pull request that carries it.
``make sync-pricing`` runs it, and the weekly ``pricing.yml`` workflow opens
that pull request. Prices never change at run time: a person reads the diff
first, and the release that ships it is the one that meters by it.

Covers every model the table has and every model Settings suggests, so a
suggestion is never left unpriced. A model the listing lacks keeps its rate.
"""

from __future__ import annotations

import asyncio
import json
import sys

from advisor.identity import SUGGESTED_MODELS
from kernel.ai_gateway.pricing import get_sync_summary, get_synced_table
from kernel.fetch import GuardedClient

# LiteLLM's community-kept listing of per-token prices by model and provider.
LISTING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
_TIMEOUT_SECONDS = 60
# The listing is a few megabytes and grows; this leaves it room.
_MAX_LISTING_BYTES = 50_000_000


async def _fetch_listing() -> dict[str, object]:
    async with GuardedClient(
        timeout_seconds=_TIMEOUT_SECONDS,
        user_agent="CareerPolarisBot/1.0 (pricing sync)",
        max_response_bytes=_MAX_LISTING_BYTES,
    ) as client:
        listing = await client.get_json(LISTING_URL)
    if not isinstance(listing, dict):
        raise ValueError("the price listing is not a JSON object")
    return listing


def main() -> None:
    table = json.load(sys.stdin)
    listing = asyncio.run(_fetch_listing())
    suggested = [model for models in SUGGESTED_MODELS.values() for model in models]
    synced, changes, missing = get_synced_table(table, listing, also=suggested)
    json.dump(synced, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stderr.write(get_sync_summary(changes, missing))


if __name__ == "__main__":
    main()
