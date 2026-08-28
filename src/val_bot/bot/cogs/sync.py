import logging
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from val_bot.db.models import Player, PlayerPuuid, Match, MatchParticipant
from val_bot.ingestion.base import NormalizedMatch
from val_bot.db.match_service import create_pending_match
from val_bot.ingestion.henrikdev import HenrikDevSource, PendingResolution
from val_bot.bot.views.report_views import ConfirmDisputeView
from val_bot.bot.views.sync_views import UnknownPlayerResolutionView

PING_COUNT = 5
logger = logging.getLogger(__name__)

async def consented_players_for_sync(session) -> list[dict]:
    primaries = await session.execute(
        select(Player.discord_id, Player.puuid, Player.region)
        .where(Player.consented.is_(True), Player.puuid.isnot(None))
    )
    players = [{"discord_id": d, "puuid": p, "region": r} for d, p, r in primaries.all()]
    alts = await session.execute(select(PlayerPuuid.discord_id, PlayerPuuid.puuid, PlayerPuuid.region))
    players += [{"discord_id": d, "puuid": p, "region": r} for d, p, r in alts.all()]
    return players

DUPLICATE_WINDOW = timedelta(hours=12)

async def _find_duplicate_match(session, normalized: NormalizedMatch) -> Match | None:
    """Fuzzy fallback for matches that already exist in the DB without an
    external_match_id to dedup against - e.g. manually reported, or backfilled
    from a CSV/history import. Matches on same map, same score-pair (checked
    as a set since a manual report's Team1/Team2 don't necessarily line up
    with HenrikDev's Red/Blue), same roster, played within DUPLICATE_WINDOW."""
    participant_ids = {p.discord_id for p in normalized.participants}
    score_pair = {normalized.team_a_score, normalized.team_b_score}
    result = await session.execute(
        select(Match)
        .options(selectinload(Match.participants))
        .where(
            Match.map == normalized.map,
            Match.played_at >= normalized.played_at - DUPLICATE_WINDOW,
            Match.played_at <= normalized.played_at + DUPLICATE_WINDOW,
        )
    )
    for match in result.scalars().unique():
        if {match.team_a_score, match.team_b_score} != score_pair:
            continue
        if {p.discord_id for p in match.participants} != participant_ids:
            continue
        return match
    return None

async def sync_matches(session, henrikdev_source_factory) -> tuple[list[Match], list[PendingResolution]]:
    source = henrikdev_source_factory()
    normalized_matches = await source.fetch_new_matches()

    existing = await session.execute(
        select(Match.external_match_id).where(Match.external_match_id.isnot(None))
    )
    existing_ids = {row[0] for row in existing}

    created = []
    for normalized in normalized_matches:
        if normalized.external_match_id in existing_ids:
            continue
        duplicate = await _find_duplicate_match(session, normalized)
        if duplicate is not None:
            if duplicate.external_match_id is None:
                duplicate.external_match_id = normalized.external_match_id
            continue
        match = await create_pending_match(session, normalized)
        created.append(match)
    return created, source.unresolved_matches

async def resolve_unknown_players(session, source, pending: PendingResolution, resolved: dict[str, str]) -> Match:
    for puuid, discord_id in resolved.items():
        player = await session.get(Player, discord_id)
        if player is None:
            player = Player(discord_id=discord_id)
            session.add(player)
        if player.puuid is None:
            # first account we've seen for them - becomes their primary
            player.puuid = puuid
            player.region = pending.region
            player.consented = True
        elif player.puuid != puuid:
            # already linked under a different account - this is an alt,
            # don't clobber their primary /link'd puuid
            existing_alt = await session.get(PlayerPuuid, puuid)
            if existing_alt is None:
                session.add(PlayerPuuid(puuid=puuid, discord_id=discord_id, region=pending.region))
    await session.flush()

    normalized = source.build_match_with_resolutions(pending.raw_match, resolved)
    return await create_pending_match(session, normalized)

async def _participant_discord_ids(session, match_id: int) -> list[str]:
    result = await session.execute(
        select(MatchParticipant.discord_id).where(MatchParticipant.match_id == match_id)
    )
    return list(result.scalars().all())

async def announce_ready_match(send, session_factory, match_id: int, map_name: str):
    async with session_factory() as session:
        discord_ids = await _participant_discord_ids(session, match_id)
    mentions = " ".join(f"<@{d}>" for d in discord_ids[:PING_COUNT])
    view = ConfirmDisputeView(session_factory, match_id)
    await send(
        f"{mentions}\nFound match #{match_id} on **{map_name}** (auto-detected via HenrikDev sync). "
        "Please confirm below once you're ready.",
        view=view,
    )

async def announce_unresolved_match(send, session_factory, source_factory, pending: PendingResolution):
    names = ", ".join(f"{u.name}#{u.tag}" for u in pending.unknown_players)

    async def on_finalized(interaction, match_id):
        async def followup_send(content, view=None):
            await interaction.followup.send(content, view=view)
        async with session_factory() as session:
            match = await session.get(Match, match_id)
            map_name = match.map
        await announce_ready_match(followup_send, session_factory, match_id, map_name)

    view = UnknownPlayerResolutionView(session_factory, source_factory, pending, on_finalized)
    await send(
        f"Found a probable pickup match on **{pending.map}**, but {len(pending.unknown_players)} "
        f"player(s) aren't recognized: {names}. Who are they on Discord? "
        "(leave blank to exclude them from the match)",
        view=view,
    )

async def _sync_and_announce(session_factory, henrikdev_api_key, send):
    async with session_factory() as session:
        consented = await consented_players_for_sync(session)

        def source_factory():
            return HenrikDevSource(henrikdev_api_key, consented)

        created, unresolved = await sync_matches(session, source_factory)
        await session.commit()
        created_info = [(m.id, m.map) for m in created]

    if not created_info and not unresolved:
        return False

    for match_id, map_name in created_info:
        await announce_ready_match(send, session_factory, match_id, map_name)
    for pending in unresolved:
        await announce_unresolved_match(send, session_factory, source_factory, pending)
    return True

class SyncCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if getattr(bot, "sync_announce_channel_id", None):
            self.poll_for_matches.start()

    def cog_unload(self):
        if self.poll_for_matches.is_running():
            self.poll_for_matches.cancel()

    @tasks.loop(minutes=15)
    async def poll_for_matches(self):
        try:
            channel = self.bot.get_channel(self.bot.sync_announce_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.bot.sync_announce_channel_id)
            await _sync_and_announce(self.bot.session_factory, self.bot.henrikdev_api_key, channel.send)
        except Exception:
            # a transient API/network error shouldn't permanently kill the
            # 15-minute poller until the bot restarts - log and retry next tick
            logger.exception("Background HenrikDev sync failed")

    @poll_for_matches.before_loop
    async def before_poll_for_matches(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="sync-matches", description="Check HenrikDev for new pickup matches (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_matches_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async def send(content, view=None):
            await interaction.followup.send(content, view=view)

        found = await _sync_and_announce(self.bot.session_factory, self.bot.henrikdev_api_key, send)
        if not found:
            await interaction.followup.send("No new matches found.", ephemeral=True)

    @commands.command(name="sync-matches")
    @commands.has_permissions(administrator=True)
    async def sync_matches_prefix(self, ctx: commands.Context):
        found = await _sync_and_announce(self.bot.session_factory, self.bot.henrikdev_api_key, ctx.send)
        if not found:
            await ctx.send("No new matches found.")

async def setup(bot):
    await bot.add_cog(SyncCog(bot))
