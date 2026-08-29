import logging
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from val_bot.db.models import (
    Player, PlayerPuuid, Match, MatchParticipant, AnnouncedUnresolvedMatch, IgnoredPuuid,
)
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

async def ignored_puuids_for_sync(session) -> set[str]:
    result = await session.execute(select(IgnoredPuuid.puuid))
    return set(result.scalars().all())

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

    # anyone left blank on purpose (e.g. they've left the server) - record
    # them so this same puuid stops tripping the unrecognized-player prompt
    # on every future sync, for this match or any other
    for unknown in pending.unknown_players:
        if unknown.puuid in resolved:
            continue
        already_ignored = await session.get(IgnoredPuuid, unknown.puuid)
        if already_ignored is None:
            session.add(IgnoredPuuid(
                puuid=unknown.puuid, name=unknown.name, tag=unknown.tag, region=pending.region,
            ))
    await session.flush()

    normalized = source.build_match_with_resolutions(pending.raw_match, resolved)
    if normalized.external_match_id is not None:
        existing = await session.execute(
            select(Match).where(Match.external_match_id == normalized.external_match_id)
        )
        existing_match = existing.scalar_one_or_none()
        if existing_match is not None:
            # this exact match was already created on a previous resolve
            # (e.g. this prompt got re-announced before the ignore above
            # took effect) - reuse it instead of hitting the unique
            # constraint on external_match_id
            return existing_match
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

async def reannounce_match_callback(send, session_factory, match_id: int):
    """Re-post the confirm/dispute prompt for a match that's already pending
    in the DB but has no live announcement anyone can act on - e.g. the
    original announce_ready_match call failed (expired interaction token,
    transient API error) after the match itself was already committed."""
    async with session_factory() as session:
        match = await session.get(Match, match_id)
        if match is None:
            await send(f"No match #{match_id} found.")
            return
        if match.status != "pending":
            await send(f"Match #{match_id} is already {match.status} - nothing to re-announce.")
            return
        map_name = match.map
    await announce_ready_match(send, session_factory, match_id, map_name)

async def reannounce_all_pending_callback(send, session_factory) -> int:
    """Same as reannounce_match_callback, but for every pending match at
    once - so recovering from a batch of failed announcements doesn't take
    one command per match."""
    async with session_factory() as session:
        result = await session.execute(
            select(Match.id, Match.map).where(Match.status == "pending").order_by(Match.played_at)
        )
        pending = result.all()

    if not pending:
        await send("No pending matches to re-announce.")
        return 0

    for match_id, map_name in pending:
        try:
            await announce_ready_match(send, session_factory, match_id, map_name)
        except Exception:
            logger.exception("Failed to re-announce match #%s", match_id)
    return len(pending)

async def _filter_unannounced(session, unresolved: list[PendingResolution]) -> list[PendingResolution]:
    """Drops any PendingResolution whose match_id has already had its
    'who is this?' prompt posted once, and records new ones as announced -
    without this, an unresolved match gets re-detected and reannounced on
    every single sync run/poll until someone acts on it."""
    new_unresolved = []
    for pending in unresolved:
        external_id = pending.raw_match["metadata"]["match_id"]
        already = await session.get(AnnouncedUnresolvedMatch, external_id)
        if already is not None:
            continue
        session.add(AnnouncedUnresolvedMatch(external_match_id=external_id))
        new_unresolved.append(pending)
    return new_unresolved

async def _player_is_synced(session, discord_id: str) -> bool:
    player = await session.get(Player, discord_id)
    return player is not None and player.consented and player.puuid is not None

