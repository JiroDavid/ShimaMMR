from unittest.mock import MagicMock
import discord
from val_bot.bot.views.leaderboard_views import fetch_leaderboard_page, format_leaderboard_embed
from val_bot.db.models import Player


def _field(embed, name):
    return next(f for f in embed.fields if f.name == name)


async def test_fetch_leaderboard_page_orders_by_mmr_desc(db_session):
    db_session.add(Player(discord_id="1", mmr=800))
    db_session.add(Player(discord_id="2", mmr=1200))
    db_session.add(Player(discord_id="3", mmr=650))
    await db_session.flush()

    page = await fetch_leaderboard_page(db_session, offset=0, limit=10)
    assert [p.discord_id for p in page] == ["2", "1", "3"]


async def test_format_leaderboard_embed_has_title_and_description():
    embed = format_leaderboard_embed([Player(discord_id="1", mmr=900)], offset=0)
    assert embed.title
    assert embed.description


async def test_format_leaderboard_embed_uses_riot_name_and_mention():
    players = [Player(discord_id="1", mmr=900, riot_username="Foo", riot_tag="NA1")]
    embed = format_leaderboard_embed(players, offset=0)
    player_field = _field(embed, "Player")
    assert "Foo#NA1" in player_field.value
    assert "<@1>" in player_field.value


async def test_format_leaderboard_embed_handles_unlinked_player():
    players = [Player(discord_id="2", mmr=700, riot_username=None, riot_tag=None)]
    embed = format_leaderboard_embed(players, offset=0)
    assert "unlinked" in _field(embed, "Player").value
    assert "<@2>" in _field(embed, "Player").value


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
    lines = _field(embed, "Player").value.split("\n\n")
    assert lines[0].startswith("🥇")
    assert lines[1].startswith("🥈")
    assert lines[2].startswith("🥉")
    assert lines[3].startswith("**4.**")


async def test_format_leaderboard_embed_no_medals_on_second_page():
    players = [Player(discord_id="11", mmr=500)]
    embed = format_leaderboard_embed(players, offset=10)
    assert _field(embed, "Player").value.startswith("**11.**")
    assert "🥇" not in _field(embed, "Player").value


async def test_format_leaderboard_embed_shows_mmr_column():
    players = [Player(discord_id="1", mmr=812)]
    embed = format_leaderboard_embed(players, offset=0)
    assert "812" in _field(embed, "MMR").value


async def test_format_leaderboard_embed_shows_rank_tier():
    players = [Player(discord_id="1", mmr=812)]  # Diamond range (800-874)
    embed = format_leaderboard_embed(players, offset=0)
    assert "Diamond" in _field(embed, "Rank").value


async def test_format_leaderboard_embed_uses_guild_emoji_when_available():
    fake_emoji = MagicMock()
    fake_emoji.name = "64465valorantdiamond3"
    fake_emoji.__str__.return_value = "<:64465valorantdiamond3:999999999999999999>"
    guild = MagicMock()
    guild.emojis = [fake_emoji]

    players = [Player(discord_id="1", mmr=812)]  # Diamond
    embed = format_leaderboard_embed(players, offset=0, guild=guild)

    assert "<:64465valorantdiamond3:999999999999999999>" in _field(embed, "Rank").value


async def test_format_leaderboard_embed_falls_back_gracefully_without_matching_emoji():
    guild = MagicMock()
    guild.emojis = []  # server doesn't have the emoji uploaded

    players = [Player(discord_id="1", mmr=812)]
    embed = format_leaderboard_embed(players, offset=0, guild=guild)

    assert "Diamond" in _field(embed, "Rank").value
