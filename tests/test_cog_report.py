from val_bot.bot.views.report_views import build_pending_match
from val_bot.db.models import Player

async def test_build_pending_match_creates_match_row(db_session):
    for d in ("1", "2", "3", "4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    match = await build_pending_match(
        session=db_session, map_name="Icebox", team_a_score=13, team_b_score=9,
        reporter_id="1", team_a_ids=["1", "2"], team_b_ids=["3", "4"],
    )

    assert match.status == "pending"
    assert match.map == "Icebox"
    assert len(match.participants) == 4

from val_bot.bot.views.report_views import ConfirmDisputeView
from val_bot.db.match_service import create_pending_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from val_bot.db.models import Match

async def _pending_match(db_session):
    for d in ("1", "2", "3", "4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()
    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Fracture", source="manual",
        team_a_score=13, team_b_score=7, reported_by_discord_id="1",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="A"),
            NormalizedParticipant(discord_id="3", team="B"),
            NormalizedParticipant(discord_id="4", team="B"),
        ],
    )
    match = await create_pending_match(db_session, normalized)
    await db_session.commit()
    return match.id

async def test_confirm_button_applies_match(db_session):
    match_id = await _pending_match(db_session)
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    view = ConfirmDisputeView(session_factory, match_id)
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()

    await view.confirm.callback(interaction)

    match = await db_session.get(Match, match_id)
    assert match.status == "confirmed"
    interaction.response.edit_message.assert_awaited_once()

async def test_dispute_button_voids_pending_match(db_session):
    match_id = await _pending_match(db_session)
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    view = ConfirmDisputeView(session_factory, match_id)
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()

    await view.dispute.callback(interaction)

    result = await db_session.execute(select(Match).where(Match.id == match_id))
    assert result.scalar_one_or_none() is None
