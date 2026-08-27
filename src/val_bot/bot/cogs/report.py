import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.report_views import MatchReportModal
from val_bot.bot.views.report_views import ConfirmDisputeView  # added in Task 13

class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="report-match", description="Report the result of a pickup match")
    async def report_match(self, interaction: discord.Interaction):
        async def on_built(inner_interaction: discord.Interaction, match_id: int):
            view = ConfirmDisputeView(self.bot.session_factory, match_id)
            await inner_interaction.followup.send(
                f"Match #{match_id} reported. Waiting for confirmation from the "
                "other team (or a moderator) before MMR is applied.",
                view=view,
            )

        modal = MatchReportModal(self.bot.session_factory, on_built)
        await interaction.response.send_modal(modal)

async def setup(bot):
    await bot.add_cog(ReportCog(bot))
