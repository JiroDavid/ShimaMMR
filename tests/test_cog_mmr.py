from val_bot.bot.cogs.mmr import build_mmr_embed
from val_bot.db.models import Player

async def test_build_mmr_embed_for_known_player(db_session):
    db_session.add(Player(discord_id="1", mmr=900, games_played=12, riot_username="Foo", riot_tag="NA1"))
    await db_session.flush()

    embed = await build_mmr_embed(db_session, "1")
    assert "900" in embed.description
    assert "Ascendant" in embed.description

async def test_build_mmr_embed_returns_none_for_unknown_player(db_session):
    embed = await build_mmr_embed(db_session, "999")
    assert embed is None
