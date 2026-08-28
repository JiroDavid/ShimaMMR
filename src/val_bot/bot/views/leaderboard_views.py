import discord
from sqlalchemy import select
from val_bot.db.models import Player
from val_bot.rating.tiers import mmr_to_tier

PAGE_SIZE = 10
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# Custom Valorant rank emoji uploaded to the server, keyed by tier name.
# Radiant has no emoji uploaded yet - falls back to plain text.
TIER_EMOJI_NAMES = {
    "Iron": "74848valorantiron3",
    "Bronze": "87648valorantbronze3",
    "Silver": "66610valorantsilver3",
    "Gold": "46597valorantgold3",
    "Platinum": "62047valorantplatinum3",
    "Diamond": "64465valorantdiamond3",
    "Ascendant": "4071valorantascendant3",
    "Immortal": "89668valorantimmortal3",
    "Radiant": None,
}


async def fetch_leaderboard_page(session, offset: int, limit: int = PAGE_SIZE) -> list[Player]:
    result = await session.execute(
        select(Player).order_by(Player.mmr.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars())


def _tier_emoji(guild, tier: str) -> str | None:
    emoji_name = TIER_EMOJI_NAMES.get(tier)
    if emoji_name is None or guild is None:
        return None
    emoji = discord.utils.get(guild.emojis, name=emoji_name)
    return str(emoji) if emoji else None


def format_leaderboard_embed(players: list[Player], offset: int, guild=None) -> discord.Embed:
    embed = discord.Embed(
        title="🏆 Pickups Leaderboard",
        description="Server rankings, ordered by MMR across all confirmed matches.",
        color=discord.Color.gold(),
    )
    if not players:
        embed.description = "No players yet."
        return embed

    player_lines, mmr_lines, rank_lines = [], [], []
    for i, p in enumerate(players):
        rank = offset + i + 1
        prefix = MEDALS.get(rank, f"**{rank}.**")
        name = f"{p.riot_username}#{p.riot_tag}" if p.riot_username else "(unlinked)"
        player_lines.append(f"{prefix} {name} (<@{p.discord_id}>)")

        mmr_lines.append(f"**{p.mmr}**")

        tier = mmr_to_tier(p.mmr)
        emoji = _tier_emoji(guild, tier)
        rank_lines.append(f"{emoji} {tier}" if emoji else tier)

    embed.add_field(name="Player", value="\n\n".join(player_lines), inline=True)
    embed.add_field(name="MMR", value="\n\n".join(mmr_lines), inline=True)
    embed.add_field(name="Rank", value="\n\n".join(rank_lines), inline=True)
    return embed


class LeaderboardView(discord.ui.View):
    def __init__(self, session_factory, offset: int = 0, guild=None):
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.offset = offset
        self.guild = guild

    async def render(self) -> discord.Embed:
        async with self.session_factory() as session:
            page = await fetch_leaderboard_page(session, self.offset)
        return format_leaderboard_embed(page, self.offset, guild=self.guild)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.offset = max(0, self.offset - PAGE_SIZE)
        await interaction.response.edit_message(embed=await self.render(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.offset += PAGE_SIZE
        await interaction.response.edit_message(embed=await self.render(), view=self)
