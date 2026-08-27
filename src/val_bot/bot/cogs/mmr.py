import discord
from discord import app_commands
from discord.ext import commands
from val_bot.db.models import Player
from val_bot.rating.tiers import mmr_to_tier

async def build_mmr_embed(session, discord_id: str) -> discord.Embed | None:
    player = await session.get(Player, discord_id)
    if player is None:
        return None
    tier = mmr_to_tier(player.mmr)
    name = f"{player.riot_username}#{player.riot_tag}" if player.riot_username else f"<@{discord_id}>"
    return discord.Embed(
        title=name,
        description=f"**{tier}** — {player.mmr} MMR\nGames played: {player.games_played}",
    )

class MmrCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mmr", description="Check your (or someone else's) MMR and rank")
    async def mmr(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        async with self.bot.session_factory() as session:
            embed = await build_mmr_embed(session, str(target.id))
        if embed is None:
            await interaction.response.send_message(
                f"{target.mention} hasn't played a rated match yet.", ephemeral=True
            )
            return
        await interaction.response.send_message(embed=embed)

    @commands.command(name="mmr")
    async def mmr_prefix(self, ctx: commands.Context, user: discord.Member | None = None):
        target = user or ctx.author
        async with self.bot.session_factory() as session:
            embed = await build_mmr_embed(session, str(target.id))
        if embed is None:
            await ctx.send(f"{target.mention} hasn't played a rated match yet.")
            return
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(MmrCog(bot))
