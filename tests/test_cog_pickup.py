from unittest.mock import AsyncMock, MagicMock
import discord
from val_bot.bot.cogs.pickup import PickupCog
from val_bot.bot.views.pickup_views import (
    CONFIRMED_CAPACITY, JOIN_EMOJI, PickupModal, PickupSession,
    StartPickupView, build_pickup_message,
)

def test_build_pickup_message_shows_placeholders_when_empty():
    content = build_pickup_message("EU", "Tonight 7:30pm BST", [], [])
    assert "*(none yet)*" in content
    assert "@everyone" in content
    assert "EU" in content
    assert "Tonight 7:30pm BST" in content

def test_build_pickup_message_lists_mentions():
    content = build_pickup_message("EU", "7:30pm BST", ["1", "2"], ["3"])
    assert "<@1>" in content
    assert "<@2>" in content
    assert "<@3>" in content
    assert "Confirmed (2/10)" in content

def test_pickup_session_join_is_idempotent():
    session = PickupSession(region="EU", time="7:30pm")
    session.join("1")
    session.join("1")
    assert session.order == ["1"]

def test_pickup_session_splits_confirmed_and_waitlist():
    session = PickupSession(region="EU", time="7:30pm")
    for i in range(12):
        session.join(str(i))
    assert session.confirmed() == [str(i) for i in range(CONFIRMED_CAPACITY)]
    assert session.waitlist() == [str(i) for i in range(CONFIRMED_CAPACITY, 12)]

def test_pickup_session_leave_promotes_waitlist():
    session = PickupSession(region="EU", time="7:30pm")
    for i in range(11):
        session.join(str(i))
    session.leave("0")  # confirmed slot 0 opens up
    assert session.confirmed() == [str(i) for i in range(1, 11)]
    assert session.waitlist() == []

async def test_modal_posts_message_and_calls_on_built():
    on_built = AsyncMock()
    modal = PickupModal(on_built)
    modal.time = "7:30pm BST"
    modal.region = "EU"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    message = MagicMock()
    interaction.original_response = AsyncMock(return_value=message)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_awaited_once()
    kwargs = interaction.response.send_message.await_args.kwargs
    assert kwargs["allowed_mentions"].everyone is True
    content = interaction.response.send_message.await_args.args[0]
    assert "EU" in content and "7:30pm BST" in content
    on_built.assert_awaited_once_with(message, "EU", "7:30pm BST")

async def test_on_built_registers_session_even_if_add_reaction_is_forbidden():
    cog = PickupCog(bot=MagicMock())
    on_built = cog._build_on_built()

    response = MagicMock(status=403, reason="Forbidden")
    message = MagicMock()
    message.id = 1
    message.channel.id = 5
    message.add_reaction = AsyncMock(side_effect=discord.Forbidden(response, "Missing Access"))

    await on_built(message, "EU", "7:30pm BST")  # should not raise

    assert 1 in cog.sessions
    assert cog.sessions[1].region == "EU"

async def test_start_pickup_button_opens_modal():
    on_built = AsyncMock()
    view = StartPickupView(on_built)

    interaction = MagicMock()
    interaction.response.send_modal = AsyncMock()

    await view.start_pickup.callback(interaction)

    interaction.response.send_modal.assert_awaited_once()
    modal = interaction.response.send_modal.await_args.args[0]
    assert isinstance(modal, PickupModal)
    assert modal.on_built is on_built

def _payload(message_id=1, user_id=99, channel_id=5, emoji=JOIN_EMOJI):
    payload = MagicMock()
    payload.message_id = message_id
    payload.user_id = user_id
    payload.channel_id = channel_id
    payload.emoji = emoji
    return payload

async def test_reaction_add_joins_and_refreshes_message():
    cog = PickupCog(bot=MagicMock())
    cog.bot.user.id = 12345
    cog.sessions[1] = PickupSession(region="EU", time="7:30pm")

    message = MagicMock()
    message.edit = AsyncMock()
    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    cog.bot.get_channel = MagicMock(return_value=channel)

    await cog.on_raw_reaction_add(_payload(user_id=99))

    assert cog.sessions[1].order == ["99"]
    message.edit.assert_awaited_once()
    assert "<@99>" in message.edit.await_args.kwargs["content"]

async def test_reaction_add_ignores_bots_own_reaction():
    cog = PickupCog(bot=MagicMock())
    cog.bot.user.id = 12345
    cog.sessions[1] = PickupSession(region="EU", time="7:30pm")
    cog.bot.get_channel = MagicMock()

    await cog.on_raw_reaction_add(_payload(user_id=12345))

    assert cog.sessions[1].order == []
    cog.bot.get_channel.assert_not_called()

async def test_reaction_add_accepts_any_emoji():
    cog = PickupCog(bot=MagicMock())
    cog.bot.user.id = 12345
    cog.sessions[1] = PickupSession(region="EU", time="7:30pm")

    message = MagicMock()
    message.edit = AsyncMock()
    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    cog.bot.get_channel = MagicMock(return_value=channel)

    await cog.on_raw_reaction_add(_payload(user_id=99, emoji="🔥"))

    assert cog.sessions[1].order == ["99"]
    message.edit.assert_awaited_once()

async def test_reaction_remove_leaves_and_refreshes_message():
    cog = PickupCog(bot=MagicMock())
    cog.sessions[1] = PickupSession(region="EU", time="7:30pm")
    cog.sessions[1].join("99")

    message = MagicMock()
    message.edit = AsyncMock()
    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    cog.bot.get_channel = MagicMock(return_value=channel)

    await cog.on_raw_reaction_remove(_payload(user_id=99))

    assert cog.sessions[1].order == []
    message.edit.assert_awaited_once()

async def test_reaction_events_ignore_untracked_message():
    cog = PickupCog(bot=MagicMock())
    cog.bot.get_channel = MagicMock()

    await cog.on_raw_reaction_add(_payload(message_id=999))
    await cog.on_raw_reaction_remove(_payload(message_id=999))

    cog.bot.get_channel.assert_not_called()
