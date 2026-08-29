import respx
import httpx
from datetime import datetime, timezone
from val_bot.ingestion.henrikdev import HenrikDevSource, resolve_account

CONSENTED = [
    {"discord_id": "1", "puuid": "puuid-1", "region": "eu"},
    {"discord_id": "2", "puuid": "puuid-2", "region": "eu"},
    {"discord_id": "3", "puuid": "puuid-3", "region": "eu"},
]

def _match(match_id="match-abc", queue_name="Custom Game", mode_type="Standard", extra_player=True, extra_players=None):
    players = [
        {"puuid": "puuid-1", "name": "one", "tag": "111", "team_id": "Red", "stats": {"kills": 20, "deaths": 10, "assists": 5, "score": 250}},
        {"puuid": "puuid-2", "name": "two", "tag": "222", "team_id": "Red", "stats": {"kills": 10, "deaths": 15, "assists": 3, "score": 150}},
    ]
    if extra_player:
        players.append(
            {"puuid": "puuid-3", "name": "three", "tag": "333", "team_id": "Blue", "stats": {"kills": 12, "deaths": 12, "assists": 4, "score": 180}}
        )
    if extra_players:
        players.extend(extra_players)
    return {
        "metadata": {
            "match_id": match_id,
            "map": {"id": "map-id", "name": "Ascent"},
            "started_at": "2026-08-24T20:33:00.591Z",
            "is_completed": True,
            "queue": {"id": "", "name": queue_name, "mode_type": mode_type},
            "region": "eu",
        },
        "players": players,
        "teams": [
            {"team_id": "Red", "rounds": {"won": 13, "lost": 7}, "won": True},
            {"team_id": "Blue", "rounds": {"won": 7, "lost": 13}, "won": False},
        ],
    }

def _mock_matchlist(puuid: str, matches: list[dict]):
    respx.get(url__regex=rf".*/by-puuid/matches/eu/pc/{puuid}.*").mock(
        return_value=httpx.Response(200, json={"data": matches})
    )

def _source(consented_players=CONSENTED, ignored_puuids=None, fetch_only_puuids=None) -> HenrikDevSource:
    source = HenrikDevSource(
        api_key=None, consented_players=consented_players,
        ignored_puuids=ignored_puuids, fetch_only_puuids=fetch_only_puuids,
    )
    source._request_interval = 0  # no need to actually throttle in tests
    return source

@respx.mock
async def test_fetch_new_matches_returns_normalized_custom_game():
    _mock_matchlist("puuid-1", [_match()])
    _mock_matchlist("puuid-2", [])
    _mock_matchlist("puuid-3", [])

    source = _source()
    matches = await source.fetch_new_matches()

    assert len(matches) == 1
    match = matches[0]
    assert match.source == "henrikdev"
    assert match.external_match_id == "match-abc"
    assert match.map == "Ascent"
    assert match.played_at == datetime(2026, 8, 24, 20, 33, 0, 591000, tzinfo=timezone.utc)
    assert match.team_a_score == 13
    assert match.team_b_score == 7
    p1 = next(p for p in match.participants if p.discord_id == "1")
    assert p1.team == "A"
    assert p1.combat_score == 250

@respx.mock
async def test_fetch_new_matches_skips_non_custom_queue():
    _mock_matchlist("puuid-1", [_match(queue_name="Competitive", mode_type="Standard")])
    _mock_matchlist("puuid-2", [])
    _mock_matchlist("puuid-3", [])

    source = _source()
    matches = await source.fetch_new_matches()
    assert matches == []

@respx.mock
async def test_fetch_new_matches_skips_non_standard_custom_modes():
    # e.g. a custom deathmatch/skirmish lobby - not a 2-team pickup match
    _mock_matchlist("puuid-1", [_match(mode_type="Deathmatch")])
    _mock_matchlist("puuid-2", [])
    _mock_matchlist("puuid-3", [])

    source = _source()
    matches = await source.fetch_new_matches()
    assert matches == []

