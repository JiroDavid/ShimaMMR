import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
import httpx
from val_bot.ingestion.base import MatchDataSource, NormalizedMatch, NormalizedParticipant

logger = logging.getLogger(__name__)

BASE_URL = "https://api.henrikdev.xyz/valorant"
MATCH_HISTORY_PAGE_SIZE = 10
# Basic API keys are limited to 30 req/min - space requests out so a sync
# run doesn't burst past that on its own.
REQUEST_INTERVAL_SECONDS = 2.1

async def resolve_account(api_key: str | None, name: str, tag: str) -> dict | None:
    """Look up a Riot ID's puuid/region via HenrikDev. Returns None if the
    account can't be found or the API errors - callers should degrade
    gracefully rather than block on this (e.g. /link should still succeed)."""
    headers = {"Authorization": api_key} if api_key else {}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/v2/account/{name}/{tag}", headers=headers)
    if resp.status_code != 200:
        return None
    data = resp.json()["data"]
    return {"puuid": data["puuid"], "region": data["region"], "name": data["name"], "tag": data["tag"]}

@dataclass
class UnknownPlayer:
    puuid: str
    name: str
    tag: str

@dataclass
class PendingResolution:
    """A match that's clearly one of ours (roster-overlap heuristic passed)
    but has some players we can't map to a Discord ID yet - a human needs
    to say who they are before this can be turned into a NormalizedMatch."""
    raw_match: dict
    map: str
    played_at: datetime
    region: str
    unknown_players: list[UnknownPlayer]

class HenrikDevSource(MatchDataSource):
    def __init__(
        self, api_key: str | None, consented_players: list[dict],
        ignored_puuids: set[str] | None = None,
    ):
        self.api_key = api_key
        self.consented_players = consented_players
        self._puuid_to_discord_id = {p["puuid"]: p["discord_id"] for p in consented_players}
        # puuids a moderator already chose not to link to anyone - treated
        # like "known" for classification purposes (never re-prompted) but
        # still dropped from participants, same as any other unlinked puuid
        self._ignored_puuids = set(ignored_puuids or ())
        self._request_interval = REQUEST_INTERVAL_SECONDS
        self.unresolved_matches: list[PendingResolution] = []

    def _headers(self) -> dict:
        return {"Authorization": self.api_key} if self.api_key else {}

    async def _get_with_backoff(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        resp = await client.get(url, headers=self._headers())
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "5"))
            await asyncio.sleep(retry_after)
            resp = await client.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp

    async def _matches_for_player(self, client: httpx.AsyncClient, puuid: str, region: str) -> list[dict]:
        url = f"{BASE_URL}/v4/by-puuid/matches/{region}/pc/{puuid}?size={MATCH_HISTORY_PAGE_SIZE}"
        resp = await self._get_with_backoff(client, url)
        return resp.json().get("data", [])

    def _played_at(self, metadata: dict) -> datetime:
        started_at = metadata.get("started_at")
        if started_at is not None:
            return datetime.fromisoformat(started_at)
        return datetime.now(timezone.utc)

    def _build_normalized(self, match: dict, puuid_to_discord_id: dict[str, str]) -> NormalizedMatch:
        metadata = match["metadata"]
        teams = {t["team_id"]: t for t in match["teams"]}
        participants = []
        for p in match["players"]:
            discord_id = puuid_to_discord_id.get(p["puuid"])
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
            played_at=self._played_at(metadata),
            map=metadata["map"]["name"],
            source="henrikdev",
            team_a_score=teams["Red"]["rounds"]["won"],
            team_b_score=teams["Blue"]["rounds"]["won"],
            reported_by_discord_id="auto",
            participants=participants,
            external_match_id=metadata["match_id"],
        )

    def build_match_with_resolutions(self, raw_match: dict, resolved: dict[str, str]) -> NormalizedMatch:
        """Build the final NormalizedMatch once a human has mapped this
        match's previously-unknown puuids to Discord IDs."""
        combined = {**self._puuid_to_discord_id, **resolved}
        return self._build_normalized(raw_match, combined)

    def _classify(self, match: dict) -> tuple[NormalizedMatch | None, PendingResolution | None]:
        metadata = match["metadata"]
        queue = metadata.get("queue") or {}
        # v4 has no provisioningFlowID; a real 5v5-style pickup custom is a
        # "Custom Game" queue with mode_type "Standard" (excludes custom
        # deathmatch/skirmish lobbies, which aren't 2-team matches).
        if queue.get("name") != "Custom Game" or queue.get("mode_type") != "Standard":
            return None, None

        players = match["players"]
        known = [p for p in players if p["puuid"] in self._puuid_to_discord_id]
        if len(known) < len(players) * 0.6:
            return None, None  # not enough of our roster in this match — likely not our pickup (roster-match heuristic: >=6 of 10)

        teams = {t["team_id"]: t for t in match["teams"]}
        if "Red" not in teams or "Blue" not in teams:
            return None, None

        unknown = [
            p for p in players
            if p["puuid"] not in self._puuid_to_discord_id and p["puuid"] not in self._ignored_puuids
        ]
        if unknown:
            pending = PendingResolution(
                raw_match=match,
                map=metadata["map"]["name"],
                played_at=self._played_at(metadata),
                region=metadata.get("region", ""),
                unknown_players=[UnknownPlayer(puuid=p["puuid"], name=p["name"], tag=p["tag"]) for p in unknown],
            )
            return None, pending

        return self._build_normalized(match, self._puuid_to_discord_id), None

    async def fetch_new_matches(self) -> list[NormalizedMatch]:
        results: dict[str, NormalizedMatch] = {}
        seen_pending: set[str] = set()
        self.unresolved_matches = []
        async with httpx.AsyncClient() as client:
            for index, player in enumerate(self.consented_players):
                if index > 0:
                    await asyncio.sleep(self._request_interval)
                try:
                    matches = await self._matches_for_player(client, player["puuid"], player["region"])
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429:
                        # still rate-limited after the one retry in
                        # _get_with_backoff - skip this player rather than
                        # aborting the whole sync; they'll get picked up on
                        # the next run instead of losing everyone else's
                        # progress too
                        logger.warning(
                            "Still rate-limited fetching matches for puuid %s - "
                            "skipping for this sync run", player["puuid"],
                        )
                        continue
                    raise
                except httpx.TimeoutException:
                    # API didn't respond at all (as opposed to a 429) -
                    # same treatment: skip this player, keep the sync going
                    logger.warning(
                        "Timed out fetching matches for puuid %s - "
                        "skipping for this sync run", player["puuid"],
                    )
                    continue
                for match in matches:
                    external_id = match["metadata"]["match_id"]
                    if external_id in results or external_id in seen_pending:
                        continue
                    normalized, pending = self._classify(match)
                    if normalized is not None:
                        results[external_id] = normalized
                    elif pending is not None:
                        seen_pending.add(external_id)
                        self.unresolved_matches.append(pending)

        return list(results.values())
