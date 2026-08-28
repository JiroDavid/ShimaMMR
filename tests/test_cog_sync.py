from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from val_bot.bot.cogs.sync import (
    SyncCog, sync_matches, resolve_unknown_players, consented_players_for_sync,
    reannounce_match_callback, _sync_and_announce,
)
from val_bot.db.models import Player, PlayerPuuid, Match, IgnoredPuuid
from val_bot.db.match_service import create_pending_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant
from val_bot.ingestion.henrikdev import PendingResolution, UnknownPlayer, HenrikDevSource
from datetime import datetime, timedelta, timezone

def _normalized_match(external_id="ext-1"):
    return NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Sunset", source="henrikdev",
        team_a_score=13, team_b_score=9, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
        external_match_id=external_id,
    )

def _fake_source(matches, unresolved=None):
    source = AsyncMock()
    source.fetch_new_matches = AsyncMock(return_value=matches)
    source.unresolved_matches = unresolved or []
    return lambda: source

async def test_sync_matches_creates_pending_match_for_new_data(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()

    created, unresolved = await sync_matches(db_session, _fake_source([_normalized_match()]))

    assert len(created) == 1
    assert unresolved == []
    match = await db_session.get(Match, created[0].id)
    assert match.status == "pending"
    assert match.external_match_id == "ext-1"

async def test_sync_matches_skips_already_ingested_external_id(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()

    normalized = _normalized_match()
    first, _ = await sync_matches(db_session, _fake_source([normalized]))
    await db_session.commit()
    second, _ = await sync_matches(db_session, _fake_source([normalized]))
    assert len(first) == 1
    assert second == []

async def test_sync_matches_skips_manually_imported_match_with_matching_roster_map_and_score(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()

    played_at = datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc)
    manual = NormalizedMatch(
        played_at=played_at, map="Ascent", source="manual",
        team_a_score=13, team_b_score=10, reported_by_discord_id="csv-import",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
    )
    await create_pending_match(db_session, manual)
    await db_session.commit()

    # HenrikDev's own Red/Blue team labeling doesn't have to agree with the
    # manual report's Team1/Team2, and its score-pair may come back swapped -
    # the fuzzy match should still catch it via roster + map + score set.
    auto = NormalizedMatch(
        played_at=played_at + timedelta(minutes=5), map="Ascent", source="henrikdev",
        team_a_score=10, team_b_score=13, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="B"),
            NormalizedParticipant(discord_id="2", team="A"),
        ],
        external_match_id="real-henrikdev-id",
    )
    created, _ = await sync_matches(db_session, _fake_source([auto]))

    assert created == []
    result = await db_session.execute(select(Match))
    matches = result.scalars().all()
    assert len(matches) == 1
    assert matches[0].external_match_id == "real-henrikdev-id"

async def test_sync_matches_does_not_dedup_different_roster(db_session):
    for d in ("1", "2", "3"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()

    played_at = datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc)
    manual = NormalizedMatch(
        played_at=played_at, map="Ascent", source="manual",
        team_a_score=13, team_b_score=10, reported_by_discord_id="csv-import",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
    )
    await create_pending_match(db_session, manual)
    await db_session.commit()

    different_roster = NormalizedMatch(
        played_at=played_at + timedelta(minutes=5), map="Ascent", source="henrikdev",
        team_a_score=13, team_b_score=10, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="3", team="B"),
        ],
        external_match_id="real-henrikdev-id",
    )
    created, _ = await sync_matches(db_session, _fake_source([different_roster]))

    assert len(created) == 1
    result = await db_session.execute(select(Match))
    assert len(result.scalars().all()) == 2

