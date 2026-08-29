import discord
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from val_bot.db.models import Match, MatchParticipant

async def fetch_recent_matches(session, discord_id: str, limit: int = 5) -> list[Match]:
    result = await session.execute(
        select(Match)
        .join(MatchParticipant)
        .where(MatchParticipant.discord_id == discord_id, Match.status == "confirmed")
        .order_by(Match.played_at.desc())
        .limit(limit)
        .options(selectinload(Match.participants))
    )
    return list(result.scalars().unique())

def _delta_str(before: int, after: int) -> str:
    delta = after - before
    return f"+{delta}" if delta >= 0 else str(delta)

def _participant_for(match: Match, discord_id: str) -> MatchParticipant:
    return next(p for p in match.participants if p.discord_id == discord_id)

def build_history_embed(target: discord.abc.User, matches: list[Match], discord_id: str) -> discord.Embed:
    embed = discord.Embed(title=f"📜 Match History — {target.display_name}", color=discord.Color.blurple())
    embed.set_thumbnail(url=target.display_avatar.url)
    for match in matches:
        p = _participant_for(match, discord_id)
        result_emoji, result_text = ("🟢", "Win") if p.won else ("🔴", "Loss")
        # "unknown" map matches (missing data from the original CSV import)
        # all look identical otherwise - add the date so they're at least
        # distinguishable rather than looking like duplicate entries
        map_label = (
            f"{match.map} ({match.played_at.strftime('%b %d')})"
            if match.map == "unknown" else match.map
        )
        embed.add_field(
            name=f"{result_emoji} {result_text} · {map_label}  ·  #{match.id}",
            value=(
                f"`{match.team_a_score}-{match.team_b_score}`  ·  "
                f"{p.kills}/{p.deaths}/{p.assists}  ·  "
                f"MMR {_delta_str(p.mmr_before, p.mmr_after)}"
            ),
            inline=False,
        )
    embed.set_footer(text=f"Last {len(matches)} confirmed match(es) — tap a button below for the full scoreboard")
    return embed

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

class MatchHistoryView(discord.ui.View):
    """One 'full match' button per match shown in the history embed - each
    reveals that specific match's complete scoreboard (ephemeral) when
    clicked, rather than only ever being able to expand the newest one."""

    def __init__(self, session_factory, matches: list[Match]):
        super().__init__(timeout=300)
        self.session_factory = session_factory
        for match in matches:
            self.add_item(self._build_button(match))

    def _build_button(self, match: Match) -> discord.ui.Button:
        button = discord.ui.Button(
            label=f"{match.map} · #{match.id}", style=discord.ButtonStyle.secondary,
        )

        async def callback(interaction: discord.Interaction):
            async with self.session_factory() as session:
                full = await session.get(Match, match.id, options=[selectinload(Match.participants)])
                text = format_full_match(full)
            await interaction.response.send_message(text, ephemeral=True)

        button.callback = callback
        return button
