import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.history_views import fetch_recent_matches, build_history_embed, MatchHistoryView

class HistoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="match-history", description="Show your (or someone else's) recent matches")
    async def match_history(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        discord_id = str(target.id)
        async with self.bot.session_factory() as session:
            matches = await fetch_recent_matches(session, discord_id)

        if not matches:
            await interaction.response.send_message(
                f"{target.mention} has no confirmed match history yet.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=build_history_embed(target, matches, discord_id),
            view=MatchHistoryView(self.bot.session_factory, matches),
        )

    @commands.command(name="match-history")
    async def match_history_prefix(self, ctx: commands.Context, user: discord.Member | None = None):
        target = user or ctx.author
        discord_id = str(target.id)
        async with self.bot.session_factory() as session:
            matches = await fetch_recent_matches(session, discord_id)

        if not matches:
            await ctx.send(f"{target.mention} has no confirmed match history yet.")
            return

        await ctx.send(
            embed=build_history_embed(target, matches, discord_id),
            view=MatchHistoryView(self.bot.session_factory, matches),
        )

async def setup(bot):
    await bot.add_cog(HistoryCog(bot))
