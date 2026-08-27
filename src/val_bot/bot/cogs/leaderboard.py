import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.leaderboard_views import LeaderboardView


class LeaderboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Show the server MMR leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        view = LeaderboardView(self.bot.session_factory)
        embed = await view.render()
        await interaction.response.send_message(embed=embed, view=view)

    @commands.command(name="leaderboard")
    async def leaderboard_prefix(self, ctx: commands.Context):
        view = LeaderboardView(self.bot.session_factory)
        embed = await view.render()
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))
