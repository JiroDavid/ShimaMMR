import logging
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.pickup_views import (
    JOIN_EMOJI, PickupModal, PickupSession, StartPickupView, build_pickup_message,
)

logger = logging.getLogger(__name__)

class PickupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # message_id -> PickupSession. In-memory only - doesn't survive a
        # bot restart mid-signup, but pickups are short-lived same-day events.
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

    async def _refresh(self, channel_id: int, message_id: int):
        session = self.sessions.get(message_id)
        if session is None:
            return
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
        content = build_pickup_message(
            session.region, session.time, session.confirmed(), session.waitlist()
        )
        await message.edit(content=content, allowed_mentions=discord.AllowedMentions(everyone=True))

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
        if payload.message_id not in self.sessions:
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        self.sessions[payload.message_id].join(str(payload.user_id))
        await self._refresh(payload.channel_id, payload.message_id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        # removing any one reaction leaves the queue, even if the user still
        # has a different emoji reaction on the message - keeps this simple
        # rather than tracking per-emoji counts per user
        if payload.message_id not in self.sessions:
            return
        self.sessions[payload.message_id].leave(str(payload.user_id))
        await self._refresh(payload.channel_id, payload.message_id)

async def setup(bot):
    await bot.add_cog(PickupCog(bot))
