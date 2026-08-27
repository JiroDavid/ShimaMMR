from val_bot.db.models import Player, Match, MatchParticipant
from datetime import datetime, timezone


async def test_create_player_defaults(db_session):
    player = Player(discord_id="123")
    db_session.add(player)
    await db_session.flush()
    assert player.mmr == 700
    assert player.games_played == 0
    assert player.consented is False


async def test_create_match_with_participants(db_session):
    for discord_id in ("p1", "p2"):
        db_session.add(Player(discord_id=discord_id))
    await db_session.flush()

    match = Match(
        played_at=datetime.now(timezone.utc), map="Bind", source="manual",
        status="pending", reported_by_discord_id="p1",
        team_a_score=13, team_b_score=7,
    )
    match.participants.append(MatchParticipant(discord_id="p1", team="A", won=True))
    match.participants.append(MatchParticipant(discord_id="p2", team="B", won=False))
    db_session.add(match)
    await db_session.flush()

    assert match.id is not None
    assert len(match.participants) == 2
    assert match.participants[0].mmr_before is None
