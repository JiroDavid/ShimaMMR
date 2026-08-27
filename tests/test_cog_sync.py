from unittest.mock import AsyncMock
from sqlalchemy import select
from val_bot.bot.cogs.sync import sync_matches
from val_bot.db.models import Player, Match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant
from datetime import datetime, timezone

def _fake_source(matches):
    source = AsyncMock()
    source.fetch_new_matches = AsyncMock(return_value=matches)
    return lambda: source

async def test_sync_matches_creates_pending_match_for_new_data(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()

    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Sunset", source="henrikdev",
        team_a_score=13, team_b_score=9, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
        external_match_id="ext-1",
    )
    ids = await sync_matches(db_session, _fake_source([normalized]))
    assert len(ids) == 1
    match = await db_session.get(Match, ids[0])
    assert match.status == "pending"
    assert match.external_match_id == "ext-1"

async def test_sync_matches_skips_already_ingested_external_id(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()

    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Sunset", source="henrikdev",
        team_a_score=13, team_b_score=9, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
        external_match_id="ext-1",
    )
    first_ids = await sync_matches(db_session, _fake_source([normalized]))
    await db_session.commit()
    second_ids = await sync_matches(db_session, _fake_source([normalized]))
    assert len(first_ids) == 1
    assert second_ids == []
