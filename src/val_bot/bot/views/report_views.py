import discord
from sqlalchemy import delete, select
from val_bot.ingestion.manual import ManualEntrySource
from val_bot.db.match_service import create_pending_match, confirm_match
from val_bot.db.models import Match, MatchParticipant

_manual_source = ManualEntrySource()

async def build_pending_match(
    session, map_name: str, team_a_score: int, team_b_score: int,
    reporter_id: str, team_a_ids: list[str], team_b_ids: list[str],
) -> Match:
    normalized = _manual_source.build_match(
        map_name=map_name, team_a_score=team_a_score, team_b_score=team_b_score,
        reported_by_discord_id=reporter_id,
        team_a_discord_ids=team_a_ids, team_b_discord_ids=team_b_ids,
    )
    return await create_pending_match(session, normalized)

class TeamSelectView(discord.ui.View):
    """Second step of /report-match: pick Team A then Team B via native
    Discord user-select components (no manual option lists needed)."""

    def __init__(self, session_factory, map_name: str, team_a_score: int,
                 team_b_score: int, reporter_id: str, on_built):
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.map_name = map_name
        self.team_a_score = team_a_score
        self.team_b_score = team_b_score
        self.reporter_id = reporter_id
        self.on_built = on_built
        self.team_a_ids: list[str] | None = None
        self.team_b_ids: list[str] | None = None

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Pick Team A (5 players)",
                        min_values=5, max_values=5)
    async def team_a(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.team_a_ids = [str(u.id) for u in select.values]
        await interaction.response.defer()
        await self._maybe_finish(interaction)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Pick Team B (5 players)",
                        min_values=5, max_values=5)
    async def team_b(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.team_b_ids = [str(u.id) for u in select.values]
        await interaction.response.defer()
        await self._maybe_finish(interaction)

    async def _maybe_finish(self, interaction: discord.Interaction):
        if self.team_a_ids is None or self.team_b_ids is None:
            return
        overlap = set(self.team_a_ids) & set(self.team_b_ids)
        if overlap:
            self.team_a_ids = None
            self.team_b_ids = None
            mentions = ", ".join(f"<@{discord_id}>" for discord_id in overlap)
            await interaction.followup.send(
                f"The following player(s) were selected on both teams: {mentions}. "
                "Please run /report-match again.",
                ephemeral=True,
            )
            self.stop()
            return
        async with self.session_factory() as session:
            match = await build_pending_match(
                session=session, map_name=self.map_name,
                team_a_score=self.team_a_score, team_b_score=self.team_b_score,
                reporter_id=self.reporter_id,
                team_a_ids=self.team_a_ids, team_b_ids=self.team_b_ids,
            )
            await session.commit()
            match_id = match.id
        await self.on_built(interaction, match_id)
        self.stop()

class MatchReportModal(discord.ui.Modal, title="Report Match"):
    map_name = discord.ui.TextInput(label="Map")
    team_a_score = discord.ui.TextInput(label="Team A score", max_length=2)
    team_b_score = discord.ui.TextInput(label="Team B score", max_length=2)

    def __init__(self, session_factory, on_built):
        super().__init__()
        self.session_factory = session_factory
        self.on_built = on_built

    async def on_submit(self, interaction: discord.Interaction):
        try:
            team_a_score = int(str(self.team_a_score))
            team_b_score = int(str(self.team_b_score))
        except ValueError:
            await interaction.response.send_message(
                "Team scores must be whole numbers - please try /report-match again.",
                ephemeral=True,
            )
            return
        view = TeamSelectView(
            session_factory=self.session_factory,
            map_name=str(self.map_name),
            team_a_score=team_a_score,
            team_b_score=team_b_score,
            reporter_id=str(interaction.user.id),
            on_built=self.on_built,
        )
        await interaction.response.send_message(
            "Now pick each team's players:", view=view, ephemeral=True
        )

class StartReportView(discord.ui.View):
    """Entry point for v!report-match: a modal can only be opened in
    response to an interaction (never a plain text command), so the
    prefix command posts this button instead — clicking it opens the
    exact same MatchReportModal the slash command opens directly."""

    def __init__(self, session_factory, on_built):
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.on_built = on_built

    @discord.ui.button(label="Start Report", style=discord.ButtonStyle.primary)
    async def start_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = MatchReportModal(self.session_factory, self.on_built)
        await interaction.response.send_modal(modal)

async def _participant_team(session, match_id: int, discord_id: str) -> str | None:
    result = await session.execute(
        select(MatchParticipant.team).where(
            MatchParticipant.match_id == match_id,
            MatchParticipant.discord_id == discord_id,
        )
    )
    return result.scalar_one_or_none()

def _has_admin_role(user) -> bool:
    roles = getattr(user, "roles", None) or []
    return discord.utils.get(roles, name="Admin") is not None

class ConfirmDisputeView(discord.ui.View):
    def __init__(self, session_factory, match_id: int):
        super().__init__(timeout=3600)
        self.session_factory = session_factory
        self.match_id = match_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.session_factory() as session:
            match = await session.get(Match, self.match_id)
            reporter_team = await _participant_team(
                session, self.match_id, match.reported_by_discord_id
            )
            user_team = await _participant_team(session, self.match_id, str(interaction.user.id))
            is_opposing_participant = (
                reporter_team is not None
                and user_team is not None
                and user_team != reporter_team
            )
            if not (is_opposing_participant or _has_admin_role(interaction.user)):
                await interaction.response.send_message(
                    "Only someone on the opposing team (or an Admin) can confirm this match.",
                    ephemeral=True,
                )
                return
            match = await confirm_match(session, self.match_id)
            await session.commit()
            lines = [
                f"<@{p.discord_id}>: {p.mmr_before} → {p.mmr_after} "
                f"({'+' if p.mmr_after >= p.mmr_before else ''}{p.mmr_after - p.mmr_before})"
                for p in match.participants
            ]
        await interaction.response.edit_message(
            content="Match confirmed! MMR changes:\n" + "\n".join(lines), view=None
        )

    @discord.ui.button(label="Dispute", style=discord.ButtonStyle.danger)
    async def dispute(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.session_factory() as session:
            user_team = await _participant_team(session, self.match_id, str(interaction.user.id))
            is_participant = user_team is not None
            if not (is_participant or _has_admin_role(interaction.user)):
                await interaction.response.send_message(
                    "Only a match participant or an Admin can dispute this match.",
                    ephemeral=True,
                )
                return
            await session.execute(
                delete(MatchParticipant).where(MatchParticipant.match_id == self.match_id)
            )
            await session.execute(delete(Match).where(Match.id == self.match_id))
            await session.commit()
        await interaction.response.edit_message(
            content="Match disputed and discarded. No MMR was applied.", view=None
        )
