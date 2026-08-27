import discord
from discord import app_commands
from discord.ext import commands
from val_bot.db.match_service import void_match, correct_match

async def void_match_callback(interaction, session_factory, match_id: int):
    async with session_factory() as session:
        await void_match(session, match_id)
        await session.commit()
    await interaction.response.send_message(
        f"Match #{match_id} voided. Downstream MMR has been recalculated.", ephemeral=True
    )

async def correct_match_callback(
    interaction, session_factory, match_id: int,
    team_a_score: int | None = None, team_b_score: int | None = None,
):
    async with session_factory() as session:
        await correct_match(session, match_id, team_a_score=team_a_score, team_b_score=team_b_score)
        await session.commit()
    await interaction.response.send_message(
        f"Match #{match_id} corrected. Downstream MMR has been recalculated.", ephemeral=True
    )

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="void-match", description="Void a match (Admin only)")
    @app_commands.checks.has_role("Admin")
    async def void_match_cmd(self, interaction: discord.Interaction, match_id: int):
        await void_match_callback(interaction, self.bot.session_factory, match_id)

    @app_commands.command(name="correct-match", description="Correct a match's scores (Admin only)")
    @app_commands.checks.has_role("Admin")
    async def correct_match_cmd(
        self, interaction: discord.Interaction, match_id: int,
        team_a_score: int | None = None, team_b_score: int | None = None,
    ):
        await correct_match_callback(
            interaction, self.bot.session_factory, match_id, team_a_score, team_b_score
        )

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
