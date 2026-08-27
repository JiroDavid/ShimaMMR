from datetime import datetime, timezone
import httpx
from val_bot.ingestion.base import MatchDataSource, NormalizedMatch, NormalizedParticipant

BASE_URL = "https://api.henrikdev.xyz/valorant"

class HenrikDevSource(MatchDataSource):
    def __init__(self, api_key: str | None, consented_players: list[dict]):
        self.api_key = api_key
        self.consented_players = consented_players
        self._puuid_to_discord_id = {p["puuid"]: p["discord_id"] for p in consented_players}

    def _headers(self) -> dict:
        return {"Authorization": self.api_key} if self.api_key else {}

    async def _match_ids_for_puuid(self, client: httpx.AsyncClient, puuid: str) -> list[str]:
        resp = await client.get(f"{BASE_URL}/v4/by-puuid/matches/na/pc/{puuid}", headers=self._headers())
        resp.raise_for_status()
        return [m["metadata"]["matchid"] for m in resp.json().get("data", [])]

    async def _match_details(self, client: httpx.AsyncClient, match_id: str) -> dict:
        resp = await client.get(f"{BASE_URL}/v4/match/{match_id}", headers=self._headers())
        resp.raise_for_status()
        return resp.json()["data"]

    def _played_at(self, metadata: dict) -> datetime:
        game_start = metadata.get("game_start")
        if game_start is not None:
            return datetime.fromtimestamp(game_start, tz=timezone.utc)
        game_start_patched = metadata.get("game_start_patched")
        if game_start_patched is not None:
            return datetime.strptime(game_start_patched, "%Y/%m/%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        return datetime.now(timezone.utc)

    def _normalize(self, details: dict) -> NormalizedMatch | None:
        if details.get("provisioningFlowID") != "CustomGame":
            return None

        players = details["players"]
        known = [p for p in players if p["puuid"] in self._puuid_to_discord_id]
        if len(known) < len(players) * 0.6:
            return None  # not enough of our roster in this match — likely not our pickup (roster-match heuristic: >=6 of 10)

        teams = details["teams"]
        red_won = teams["red"]["has_won"]

        participants = []
        for p in players:
            discord_id = self._puuid_to_discord_id.get(p["puuid"])
            if discord_id is None:
                continue
            team = "A" if p["team_id"] == "Red" else "B"
            stats = p["stats"]
            participants.append(NormalizedParticipant(
                discord_id=discord_id, team=team,
                kills=stats["kills"], deaths=stats["deaths"], assists=stats["assists"],
                combat_score=stats["score"],
            ))

        return NormalizedMatch(
            played_at=self._played_at(details["metadata"]),
            map=details["metadata"]["map"],
            source="henrikdev",
            team_a_score=teams["red"]["rounds_won"],
            team_b_score=teams["blue"]["rounds_won"],
            reported_by_discord_id="auto",
            participants=participants,
            external_match_id=details["metadata"]["matchid"],
        )

    async def fetch_new_matches(self) -> list[NormalizedMatch]:
        results: dict[str, NormalizedMatch] = {}
        async with httpx.AsyncClient() as client:
            match_ids: set[str] = set()
            for player in self.consented_players:
                match_ids.update(await self._match_ids_for_puuid(client, player["puuid"]))

            for match_id in match_ids:
                details = await self._match_details(client, match_id)
                normalized = self._normalize(details)
                if normalized is not None:
                    results[normalized.external_match_id] = normalized

        return list(results.values())
