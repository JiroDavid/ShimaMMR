import discord
from discord import app_commands
from discord.ext import commands
from val_bot.db.models import Player

async def link_command_callback(interaction, session_factory, riot_username: str, riot_tag: str):
    discord_id = str(interaction.user.id)
    async with session_factory() as session:
        player = await session.get(Player, discord_id)
        if player is None:
            player = Player(discord_id=discord_id)
            session.add(player)
        player.riot_username = riot_username
        player.riot_tag = riot_tag
        player.consented = True
        await session.commit()
    await interaction.response.send_message(
        f"Linked to **{riot_username}#{riot_tag}**. You'll now show up with your Riot name "
        "on the leaderboard, and be eligible for automatic match detection once that's live.",
        ephemeral=True,
    )

class LinkingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="link", description="Link your Discord account to your Riot ID")
    @app_commands.describe(riot_username="Your Riot username (before the #)", riot_tag="Your Riot tag (after the #)")
    async def link(self, interaction: discord.Interaction, riot_username: str, riot_tag: str):
        await link_command_callback(interaction, self.bot.session_factory, riot_username, riot_tag)

async def setup(bot):
    await bot.add_cog(LinkingCog(bot))
