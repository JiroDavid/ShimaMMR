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

from val_bot.db.match_service import void_match, correct_match

async def _play_three_matches(db_session):
    """a,b beat c,d twice, then c,d beat a,b once — gives every player
    enough history that a correction to match 1 has somewhere to ripple."""
    for d in ("a", "b", "c", "d"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    def match(team_a_score, team_b_score):
        return NormalizedMatch(
            played_at=datetime.now(timezone.utc), map="Bind", source="manual",
            team_a_score=team_a_score, team_b_score=team_b_score,
            reported_by_discord_id="a",
            participants=[
                NormalizedParticipant(discord_id="a", team="A"),
                NormalizedParticipant(discord_id="b", team="A"),
                NormalizedParticipant(discord_id="c", team="B"),
                NormalizedParticipant(discord_id="d", team="B"),
            ],
        )

    m1 = await confirm_match(db_session, (await create_pending_match(db_session, match(13, 4))).id)
    m2 = await confirm_match(db_session, (await create_pending_match(db_session, match(13, 8))).id)
    m3 = await confirm_match(db_session, (await create_pending_match(db_session, match(6, 13))).id)
    return m1, m2, m3

async def test_correct_match_recomputes_forward_and_ripples(db_session):
    m1, m2, m3 = await _play_three_matches(db_session)
    a_before_correction = (await db_session.get(Player, "a")).mmr

    # correct match 1: the score was mis-recorded and team B actually won,
    # so team A's win should be reversed to a loss
    await correct_match(db_session, m1.id, team_a_score=10, team_b_score=13)

    a_after_correction = (await db_session.get(Player, "a")).mmr
    assert a_after_correction != a_before_correction  # ripples through m2 and m3 too

    # m2 and m3's mmr_before for "a" must now chain consistently
    await db_session.refresh(m2, attribute_names=["participants"])
    await db_session.refresh(m3, attribute_names=["participants"])
    m2_a = next(p for p in m2.participants if p.discord_id == "a")
    m3_a = next(p for p in m3.participants if p.discord_id == "a")
    assert m2_a.mmr_after == m3_a.mmr_before

async def test_void_match_removes_its_contribution(db_session):
    m1, m2, m3 = await _play_three_matches(db_session)
    await void_match(db_session, m2.id)

    await db_session.refresh(m2)
    assert m2.status == "voided"

    # m3's mmr_before for "a" should now chain directly from m1's mmr_after,
    # since m2 no longer contributes
    await db_session.refresh(m1, attribute_names=["participants"])
    await db_session.refresh(m3, attribute_names=["participants"])
    m1_a = next(p for p in m1.participants if p.discord_id == "a")
    m3_a = next(p for p in m3.participants if p.discord_id == "a")
    assert m3_a.mmr_before == m1_a.mmr_after
