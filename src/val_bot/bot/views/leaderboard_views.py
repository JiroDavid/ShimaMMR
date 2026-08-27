import discord
from sqlalchemy import select
from val_bot.db.models import Player

PAGE_SIZE = 10
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


async def fetch_leaderboard_page(session, offset: int, limit: int = PAGE_SIZE) -> list[Player]:
    result = await session.execute(
        select(Player).order_by(Player.mmr.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars())


def format_leaderboard_embed(players: list[Player], offset: int) -> discord.Embed:
    embed = discord.Embed(title="🏆 Leaderboard", color=discord.Color.gold())
    if not players:
        embed.description = "No players yet."
        return embed
    lines = []
    for i, p in enumerate(players):
        rank = offset + i + 1
        prefix = MEDALS.get(rank, f"**{rank}.**")
        name = f"{p.riot_username}#{p.riot_tag}" if p.riot_username else "(unlinked)"
        lines.append(f"{prefix} {name} (<@{p.discord_id}>) — {p.mmr} MMR")
    embed.description = "\n".join(lines)
    return embed


class LeaderboardView(discord.ui.View):
    def __init__(self, session_factory, offset: int = 0):
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.offset = offset

    async def render(self) -> discord.Embed:
        async with self.session_factory() as session:
            page = await fetch_leaderboard_page(session, self.offset)
        return format_leaderboard_embed(page, self.offset)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.offset = max(0, self.offset - PAGE_SIZE)
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.offset += PAGE_SIZE
        await interaction.response.edit_message(embed=await self.render(), view=self)
