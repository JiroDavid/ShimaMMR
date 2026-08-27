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
