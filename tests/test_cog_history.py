from datetime import datetime, timezone
from val_bot.bot.views.history_views import (
    fetch_recent_matches, format_match_summary, format_full_match,
)
from val_bot.db.models import Player, Match, MatchParticipant

async def _confirmed_match(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()
    match = Match(
        played_at=datetime.now(timezone.utc), map="Lotus", source="manual",
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

async def test_fetch_recent_matches_filters_by_player(db_session):
    match = await _confirmed_match(db_session)
    matches = await fetch_recent_matches(db_session, "1")
    assert [m.id for m in matches] == [match.id]
    matches_for_unrelated_player = await fetch_recent_matches(db_session, "999")
    assert matches_for_unrelated_player == []

async def test_format_match_summary_shows_result_and_delta(db_session):
    match = await _confirmed_match(db_session)
    text = format_match_summary(match, "1")
    assert "Win" in text
    assert "20/10/5" in text
    assert "+20" in text

async def test_format_full_match_shows_all_participants(db_session):
    match = await _confirmed_match(db_session)
    text = format_full_match(match)
    assert "<@1>" in text and "<@2>" in text
    assert "+20" in text and "-15" in text
