from datetime import datetime, timezone
from val_bot.db.models import Player
from val_bot.db.match_service import create_pending_match, confirm_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant

def _normalized_match():
    return NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Split", source="manual",
        team_a_score=13, team_b_score=6, reported_by_discord_id="p1",
        participants=[
            NormalizedParticipant(discord_id="p1", team="A"),
            NormalizedParticipant(discord_id="p2", team="A"),
            NormalizedParticipant(discord_id="p3", team="B"),
            NormalizedParticipant(discord_id="p4", team="B"),
        ],
    )

async def test_create_pending_match_does_not_touch_mmr(db_session):
    for d in ("p1", "p2", "p3", "p4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    match = await create_pending_match(db_session, _normalized_match())
    assert match.status == "pending"
    assert all(p.mmr_before is None for p in match.participants)
    p1 = await db_session.get(Player, "p1")
    assert p1.mmr == 700  # unchanged until confirmed

async def test_confirm_match_applies_ratings(db_session):
    for d in ("p1", "p2", "p3", "p4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    match = await create_pending_match(db_session, _normalized_match())
    confirmed = await confirm_match(db_session, match.id)

    assert confirmed.status == "confirmed"
    p1 = await db_session.get(Player, "p1")
    p3 = await db_session.get(Player, "p3")
    assert p1.mmr > 700  # winner
    assert p3.mmr < 700  # loser
    assert p1.games_played == 1
    winner_row = next(p for p in confirmed.participants if p.discord_id == "p1")
    assert winner_row.mmr_before == 700
    assert winner_row.mmr_after == p1.mmr
