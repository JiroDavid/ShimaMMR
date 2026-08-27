from datetime import datetime, timezone
from val_bot.ingestion.base import MatchDataSource, NormalizedMatch, NormalizedParticipant
import pytest

def test_normalized_match_holds_participants():
    match = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Haven", source="manual",
        team_a_score=13, team_b_score=9, reported_by_discord_id="p1",
        participants=[NormalizedParticipant(discord_id="p1", team="A")],
    )
    assert match.participants[0].discord_id == "p1"
    assert match.external_match_id is None

def test_match_data_source_is_abstract():
    with pytest.raises(TypeError):
        MatchDataSource()
