import discord
from discord import app_commands
from discord.ext import commands
from val_bot.db.models import Player
from val_bot.ingestion.henrikdev import resolve_account

async def link_command_callback(
    send, session_factory, discord_id: str, riot_username: str, riot_tag: str,
    api_key: str | None = None,
):
    account = await resolve_account(api_key, riot_username, riot_tag) if api_key else None
    if account is not None:
        riot_username, riot_tag = account["name"], account["tag"]

    async with session_factory() as session:
        player = await session.get(Player, discord_id)
        if player is None:
            player = Player(discord_id=discord_id)
            session.add(player)
        player.riot_username = riot_username
        player.riot_tag = riot_tag
        if account is not None:
            player.puuid = account["puuid"]
            player.region = account["region"]
        player.consented = True
        await session.commit()

    if account is not None:
        await send(
            f"Linked to **{riot_username}#{riot_tag}**. You'll now show up with your Riot name "
            "on the leaderboard, and be eligible for automatic match detection."
        )
    else:
        await send(
            f"Linked to **{riot_username}#{riot_tag}**, but I couldn't verify that Riot ID with "
            "Riot's servers just now - double check the spelling if this doesn't look right. "
            "Automatic match detection won't pick you up until this resolves (re-run /link to retry)."
        )

class LinkingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="link", description="Link your Discord account to your Riot ID")
    @app_commands.describe(riot_username="Your Riot username (before the #)", riot_tag="Your Riot tag (after the #)")
    async def link(self, interaction: discord.Interaction, riot_username: str, riot_tag: str):
        async def send(content):
            await interaction.response.send_message(content, ephemeral=True)
        await link_command_callback(
            send, self.bot.session_factory, str(interaction.user.id), riot_username, riot_tag,
            api_key=self.bot.henrikdev_api_key,
        )

    @commands.command(name="link")
    async def link_prefix(self, ctx: commands.Context, riot_username: str, riot_tag: str):
        await link_command_callback(
            ctx.send, self.bot.session_factory, str(ctx.author.id), riot_username, riot_tag,
            api_key=self.bot.henrikdev_api_key,
        )

async def setup(bot):
    await bot.add_cog(LinkingCog(bot))
