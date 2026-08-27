import discord
from sqlalchemy import select
from val_bot.db.models import Match, MatchParticipant

async def fetch_recent_matches(session, discord_id: str, limit: int = 5) -> list[Match]:
    result = await session.execute(
        select(Match)
        .join(MatchParticipant)
        .where(MatchParticipant.discord_id == discord_id, Match.status == "confirmed")
        .order_by(Match.played_at.desc())
        .limit(limit)
    )
    return list(result.scalars().unique())

def _delta_str(before: int, after: int) -> str:
    delta = after - before
    return f"+{delta}" if delta >= 0 else str(delta)

def format_match_summary(match: Match, discord_id: str) -> str:
    p = next(x for x in match.participants if x.discord_id == discord_id)
    result = "Win" if p.won else "Loss"
    return (
        f"**{result}** on {match.map} ({match.team_a_score}-{match.team_b_score}) — "
        f"{p.kills}/{p.deaths}/{p.assists} — MMR {_delta_str(p.mmr_before, p.mmr_after)}"
    )

def format_full_match(match: Match) -> str:
    lines = [f"**{match.map}** — {match.team_a_score}-{match.team_b_score}"]
    for team in ("A", "B"):
        lines.append(f"__Team {team}__")
        for p in match.participants:
            if p.team != team:
                continue
            lines.append(
                f"<@{p.discord_id}>: {p.kills}/{p.deaths}/{p.assists} — "
                f"MMR {_delta_str(p.mmr_before, p.mmr_after)}"
            )
    return "\n".join(lines)

class FullMatchView(discord.ui.View):
    def __init__(self, session_factory, match_id: int):
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.match_id = match_id

    @discord.ui.button(label="View Full Match", style=discord.ButtonStyle.primary)
    async def view_full(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.session_factory() as session:
            match = await session.get(Match, self.match_id)
            text = format_full_match(match)
        await interaction.response.send_message(text, ephemeral=True)
