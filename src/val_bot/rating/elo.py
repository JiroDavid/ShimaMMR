def expected_score(own_team_avg: float, opp_team_avg: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opp_team_avg - own_team_avg) / 400.0))

def k_factor(games_played: int) -> int:
    return 40 if games_played < 10 else 20

def performance_modifier(player_score: float, match_avg_score: float) -> float:
    if match_avg_score <= 0:
        return 1.0
    ratio = player_score / match_avg_score
    modifier = 1.0 + 0.5 * (ratio - 1.0)
    return max(0.5, min(1.5, modifier))

def compute_delta(
    own_team_avg: float,
    opp_team_avg: float,
    won: bool,
    games_played: int,
    performance_mod: float = 1.0,
    loss_streak: int = 0,
    cap: int = 40,
) -> int:
    expected = expected_score(own_team_avg, opp_team_avg)
    actual = 1.0 if won else 0.0
    base_delta = k_factor(games_played) * (actual - expected)
    delta = base_delta * performance_mod
    if delta < 0 and loss_streak >= 3:
        delta *= 0.65
    delta = max(-cap, min(cap, delta))
    return round(delta)
