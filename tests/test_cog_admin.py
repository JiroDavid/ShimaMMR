from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
from val_bot.bot.cogs.admin import void_match_callback, correct_match_callback
from val_bot.db.models import Player, Match
from val_bot.db.match_service import create_pending_match, confirm_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant

async def _confirmed_match_id(db_session):
    for d in ("1", "2", "3", "4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()
    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Pearl", source="manual",
        team_a_score=13, team_b_score=6, reported_by_discord_id="1",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="A"),
            NormalizedParticipant(discord_id="3", team="B"),
            NormalizedParticipant(discord_id="4", team="B"),
        ],
    )
    match = await create_pending_match(db_session, normalized)
    await confirm_match(db_session, match.id)
    await db_session.commit()
    return match.id

def _session_factory(db_session):
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return session_factory

async def test_void_match_callback_voids_and_responds(db_session):
    match_id = await _confirmed_match_id(db_session)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await void_match_callback(interaction, _session_factory(db_session), match_id)

    match = await db_session.get(Match, match_id)
    assert match.status == "voided"
    interaction.response.send_message.assert_awaited_once()

async def test_correct_match_callback_updates_scores(db_session):
    match_id = await _confirmed_match_id(db_session)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await correct_match_callback(
        interaction, _session_factory(db_session), match_id,
        team_a_score=13, team_b_score=11,
    )

    match = await db_session.get(Match, match_id)
    assert match.team_a_score == 13
    assert match.team_b_score == 11
    interaction.response.send_message.assert_awaited_once()
