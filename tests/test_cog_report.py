from val_bot.bot.views.report_views import build_pending_match, MatchReportModal, TeamSelectView
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
    interaction.user.id = "3"  # opposing-team participant (reporter "1" is on team A)
    interaction.user.roles = []
    interaction.response.edit_message = AsyncMock()

    await view.confirm.callback(interaction)

    match = await db_session.get(Match, match_id)
    assert match.status == "confirmed"
    interaction.response.edit_message.assert_awaited_once()

async def test_confirm_button_rejects_reporter(db_session):
    match_id = await _pending_match(db_session)
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    view = ConfirmDisputeView(session_factory, match_id)
    interaction = MagicMock()
    interaction.user.id = "1"  # the reporter, same team as themselves
    interaction.user.roles = []
    interaction.response.send_message = AsyncMock()

    await view.confirm.callback(interaction)

    match = await db_session.get(Match, match_id)
    assert match.status == "pending"
    interaction.response.send_message.assert_awaited_once()

async def test_dispute_button_voids_pending_match(db_session):
    match_id = await _pending_match(db_session)
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    view = ConfirmDisputeView(session_factory, match_id)
    interaction = MagicMock()
    interaction.user.id = "1"  # the reporter may retract their own report
    interaction.user.roles = []
    interaction.response.edit_message = AsyncMock()

    await view.dispute.callback(interaction)

    result = await db_session.execute(select(Match).where(Match.id == match_id))
    assert result.scalar_one_or_none() is None

async def test_overlapping_team_selection_is_rejected(db_session):
    for d in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    on_built = AsyncMock()

    view = TeamSelectView(
        session_factory=session_factory, map_name="Bind",
        team_a_score=13, team_b_score=8, reporter_id="1", on_built=on_built,
    )
    interaction = MagicMock()
    interaction.followup.send = AsyncMock()

    # player "5" picked on both teams
    view.team_a_ids = ["1", "2", "3", "4", "5"]
    view.team_b_ids = ["5", "6", "7", "8", "9"]

    await view._maybe_finish(interaction)

    result = await db_session.execute(select(Match))
    assert result.scalar_one_or_none() is None
    on_built.assert_not_awaited()
    interaction.followup.send.assert_awaited_once()
    message = interaction.followup.send.await_args.args[0]
    assert "<@5>" in message
    assert view.team_a_ids is None
    assert view.team_b_ids is None

async def test_modal_rejects_non_numeric_score():
    on_built = AsyncMock()
    modal = MatchReportModal(session_factory=MagicMock(), on_built=on_built)
    modal.map_name = "Bind"
    modal.team_a_score = "thirteen"
    modal.team_b_score = "8"

    interaction = MagicMock()
    interaction.user.id = "1"
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_awaited_once()
    kwargs = interaction.response.send_message.await_args.kwargs
    assert kwargs.get("ephemeral") is True
    assert "view" not in kwargs
    on_built.assert_not_awaited()

async def test_start_report_button_opens_modal():
    from val_bot.bot.views.report_views import StartReportView

    on_built = AsyncMock()
    session_factory = MagicMock()
    view = StartReportView(session_factory=session_factory, on_built=on_built)

    interaction = MagicMock()
    interaction.response.send_modal = AsyncMock()

    await view.start_report.callback(interaction)

    interaction.response.send_modal.assert_awaited_once()
    modal = interaction.response.send_modal.await_args.args[0]
    assert isinstance(modal, MatchReportModal)
    assert modal.session_factory is session_factory
    assert modal.on_built is on_built

async def test_dispute_button_rejects_non_participant(db_session):
    match_id = await _pending_match(db_session)
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    view = ConfirmDisputeView(session_factory, match_id)
    interaction = MagicMock()
    interaction.user.id = "999"  # not a participant, not an admin
    interaction.user.roles = []
    interaction.response.send_message = AsyncMock()

    await view.dispute.callback(interaction)

    result = await db_session.execute(select(Match).where(Match.id == match_id))
    assert result.scalar_one_or_none() is not None
    interaction.response.send_message.assert_awaited_once()