async def _sync_and_announce(session_factory, henrikdev_api_key, send, only_discord_id: str | None = None):
    async with session_factory() as session:
        consented = await consented_players_for_sync(session)
        ignored = await ignored_puuids_for_sync(session)

        fetch_only_puuids = None
        if only_discord_id is not None:
            fetch_only_puuids = {p["puuid"] for p in consented if p["discord_id"] == only_discord_id}

        def source_factory():
            return HenrikDevSource(
                henrikdev_api_key, consented, ignored_puuids=ignored, fetch_only_puuids=fetch_only_puuids,
            )

        created, unresolved = await sync_matches(session, source_factory)
        unresolved = await _filter_unannounced(session, unresolved)
        await session.commit()
        created_info = [(m.id, m.map) for m in created]

    if not created_info and not unresolved:
        return False

    for match_id, map_name in created_info:
        try:
            await announce_ready_match(send, session_factory, match_id, map_name)
        except Exception:
            # one match's announcement failing (e.g. an expired interaction
            # token) shouldn't stop every other match this run from being
            # announced too - it's already safely committed either way and
            # can be recovered with /reannounce-match
            logger.exception("Failed to announce match #%s - it's still saved, use /reannounce-match", match_id)
    for pending in unresolved:
        try:
            await announce_unresolved_match(send, session_factory, source_factory, pending)
        except Exception:
            # already marked as announced (see _filter_unannounced) even
            # though the send itself failed, so this won't come back on its
            # own next sync - logged so it can be investigated manually
            logger.exception("Failed to announce unresolved match on %s", pending.map)
    return True

class SyncCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sync-matches", description="Check HenrikDev for new pickup matches (Admin only)")
    @app_commands.describe(
        player="Only check this player's recent matches instead of everyone - "
               "much faster and uses far less API quota (their match still includes everyone else in it)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_matches_cmd(self, interaction: discord.Interaction, player: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True)

        if player is not None:
            async with self.bot.session_factory() as session:
                synced = await _player_is_synced(session, str(player.id))
            if not synced:
                await interaction.followup.send(
                    f"<@{player.id}> isn't linked yet - they need to run /link first before "
                    "a sync can be narrowed to just them.",
                    ephemeral=True,
                )
                return

        async def send(content, view=None):
            await interaction.followup.send(content, view=view)

        try:
            found = await _sync_and_announce(
                self.bot.session_factory, self.bot.henrikdev_api_key, send,
                only_discord_id=str(player.id) if player else None,
            )
        except Exception:
            logger.exception("Manual /sync-matches failed")
            await interaction.followup.send(
                "Sync failed (likely a HenrikDev API error) - check the bot logs. "
                "Nothing was lost, safe to try again.",
                ephemeral=True,
            )
            return
        if not found:
            await interaction.followup.send("No new matches found.", ephemeral=True)

    @commands.command(name="sync-matches")
    @commands.has_permissions(administrator=True)
    async def sync_matches_prefix(self, ctx: commands.Context, player: discord.Member | None = None):
        if player is not None:
            async with self.bot.session_factory() as session:
                synced = await _player_is_synced(session, str(player.id))
            if not synced:
                await ctx.send(
                    f"<@{player.id}> isn't linked yet - they need to run /link first before "
                    "a sync can be narrowed to just them."
                )
                return

        try:
            found = await _sync_and_announce(
                self.bot.session_factory, self.bot.henrikdev_api_key, ctx.send,
                only_discord_id=str(player.id) if player else None,
            )
        except Exception:
            logger.exception("Manual v!sync-matches failed")
            await ctx.send(
                "Sync failed (likely a HenrikDev API error) - check the bot logs. "
                "Nothing was lost, safe to try again."
            )
            return
        if not found:
            await ctx.send("No new matches found.")

    @app_commands.command(
        name="reannounce-match",
        description="Re-post the confirm/dispute prompt for a pending match, or all of them if no id given (Admin only)",
    )
    @app_commands.describe(match_id="Leave blank to re-announce every pending match at once")
    @app_commands.checks.has_permissions(administrator=True)
    async def reannounce_match_cmd(self, interaction: discord.Interaction, match_id: int | None = None):
        await interaction.response.defer()

        async def send(content, view=None):
            await interaction.followup.send(content, view=view)

        if match_id is None:
            await reannounce_all_pending_callback(send, self.bot.session_factory)
            return
        await reannounce_match_callback(send, self.bot.session_factory, match_id)

    @commands.command(name="reannounce-match")
    @commands.has_permissions(administrator=True)
    async def reannounce_match_prefix(self, ctx: commands.Context, match_id: int | None = None):
        if match_id is None:
            await reannounce_all_pending_callback(ctx.send, self.bot.session_factory)
            return
        await reannounce_match_callback(ctx.send, self.bot.session_factory, match_id)

async def setup(bot):
    await bot.add_cog(SyncCog(bot))
