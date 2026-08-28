import respx
import httpx
from unittest.mock import AsyncMock, MagicMock
from val_bot.bot.cogs.linking import link_command_callback
from val_bot.db.models import Player

async def test_link_creates_new_player(db_session):
    send = AsyncMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    await link_command_callback(send, session_factory, "123", "Phantom", "NA1")

    player = await db_session.get(Player, "123")
    assert player.riot_username == "Phantom"
    assert player.riot_tag == "NA1"
    assert player.consented is True
    send.assert_awaited_once()

async def test_link_updates_existing_player(db_session):
    db_session.add(Player(discord_id="123", riot_username="Old", riot_tag="EU1"))
    await db_session.flush()

    send = AsyncMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    await link_command_callback(send, session_factory, "123", "New", "NA1")

    player = await db_session.get(Player, "123")
    assert player.riot_username == "New"
    assert player.riot_tag == "NA1"

def _session_factory(db_session):
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return session_factory

@respx.mock
async def test_link_resolves_puuid_and_region_when_api_key_configured(db_session):
    respx.get(url__regex=r".*/v2/account/jiroshima/NMS$").mock(
        return_value=httpx.Response(200, json={
            "status": 200,
            "data": {"puuid": "puuid-123", "region": "eu", "name": "Jiroshima", "tag": "NMS"},
        })
    )
    send = AsyncMock()

    await link_command_callback(
        send, _session_factory(db_session), "123", "jiroshima", "NMS", api_key="key",
    )

    player = await db_session.get(Player, "123")
    assert player.puuid == "puuid-123"
    assert player.region == "eu"
    # stores the API's normalized capitalization, not whatever the user typed
    assert player.riot_username == "Jiroshima"

@respx.mock
async def test_link_still_succeeds_when_account_lookup_fails(db_session):
    respx.get(url__regex=r".*/v2/account/typoed/NAME$").mock(
        return_value=httpx.Response(404, json={"errors": [{"message": "Not Found"}]})
    )
    send = AsyncMock()

    await link_command_callback(
        send, _session_factory(db_session), "123", "typoed", "NAME", api_key="key",
    )

    player = await db_session.get(Player, "123")
    assert player.riot_username == "typoed"  # kept what the user typed
    assert player.riot_tag == "NAME"
    assert player.consented is True
    assert player.puuid is None
    send.assert_awaited_once()
    message = send.await_args.args[0]
    assert "couldn't verify" in message

async def test_link_skips_resolution_when_no_api_key_configured(db_session):
    send = AsyncMock()

    await link_command_callback(
        send, _session_factory(db_session), "123", "Phantom", "NA1", api_key=None,
    )

    player = await db_session.get(Player, "123")
    assert player.riot_username == "Phantom"
    assert player.puuid is None
