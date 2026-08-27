from val_bot.rating.elo import (
    expected_score, k_factor, performance_modifier, compute_delta,
)

def test_expected_score_even_teams_is_half():
    assert abs(expected_score(1000, 1000) - 0.5) < 1e-9

def test_expected_score_favors_higher_team():
    assert expected_score(1200, 1000) > 0.5
    assert expected_score(1000, 1200) < 0.5

def test_k_factor_provisional_then_standard():
    assert k_factor(0) == 40
    assert k_factor(9) == 40
    assert k_factor(10) == 20
    assert k_factor(100) == 20

def test_performance_modifier_clamped_and_centered():
    assert performance_modifier(200, 200) == 1.0
    assert performance_modifier(400, 200) == 1.5  # double the average, clamps at 1.5
    assert performance_modifier(0, 200) == 0.5     # far below average, clamps at 0.5

def test_compute_delta_win_as_underdog_gains_more_than_expected():
    delta = compute_delta(own_team_avg=1000, opp_team_avg=1200, won=True, games_played=20)
    assert delta > 10  # underdog win nets more than the 10 a coin-flip win would give at K=20
    assert delta > 0

def test_compute_delta_capped_at_40():
    delta = compute_delta(
        own_team_avg=700, opp_team_avg=700, won=True, games_played=0,
        performance_mod=1.5,
    )
    assert delta <= 40

def test_compute_delta_loss_streak_dampens_loss():
    normal_loss = compute_delta(own_team_avg=1000, opp_team_avg=1000, won=False, games_played=20)
    streak_loss = compute_delta(
        own_team_avg=1000, opp_team_avg=1000, won=False, games_played=20, loss_streak=3
    )
    assert streak_loss > normal_loss  # dampened loss is less negative
