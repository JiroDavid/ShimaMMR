import discord
from val_bot.ingestion.henrikdev import PendingResolution

class UnknownPlayerResolutionView(discord.ui.View):
    """Posted when an auto-detected match has some players HenrikDev
    reports but we can't map to a Discord ID. Lets whoever's looking pick
    a Discord user per unknown Riot ID (or leave one blank to exclude that
    player from the match), then finalizes it into a confirmable match."""

    def __init__(self, session_factory, source_factory, pending: PendingResolution, on_finalized):
        super().__init__(timeout=3600)
        self.session_factory = session_factory
        self.source_factory = source_factory
        self.pending = pending
        self.on_finalized = on_finalized
        self._selections: dict[str, str | None] = {u.puuid: None for u in pending.unknown_players}

        for unknown in pending.unknown_players:
            self.add_item(self._build_select(unknown))

    def _build_select(self, unknown) -> discord.ui.UserSelect:
        select = discord.ui.UserSelect(
            placeholder=f"Who is {unknown.name}#{unknown.tag}?", min_values=0, max_values=1,
        )

        async def callback(interaction: discord.Interaction):
            select_values = select.values
            self._selections[unknown.puuid] = str(select_values[0].id) if select_values else None
            await interaction.response.defer()

        select.callback = callback
        return select

    @discord.ui.button(label="Resolve & Create Match", style=discord.ButtonStyle.primary, row=4)
    async def finalize(self, interaction: discord.Interaction, button: discord.ui.Button):
        from val_bot.bot.cogs.sync import resolve_unknown_players

        # must ack within Discord's 3-second component-interaction window -
        # on_finalized posts its result via interaction.followup, which is
        # only valid once the interaction has been responded to
        await interaction.response.defer()

        resolved = {puuid: discord_id for puuid, discord_id in self._selections.items() if discord_id}
        async with self.session_factory() as session:
            match = await resolve_unknown_players(session, self.source_factory(), self.pending, resolved)
            await session.commit()
            match_id = match.id
        self.stop()
        await self.on_finalized(interaction, match_id)
