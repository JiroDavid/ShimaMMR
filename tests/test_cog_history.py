from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import discord
from val_bot.bot.views.history_views import (
    fetch_recent_matches, build_history_embed, format_full_match, MatchHistoryView,
)
from val_bot.db.models import Player, Match, MatchParticipant

async def _confirmed_match(db_session, map_name="Lotus"):
    for d in ("1", "2"):
        existing = await db_session.get(Player, d)
        if existing is None:
            db_session.add(Player(discord_id=d))
    await db_session.flush()
    match = Match(
        played_at=datetime.now(timezone.utc), map=map_name, source="manual",
        status="confirmed", reported_by_discord_id="1", team_a_score=13, team_b_score=5,
    )
    match.participants.append(MatchParticipant(
        discord_id="1", team="A", kills=20, deaths=10, assists=5,
        won=True, mmr_before=700, mmr_after=720,
    ))
    match.participants.append(MatchParticipant(
        discord_id="2", team="B", kills=10, deaths=20, assists=2,
        won=False, mmr_before=700, mmr_after=685,
    ))
    db_session.add(match)
    await db_session.flush()
    return match

def _user(display_name="jiro"):
    user = MagicMock()
    user.display_name = display_name
    user.display_avatar.url = "https://example.com/avatar.png"
    return user

async def test_fetch_recent_matches_filters_by_player(db_session):
    match = await _confirmed_match(db_session)
    matches = await fetch_recent_matches(db_session, "1")
    assert [m.id for m in matches] == [match.id]
    matches_for_unrelated_player = await fetch_recent_matches(db_session, "999")
    assert matches_for_unrelated_player == []

async def test_build_history_embed_works_on_freshly_fetched_matches(db_session):
    """Regression test: history.py builds the embed from whatever
    fetch_recent_matches returns, not the just-created object - participants
    must be eager-loaded or this crashes with a MissingGreenlet lazy-load
    error outside of the session's async context."""
    await _confirmed_match(db_session)
    await db_session.commit()

    matches = await fetch_recent_matches(db_session, "1")
    embed = build_history_embed(_user(), matches, "1")

    assert "Win" in embed.fields[0].name

async def test_build_history_embed_shows_result_score_and_mmr_delta(db_session):
    match = await _confirmed_match(db_session)
    embed = build_history_embed(_user(), [match], "1")

    field = embed.fields[0]
    assert "Win" in field.name and "Lotus" in field.name and f"#{match.id}" in field.name
    assert "13-5" in field.value
    assert "20/10/5" in field.value
    assert "+20" in field.value

async def test_build_history_embed_distinguishes_unknown_map_matches_by_date(db_session):
    match_a = await _confirmed_match(db_session, map_name="unknown")
    match_b = await _confirmed_match(db_session, map_name="unknown")
    embed = build_history_embed(_user(), [match_a, match_b], "1")
    names = [f.name for f in embed.fields]
    assert names[0] != names[1]
    assert match_a.played_at.strftime("%b %d") in names[0]

async def test_build_history_embed_has_one_field_per_match(db_session):
    match_a = await _confirmed_match(db_session, map_name="Bind")
    match_b = await _confirmed_match(db_session, map_name="Ascent")
    embed = build_history_embed(_user(), [match_a, match_b], "1")
    assert len(embed.fields) == 2

async def test_format_full_match_shows_all_participants(db_session):
    match = await _confirmed_match(db_session)
    text = format_full_match(match)
    assert "<@1>" in text and "<@2>" in text
    assert "+20" in text and "-15" in text

async def test_match_history_view_has_one_button_per_match(db_session):
    match_a = await _confirmed_match(db_session, map_name="Bind")
    match_b = await _confirmed_match(db_session, map_name="Ascent")
    view = MatchHistoryView(MagicMock(), [match_a, match_b])
    buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
    assert len(buttons) == 2

async def test_match_history_view_button_shows_the_right_matchs_scoreboard(db_session):
    """Regression test: each button re-fetches its OWN match by id via
    session.get() rather than reusing an already-loaded object - same
    eager-load requirement as fetch_recent_matches above - and must show
    the correct match, not just whichever was clicked first/last."""
    match_a = await _confirmed_match(db_session, map_name="Bind")
    match_b = await _confirmed_match(db_session, map_name="Ascent")
    await db_session.commit()

    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    view = MatchHistoryView(session_factory, [match_a, match_b])
    buttons = [item for item in view.children if item.label == f"Ascent · #{match_b.id}"]
    assert len(buttons) == 1

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    await buttons[0].callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    text = interaction.response.send_message.await_args.args[0]
    assert "Ascent" in text
    assert "Bind" not in text