async def test_sync_and_announce_only_announces_unresolved_match_once(db_session):
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    pending = PendingResolution(
        raw_match={"metadata": {"match_id": "unresolved-1"}}, map="Corrode",
        played_at=datetime.now(timezone.utc), region="eu",
        unknown_players=[UnknownPlayer(puuid="unk", name="gabbo", tag="2112")],
    )

    def fake_source(*args, **kwargs):
        source = MagicMock()
        source.fetch_new_matches = AsyncMock(return_value=[])
        source.unresolved_matches = [pending]
        return source

    with patch("val_bot.bot.cogs.sync.HenrikDevSource", side_effect=fake_source):
        send1 = AsyncMock()
        found1 = await _sync_and_announce(session_factory, None, send1)
        await db_session.commit()

        send2 = AsyncMock()
        found2 = await _sync_and_announce(session_factory, None, send2)

    assert found1 is True
    send1.assert_awaited()
    assert found2 is False
    send2.assert_not_awaited()

async def test_sync_matches_surfaces_unresolved_matches(db_session):
    pending = PendingResolution(
        raw_match={}, map="Bind", played_at=datetime.now(timezone.utc), region="eu",
        unknown_players=[UnknownPlayer(puuid="unk", name="stranger", tag="123")],
    )
    created, unresolved = await sync_matches(db_session, _fake_source([], unresolved=[pending]))
    assert created == []
    assert unresolved == [pending]

async def test_consented_players_for_sync_includes_primary_and_alt_puuids(db_session):
    db_session.add(Player(discord_id="1", consented=True, puuid="puuid-1", region="eu"))
    db_session.add(Player(discord_id="2", consented=False, puuid="puuid-2", region="eu"))  # not consented - excluded
    db_session.add(Player(discord_id="3", consented=True, puuid=None, region=None))  # no puuid yet - excluded
    db_session.add(PlayerPuuid(puuid="alt-puuid-1", discord_id="1", region="eu"))
    await db_session.flush()

    players = await consented_players_for_sync(db_session)

    puuids = {p["puuid"] for p in players}
    assert puuids == {"puuid-1", "alt-puuid-1"}

