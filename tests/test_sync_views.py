from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from val_bot.bot.views.sync_views import UnknownPlayerResolutionView
from val_bot.ingestion.henrikdev import HenrikDevSource, PendingResolution, UnknownPlayer
from val_bot.db.models import Player

def _pending():
    raw_match = {
        "metadata": {"match_id": "m1", "map": {"name": "Bind"}, "started_at": "2026-08-24T20:33:00.591Z", "region": "eu"},
        "players": [
            {"puuid": "puuid-1", "team_id": "Red", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
            {"puuid": "unk-puuid", "team_id": "Blue", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
        ],
        "teams": [
            {"team_id": "Red", "rounds": {"won": 13}},
            {"team_id": "Blue", "rounds": {"won": 5}},
        ],
    }
    return PendingResolution(
        raw_match=raw_match, map="Bind", played_at=datetime.now(timezone.utc), region="eu",
        unknown_players=[UnknownPlayer(puuid="unk-puuid", name="stranger", tag="123")],
    )

def _source_factory():
    return lambda: HenrikDevSource(
        api_key=None, consented_players=[{"discord_id": "1", "puuid": "puuid-1", "region": "eu"}],
    )

def test_view_builds_one_select_per_unknown_player():
    view = UnknownPlayerResolutionView(
        session_factory=MagicMock(), source_factory=_source_factory(), pending=_pending(), on_finalized=AsyncMock(),
    )
    import discord
    selects = [item for item in view.children if isinstance(item, discord.ui.UserSelect)]
    assert len(selects) == 1
    assert "stranger#123" in selects[0].placeholder

async def test_finalize_resolves_selection_and_creates_match(db_session):
    db_session.add(Player(discord_id="1", consented=True, puuid="puuid-1", region="eu"))
    await db_session.flush()

    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    on_finalized = AsyncMock()
    view = UnknownPlayerResolutionView(
        session_factory=session_factory, source_factory=_source_factory(), pending=_pending(), on_finalized=on_finalized,
    )
    # simulate the admin having picked a Discord user for the unknown player
    view._selections["unk-puuid"] = "999"

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    await view.finalize.callback(interaction)

    interaction.response.defer.assert_awaited_once()
    new_player = await db_session.get(Player, "999")
    assert new_player is not None
    assert new_player.puuid == "unk-puuid"
    on_finalized.assert_awaited_once()
    call_args = on_finalized.await_args.args
    assert call_args[0] is interaction

async def test_finalize_excludes_players_left_unselected(db_session):
    db_session.add(Player(discord_id="1", consented=True, puuid="puuid-1", region="eu"))
    await db_session.flush()

    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    on_finalized = AsyncMock()
    view = UnknownPlayerResolutionView(
        session_factory=session_factory, source_factory=_source_factory(), pending=_pending(), on_finalized=on_finalized,
    )
    # left the unknown player's select empty - they should just be excluded

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    await view.finalize.callback(interaction)

    from val_bot.db.models import Match
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    result = await db_session.execute(select(Match).options(selectinload(Match.participants)))
    match = result.scalar_one()
    assert len(match.participants) == 1