@respx.mock
async def test_fetch_new_matches_skips_matches_with_too_few_known_players():
    _mock_matchlist("puuid-1", [_match(extra_player=False)])
    _mock_matchlist("puuid-2", [])

    # only puuid-1 known among these consented players is present with no
    # others - well below the 60% roster-overlap heuristic for a real 10-man
    source = _source([{"discord_id": "1", "puuid": "puuid-1", "region": "eu"}])
    matches = await source.fetch_new_matches()
    assert matches == []

@respx.mock
async def test_fetch_new_matches_dedupes_a_match_seen_via_multiple_players():
    shared = _match()
    _mock_matchlist("puuid-1", [shared])
    _mock_matchlist("puuid-2", [shared])
    _mock_matchlist("puuid-3", [])

    source = _source()
    matches = await source.fetch_new_matches()
    assert len(matches) == 1

@respx.mock
async def test_fetch_new_matches_retries_after_429():
    route = respx.get(url__regex=r".*/by-puuid/matches/eu/pc/puuid-1.*")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"errors": [{"message": "rate limited"}]}),
        httpx.Response(200, json={"data": [_match()]}),
    ]
    _mock_matchlist("puuid-2", [])
    _mock_matchlist("puuid-3", [])

    source = _source()
    matches = await source.fetch_new_matches()

    assert len(matches) == 1
    assert route.call_count == 2

@respx.mock
async def test_fetch_new_matches_skips_player_on_timeout():
    # API doesn't respond at all (no status code, unlike a 429) - should be
    # skipped rather than aborting the whole sync
    respx.get(url__regex=r".*/by-puuid/matches/eu/pc/puuid-1.*").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )
    _mock_matchlist("puuid-2", [_match()])
    _mock_matchlist("puuid-3", [])

    source = _source()
    matches = await source.fetch_new_matches()

    assert len(matches) == 1

@respx.mock
async def test_fetch_new_matches_stops_early_when_still_rate_limited_after_retry():
    # puuid-1 succeeds, then puuid-2 stays 429 even after the one built-in
    # retry - the key is genuinely out of budget, so the whole run should
    # stop there (returning whatever was already found) rather than
    # continuing to burn through puuid-3 too
    _mock_matchlist("puuid-1", [_match()])
    respx.get(url__regex=r".*/by-puuid/matches/eu/pc/puuid-2.*").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"}, json={"errors": [{"message": "rate limited"}]})
    )
    route3 = respx.get(url__regex=r".*/by-puuid/matches/eu/pc/puuid-3.*")
    route3.mock(return_value=httpx.Response(200, json={"data": []}))

    source = _source()
    matches = await source.fetch_new_matches()

    assert len(matches) == 1
    assert route3.call_count == 0

@respx.mock
async def test_fetch_new_matches_fetch_only_puuids_limits_requests_but_not_classification():
    # only puuid-1's match history is fetched (1 request instead of 3), but
    # the returned match's roster is still checked against the FULL
    # consented list, so puuid-2/puuid-3 (also in that match) are still
    # correctly recognized rather than surfaced as unknown
    match = _match()  # puuid-1, puuid-2, puuid-3
    _mock_matchlist("puuid-1", [match])
    route2 = respx.get(url__regex=r".*/by-puuid/matches/eu/pc/puuid-2.*").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    route3 = respx.get(url__regex=r".*/by-puuid/matches/eu/pc/puuid-3.*").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    source = _source(fetch_only_puuids={"puuid-1"})
    matches = await source.fetch_new_matches()

    assert len(matches) == 1
    assert len(matches[0].participants) == 3
    assert source.unresolved_matches == []
    assert route2.call_count == 0
    assert route3.call_count == 0

