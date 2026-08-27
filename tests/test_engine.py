from val_bot.rating.engine import ParticipantInput, rate_match

def _players(*ids):
    return {d: 700 for d in ids}, {d: 0 for d in ids}, {d: 0 for d in ids}

def test_single_match_updates_winners_up_losers_down():
    current_mmr, games_played, loss_streak = _players("a", "b", "c", "d")
    participants = [
        ParticipantInput("a", "A", True, None),
        ParticipantInput("b", "A", True, None),
        ParticipantInput("c", "B", False, None),
        ParticipantInput("d", "B", False, None),
    ]
    results = rate_match(participants, current_mmr, games_played, loss_streak)
    assert results["a"][1] > results["a"][0]
    assert results["c"][1] < results["c"][0]
    assert current_mmr["a"] == results["a"][1]
    assert games_played["a"] == 1
    assert loss_streak["c"] == 1
    assert loss_streak["a"] == 0

def test_replay_two_matches_ripples_state_forward():
    current_mmr, games_played, loss_streak = _players("a", "b", "c", "d")
    match1 = [
        ParticipantInput("a", "A", True, None),
        ParticipantInput("b", "A", True, None),
        ParticipantInput("c", "B", False, None),
        ParticipantInput("d", "B", False, None),
    ]
    match2 = [
        ParticipantInput("a", "A", False, None),
        ParticipantInput("c", "A", False, None),
        ParticipantInput("b", "B", True, None),
        ParticipantInput("d", "B", True, None),
    ]
    r1 = rate_match(match1, current_mmr, games_played, loss_streak)
    r2 = rate_match(match2, current_mmr, games_played, loss_streak)
    # match2's mmr_before for "a" must equal match1's mmr_after for "a" —
    # this is the ripple: a later match's inputs depend on the earlier one.
    assert r2["a"][0] == r1["a"][1]
    assert games_played["a"] == 2

def test_performance_modifier_applied_when_combat_score_present():
    current_mmr, games_played, loss_streak = _players("a", "b", "c", "d")
    participants = [
        ParticipantInput("a", "A", True, 400),   # way above match average
        ParticipantInput("b", "A", True, 200),
        ParticipantInput("c", "B", False, 200),
        ParticipantInput("d", "B", False, 200),
    ]
    results = rate_match(participants, current_mmr, games_played, loss_streak)
    gain_a = results["a"][1] - results["a"][0]
    gain_b = results["b"][1] - results["b"][0]
    assert gain_a > gain_b  # "a" overperformed relative to match average
