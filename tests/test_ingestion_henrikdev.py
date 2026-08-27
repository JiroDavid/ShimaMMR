import respx
import httpx
from datetime import datetime, timezone
from val_bot.ingestion.henrikdev import HenrikDevSource

CONSENTED = [
    {"discord_id": "1", "puuid": "puuid-1"},
    {"discord_id": "2", "puuid": "puuid-2"},
]

MATCHLIST_RESPONSE = {
    "data": [{"metadata": {"matchid": "match-abc"}}],
}

MATCH_GAME_START = 1700000000

MATCH_DETAILS_CUSTOM = {
    "data": {
        "metadata": {
            "matchid": "match-abc", "map": "Ascent", "mode": "Custom",
            "game_start": MATCH_GAME_START,
        },
        "players": [
            {"puuid": "puuid-1", "team_id": "Red", "stats": {"kills": 20, "deaths": 10, "assists": 5, "score": 250}},
            {"puuid": "puuid-2", "team_id": "Red", "stats": {"kills": 10, "deaths": 15, "assists": 3, "score": 150}},
            {"puuid": "puuid-3", "team_id": "Blue", "stats": {"kills": 12, "deaths": 12, "assists": 4, "score": 180}},
        ],
        "teams": {"red": {"has_won": True, "rounds_won": 13}, "blue": {"has_won": False, "rounds_won": 7}},
        "provisioningFlowID": "CustomGame",
    },
}

@respx.mock
async def test_fetch_new_matches_returns_normalized_custom_game():
    respx.get(url__regex=r".*/matches/.*/puuid-1$").mock(
        return_value=httpx.Response(200, json=MATCHLIST_RESPONSE)
    )
    respx.get(url__regex=r".*/matches/.*/puuid-2$").mock(
        return_value=httpx.Response(200, json=MATCHLIST_RESPONSE)
    )
    respx.get(url__regex=r".*/match/match-abc$").mock(
        return_value=httpx.Response(200, json=MATCH_DETAILS_CUSTOM)
    )

    source = HenrikDevSource(api_key=None, consented_players=CONSENTED)
    matches = await source.fetch_new_matches()

    assert len(matches) == 1
    match = matches[0]
    assert match.source == "henrikdev"
    assert match.external_match_id == "match-abc"
    assert match.map == "Ascent"
    assert match.played_at == datetime.fromtimestamp(MATCH_GAME_START, tz=timezone.utc)
    p1 = next(p for p in match.participants if p.discord_id == "1")
    assert p1.team == "A"
    assert p1.combat_score == 250

@respx.mock
async def test_fetch_new_matches_skips_non_custom_provisioning():
    non_custom = {**MATCH_DETAILS_CUSTOM, "data": {**MATCH_DETAILS_CUSTOM["data"], "provisioningFlowID": "Matchmaking"}}
    respx.get(url__regex=r".*/matches/.*/puuid-1$").mock(
        return_value=httpx.Response(200, json=MATCHLIST_RESPONSE)
    )
    respx.get(url__regex=r".*/matches/.*/puuid-2$").mock(
        return_value=httpx.Response(200, json=MATCHLIST_RESPONSE)
    )
    respx.get(url__regex=r".*/match/match-abc$").mock(
        return_value=httpx.Response(200, json=non_custom)
    )

    source = HenrikDevSource(api_key=None, consented_players=CONSENTED)
    matches = await source.fetch_new_matches()
    assert matches == []