@respx.mock
async def test_fetch_new_matches_treats_ignored_puuid_as_known_and_drops_them():
    # a puuid a moderator already left blank once shouldn't trip the
    # unrecognized-player prompt again - just silently excluded like any
    # other unlinked puuid, and the match resolves normally
    ignored_player = {
        "puuid": "ignored-1", "name": "ghost", "tag": "000", "team_id": "Blue",
        "stats": {"kills": 1, "deaths": 1, "assists": 1, "score": 50},
    }
    match = _match(extra_players=[ignored_player])
    _mock_matchlist("puuid-1", [match])
    _mock_matchlist("puuid-2", [])
    _mock_matchlist("puuid-3", [])

    source = _source(ignored_puuids={"ignored-1"})
    matches = await source.fetch_new_matches()

    assert len(matches) == 1
    assert source.unresolved_matches == []
    assert len(matches[0].participants) == 3
    assert all(p.discord_id != "ignored-1" for p in matches[0].participants)

@respx.mock
async def test_fetch_new_matches_surfaces_unknown_players_instead_of_dropping_them():
    # 7 known (>=60% of 10) + 3 unknown - still "our" pickup, but 3 players
    # need a human to say who they are before this can be imported.
    unknowns = [
        {"puuid": f"unk-{i}", "name": f"stranger{i}", "tag": "999", "team_id": "Blue",
         "stats": {"kills": 5, "deaths": 5, "assists": 5, "score": 100}}
        for i in range(3)
    ]
    known_fill = [
        {"puuid": f"puuid-{i}", "name": f"known{i}", "tag": "111", "team_id": "Red" if i % 2 else "Blue",
         "stats": {"kills": 5, "deaths": 5, "assists": 5, "score": 100}}
        for i in range(4, 8)
    ]
    match = _match(extra_players=unknowns + known_fill)

    consented = CONSENTED + [
        {"discord_id": str(i), "puuid": f"puuid-{i}", "region": "eu"} for i in range(4, 8)
    ]
    _mock_matchlist("puuid-1", [match])
    for p in consented[1:]:
        _mock_matchlist(p["puuid"], [])

    source = _source(consented)
    ready = await source.fetch_new_matches()

    assert ready == []
    assert len(source.unresolved_matches) == 1
    pending = source.unresolved_matches[0]
    assert pending.map == "Ascent"
    assert {u.puuid for u in pending.unknown_players} == {"unk-0", "unk-1", "unk-2"}
    assert next(u for u in pending.unknown_players if u.puuid == "unk-0").name == "stranger0"

@respx.mock
async def test_build_match_with_resolutions_includes_resolved_players():
    match = _match()  # puuid-1, puuid-2 known (Red); puuid-3 unknown (Blue)
    source = _source(CONSENTED[:2])

    normalized = source.build_match_with_resolutions(match, resolved={"puuid-3": "999"})

    assert len(normalized.participants) == 3
    p3 = next(p for p in normalized.participants if p.discord_id == "999")
    assert p3.team == "B"
    assert p3.combat_score == 180

@respx.mock
async def test_resolve_account_returns_puuid_and_region_on_success():
    respx.get(url__regex=r".*/v2/account/jiroshima/NMS$").mock(
        return_value=httpx.Response(200, json={
            "status": 200,
            "data": {
                "puuid": "2b9b14f8-aacd-5ee5-bcfc-d30d027dd947",
                "region": "eu",
                "name": "Jiroshima",
                "tag": "NMS",
            },
        })
    )

    account = await resolve_account("key", "jiroshima", "NMS")

    assert account == {
        "puuid": "2b9b14f8-aacd-5ee5-bcfc-d30d027dd947",
        "region": "eu",
        "name": "Jiroshima",
        "tag": "NMS",
    }

@respx.mock
async def test_resolve_account_returns_none_when_not_found():
    respx.get(url__regex=r".*/v2/account/typoed/NAME$").mock(
        return_value=httpx.Response(404, json={"errors": [{"message": "Not Found"}]})
    )

    account = await resolve_account("key", "typoed", "NAME")

    assert account is None

@respx.mock
async def test_resolve_account_returns_none_on_server_error():
    respx.get(url__regex=r".*/v2/account/whoever/TAG$").mock(
        return_value=httpx.Response(500, json={"errors": [{"message": "boom"}]})
    )

    account = await resolve_account("key", "whoever", "TAG")

    assert account is None
