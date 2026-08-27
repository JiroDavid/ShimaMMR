from datetime import datetime, timezone
from val_bot.ingestion.base import MatchDataSource, NormalizedMatch, NormalizedParticipant

class ManualEntrySource(MatchDataSource):
    """Push-based: /report-match calls build_match directly with data
    already collected from Discord UI, so fetch_new_matches is a no-op —
    this source never polls anything on its own."""

    async def fetch_new_matches(self) -> list[NormalizedMatch]:
        return []

    def build_match(
        self,
        map_name: str,
        team_a_score: int,
        team_b_score: int,
        reported_by_discord_id: str,
        team_a_discord_ids: list[str],
        team_b_discord_ids: list[str],
        stats: dict[str, dict] | None = None,
    ) -> NormalizedMatch:
        stats = stats or {}

        def build(discord_id: str, team: str) -> NormalizedParticipant:
            s = stats.get(discord_id, {})
            return NormalizedParticipant(
                discord_id=discord_id, team=team,
                kills=s.get("kills", 0), deaths=s.get("deaths", 0),
                assists=s.get("assists", 0), combat_score=s.get("combat_score"),
            )

        participants = [build(d, "A") for d in team_a_discord_ids] + [
            build(d, "B") for d in team_b_discord_ids
        ]
        return NormalizedMatch(
            played_at=datetime.now(timezone.utc),
            map=map_name, source="manual",
            team_a_score=team_a_score, team_b_score=team_b_score,
            reported_by_discord_id=reported_by_discord_id,
            participants=participants,
        )
