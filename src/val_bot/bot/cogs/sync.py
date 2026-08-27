import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from val_bot.db.models import Player, Match
from val_bot.db.match_service import create_pending_match
from val_bot.ingestion.henrikdev import HenrikDevSource

async def sync_matches(session, henrikdev_source_factory) -> list[int]:
    source = henrikdev_source_factory()
    normalized_matches = await source.fetch_new_matches()

    existing = await session.execute(
        select(Match.external_match_id).where(Match.external_match_id.isnot(None))
    )
    existing_ids = {row[0] for row in existing}

    created_ids = []
    for normalized in normalized_matches:
        if normalized.external_match_id in existing_ids:
            continue
        match = await create_pending_match(session, normalized)
        created_ids.append(match.id)
    return created_ids

class SyncCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sync-matches", description="Check HenrikDev for new pickup matches (Admin only)")
    @app_commands.checks.has_role("Admin")
    async def sync_matches_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.session_factory() as session:
            result = await session.execute(select(Player).where(Player.consented.is_(True)))
            consented = [
                {"discord_id": p.discord_id, "puuid": p.riot_username}  # puuid populated once /link stores it (see note below)
                for p in result.scalars() if p.riot_username
            ]

            def source_factory():
                return HenrikDevSource(self.bot.henrikdev_api_key, consented)

            new_ids = await sync_matches(session, source_factory)
            await session.commit()

        if not new_ids:
            await interaction.followup.send("No new matches found.")
        else:
            await interaction.followup.send(
                f"Found {len(new_ids)} new match(es): {', '.join(f'#{i}' for i in new_ids)}. "
                "Each needs confirmation before MMR applies — check the pending matches."
            )

    @commands.command(name="sync-matches")
    @commands.has_role("Admin")
    async def sync_matches_prefix(self, ctx: commands.Context):
        async with self.bot.session_factory() as session:
            result = await session.execute(select(Player).where(Player.consented.is_(True)))
            consented = [
                {"discord_id": p.discord_id, "puuid": p.riot_username}
                for p in result.scalars() if p.riot_username
            ]

            def source_factory():
                return HenrikDevSource(self.bot.henrikdev_api_key, consented)

            new_ids = await sync_matches(session, source_factory)
            await session.commit()

        if not new_ids:
            await ctx.send("No new matches found.")
        else:
            await ctx.send(
                f"Found {len(new_ids)} new match(es): {', '.join(f'#{i}' for i in new_ids)}. "
                "Each needs confirmation before MMR applies — check the pending matches."
            )

async def setup(bot):
    await bot.add_cog(SyncCog(bot))
