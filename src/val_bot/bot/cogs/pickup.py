import logging
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.pickup_views import (
    JOIN_EMOJI, PickupModal, PickupSession, StartPickupView,
    build_pickup_message, parse_pickup_message,
)

logger = logging.getLogger(__name__)

class PickupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # message_id -> PickupSession. In-memory only, but self-healing: if
        # this process loses a session (e.g. a bot restart mid-signup), the
        # next reaction event on that message rebuilds it from the message's
        # own text plus Discord's live reaction-user list instead of the
        # message being silently ignored forever.
        self.sessions: dict[int, PickupSession] = {}

    def _build_on_built(self):
        async def on_built(message: discord.Message, region: str, time: str):
            self.sessions[message.id] = PickupSession(region=region, time=time)
            try:
                await message.add_reaction(JOIN_EMOJI)
            except discord.Forbidden:
                # missing "Add Reactions" in this channel - the session still
                # works, players can just react with anything themselves
                # instead of clicking a pre-added one
                logger.warning(
                    "Missing Add Reactions permission in channel %s - pickup "
                    "message posted without an auto-added reaction",
                    message.channel.id,
                )
        return on_built

    async def _fetch_message(self, channel_id: int, message_id: int) -> discord.Message | None:
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound:
            return None

    async def _recover_session(self, channel_id: int, message_id: int) -> PickupSession | None:
        message = await self._fetch_message(channel_id, message_id)
        if message is None or self.bot.user is None or message.author.id != self.bot.user.id:
            return None
        parsed = parse_pickup_message(message.content)
        if parsed is None:
            return None
        region, time = parsed
        session = PickupSession(region=region, time=time)
        seen: set[int] = set()
        for reaction in message.reactions:
            async for user in reaction.users():
                if user.id == self.bot.user.id or user.id in seen:
                    continue
                seen.add(user.id)
                session.order.append(str(user.id))
        self.sessions[message_id] = session
        return session

    async def _get_session(self, channel_id: int, message_id: int) -> PickupSession | None:
        session = self.sessions.get(message_id)
        if session is not None:
            return session
        return await self._recover_session(channel_id, message_id)

    async def _refresh(self, channel_id: int, message_id: int):
        session = self.sessions.get(message_id)
        if session is None:
            return
        message = await self._fetch_message(channel_id, message_id)
        if message is None:
            return
        content = build_pickup_message(
            session.region, session.time, session.confirmed(), session.waitlist()
        )
        await message.edit(content=content, allowed_mentions=discord.AllowedMentions(everyone=True))
        if session.order and not session.bot_reaction_removed:
            session.bot_reaction_removed = True
            try:
                await message.remove_reaction(JOIN_EMOJI, self.bot.user)
            except discord.HTTPException:
                pass  # nothing to remove, or missing permission - not critical

    @app_commands.command(name="pickup", description="Announce a pickup game and open sign-ups (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def pickup(self, interaction: discord.Interaction):
        modal = PickupModal(self._build_on_built())
        await interaction.response.send_modal(modal)

    @commands.command(name="pickup")
    @commands.has_permissions(administrator=True)
    async def pickup_prefix(self, ctx: commands.Context):
        view = StartPickupView(self._build_on_built())
        await ctx.send("Click below to set up a pickup:", view=view)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # any emoji counts as joining - not just the auto-added JOIN_EMOJI
        was_tracked = payload.message_id in self.sessions
        if was_tracked and self.bot.user is not None and payload.user_id == self.bot.user.id:
            return  # already-tracked session, bot's own reaction - nothing changed
        session = await self._get_session(payload.channel_id, payload.message_id)
        if session is None:
            return
        if was_tracked:
            session.join(str(payload.user_id))
        # else: this session was just recovered from live reactions, which
        # already reflect this event - no separate join() needed
        await self._refresh(payload.channel_id, payload.message_id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        # removing any one reaction leaves the queue, even if the user still
        # has a different emoji reaction on the message - keeps this simple
        # rather than tracking per-emoji counts per user
        was_tracked = payload.message_id in self.sessions
        session = await self._get_session(payload.channel_id, payload.message_id)
        if session is None:
            return
        if was_tracked:
            session.leave(str(payload.user_id))
        await self._refresh(payload.channel_id, payload.message_id)

async def setup(bot):
    await bot.add_cog(PickupCog(bot))
