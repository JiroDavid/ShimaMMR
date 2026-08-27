import discord
from val_bot.bot.views.leaderboard_views import fetch_leaderboard_page, format_leaderboard_embed
from val_bot.db.models import Player


async def test_fetch_leaderboard_page_orders_by_mmr_desc(db_session):
    db_session.add(Player(discord_id="1", mmr=800))
    db_session.add(Player(discord_id="2", mmr=1200))
    db_session.add(Player(discord_id="3", mmr=650))
    await db_session.flush()

    page = await fetch_leaderboard_page(db_session, offset=0, limit=10)
    assert [p.discord_id for p in page] == ["2", "1", "3"]


async def test_format_leaderboard_embed_uses_riot_name_and_mention():
    players = [Player(discord_id="1", mmr=900, riot_username="Foo", riot_tag="NA1")]
    embed = format_leaderboard_embed(players, offset=0)
    assert isinstance(embed, discord.Embed)
    assert "Foo#NA1" in embed.description
    assert "<@1>" in embed.description


async def test_format_leaderboard_embed_handles_unlinked_player():
    players = [Player(discord_id="2", mmr=700, riot_username=None, riot_tag=None)]
    embed = format_leaderboard_embed(players, offset=0)
    assert "unlinked" in embed.description
    assert "<@2>" in embed.description


async def test_format_leaderboard_embed_handles_empty_page():
    embed = format_leaderboard_embed([], offset=0)
    assert "No players yet." in embed.description


async def test_format_leaderboard_embed_adds_medals_for_top_three():
    players = [
        Player(discord_id="1", mmr=1000),
        Player(discord_id="2", mmr=900),
        Player(discord_id="3", mmr=800),
        Player(discord_id="4", mmr=700),
    ]
    embed = format_leaderboard_embed(players, offset=0)
    lines = embed.description.split("\n")
    assert lines[0].startswith("🥇")
    assert lines[1].startswith("🥈")
    assert lines[2].startswith("🥉")
    assert lines[3].startswith("**4.**")


async def test_format_leaderboard_embed_no_medals_on_second_page():
    players = [Player(discord_id="11", mmr=500)]
    embed = format_leaderboard_embed(players, offset=10)
    assert embed.description.startswith("**11.**")
    assert "🥇" not in embed.description
