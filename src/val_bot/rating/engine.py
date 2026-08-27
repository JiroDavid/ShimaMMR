from dataclasses import dataclass
from val_bot.rating.elo import compute_delta, performance_modifier

@dataclass
class ParticipantInput:
    discord_id: str
    team: str
    won: bool
    combat_score: int | None

def rate_match(
    participants: list[ParticipantInput],
    current_mmr: dict[str, int],
    games_played: dict[str, int],
    loss_streak: dict[str, int],
) -> dict[str, tuple[int, int]]:
    team_a = [p for p in participants if p.team == "A"]
    team_b = [p for p in participants if p.team == "B"]
    team_a_avg = sum(current_mmr[p.discord_id] for p in team_a) / len(team_a)
    team_b_avg = sum(current_mmr[p.discord_id] for p in team_b) / len(team_b)

    scores = [p.combat_score for p in participants if p.combat_score is not None]
    match_avg_score = sum(scores) / len(scores) if scores else 0.0

    results: dict[str, tuple[int, int]] = {}
    for p in participants:
        own_avg = team_a_avg if p.team == "A" else team_b_avg
        opp_avg = team_b_avg if p.team == "A" else team_a_avg
        mod = (
            performance_modifier(p.combat_score, match_avg_score)
            if p.combat_score is not None and match_avg_score > 0
            else 1.0
        )
        before = current_mmr[p.discord_id]
        delta = compute_delta(
            own_team_avg=own_avg,
            opp_team_avg=opp_avg,
            won=p.won,
            games_played=games_played[p.discord_id],
            performance_mod=mod,
            loss_streak=loss_streak[p.discord_id],
        )
        after = before + delta
        results[p.discord_id] = (before, after)
        current_mmr[p.discord_id] = after
        games_played[p.discord_id] += 1
        loss_streak[p.discord_id] = 0 if p.won else loss_streak[p.discord_id] + 1
    return results
