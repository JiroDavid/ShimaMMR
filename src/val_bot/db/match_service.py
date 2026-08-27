from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from val_bot.db.models import Player, Match, MatchParticipant
from val_bot.ingestion.base import NormalizedMatch
from val_bot.rating.engine import ParticipantInput, rate_match

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
    match = await session.get(Match, match_id)
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