async def test_resolve_unknown_players_links_brand_new_player(db_session):
    db_session.add(Player(discord_id="1", consented=True, puuid="puuid-1", region="eu"))
    db_session.add(Player(discord_id="2", consented=True, puuid="puuid-2", region="eu"))
    await db_session.flush()

    consented = [{"discord_id": "1", "puuid": "puuid-1", "region": "eu"}, {"discord_id": "2", "puuid": "puuid-2", "region": "eu"}]
    source = HenrikDevSource(api_key=None, consented_players=consented)
    raw_match = {
        "metadata": {"match_id": "m1", "map": {"name": "Bind"}, "started_at": "2026-08-24T20:33:00.591Z", "region": "eu"},
        "players": [
            {"puuid": "puuid-1", "team_id": "Red", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
            {"puuid": "puuid-2", "team_id": "Red", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
            {"puuid": "unk-puuid", "team_id": "Blue", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
        ],
        "teams": [
            {"team_id": "Red", "rounds": {"won": 13}},
            {"team_id": "Blue", "rounds": {"won": 5}},
        ],
    }
    pending = PendingResolution(
        raw_match=raw_match, map="Bind", played_at=datetime.now(timezone.utc), region="eu",
        unknown_players=[UnknownPlayer(puuid="unk-puuid", name="newbie", tag="000")],
    )

    match = await resolve_unknown_players(db_session, source, pending, resolved={"unk-puuid": "999"})

    new_player = await db_session.get(Player, "999")
    assert new_player is not None
    assert new_player.puuid == "unk-puuid"
    assert new_player.consented is True
    assert len(match.participants) == 3

async def test_resolve_unknown_players_stores_alt_puuid_for_already_linked_player(db_session):
    db_session.add(Player(discord_id="1", consented=True, puuid="puuid-1", region="eu"))
    db_session.add(Player(discord_id="2", consented=True, puuid="puuid-2", region="eu"))
    # "2" is already linked under puuid-2, but shows up in this match on a
    # different account (an alt) - should NOT overwrite their primary puuid.
    db_session.add(Player(discord_id="999", consented=True, puuid="puuid-999-main", region="eu"))
    await db_session.flush()

    consented = [{"discord_id": "1", "puuid": "puuid-1", "region": "eu"}, {"discord_id": "999", "puuid": "puuid-999-main", "region": "eu"}]
    source = HenrikDevSource(api_key=None, consented_players=consented)
    raw_match = {
        "metadata": {"match_id": "m1", "map": {"name": "Bind"}, "started_at": "2026-08-24T20:33:00.591Z", "region": "eu"},
        "players": [
            {"puuid": "puuid-1", "team_id": "Red", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
            {"puuid": "puuid-999-main", "team_id": "Red", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
            {"puuid": "alt-of-999", "team_id": "Blue", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
        ],
        "teams": [
            {"team_id": "Red", "rounds": {"won": 13}},
            {"team_id": "Blue", "rounds": {"won": 5}},
        ],
    }
    pending = PendingResolution(
        raw_match=raw_match, map="Bind", played_at=datetime.now(timezone.utc), region="eu",
        unknown_players=[UnknownPlayer(puuid="alt-of-999", name="samepersonalt", tag="000")],
    )

    await resolve_unknown_players(db_session, source, pending, resolved={"alt-of-999": "999"})

    player_999 = await db_session.get(Player, "999")
    assert player_999.puuid == "puuid-999-main"  # primary untouched
    alt = await db_session.get(PlayerPuuid, "alt-of-999")
    assert alt.discord_id == "999"

async def test_resolve_unknown_players_ignores_a_puuid_left_blank(db_session):
    db_session.add(Player(discord_id="1", consented=True, puuid="puuid-1", region="eu"))
    await db_session.flush()

    consented = [{"discord_id": "1", "puuid": "puuid-1", "region": "eu"}]
    source = HenrikDevSource(api_key=None, consented_players=consented)
    raw_match = {
        "metadata": {"match_id": "m1", "map": {"name": "Bind"}, "started_at": "2026-08-24T20:33:00.591Z", "region": "eu"},
        "players": [
            {"puuid": "puuid-1", "team_id": "Red", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
            {"puuid": "ghost-puuid", "team_id": "Blue", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
        ],
        "teams": [
            {"team_id": "Red", "rounds": {"won": 13}},
            {"team_id": "Blue", "rounds": {"won": 5}},
        ],
    }
    pending = PendingResolution(
        raw_match=raw_match, map="Bind", played_at=datetime.now(timezone.utc), region="eu",
        unknown_players=[UnknownPlayer(puuid="ghost-puuid", name="gabbo", tag="2112")],
    )

    # "ghost-puuid" left blank (excluded from `resolved`) - should be
    # recorded as ignored, not just dropped from this one match
    await resolve_unknown_players(db_session, source, pending, resolved={})

    ignored = await db_session.get(IgnoredPuuid, "ghost-puuid")
    assert ignored is not None
    assert ignored.name == "gabbo"
    assert ignored.tag == "2112"

async def test_resolve_unknown_players_reuses_existing_match_instead_of_crashing(db_session):
    """If this same real match already has a Match row (e.g. resolved once
    before, or re-announced due to a since-fixed bug), resolving it again
    must not try to INSERT a second row with the same external_match_id."""
    db_session.add(Player(discord_id="1", consented=True, puuid="puuid-1", region="eu"))
    await db_session.flush()

    consented = [{"discord_id": "1", "puuid": "puuid-1", "region": "eu"}]
    source = HenrikDevSource(api_key=None, consented_players=consented)
    raw_match = {
        "metadata": {"match_id": "dupe-id", "map": {"name": "Corrode"}, "started_at": "2026-08-24T20:33:00.591Z", "region": "eu"},
        "players": [
            {"puuid": "puuid-1", "team_id": "Red", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
            {"puuid": "ghost-puuid", "team_id": "Blue", "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 100}},
        ],
        "teams": [
            {"team_id": "Red", "rounds": {"won": 13}},
            {"team_id": "Blue", "rounds": {"won": 5}},
        ],
    }
    pending = PendingResolution(
        raw_match=raw_match, map="Corrode", played_at=datetime.now(timezone.utc), region="eu",
        unknown_players=[UnknownPlayer(puuid="ghost-puuid", name="gabbo", tag="2112")],
    )

    first = await resolve_unknown_players(db_session, source, pending, resolved={})
    await db_session.commit()

    second = await resolve_unknown_players(db_session, source, pending, resolved={})

    assert second.id == first.id
    result = await db_session.execute(select(Match).where(Match.external_match_id == "dupe-id"))
    assert len(result.scalars().all()) == 1

async def test_reannounce_match_posts_confirm_prompt_for_pending_match(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()
    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Bind", source="henrikdev",
        team_a_score=13, team_b_score=6, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
    )
    match = await create_pending_match(db_session, normalized)
    await db_session.commit()

    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    send = AsyncMock()

    await reannounce_match_callback(send, session_factory, match.id)

    send.assert_awaited_once()
    content, kwargs = send.await_args.args[0], send.await_args.kwargs
    assert f"match #{match.id}" in content
    assert "Bind" in content
    assert kwargs["view"] is not None

async def test_reannounce_match_reports_missing_match():
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
        get=AsyncMock(return_value=None),
    ))
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    send = AsyncMock()

    await reannounce_match_callback(send, session_factory, 999)

    send.assert_awaited_once_with("No match #999 found.")

async def test_reannounce_match_refuses_non_pending_match(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()
    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Bind", source="henrikdev",
        team_a_score=13, team_b_score=6, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
    )
    match = await create_pending_match(db_session, normalized)
    match.status = "voided"
    await db_session.commit()

    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    send = AsyncMock()

    await reannounce_match_callback(send, session_factory, match.id)

    send.assert_awaited_once_with(f"Match #{match.id} is already voided - nothing to re-announce.")

def test_reannounce_match_app_command_gates_on_administrator_permission():
    predicate = SyncCog.reannounce_match_cmd.checks[0]

    with pytest.raises(app_commands.MissingPermissions):
        predicate(SimpleNamespace(permissions=SimpleNamespace(administrator=False)))
    assert predicate(SimpleNamespace(permissions=SimpleNamespace(administrator=True))) is True

async def test_sync_matches_cmd_reports_failure_instead_of_hanging():
    bot = MagicMock()
    bot.sync_announce_channel_id = None  # don't start the background poller
    cog = SyncCog(bot)

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    with patch(
        "val_bot.bot.cogs.sync._sync_and_announce",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await cog.sync_matches_cmd.callback(cog, interaction)

    interaction.followup.send.assert_awaited_once()
    message = interaction.followup.send.await_args.args[0]
    assert "failed" in message.lower()

async def test_sync_matches_prefix_reports_failure_instead_of_hanging():
    bot = MagicMock()
    bot.sync_announce_channel_id = None
    cog = SyncCog(bot)

    ctx = MagicMock()
    ctx.send = AsyncMock()

    with patch(
        "val_bot.bot.cogs.sync._sync_and_announce",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await cog.sync_matches_prefix.callback(cog, ctx)

    ctx.send.assert_awaited_once()
    message = ctx.send.await_args.args[0]
    assert "failed" in message.lower()

def test_sync_matches_app_command_gates_on_administrator_permission():
    predicate = SyncCog.sync_matches_cmd.checks[0]

    with pytest.raises(app_commands.MissingPermissions):
        predicate(SimpleNamespace(permissions=SimpleNamespace(administrator=False)))
    assert predicate(SimpleNamespace(permissions=SimpleNamespace(administrator=True))) is True

def test_sync_matches_prefix_command_gates_on_administrator_permission():
    predicate = SyncCog.sync_matches_prefix.checks[0]

    with pytest.raises(commands.MissingPermissions):
        predicate(SimpleNamespace(permissions=SimpleNamespace(administrator=False)))
    assert predicate(SimpleNamespace(permissions=SimpleNamespace(administrator=True))) is True
