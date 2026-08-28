from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"
    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    riot_username: Mapped[str | None] = mapped_column(String, nullable=True)
    riot_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    puuid: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    consented: Mapped[bool] = mapped_column(Boolean, default=False)
    mmr: Mapped[int] = mapped_column(Integer, default=700)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class PlayerPuuid(Base):
    """Additional Riot accounts (alts) linked to a Discord ID beyond the
    primary one on players.puuid - populated when an unrecognized player in
    a synced match is manually identified as someone already linked under a
    different account. Sync-matching consults both tables; nothing else
    (display, /link) needs to know this exists."""
    __tablename__ = "player_puuids"
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    discord_id: Mapped[str] = mapped_column(ForeignKey("players.discord_id"))
    region: Mapped[str] = mapped_column(String)


class IgnoredPuuid(Base):
    """A Riot puuid a moderator explicitly left blank (chose not to link to
    any Discord account) when resolving an unrecognized-player prompt -
    typically someone who's left the server. Without this, the same puuid
    keeps tripping the 'unrecognized player' prompt on every future sync
    for any match they appear in, including ones already resolved."""
    __tablename__ = "ignored_puuids"
    puuid: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    tag: Mapped[str] = mapped_column(String)
    region: Mapped[str] = mapped_column(String)
    ignored_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class AnnouncedUnresolvedMatch(Base):
    """Marks a HenrikDev match_id whose 'who is this unrecognized player?'
    prompt has already been posted once. Without this, a match that nobody
    resolves (e.g. a player who's since left the server) gets re-detected
    and re-announced on every single sync run/poll forever - this caps it
    at one announcement per real match."""
    __tablename__ = "announced_unresolved_matches"
    external_match_id: Mapped[str] = mapped_column(String, primary_key=True)
    announced_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    played_at: Mapped[datetime] = mapped_column(DateTime)
    map: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    reported_by_discord_id: Mapped[str] = mapped_column(String)
    team_a_score: Mapped[int] = mapped_column(Integer)
    team_b_score: Mapped[int] = mapped_column(Integer)
    external_match_id: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True
    )
    participants: Mapped[list["MatchParticipant"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )


class MatchParticipant(Base):
    __tablename__ = "match_participants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    discord_id: Mapped[str] = mapped_column(ForeignKey("players.discord_id"))
    team: Mapped[str] = mapped_column(String)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    deaths: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    combat_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    won: Mapped[bool] = mapped_column(Boolean)
    mmr_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mmr_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match: Mapped["Match"] = relationship(back_populates="participants")
