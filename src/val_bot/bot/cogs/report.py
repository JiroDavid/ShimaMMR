import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.report_views import MatchReportModal, StartReportView
from val_bot.bot.views.report_views import ConfirmDisputeView  # added in Task 13

def _build_on_built(session_factory):
    async def on_built(inner_interaction: discord.Interaction, match_id: int):
        view = ConfirmDisputeView(session_factory, match_id)
        await inner_interaction.followup.send(
            f"Match #{match_id} reported. Waiting for confirmation from the "
            "other team (or a moderator) before MMR is applied.",
            view=view,
        )
    return on_built

class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="report-match", description="Report the result of a pickup match")
    async def report_match(self, interaction: discord.Interaction):
        modal = MatchReportModal(self.bot.session_factory, _build_on_built(self.bot.session_factory))
        await interaction.response.send_modal(modal)

    @commands.command(name="report-match")
    async def report_match_prefix(self, ctx: commands.Context):
        view = StartReportView(self.bot.session_factory, _build_on_built(self.bot.session_factory))
        await ctx.send("Click below to report a match:", view=view)

async def setup(bot):
    await bot.add_cog(ReportCog(bot))
