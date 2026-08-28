from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from val_bot.db.models import Player, Match, MatchParticipant
from val_bot.ingestion.base import NormalizedMatch
from val_bot.rating.engine import ParticipantInput, rate_match

async def _get_match_with_participants(session: AsyncSession, match_id: int) -> Match:
    result = await session.execute(
        select(Match)
        .options(selectinload(Match.participants))
        .where(Match.id == match_id)
    )
    return result.scalar_one()

async def create_pending_match(session: AsyncSession, normalized: NormalizedMatch) -> Match:
    winning_team = "A" if normalized.team_a_score > normalized.team_b_score else "B"
    match = Match(
        played_at=normalized.played_at, map=normalized.map, source=normalized.source,
        status="pending", reported_by_discord_id=normalized.reported_by_discord_id,
        team_a_score=normalized.team_a_score, team_b_score=normalized.team_b_score,
        external_match_id=normalized.external_match_id,
    )
    for p in normalized.participants:
        match.participants.append(MatchParticipant(
            discord_id=p.discord_id, team=p.team, kills=p.kills, deaths=p.deaths,
            assists=p.assists, combat_score=p.combat_score,
            won=(p.team == winning_team),
        ))
    session.add(match)
    await session.flush()
    return match

async def _trailing_loss_streak(session: AsyncSession, discord_id: str) -> int:
    result = await session.execute(
        select(MatchParticipant.won)
        .join(Match)
        .where(MatchParticipant.discord_id == discord_id, Match.status == "confirmed")
        .order_by(Match.played_at.desc())
    )
    streak = 0
    for (won,) in result:
        if won:
            break
        streak += 1
    return streak

async def _seed_state(session: AsyncSession, discord_ids: set[str]):
    current_mmr, games_played, loss_streak = {}, {}, {}
    for discord_id in discord_ids:
        player = await session.get(Player, discord_id)
        current_mmr[discord_id] = player.mmr
        games_played[discord_id] = player.games_played
        loss_streak[discord_id] = await _trailing_loss_streak(session, discord_id)
    return current_mmr, games_played, loss_streak

async def confirm_match(session: AsyncSession, match_id: int) -> Match:
    match = await _get_match_with_participants(session, match_id)
    if match.status != "pending":
        # already confirmed (e.g. a stale duplicate confirm/dispute prompt
        # got clicked after the match was already resolved elsewhere) -
        # applying MMR a second time would double-count it, so no-op
        return match
    discord_ids = {p.discord_id for p in match.participants}
    current_mmr, games_played, loss_streak = await _seed_state(session, discord_ids)

    participant_inputs = [
        ParticipantInput(p.discord_id, p.team, p.won, p.combat_score)
        for p in match.participants
    ]
    results = rate_match(participant_inputs, current_mmr, games_played, loss_streak)

    for p in match.participants:
        before, after = results[p.discord_id]
        p.mmr_before, p.mmr_after = before, after
        player = await session.get(Player, p.discord_id)
        player.mmr = after
        player.games_played += 1

    match.status = "confirmed"
    await session.flush()
    return match

async def _seed_state_before(session: AsyncSession, discord_id: str, from_played_at: datetime):
    result = await session.execute(
        select(MatchParticipant)
        .join(Match)
        .where(
            MatchParticipant.discord_id == discord_id,
            Match.status == "confirmed",
            Match.played_at < from_played_at,
        )
        .order_by(Match.played_at.desc())
    )
    rows = list(result.scalars())
    games = len(rows)
    mmr = rows[0].mmr_after if rows else 700
    streak = 0
    for row in rows:
        if row.won:
            break
        streak += 1
    return mmr, games, streak

async def recompute_from(
    session: AsyncSession,
    from_played_at: datetime,
    discord_ids: set[str] | None = None,
) -> None:
    """Replay confirmed matches at/after `from_played_at` and rewrite their
    mmr_before/mmr_after plus each affected Player's mmr/games_played.

    `discord_ids` should include the participants of whatever match triggered
    this call (e.g. the one just voided or corrected), even if that match
    itself is no longer "confirmed" and therefore won't appear in the replay
    query below. Without this, voiding the chronologically-last confirmed
    match for a player would leave nothing to replay and their Player row
    would never be reset to reflect the void.
    """
    result = await session.execute(
        select(Match)
        .options(selectinload(Match.participants))
        .where(Match.status == "confirmed", Match.played_at >= from_played_at)
        .order_by(Match.played_at.asc())
    )
    matches = list(result.scalars().unique())

    all_discord_ids = set(discord_ids or ())
    all_discord_ids |= {p.discord_id for m in matches for p in m.participants}
    if not all_discord_ids:
        return

    current_mmr, games_played, loss_streak = {}, {}, {}
    for discord_id in all_discord_ids:
        mmr, games, streak = await _seed_state_before(session, discord_id, from_played_at)
        current_mmr[discord_id] = mmr
        games_played[discord_id] = games
        loss_streak[discord_id] = streak

    for match in matches:
        participant_inputs = [
            ParticipantInput(p.discord_id, p.team, p.won, p.combat_score)
            for p in match.participants
        ]
        results = rate_match(participant_inputs, current_mmr, games_played, loss_streak)
        for p in match.participants:
            p.mmr_before, p.mmr_after = results[p.discord_id]

    for discord_id in all_discord_ids:
        player = await session.get(Player, discord_id)
        player.mmr = current_mmr[discord_id]
        player.games_played = games_played[discord_id]

    await session.flush()

async def void_match(session: AsyncSession, match_id: int) -> None:
    match = await _get_match_with_participants(session, match_id)
    played_at = match.played_at
    discord_ids = {p.discord_id for p in match.participants}
    match.status = "voided"
    await session.flush()
    await recompute_from(session, played_at, discord_ids)

async def correct_match(
    session: AsyncSession,
    match_id: int,
    team_a_score: int | None = None,
    team_b_score: int | None = None,
    participant_updates: dict[str, dict] | None = None,
) -> None:
    match = await _get_match_with_participants(session, match_id)
    if team_a_score is not None:
        match.team_a_score = team_a_score
    if team_b_score is not None:
        match.team_b_score = team_b_score
    winning_team = "A" if match.team_a_score > match.team_b_score else "B"

    participant_updates = participant_updates or {}
    for p in match.participants:
        p.won = (p.team == winning_team)
        updates = participant_updates.get(p.discord_id, {})
        for field_name in ("kills", "deaths", "assists", "combat_score"):
            if field_name in updates:
                setattr(p, field_name, updates[field_name])

    played_at = match.played_at
    discord_ids = {p.discord_id for p in match.participants}
    await session.flush()
    await recompute_from(session, played_at, discord_ids)
