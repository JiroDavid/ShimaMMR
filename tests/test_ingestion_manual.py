from val_bot.ingestion.manual import ManualEntrySource

def test_build_match_without_stats():
    source = ManualEntrySource()
    match = source.build_match(
        map_name="Ascent", team_a_score=13, team_b_score=5,
        reported_by_discord_id="p1",
        team_a_discord_ids=["p1", "p2"], team_b_discord_ids=["p3", "p4"],
    )
    assert match.source == "manual"
    assert len(match.participants) == 4
    a = next(p for p in match.participants if p.discord_id == "p1")
    assert a.team == "A"
    assert a.combat_score is None

def test_build_match_with_stats():
    source = ManualEntrySource()
    match = source.build_match(
        map_name="Bind", team_a_score=13, team_b_score=10,
        reported_by_discord_id="p1",
        team_a_discord_ids=["p1"], team_b_discord_ids=["p2"],
        stats={"p1": {"kills": 20, "deaths": 10, "assists": 5, "combat_score": 250}},
    )
    p1 = next(p for p in match.participants if p.discord_id == "p1")
    assert p1.kills == 20
    assert p1.combat_score == 250

async def test_fetch_new_matches_returns_empty():
    source = ManualEntrySource()
    assert await source.fetch_new_matches() == []
