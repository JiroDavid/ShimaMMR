from val_bot.bot.views.leaderboard_views import fetch_leaderboard_page, format_leaderboard_page
from val_bot.db.models import Player


async def test_fetch_leaderboard_page_orders_by_mmr_desc(db_session):
    db_session.add(Player(discord_id="1", mmr=800))
    db_session.add(Player(discord_id="2", mmr=1200))
    db_session.add(Player(discord_id="3", mmr=650))
    await db_session.flush()

    page = await fetch_leaderboard_page(db_session, offset=0, limit=10)
    assert [p.discord_id for p in page] == ["2", "1", "3"]


async def test_format_leaderboard_page_uses_riot_name_and_mention():
    players = [Player(discord_id="1", mmr=900, riot_username="Foo", riot_tag="NA1")]
    text = format_leaderboard_page(players)
    assert "Foo#NA1" in text
    assert "<@1>" in text


async def test_format_leaderboard_page_handles_unlinked_player():
    players = [Player(discord_id="2", mmr=700, riot_username=None, riot_tag=None)]
    text = format_leaderboard_page(players)
    assert "unlinked" in text
    assert "<@2>" in text
