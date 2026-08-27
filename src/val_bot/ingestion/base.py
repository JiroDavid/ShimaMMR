from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class NormalizedParticipant:
    discord_id: str
    team: str
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    combat_score: int | None = None

@dataclass
class NormalizedMatch:
    played_at: datetime
    map: str
    source: str
    team_a_score: int
    team_b_score: int
    reported_by_discord_id: str
    participants: list[NormalizedParticipant]
    external_match_id: str | None = None

class MatchDataSource(ABC):
    @abstractmethod
    async def fetch_new_matches(self) -> list[NormalizedMatch]:
        raise NotImplementedError
