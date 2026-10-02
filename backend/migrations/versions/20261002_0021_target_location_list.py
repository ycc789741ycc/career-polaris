"""Target locations come from a list (ADR 0026).

``market_user.market_preference`` held whatever the user typed. Each row is
rewritten to the place on the list it names: "UK" is "United Kingdom",
"Remote Taiwan" is "Taiwan", "Remote EU" is "Europe". A row naming no place on
the list (a city, an unknown region) is deleted, as is a second row that now
names a place the user already has.

No event is recorded: the role map is rebuilt when the user next asks.

The mapping is frozen here rather than read from ``advisor.market``, so this
migration does the same thing whatever the list becomes later.

Downgrading leaves the rows as they are: every name on the list was also a
valid free-text location.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from alembic import op
from sqlalchemy import text

revision: str = "0021_target_location_list"
down_revision: str | None = "0020_search_sources"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

_TABLE = "market_user.market_preference"

# Every way a stored location may have named a place, folded the way
# ``_folded`` folds it, to the place's name on the list.
_PLACES: dict[str, str] = {
    "remote": "Remote",
    "worldwide": "Remote",
    "anywhere": "Remote",
    "asia pacific": "Asia-Pacific",
    "apac": "Asia-Pacific",
    "europe": "Europe",
    "eu": "Europe",
    "european union": "Europe",
    "latin america": "Latin America",
    "latam": "Latin America",
    "middle east africa": "Middle East & Africa",
    "north america": "North America",
    "argentina": "Argentina",
    "australia": "Australia",
    "austria": "Austria",
    "belgium": "Belgium",
    "brazil": "Brazil",
    "brasil": "Brazil",
    "canada": "Canada",
    "chile": "Chile",
    "china": "China",
    "colombia": "Colombia",
    "czechia": "Czechia",
    "czech republic": "Czechia",
    "denmark": "Denmark",
    "estonia": "Estonia",
    "finland": "Finland",
    "france": "France",
    "germany": "Germany",
    "deutschland": "Germany",
    "greece": "Greece",
    "hong kong": "Hong Kong",
    "hungary": "Hungary",
    "india": "India",
    "indonesia": "Indonesia",
    "ireland": "Ireland",
    "israel": "Israel",
    "italy": "Italy",
    "japan": "Japan",
    "malaysia": "Malaysia",
    "mexico": "Mexico",
    "netherlands": "Netherlands",
    "the netherlands": "Netherlands",
    "new zealand": "New Zealand",
    "norway": "Norway",
    "philippines": "Philippines",
    "poland": "Poland",
    "portugal": "Portugal",
    "romania": "Romania",
    "singapore": "Singapore",
    "south africa": "South Africa",
    "south korea": "South Korea",
    "korea": "South Korea",
    "spain": "Spain",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "taiwan": "Taiwan",
    "thailand": "Thailand",
    "turkey": "Turkey",
    "turkiye": "Turkey",
    "ukraine": "Ukraine",
    "united arab emirates": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "great britain": "United Kingdom",
    "united states": "United States",
    "usa": "United States",
    "us": "United States",
    "vietnam": "Vietnam",
    "viet nam": "Vietnam",
}


def _folded(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def place_for(value: str) -> str | None:
    """The place on the list a stored location names, or ``None``. "Remote"
    around a place's name is dropped: remote work open to Taiwan is in
    "Taiwan" already."""
    folded = _folded(value)
    if folded in _PLACES:
        return _PLACES[folded]
    words = folded.split()
    while words and words[0] == "remote":
        words = words[1:]
    while words and words[-1] in {"remote", "only"}:
        words = words[:-1]
    return _PLACES.get(" ".join(words))


def upgrade() -> None:
    # FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user
    # policy; lift it for the data step.
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    bind = op.get_bind()
    rows = bind.execute(
        text(
            "SELECT id, owner_id, market FROM market_user.market_preference "
            "ORDER BY owner_id, created_at, id"
        )
    ).all()
    kept: set[tuple[str, str]] = set()
    doomed: list[object] = []
    moves: list[tuple[object, str]] = []
    for row_id, owner_id, market in rows:
        place = place_for(market)
        if place is None or (str(owner_id), place) in kept:
            doomed.append(row_id)
            continue
        kept.add((str(owner_id), place))
        if place != market:
            moves.append((row_id, place))
    # Deletes first: a row renamed to a place the user also typed out in full
    # would otherwise collide with it on (owner_id, market).
    for row_id in doomed:
        bind.execute(
            text("DELETE FROM market_user.market_preference WHERE id = :id"), {"id": row_id}
        )
    for row_id, place in moves:
        bind.execute(
            text("UPDATE market_user.market_preference SET market = :place WHERE id = :id"),
            {"place": place, "id": row_id},
        )
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    log.info("Moved %s target location(s) onto the list; deleted %s", len(moves), len(doomed))


def downgrade() -> None:
    pass
