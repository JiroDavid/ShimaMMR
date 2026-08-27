from unittest.mock import AsyncMock, MagicMock
from val_bot.bot.cogs.linking import link_command_callback
from val_bot.db.models import Player

async def test_link_creates_new_player(db_session):
    interaction = MagicMock()
    interaction.user.id = 123
    interaction.response.send_message = AsyncMock()

    async def session_factory_cm():
        return db_session
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    await link_command_callback(interaction, session_factory, "Phantom", "NA1")

    player = await db_session.get(Player, "123")
    assert player.riot_username == "Phantom"
    assert player.riot_tag == "NA1"
    assert player.consented is True
    interaction.response.send_message.assert_awaited_once()

async def test_link_updates_existing_player(db_session):
    db_session.add(Player(discord_id="123", riot_username="Old", riot_tag="EU1"))
    await db_session.flush()

    interaction = MagicMock()
    interaction.user.id = 123
    interaction.response.send_message = AsyncMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    await link_command_callback(interaction, session_factory, "New", "NA1")

    player = await db_session.get(Player, "123")
    assert player.riot_username == "New"
    assert player.riot_tag == "NA1"
