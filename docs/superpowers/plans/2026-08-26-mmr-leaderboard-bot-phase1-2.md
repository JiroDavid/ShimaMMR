# MMR/Leaderboard Discord Bot — Phase 1 + Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Discord bot that ingests Val pickup match results (manual
report today, HenrikDev auto-detection by end of Phase 2) and maintains a
persistent per-player MMR/rank leaderboard.

**Architecture:** Single Python process (`discord.py`), SQLAlchemy 2.0 async
ORM over SQLite, one Docker container. Three isolated layers: `rating/`
(pure functions), `ingestion/` (swappable `MatchDataSource` interface),
`bot/` (Discord-facing cogs/views). `db/match_service.py` is the glue that
calls `rating/` and writes through SQLAlchemy, shared by every ingestion
source and every mutating command.

**Tech Stack:** Python 3.12, discord.py 2.4+, SQLAlchemy 2.0 (async) +
aiosqlite, Alembic, httpx + respx (HTTP client/mocking for HenrikDev),
pytest + pytest-asyncio, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-26-mmr-leaderboard-bot-design.md`

## Global Constraints

- $0 hosting: SQLite (not Postgres), single container, no paid services.
- Discord is the only UI — no web dashboard, no separate HTTP-facing process.
- Starting MMR: **700**. Per-match cap: **±40**. Provisional K: **40** for a
  player's first 10 games, **20** after.
- Performance modifier: multiplier in **[0.5, 1.5]** derived from combat
  score vs. match average; defaults to **1.0** when no stats were submitted.
- Soft floor: on a **3+ game losing streak**, loss magnitude is dampened by
  **35%**.
- Rank tiers (flat, no sub-divisions): Iron <500, Bronze 500-574, Silver
  575-649, Gold 650-724, Platinum 725-799, Diamond 800-874, Ascendant
  875-949, Immortal 950-1099, Radiant 1100+.
- `players.consented` (set by `/link`) gates whether a linked Riot ID is
  ever used for display or auto-ingestion.
- `/correct-match` and voiding a match both trigger a full recompute
  cascade forward from that match's timestamp (voiding removes a match's
  contribution to history exactly as correcting it does, so both mutate
  history and both must ripple forward the same way).

---

## File Structure

```
val-bot/
  Dockerfile
  docker-compose.yml
  requirements.txt
  alembic.ini
  migrations/
    env.py
    versions/
  src/val_bot/
    __init__.py
    config.py
    db/
      __init__.py
      models.py
      session.py
      match_service.py
    rating/
      __init__.py
      elo.py
      tiers.py
      engine.py
    ingestion/
      __init__.py
      base.py
      manual.py
      henrikdev.py
    bot/
      __init__.py
      main.py
      cogs/
        linking.py
        report.py
        mmr.py
        leaderboard.py
        history.py
        admin.py
        sync.py
      views/
        report_views.py
        history_views.py
        leaderboard_views.py
  tests/
    conftest.py
    test_elo.py
    test_tiers.py
    test_engine.py
    test_ingestion_manual.py
    test_ingestion_henrikdev.py
    test_match_service.py
    test_cog_linking.py
    test_cog_report.py
    test_cog_mmr.py
    test_cog_leaderboard.py
    test_cog_history.py
    test_cog_admin.py
    test_cog_sync.py
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`
- Create: `src/val_bot/__init__.py`, `src/val_bot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `val_bot.config.Config` dataclass with fields `discord_token: str`,
  `henrikdev_api_key: str | None`, `db_path: str`, loaded via
  `Config.from_env()`.

- [ ] **Step 1: Create `requirements.txt`**

```
discord.py>=2.4,<3.0
SQLAlchemy>=2.0,<3.0
aiosqlite>=0.20,<1.0
alembic>=1.13,<2.0
httpx>=0.27,<1.0
python-dotenv>=1.0,<2.0
pytest>=8.0,<9.0
pytest-asyncio>=0.24,<1.0
respx>=0.21,<1.0
```

- [ ] **Step 2: Write the failing test for config loading**

```python
# tests/test_config.py
import os
from val_bot.config import Config

def test_from_env_reads_required_and_optional_vars(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "abc123")
    monkeypatch.setenv("DB_PATH", "/data/bot.db")
    monkeypatch.delenv("HENRIKDEV_API_KEY", raising=False)
    cfg = Config.from_env()
    assert cfg.discord_token == "abc123"
    assert cfg.db_path == "/data/bot.db"
    assert cfg.henrikdev_api_key is None

def test_from_env_missing_token_raises(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    try:
        Config.from_env()
        assert False, "expected ValueError"
    except ValueError as e:
        assert "DISCORD_TOKEN" in str(e)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'val_bot'`

- [ ] **Step 4: Create the package skeleton and `config.py`**

```python
# src/val_bot/__init__.py
```

```python
# src/val_bot/config.py
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    discord_token: str
    db_path: str
    henrikdev_api_key: str | None

    @staticmethod
    def from_env() -> "Config":
        token = os.environ.get("DISCORD_TOKEN")
        if not token:
            raise ValueError("DISCORD_TOKEN environment variable is required")
        return Config(
            discord_token=token,
            db_path=os.environ.get("DB_PATH", "/data/bot.db"),
            henrikdev_api_key=os.environ.get("HENRIKDEV_API_KEY") or None,
        )
```

- [ ] **Step 5: Create a `pyproject.toml` so `val_bot` is importable in editable mode**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "val-bot"
version = "0.1.0"
requires-python = ">=3.12"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 6: Install and run the test to verify it passes**

Run: `pip install -e . && pip install -r requirements.txt && pytest tests/test_config.py -v`
Expected: PASS (both tests)

- [ ] **Step 7: Write `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`**

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "val_bot.bot.main"]
```

```yaml
# docker-compose.yml
services:
  bot:
    build: .
    env_file: .env
    volumes:
      - bot_data:/data
    restart: unless-stopped
volumes:
  bot_data:
```

```
# .env.example
DISCORD_TOKEN=
HENRIKDEV_API_KEY=
DB_PATH=/data/bot.db
```

```
# .gitignore
__pycache__/
*.pyc
.env
*.db
.venv/
```

- [ ] **Step 8: Commit**

```bash
git add requirements.txt Dockerfile docker-compose.yml .env.example .gitignore pyproject.toml src/val_bot/__init__.py src/val_bot/config.py tests/test_config.py
git commit -m "feat: project scaffolding and config loading"
```

---

### Task 2: Database Models + Migration

**Files:**
- Create: `src/val_bot/db/__init__.py`, `src/val_bot/db/models.py`, `src/val_bot/db/session.py`
- Create: `migrations/env.py`, `alembic.ini`
- Test: `tests/conftest.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `Base` (declarative base), `Player`, `Match`, `MatchParticipant`
  ORM classes exactly as fielded below; `val_bot.db.session.make_engine(db_path: str)`
  returning an `AsyncEngine`; a `db_session` pytest fixture yielding an
  `AsyncSession` against an in-memory DB with tables created.

- [ ] **Step 1: Write the failing test**

```python
# tests/conftest.py
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from val_bot.db.models import Base

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()
```

```python
# tests/test_models.py
from val_bot.db.models import Player, Match, MatchParticipant
from datetime import datetime, timezone

async def test_create_player_defaults(db_session):
    player = Player(discord_id="123")
    db_session.add(player)
    await db_session.flush()
    assert player.mmr == 700
    assert player.games_played == 0
    assert player.consented is False

async def test_create_match_with_participants(db_session):
    for discord_id in ("p1", "p2"):
        db_session.add(Player(discord_id=discord_id))
    await db_session.flush()

    match = Match(
        played_at=datetime.now(timezone.utc), map="Bind", source="manual",
        status="pending", reported_by_discord_id="p1",
        team_a_score=13, team_b_score=7,
    )
    match.participants.append(MatchParticipant(discord_id="p1", team="A", won=True))
    match.participants.append(MatchParticipant(discord_id="p2", team="B", won=False))
    db_session.add(match)
    await db_session.flush()

    assert match.id is not None
    assert len(match.participants) == 2
    assert match.participants[0].mmr_before is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'val_bot.db'`

- [ ] **Step 3: Write `models.py`**

```python
# src/val_bot/db/__init__.py
```

```python
# src/val_bot/db/models.py
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
    consented: Mapped[bool] = mapped_column(Boolean, default=False)
    mmr: Mapped[int] = mapped_column(Integer, default=700)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
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
```

```python
# src/val_bot/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine

def make_engine(db_path: str) -> AsyncEngine:
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}")

def make_session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Set up Alembic for the SQLite file used outside tests**

Run: `alembic init migrations`

Edit `migrations/env.py` to import the metadata and use an async-compatible
run:

```python
# migrations/env.py (replace the generated target_metadata line and the
# run_migrations_online body with the following)
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config
from val_bot.db.models import Base

target_metadata = Base.metadata

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

Set `sqlalchemy.url = sqlite+aiosqlite:///./bot.db` in `alembic.ini`.

Run: `alembic revision --autogenerate -m "initial schema" && alembic upgrade head`
Expected: creates `migrations/versions/<hash>_initial_schema.py` and a local `bot.db` with all three tables.

- [ ] **Step 6: Commit**

```bash
git add src/val_bot/db tests/conftest.py tests/test_models.py migrations alembic.ini
git commit -m "feat: SQLAlchemy models and Alembic migration setup"
```

---

### Task 3: Rating Engine Core (`rating/elo.py`)

**Files:**
- Create: `src/val_bot/rating/__init__.py`, `src/val_bot/rating/elo.py`
- Test: `tests/test_elo.py`

**Interfaces:**
- Produces: `expected_score(own_team_avg: float, opp_team_avg: float) -> float`,
  `k_factor(games_played: int) -> int`,
  `performance_modifier(player_score: float, match_avg_score: float) -> float`,
  `compute_delta(own_team_avg: float, opp_team_avg: float, won: bool,
  games_played: int, performance_mod: float = 1.0, loss_streak: int = 0,
  cap: int = 40) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_elo.py
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
    assert delta > 20 * (1 - expected_score(1000, 1200))  # sanity: matches formula direction
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_elo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'val_bot.rating'`

- [ ] **Step 3: Implement `elo.py`**

```python
# src/val_bot/rating/__init__.py
```

```python
# src/val_bot/rating/elo.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_elo.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/rating/__init__.py src/val_bot/rating/elo.py tests/test_elo.py
git commit -m "feat: core Elo rating functions with performance modifier"
```

---

### Task 4: Rank Tier Mapping (`rating/tiers.py`)

**Files:**
- Create: `src/val_bot/rating/tiers.py`
- Test: `tests/test_tiers.py`

**Interfaces:**
- Produces: `mmr_to_tier(mmr: int) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tiers.py
from val_bot.rating.tiers import mmr_to_tier

def test_boundaries():
    assert mmr_to_tier(0) == "Iron"
    assert mmr_to_tier(499) == "Iron"
    assert mmr_to_tier(500) == "Bronze"
    assert mmr_to_tier(574) == "Bronze"
    assert mmr_to_tier(575) == "Silver"
    assert mmr_to_tier(649) == "Silver"
    assert mmr_to_tier(650) == "Gold"
    assert mmr_to_tier(724) == "Gold"
    assert mmr_to_tier(725) == "Platinum"
    assert mmr_to_tier(799) == "Platinum"
    assert mmr_to_tier(800) == "Diamond"
    assert mmr_to_tier(874) == "Diamond"
    assert mmr_to_tier(875) == "Ascendant"
    assert mmr_to_tier(949) == "Ascendant"
    assert mmr_to_tier(950) == "Immortal"
    assert mmr_to_tier(1099) == "Immortal"
    assert mmr_to_tier(1100) == "Radiant"
    assert mmr_to_tier(5000) == "Radiant"

def test_starting_mmr_is_gold():
    assert mmr_to_tier(700) == "Gold"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tiers.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `tiers.py`**

```python
# src/val_bot/rating/tiers.py

TIERS = [
    ("Iron", 0, 499),
    ("Bronze", 500, 574),
    ("Silver", 575, 649),
    ("Gold", 650, 724),
    ("Platinum", 725, 799),
    ("Diamond", 800, 874),
    ("Ascendant", 875, 949),
    ("Immortal", 950, 1099),
    ("Radiant", 1100, None),
]

def mmr_to_tier(mmr: int) -> str:
    for name, low, high in TIERS:
        if mmr >= low and (high is None or mmr <= high):
            return name
    raise ValueError(f"no tier found for mmr={mmr}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tiers.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/rating/tiers.py tests/test_tiers.py
git commit -m "feat: MMR to rank tier mapping"
```

---

### Task 5: Rating Sequencing Engine (`rating/engine.py`)

This is the shared core that both a single new match (`confirm_match`) and a
multi-match replay (`recompute_from`) call, so the ripple-across-players
behavior is implemented exactly once.

**Files:**
- Create: `src/val_bot/rating/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `expected_score`, `k_factor`, `performance_modifier`,
  `compute_delta` from `val_bot.rating.elo`.
- Produces: `ParticipantInput` dataclass (`discord_id: str, team: str, won:
  bool, combat_score: int | None`); `rate_match(participants:
  list[ParticipantInput], current_mmr: dict[str, int], games_played:
  dict[str, int], loss_streak: dict[str, int]) -> dict[str, tuple[int,
  int]]` — returns `{discord_id: (mmr_before, mmr_after)}` and mutates the
  three state dicts in place, so callers can feed the same dicts into
  a sequence of matches for a chronological replay.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_engine.py
from val_bot.rating.engine import ParticipantInput, rate_match

def _players(*ids):
    return {d: 700 for d in ids}, {d: 0 for d in ids}, {d: 0 for d in ids}

def test_single_match_updates_winners_up_losers_down():
    current_mmr, games_played, loss_streak = _players("a", "b", "c", "d")
    participants = [
        ParticipantInput("a", "A", True, None),
        ParticipantInput("b", "A", True, None),
        ParticipantInput("c", "B", False, None),
        ParticipantInput("d", "B", False, None),
    ]
    results = rate_match(participants, current_mmr, games_played, loss_streak)
    assert results["a"][1] > results["a"][0]
    assert results["c"][1] < results["c"][0]
    assert current_mmr["a"] == results["a"][1]
    assert games_played["a"] == 1
    assert loss_streak["c"] == 1
    assert loss_streak["a"] == 0

def test_replay_two_matches_ripples_state_forward():
    current_mmr, games_played, loss_streak = _players("a", "b", "c", "d")
    match1 = [
        ParticipantInput("a", "A", True, None),
        ParticipantInput("b", "A", True, None),
        ParticipantInput("c", "B", False, None),
        ParticipantInput("d", "B", False, None),
    ]
    match2 = [
        ParticipantInput("a", "A", False, None),
        ParticipantInput("c", "A", False, None),
        ParticipantInput("b", "B", True, None),
        ParticipantInput("d", "B", True, None),
    ]
    r1 = rate_match(match1, current_mmr, games_played, loss_streak)
    r2 = rate_match(match2, current_mmr, games_played, loss_streak)
    # match2's mmr_before for "a" must equal match1's mmr_after for "a" —
    # this is the ripple: a later match's inputs depend on the earlier one.
    assert r2["a"][0] == r1["a"][1]
    assert games_played["a"] == 2

def test_performance_modifier_applied_when_combat_score_present():
    current_mmr, games_played, loss_streak = _players("a", "b", "c", "d")
    participants = [
        ParticipantInput("a", "A", True, 400),   # way above match average
        ParticipantInput("b", "A", True, 200),
        ParticipantInput("c", "B", False, 200),
        ParticipantInput("d", "B", False, 200),
    ]
    results = rate_match(participants, current_mmr, games_played, loss_streak)
    gain_a = results["a"][1] - results["a"][0]
    gain_b = results["b"][1] - results["b"][0]
    assert gain_a > gain_b  # "a" overperformed relative to match average
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `engine.py`**

```python
# src/val_bot/rating/engine.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_engine.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/rating/engine.py tests/test_engine.py
git commit -m "feat: shared rating sequencing engine for single-match and replay use"
```

---

### Task 6: Ingestion Abstraction (`ingestion/base.py`)

**Files:**
- Create: `src/val_bot/ingestion/__init__.py`, `src/val_bot/ingestion/base.py`
- Test: `tests/test_ingestion_base.py`

**Interfaces:**
- Produces: `NormalizedParticipant`, `NormalizedMatch` dataclasses;
  `MatchDataSource` ABC with `async def fetch_new_matches(self) ->
  list[NormalizedMatch]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingestion_base.py
from datetime import datetime, timezone
from val_bot.ingestion.base import MatchDataSource, NormalizedMatch, NormalizedParticipant
import pytest

def test_normalized_match_holds_participants():
    match = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Haven", source="manual",
        team_a_score=13, team_b_score=9, reported_by_discord_id="p1",
        participants=[NormalizedParticipant(discord_id="p1", team="A")],
    )
    assert match.participants[0].discord_id == "p1"
    assert match.external_match_id is None

def test_match_data_source_is_abstract():
    with pytest.raises(TypeError):
        MatchDataSource()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingestion_base.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `base.py`**

```python
# src/val_bot/ingestion/__init__.py
```

```python
# src/val_bot/ingestion/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class NormalizedParticipant:
    discord_id: str
    team: str
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    combat_score: int | None = None

@dataclass
class NormalizedMatch:
    played_at: datetime
    map: str
    source: str
    team_a_score: int
    team_b_score: int
    reported_by_discord_id: str
    participants: list[NormalizedParticipant]
    external_match_id: str | None = None

class MatchDataSource(ABC):
    @abstractmethod
    async def fetch_new_matches(self) -> list[NormalizedMatch]:
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingestion_base.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/ingestion/__init__.py src/val_bot/ingestion/base.py tests/test_ingestion_base.py
git commit -m "feat: MatchDataSource abstraction and normalized match schema"
```

---

### Task 7: Manual Entry Source (`ingestion/manual.py`)

**Files:**
- Create: `src/val_bot/ingestion/manual.py`
- Test: `tests/test_ingestion_manual.py`

**Interfaces:**
- Consumes: `NormalizedMatch`, `NormalizedParticipant`, `MatchDataSource` from
  `val_bot.ingestion.base`.
- Produces: `ManualEntrySource.build_match(map_name: str, team_a_score: int,
  team_b_score: int, reported_by_discord_id: str, team_a_discord_ids:
  list[str], team_b_discord_ids: list[str], stats: dict[str, dict] | None =
  None) -> NormalizedMatch`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingestion_manual.py
from val_bot.ingestion.manual import ManualEntrySource

def test_build_match_without_stats():
    source = ManualEntrySource()
    match = source.build_match(
        map_name="Ascent", team_a_score=13, team_b_score=5,
        reported_by_discord_id="p1",
        team_a_discord_ids=["p1", "p2"], team_b_discord_ids=["p3", "p4"],
    )
    assert match.source == "manual"
    assert len(match.participants) == 4
    a = next(p for p in match.participants if p.discord_id == "p1")
    assert a.team == "A"
    assert a.combat_score is None

def test_build_match_with_stats():
    source = ManualEntrySource()
    match = source.build_match(
        map_name="Bind", team_a_score=13, team_b_score=10,
        reported_by_discord_id="p1",
        team_a_discord_ids=["p1"], team_b_discord_ids=["p2"],
        stats={"p1": {"kills": 20, "deaths": 10, "assists": 5, "combat_score": 250}},
    )
    p1 = next(p for p in match.participants if p.discord_id == "p1")
    assert p1.kills == 20
    assert p1.combat_score == 250

async def test_fetch_new_matches_returns_empty():
    source = ManualEntrySource()
    assert await source.fetch_new_matches() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingestion_manual.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `manual.py`**

```python
# src/val_bot/ingestion/manual.py
from datetime import datetime, timezone
from val_bot.ingestion.base import MatchDataSource, NormalizedMatch, NormalizedParticipant

class ManualEntrySource(MatchDataSource):
    """Push-based: /report-match calls build_match directly with data
    already collected from Discord UI, so fetch_new_matches is a no-op —
    this source never polls anything on its own."""

    async def fetch_new_matches(self) -> list[NormalizedMatch]:
        return []

    def build_match(
        self,
        map_name: str,
        team_a_score: int,
        team_b_score: int,
        reported_by_discord_id: str,
        team_a_discord_ids: list[str],
        team_b_discord_ids: list[str],
        stats: dict[str, dict] | None = None,
    ) -> NormalizedMatch:
        stats = stats or {}

        def build(discord_id: str, team: str) -> NormalizedParticipant:
            s = stats.get(discord_id, {})
            return NormalizedParticipant(
                discord_id=discord_id, team=team,
                kills=s.get("kills", 0), deaths=s.get("deaths", 0),
                assists=s.get("assists", 0), combat_score=s.get("combat_score"),
            )

        participants = [build(d, "A") for d in team_a_discord_ids] + [
            build(d, "B") for d in team_b_discord_ids
        ]
        return NormalizedMatch(
            played_at=datetime.now(timezone.utc),
            map=map_name, source="manual",
            team_a_score=team_a_score, team_b_score=team_b_score,
            reported_by_discord_id=reported_by_discord_id,
            participants=participants,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingestion_manual.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/ingestion/manual.py tests/test_ingestion_manual.py
git commit -m "feat: ManualEntrySource for /report-match"
```

---

### Task 8: Match Service — Create Pending + Confirm

**Files:**
- Create: `src/val_bot/db/match_service.py`
- Test: `tests/test_match_service.py` (this task's tests only)

**Interfaces:**
- Consumes: `Player`, `Match`, `MatchParticipant` from `val_bot.db.models`;
  `NormalizedMatch` from `val_bot.ingestion.base`; `ParticipantInput`,
  `rate_match` from `val_bot.rating.engine`.
- Produces: `async def create_pending_match(session: AsyncSession,
  normalized: NormalizedMatch) -> Match`; `async def confirm_match(session:
  AsyncSession, match_id: int) -> Match`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_match_service.py
from datetime import datetime, timezone
from val_bot.db.models import Player
from val_bot.db.match_service import create_pending_match, confirm_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant

def _normalized_match():
    return NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Split", source="manual",
        team_a_score=13, team_b_score=6, reported_by_discord_id="p1",
        participants=[
            NormalizedParticipant(discord_id="p1", team="A"),
            NormalizedParticipant(discord_id="p2", team="A"),
            NormalizedParticipant(discord_id="p3", team="B"),
            NormalizedParticipant(discord_id="p4", team="B"),
        ],
    )

async def test_create_pending_match_does_not_touch_mmr(db_session):
    for d in ("p1", "p2", "p3", "p4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    match = await create_pending_match(db_session, _normalized_match())
    assert match.status == "pending"
    assert all(p.mmr_before is None for p in match.participants)
    p1 = await db_session.get(Player, "p1")
    assert p1.mmr == 700  # unchanged until confirmed

async def test_confirm_match_applies_ratings(db_session):
    for d in ("p1", "p2", "p3", "p4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    match = await create_pending_match(db_session, _normalized_match())
    confirmed = await confirm_match(db_session, match.id)

    assert confirmed.status == "confirmed"
    p1 = await db_session.get(Player, "p1")
    p3 = await db_session.get(Player, "p3")
    assert p1.mmr > 700  # winner
    assert p3.mmr < 700  # loser
    assert p1.games_played == 1
    winner_row = next(p for p in confirmed.participants if p.discord_id == "p1")
    assert winner_row.mmr_before == 700
    assert winner_row.mmr_after == p1.mmr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_match_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'val_bot.db.match_service'`

- [ ] **Step 3: Implement `match_service.py` (this task's two functions only — more are added in Task 9)**

```python
# src/val_bot/db/match_service.py
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from val_bot.db.models import Player, Match, MatchParticipant
from val_bot.ingestion.base import NormalizedMatch
from val_bot.rating.engine import ParticipantInput, rate_match

async def create_pending_match(session: AsyncSession, normalized: NormalizedMatch) -> Match:
    winning_team = "A" if normalized.team_a_score > normalized.team_b_score else "B"
    match = Match(
        played_at=normalized.played_at, map=normalized.map, source=normalized.source,
        status="pending", reported_by_discord_id=normalized.reported_by_discord_id,
        team_a_score=normalized.team_a_score, team_b_score=normalized.team_b_score,
        external_match_id=normalized.external_match_id,
    )
    for p in normalized.participants:
        match.participants.append(MatchParticipant(
            discord_id=p.discord_id, team=p.team, kills=p.kills, deaths=p.deaths,
            assists=p.assists, combat_score=p.combat_score,
            won=(p.team == winning_team),
        ))
    session.add(match)
    await session.flush()
    return match

async def _trailing_loss_streak(session: AsyncSession, discord_id: str) -> int:
    result = await session.execute(
        select(MatchParticipant.won)
        .join(Match)
        .where(MatchParticipant.discord_id == discord_id, Match.status == "confirmed")
        .order_by(Match.played_at.desc())
    )
    streak = 0
    for (won,) in result:
        if won:
            break
        streak += 1
    return streak

async def _seed_state(session: AsyncSession, discord_ids: set[str]):
    current_mmr, games_played, loss_streak = {}, {}, {}
    for discord_id in discord_ids:
        player = await session.get(Player, discord_id)
        current_mmr[discord_id] = player.mmr
        games_played[discord_id] = player.games_played
        loss_streak[discord_id] = await _trailing_loss_streak(session, discord_id)
    return current_mmr, games_played, loss_streak

async def confirm_match(session: AsyncSession, match_id: int) -> Match:
    match = await session.get(Match, match_id)
    discord_ids = {p.discord_id for p in match.participants}
    current_mmr, games_played, loss_streak = await _seed_state(session, discord_ids)

    participant_inputs = [
        ParticipantInput(p.discord_id, p.team, p.won, p.combat_score)
        for p in match.participants
    ]
    results = rate_match(participant_inputs, current_mmr, games_played, loss_streak)

    for p in match.participants:
        before, after = results[p.discord_id]
        p.mmr_before, p.mmr_after = before, after
        player = await session.get(Player, p.discord_id)
        player.mmr = after
        player.games_played += 1

    match.status = "confirmed"
    await session.flush()
    return match
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_match_service.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/db/match_service.py tests/test_match_service.py
git commit -m "feat: match service create_pending_match and confirm_match"
```

---

### Task 9: Match Service — Recompute Cascade, Void, Correct

**Files:**
- Modify: `src/val_bot/db/match_service.py`
- Modify: `tests/test_match_service.py` (append tests)

**Interfaces:**
- Consumes: everything from Task 8, plus reads `Match.played_at` to bound
  the replay window.
- Produces: `async def recompute_from(session: AsyncSession, from_played_at:
  datetime) -> None`; `async def void_match(session: AsyncSession, match_id:
  int) -> None`; `async def correct_match(session: AsyncSession, match_id:
  int, team_a_score: int | None = None, team_b_score: int | None = None,
  participant_updates: dict[str, dict] | None = None) -> None`.

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_match_service.py
from val_bot.db.match_service import void_match, correct_match

async def _play_three_matches(db_session):
    """a,b beat c,d twice, then c,d beat a,b once — gives every player
    enough history that a correction to match 1 has somewhere to ripple."""
    for d in ("a", "b", "c", "d"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    def match(team_a_score, team_b_score):
        return NormalizedMatch(
            played_at=datetime.now(timezone.utc), map="Bind", source="manual",
            team_a_score=team_a_score, team_b_score=team_b_score,
            reported_by_discord_id="a",
            participants=[
                NormalizedParticipant(discord_id="a", team="A"),
                NormalizedParticipant(discord_id="b", team="A"),
                NormalizedParticipant(discord_id="c", team="B"),
                NormalizedParticipant(discord_id="d", team="B"),
            ],
        )

    m1 = await confirm_match(db_session, (await create_pending_match(db_session, match(13, 4))).id)
    m2 = await confirm_match(db_session, (await create_pending_match(db_session, match(13, 8))).id)
    m3 = await confirm_match(db_session, (await create_pending_match(db_session, match(6, 13))).id)
    return m1, m2, m3

async def test_correct_match_recomputes_forward_and_ripples(db_session):
    m1, m2, m3 = await _play_three_matches(db_session)
    a_before_correction = (await db_session.get(Player, "a")).mmr

    # correct match 1: it was actually a much closer game (13-12), so
    # team A's win should have been worth less MMR than originally applied
    await correct_match(db_session, m1.id, team_a_score=13, team_b_score=12)

    a_after_correction = (await db_session.get(Player, "a")).mmr
    assert a_after_correction != a_before_correction  # ripples through m2 and m3 too

    # m2 and m3's mmr_before for "a" must now chain consistently
    await db_session.refresh(m2, attribute_names=["participants"])
    await db_session.refresh(m3, attribute_names=["participants"])
    m2_a = next(p for p in m2.participants if p.discord_id == "a")
    m3_a = next(p for p in m3.participants if p.discord_id == "a")
    assert m2_a.mmr_after == m3_a.mmr_before

async def test_void_match_removes_its_contribution(db_session):
    m1, m2, m3 = await _play_three_matches(db_session)
    await void_match(db_session, m2.id)

    await db_session.refresh(m2)
    assert m2.status == "voided"

    # m3's mmr_before for "a" should now chain directly from m1's mmr_after,
    # since m2 no longer contributes
    await db_session.refresh(m1, attribute_names=["participants"])
    await db_session.refresh(m3, attribute_names=["participants"])
    m1_a = next(p for p in m1.participants if p.discord_id == "a")
    m3_a = next(p for p in m3.participants if p.discord_id == "a")
    assert m3_a.mmr_before == m1_a.mmr_after
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_match_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'void_match'`

- [ ] **Step 3: Append `recompute_from`, `void_match`, `correct_match` to `match_service.py`**

```python
# append to src/val_bot/db/match_service.py

async def _seed_state_before(session: AsyncSession, discord_id: str, from_played_at: datetime):
    result = await session.execute(
        select(MatchParticipant)
        .join(Match)
        .where(
            MatchParticipant.discord_id == discord_id,
            Match.status == "confirmed",
            Match.played_at < from_played_at,
        )
        .order_by(Match.played_at.desc())
    )
    rows = list(result.scalars())
    games = len(rows)
    mmr = rows[0].mmr_after if rows else 700
    streak = 0
    for row in rows:
        if row.won:
            break
        streak += 1
    return mmr, games, streak

async def recompute_from(session: AsyncSession, from_played_at: datetime) -> None:
    result = await session.execute(
        select(Match)
        .where(Match.status == "confirmed", Match.played_at >= from_played_at)
        .order_by(Match.played_at.asc())
    )
    matches = list(result.scalars().unique())
    if not matches:
        return

    discord_ids = {p.discord_id for m in matches for p in m.participants}
    current_mmr, games_played, loss_streak = {}, {}, {}
    for discord_id in discord_ids:
        mmr, games, streak = await _seed_state_before(session, discord_id, from_played_at)
        current_mmr[discord_id] = mmr
        games_played[discord_id] = games
        loss_streak[discord_id] = streak

    for match in matches:
        participant_inputs = [
            ParticipantInput(p.discord_id, p.team, p.won, p.combat_score)
            for p in match.participants
        ]
        results = rate_match(participant_inputs, current_mmr, games_played, loss_streak)
        for p in match.participants:
            p.mmr_before, p.mmr_after = results[p.discord_id]

    for discord_id in discord_ids:
        player = await session.get(Player, discord_id)
        player.mmr = current_mmr[discord_id]
        player.games_played = games_played[discord_id]

    await session.flush()

async def void_match(session: AsyncSession, match_id: int) -> None:
    match = await session.get(Match, match_id)
    played_at = match.played_at
    match.status = "voided"
    await session.flush()
    await recompute_from(session, played_at)

async def correct_match(
    session: AsyncSession,
    match_id: int,
    team_a_score: int | None = None,
    team_b_score: int | None = None,
    participant_updates: dict[str, dict] | None = None,
) -> None:
    match = await session.get(Match, match_id)
    if team_a_score is not None:
        match.team_a_score = team_a_score
    if team_b_score is not None:
        match.team_b_score = team_b_score
    winning_team = "A" if match.team_a_score > match.team_b_score else "B"

    participant_updates = participant_updates or {}
    for p in match.participants:
        p.won = (p.team == winning_team)
        updates = participant_updates.get(p.discord_id, {})
        for field_name in ("kills", "deaths", "assists", "combat_score"):
            if field_name in updates:
                setattr(p, field_name, updates[field_name])

    played_at = match.played_at
    await session.flush()
    await recompute_from(session, played_at)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_match_service.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/db/match_service.py tests/test_match_service.py
git commit -m "feat: recompute cascade for match voiding and correction"
```

---

### Task 10: Bot Scaffolding + Smoke-Test Command

**Files:**
- Create: `src/val_bot/bot/__init__.py`, `src/val_bot/bot/main.py`
- Create: `src/val_bot/bot/cogs/__init__.py`
- Test: `tests/test_bot_main.py`

**Interfaces:**
- Produces: `val_bot.bot.main.build_bot(config: Config,
  session_factory) -> discord.ext.commands.Bot`, with an `/ping` slash
  command registered for a live smoke test; `main()` entrypoint that loads
  `Config.from_env()`, creates the engine/session factory via
  `val_bot.db.session`, builds the bot, and runs it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bot_main.py
from val_bot.config import Config
from val_bot.bot.main import build_bot

def test_build_bot_registers_ping_command():
    cfg = Config(discord_token="x", db_path=":memory:", henrikdev_api_key=None)
    bot = build_bot(cfg, session_factory=None)
    command_names = {cmd.name for cmd in bot.tree.get_commands()}
    assert "ping" in command_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bot_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'val_bot.bot'`

- [ ] **Step 3: Implement `bot/main.py`**

```python
# src/val_bot/bot/__init__.py
```

```python
# src/val_bot/bot/cogs/__init__.py
```

```python
# src/val_bot/bot/main.py
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.config import Config
from val_bot.db.session import make_engine, make_session_factory

class ValBot(commands.Bot):
    def __init__(self, session_factory, henrikdev_api_key: str | None):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.session_factory = session_factory
        self.henrikdev_api_key = henrikdev_api_key

    async def setup_hook(self):
        await self.tree.sync()

def build_bot(config: Config, session_factory) -> ValBot:
    bot = ValBot(session_factory=session_factory, henrikdev_api_key=config.henrikdev_api_key)

    @bot.tree.command(name="ping", description="Check that the bot is alive")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message("pong", ephemeral=True)

    return bot

def main():
    config = Config.from_env()
    engine = make_engine(config.db_path)
    session_factory = make_session_factory(engine)
    bot = build_bot(config, session_factory)
    bot.run(config.discord_token)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bot_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/bot/__init__.py src/val_bot/bot/main.py src/val_bot/bot/cogs/__init__.py tests/test_bot_main.py
git commit -m "feat: bot scaffolding with /ping smoke-test command"
```

- [ ] **Step 6: Manual verification against real Discord**

Create a Discord application + bot user at https://discord.com/developers/applications,
enable the "Server Members Intent" under Bot settings, invite it to a test
server with the `applications.commands` and `bot` scopes, put the token in
`.env`, then run:

```bash
pip install -e . && pip install -r requirements.txt
export $(cat .env | xargs) && python -m val_bot.bot.main
```

Expected: bot comes online in the test server; typing `/ping` returns "pong".
This confirms the Discord token, intents, and slash-command sync all work
before building UI-heavy commands on top.

---

### Task 11: `/link` Command

**Files:**
- Create: `src/val_bot/bot/cogs/linking.py`
- Modify: `src/val_bot/bot/main.py` (register the cog)
- Test: `tests/test_cog_linking.py`

**Interfaces:**
- Consumes: `Player` from `val_bot.db.models`; `session_factory` stored on
  `ValBot`.
- Produces: `/link riot_username riot_tag` slash command that upserts a
  `Player` row with `consented=True`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cog_linking.py
from unittest.mock import AsyncMock, MagicMock
from val_bot.bot.cogs.linking import link_command_callback
from val_bot.db.models import Player

async def test_link_creates_new_player(db_session):
    interaction = MagicMock()
    interaction.user.id = 123
    interaction.response.send_message = AsyncMock()

    async def session_factory_cm():
        return db_session
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    await link_command_callback(interaction, session_factory, "Phantom", "NA1")

    player = await db_session.get(Player, "123")
    assert player.riot_username == "Phantom"
    assert player.riot_tag == "NA1"
    assert player.consented is True
    interaction.response.send_message.assert_awaited_once()

async def test_link_updates_existing_player(db_session):
    db_session.add(Player(discord_id="123", riot_username="Old", riot_tag="EU1"))
    await db_session.flush()

    interaction = MagicMock()
    interaction.user.id = 123
    interaction.response.send_message = AsyncMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    await link_command_callback(interaction, session_factory, "New", "NA1")

    player = await db_session.get(Player, "123")
    assert player.riot_username == "New"
    assert player.riot_tag == "NA1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cog_linking.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `linking.py`**

```python
# src/val_bot/bot/cogs/linking.py
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.db.models import Player

async def link_command_callback(interaction, session_factory, riot_username: str, riot_tag: str):
    discord_id = str(interaction.user.id)
    async with session_factory() as session:
        player = await session.get(Player, discord_id)
        if player is None:
            player = Player(discord_id=discord_id)
            session.add(player)
        player.riot_username = riot_username
        player.riot_tag = riot_tag
        player.consented = True
        await session.commit()
    await interaction.response.send_message(
        f"Linked to **{riot_username}#{riot_tag}**. You'll now show up with your Riot name "
        "on the leaderboard, and be eligible for automatic match detection once that's live.",
        ephemeral=True,
    )

class LinkingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="link", description="Link your Discord account to your Riot ID")
    @app_commands.describe(riot_username="Your Riot username (before the #)", riot_tag="Your Riot tag (after the #)")
    async def link(self, interaction: discord.Interaction, riot_username: str, riot_tag: str):
        await link_command_callback(interaction, self.bot.session_factory, riot_username, riot_tag)

async def setup(bot):
    await bot.add_cog(LinkingCog(bot))
```

- [ ] **Step 4: Register the cog in `bot/main.py`**

```python
# in src/val_bot/bot/main.py, inside ValBot.setup_hook, before self.tree.sync():
        from val_bot.bot.cogs.linking import setup as setup_linking
        await setup_linking(self)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cog_linking.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add src/val_bot/bot/cogs/linking.py src/val_bot/bot/main.py tests/test_cog_linking.py
git commit -m "feat: /link command"
```

---

### Task 12: `/report-match` — Collection UI

**Files:**
- Create: `src/val_bot/bot/views/report_views.py`
- Create: `src/val_bot/bot/cogs/report.py`
- Modify: `src/val_bot/bot/main.py` (register the cog)
- Test: `tests/test_cog_report.py`

**Interfaces:**
- Consumes: `ManualEntrySource` from `val_bot.ingestion.manual`;
  `create_pending_match` from `val_bot.db.match_service`.
- Produces: `MatchReportModal` (map + scores), `TeamSelectView` (two
  `discord.ui.UserSelect`, 5 users each), and a
  `build_pending_match(map_name, team_a_score, team_b_score,
  reporter_id, team_a_ids, team_b_ids, session_factory) -> Match` helper
  the modal/view flow calls once both teams are picked.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cog_report.py
from val_bot.bot.views.report_views import build_pending_match
from val_bot.db.models import Player

async def test_build_pending_match_creates_match_row(db_session):
    for d in ("1", "2", "3", "4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()

    match = await build_pending_match(
        session=db_session, map_name="Icebox", team_a_score=13, team_b_score=9,
        reporter_id="1", team_a_ids=["1", "2"], team_b_ids=["3", "4"],
    )

    assert match.status == "pending"
    assert match.map == "Icebox"
    assert len(match.participants) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cog_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `report_views.py`**

```python
# src/val_bot/bot/views/report_views.py
import discord
from val_bot.ingestion.manual import ManualEntrySource
from val_bot.db.match_service import create_pending_match
from val_bot.db.models import Match

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
        view = TeamSelectView(
            session_factory=self.session_factory,
            map_name=str(self.map_name),
            team_a_score=int(str(self.team_a_score)),
            team_b_score=int(str(self.team_b_score)),
            reporter_id=str(interaction.user.id),
            on_built=self.on_built,
        )
        await interaction.response.send_message(
            "Now pick each team's players:", view=view, ephemeral=True
        )
```

- [ ] **Step 4: Implement `cogs/report.py`**

```python
# src/val_bot/bot/cogs/report.py
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.report_views import MatchReportModal
from val_bot.bot.views.report_views import ConfirmDisputeView  # added in Task 13

class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="report-match", description="Report the result of a pickup match")
    async def report_match(self, interaction: discord.Interaction):
        async def on_built(inner_interaction: discord.Interaction, match_id: int):
            view = ConfirmDisputeView(self.bot.session_factory, match_id)
            await inner_interaction.followup.send(
                f"Match #{match_id} reported. Waiting for confirmation from the "
                "other team (or a moderator) before MMR is applied.",
                view=view,
            )

        modal = MatchReportModal(self.bot.session_factory, on_built)
        await interaction.response.send_modal(modal)

async def setup(bot):
    await bot.add_cog(ReportCog(bot))
```

Note: `ConfirmDisputeView` doesn't exist yet — it's built in Task 13. This
task's test only exercises `build_pending_match`, so the cog file is written
now but not imported by tests until Task 13 wires it up; `bot/main.py`
registration for this cog is deferred to Task 13 as well so `main.py` never
imports a name that doesn't exist yet.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cog_report.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/val_bot/bot/views/report_views.py src/val_bot/bot/cogs/report.py tests/test_cog_report.py
git commit -m "feat: /report-match modal and team-select collection UI"
```

---

### Task 13: Confirm/Dispute Flow

**Files:**
- Modify: `src/val_bot/bot/views/report_views.py` (add `ConfirmDisputeView`)
- Modify: `src/val_bot/bot/main.py` (register `ReportCog`)
- Modify: `tests/test_cog_report.py` (append tests)

**Interfaces:**
- Consumes: `confirm_match` from `val_bot.db.match_service`.
- Produces: `ConfirmDisputeView(session_factory, match_id)` — a
  `discord.ui.View` with "Confirm" and "Dispute" buttons; Confirm calls
  `confirm_match` and edits the message to show final MMR deltas; Dispute
  deletes the pending match row.

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_cog_report.py
from val_bot.bot.views.report_views import ConfirmDisputeView
from val_bot.db.match_service import create_pending_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from val_bot.db.models import Match

async def _pending_match(db_session):
    for d in ("1", "2", "3", "4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()
    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Fracture", source="manual",
        team_a_score=13, team_b_score=7, reported_by_discord_id="1",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="A"),
            NormalizedParticipant(discord_id="3", team="B"),
            NormalizedParticipant(discord_id="4", team="B"),
        ],
    )
    match = await create_pending_match(db_session, normalized)
    await db_session.commit()
    return match.id

async def test_confirm_button_applies_match(db_session):
    match_id = await _pending_match(db_session)
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    view = ConfirmDisputeView(session_factory, match_id)
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()

    await view.confirm.callback(interaction)

    match = await db_session.get(Match, match_id)
    assert match.status == "confirmed"
    interaction.response.edit_message.assert_awaited_once()

async def test_dispute_button_voids_pending_match(db_session):
    match_id = await _pending_match(db_session)
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    view = ConfirmDisputeView(session_factory, match_id)
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()

    await view.dispute.callback(interaction)

    result = await db_session.execute(select(Match).where(Match.id == match_id))
    assert result.scalar_one_or_none() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cog_report.py -v`
Expected: FAIL with `ImportError: cannot import name 'ConfirmDisputeView'`

- [ ] **Step 3: Append `ConfirmDisputeView` to `report_views.py`**

```python
# append to src/val_bot/bot/views/report_views.py
from sqlalchemy import delete
from val_bot.db.match_service import confirm_match
from val_bot.db.models import MatchParticipant

class ConfirmDisputeView(discord.ui.View):
    def __init__(self, session_factory, match_id: int):
        super().__init__(timeout=3600)
        self.session_factory = session_factory
        self.match_id = match_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.session_factory() as session:
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
            await session.execute(
                delete(MatchParticipant).where(MatchParticipant.match_id == self.match_id)
            )
            await session.execute(delete(Match).where(Match.id == self.match_id))
            await session.commit()
        await interaction.response.edit_message(
            content="Match disputed and discarded. No MMR was applied.", view=None
        )
```

- [ ] **Step 4: Fix the forward-reference import in `cogs/report.py`**

The import at the top of `src/val_bot/bot/cogs/report.py` (`from
val_bot.bot.views.report_views import ConfirmDisputeView`) now resolves
correctly since `ConfirmDisputeView` exists — no change needed to that file.

- [ ] **Step 5: Register `ReportCog` in `bot/main.py`**

```python
# in src/val_bot/bot/main.py, inside ValBot.setup_hook, alongside the linking cog:
        from val_bot.bot.cogs.report import setup as setup_report
        await setup_report(self)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_cog_report.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 7: Commit**

```bash
git add src/val_bot/bot/views/report_views.py src/val_bot/bot/main.py tests/test_cog_report.py
git commit -m "feat: confirm/dispute flow for reported matches"
```

---

### Task 14: `/mmr` Command

**Files:**
- Create: `src/val_bot/bot/cogs/mmr.py`
- Modify: `src/val_bot/bot/main.py` (register the cog)
- Test: `tests/test_cog_mmr.py`

**Interfaces:**
- Consumes: `Player` from `val_bot.db.models`; `mmr_to_tier` from
  `val_bot.rating.tiers`.
- Produces: `async def build_mmr_embed(session, discord_id: str) ->
  discord.Embed | None` (returns `None` if the player has never played).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cog_mmr.py
from val_bot.bot.cogs.mmr import build_mmr_embed
from val_bot.db.models import Player

async def test_build_mmr_embed_for_known_player(db_session):
    db_session.add(Player(discord_id="1", mmr=900, games_played=12, riot_username="Foo", riot_tag="NA1"))
    await db_session.flush()

    embed = await build_mmr_embed(db_session, "1")
    assert "900" in embed.description
    assert "Platinum" in embed.description

async def test_build_mmr_embed_returns_none_for_unknown_player(db_session):
    embed = await build_mmr_embed(db_session, "999")
    assert embed is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cog_mmr.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `cogs/mmr.py`**

```python
# src/val_bot/bot/cogs/mmr.py
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.db.models import Player
from val_bot.rating.tiers import mmr_to_tier

async def build_mmr_embed(session, discord_id: str) -> discord.Embed | None:
    player = await session.get(Player, discord_id)
    if player is None:
        return None
    tier = mmr_to_tier(player.mmr)
    name = f"{player.riot_username}#{player.riot_tag}" if player.riot_username else f"<@{discord_id}>"
    return discord.Embed(
        title=name,
        description=f"**{tier}** — {player.mmr} MMR\nGames played: {player.games_played}",
    )

class MmrCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mmr", description="Check your (or someone else's) MMR and rank")
    async def mmr(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        async with self.bot.session_factory() as session:
            embed = await build_mmr_embed(session, str(target.id))
        if embed is None:
            await interaction.response.send_message(
                f"{target.mention} hasn't played a rated match yet.", ephemeral=True
            )
            return
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(MmrCog(bot))
```

- [ ] **Step 4: Register the cog in `bot/main.py`**

```python
# in src/val_bot/bot/main.py, inside ValBot.setup_hook:
        from val_bot.bot.cogs.mmr import setup as setup_mmr
        await setup_mmr(self)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cog_mmr.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add src/val_bot/bot/cogs/mmr.py src/val_bot/bot/main.py tests/test_cog_mmr.py
git commit -m "feat: /mmr command"
```

---

### Task 15: `/leaderboard` Command

**Files:**
- Create: `src/val_bot/bot/views/leaderboard_views.py`
- Create: `src/val_bot/bot/cogs/leaderboard.py`
- Modify: `src/val_bot/bot/main.py` (register the cog)
- Test: `tests/test_cog_leaderboard.py`

**Interfaces:**
- Consumes: `Player` from `val_bot.db.models`.
- Produces: `async def fetch_leaderboard_page(session, offset: int, limit:
  int = 10) -> list[Player]` (ordered by MMR desc); `format_leaderboard_page(players:
  list[Player]) -> str` returning rows as `"RiotUsername (@DiscordMention)"`, or
  `"(unlinked, @DiscordMention)"` for players who haven't linked.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cog_leaderboard.py
from val_bot.bot.views.leaderboard_views import fetch_leaderboard_page, format_leaderboard_page
from val_bot.db.models import Player

async def test_fetch_leaderboard_page_orders_by_mmr_desc(db_session):
    db_session.add(Player(discord_id="1", mmr=800))
    db_session.add(Player(discord_id="2", mmr=1200))
    db_session.add(Player(discord_id="3", mmr=650))
    await db_session.flush()

    page = await fetch_leaderboard_page(db_session, offset=0, limit=10)
    assert [p.discord_id for p in page] == ["2", "1", "3"]

async def test_format_leaderboard_page_uses_riot_name_and_mention():
    players = [Player(discord_id="1", mmr=900, riot_username="Foo", riot_tag="NA1")]
    text = format_leaderboard_page(players)
    assert "Foo#NA1" in text
    assert "<@1>" in text

async def test_format_leaderboard_page_handles_unlinked_player():
    players = [Player(discord_id="2", mmr=700, riot_username=None, riot_tag=None)]
    text = format_leaderboard_page(players)
    assert "unlinked" in text
    assert "<@2>" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cog_leaderboard.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `leaderboard_views.py`**

```python
# src/val_bot/bot/views/leaderboard_views.py
import discord
from sqlalchemy import select
from val_bot.db.models import Player

PAGE_SIZE = 10

async def fetch_leaderboard_page(session, offset: int, limit: int = PAGE_SIZE) -> list[Player]:
    result = await session.execute(
        select(Player).order_by(Player.mmr.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars())

def format_leaderboard_page(players: list[Player]) -> str:
    lines = []
    for i, p in enumerate(players):
        name = f"{p.riot_username}#{p.riot_tag}" if p.riot_username else "(unlinked)"
        lines.append(f"**{i + 1}.** {name} (<@{p.discord_id}>) — {p.mmr} MMR")
    return "\n".join(lines) if lines else "No players yet."

class LeaderboardView(discord.ui.View):
    def __init__(self, session_factory, offset: int = 0):
        super().__init__(timeout=300)
        self.session_factory = session_factory
        self.offset = offset

    async def render(self) -> str:
        async with self.session_factory() as session:
            page = await fetch_leaderboard_page(session, self.offset)
        return format_leaderboard_page(page)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.offset = max(0, self.offset - PAGE_SIZE)
        await interaction.response.edit_message(content=await self.render(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.offset += PAGE_SIZE
        await interaction.response.edit_message(content=await self.render(), view=self)
```

- [ ] **Step 4: Implement `cogs/leaderboard.py`**

```python
# src/val_bot/bot/cogs/leaderboard.py
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.leaderboard_views import LeaderboardView

class LeaderboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Show the server MMR leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        view = LeaderboardView(self.bot.session_factory)
        content = await view.render()
        await interaction.response.send_message(content=content, view=view)

async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))
```

- [ ] **Step 5: Register the cog in `bot/main.py`**

```python
# in src/val_bot/bot/main.py, inside ValBot.setup_hook:
        from val_bot.bot.cogs.leaderboard import setup as setup_leaderboard
        await setup_leaderboard(self)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_cog_leaderboard.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/val_bot/bot/views/leaderboard_views.py src/val_bot/bot/cogs/leaderboard.py src/val_bot/bot/main.py tests/test_cog_leaderboard.py
git commit -m "feat: /leaderboard command with pagination"
```

---

### Task 16: `/match-history` Command + Expand Button

**Files:**
- Create: `src/val_bot/bot/views/history_views.py`
- Create: `src/val_bot/bot/cogs/history.py`
- Modify: `src/val_bot/bot/main.py` (register the cog)
- Test: `tests/test_cog_history.py`

**Interfaces:**
- Consumes: `Match`, `MatchParticipant` from `val_bot.db.models`.
- Produces: `async def fetch_recent_matches(session, discord_id: str, limit:
  int = 5) -> list[Match]`; `format_match_summary(match: Match, discord_id:
  str) -> str` (one player's line: win/loss, K/D/A, MMR delta);
  `format_full_match(match: Match) -> str` (all 10 participants).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cog_history.py
from datetime import datetime, timezone
from val_bot.bot.views.history_views import (
    fetch_recent_matches, format_match_summary, format_full_match,
)
from val_bot.db.models import Player, Match, MatchParticipant

async def _confirmed_match(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()
    match = Match(
        played_at=datetime.now(timezone.utc), map="Lotus", source="manual",
        status="confirmed", reported_by_discord_id="1", team_a_score=13, team_b_score=5,
    )
    match.participants.append(MatchParticipant(
        discord_id="1", team="A", kills=20, deaths=10, assists=5,
        won=True, mmr_before=700, mmr_after=720,
    ))
    match.participants.append(MatchParticipant(
        discord_id="2", team="B", kills=10, deaths=20, assists=2,
        won=False, mmr_before=700, mmr_after=685,
    ))
    db_session.add(match)
    await db_session.flush()
    return match

async def test_fetch_recent_matches_filters_by_player(db_session):
    match = await _confirmed_match(db_session)
    matches = await fetch_recent_matches(db_session, "1")
    assert [m.id for m in matches] == [match.id]
    matches_for_unrelated_player = await fetch_recent_matches(db_session, "999")
    assert matches_for_unrelated_player == []

async def test_format_match_summary_shows_result_and_delta(db_session):
    match = await _confirmed_match(db_session)
    text = format_match_summary(match, "1")
    assert "Win" in text
    assert "20/10/5" in text
    assert "+20" in text

async def test_format_full_match_shows_all_participants(db_session):
    match = await _confirmed_match(db_session)
    text = format_full_match(match)
    assert "<@1>" in text and "<@2>" in text
    assert "+20" in text and "-15" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cog_history.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `history_views.py`**

```python
# src/val_bot/bot/views/history_views.py
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
```

- [ ] **Step 4: Implement `cogs/history.py`**

```python
# src/val_bot/bot/cogs/history.py
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.bot.views.history_views import fetch_recent_matches, format_match_summary, FullMatchView

class HistoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="match-history", description="Show your (or someone else's) recent matches")
    async def match_history(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        discord_id = str(target.id)
        async with self.bot.session_factory() as session:
            matches = await fetch_recent_matches(session, discord_id)
            summaries = [format_match_summary(m, discord_id) for m in matches]

        if not matches:
            await interaction.response.send_message(
                f"{target.mention} has no confirmed match history yet.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "\n".join(summaries),
            view=FullMatchView(self.bot.session_factory, matches[0].id),
        )

async def setup(bot):
    await bot.add_cog(HistoryCog(bot))
```

- [ ] **Step 5: Register the cog in `bot/main.py`**

```python
# in src/val_bot/bot/main.py, inside ValBot.setup_hook:
        from val_bot.bot.cogs.history import setup as setup_history
        await setup_history(self)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_cog_history.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/val_bot/bot/views/history_views.py src/val_bot/bot/cogs/history.py src/val_bot/bot/main.py tests/test_cog_history.py
git commit -m "feat: /match-history command with expandable full-match view"
```

---

### Task 17: Admin Commands — `/void-match` and `/correct-match`

**Files:**
- Create: `src/val_bot/bot/cogs/admin.py`
- Modify: `src/val_bot/bot/main.py` (register the cog)
- Test: `tests/test_cog_admin.py`

**Interfaces:**
- Consumes: `void_match`, `correct_match` from `val_bot.db.match_service`.
- Produces: `/void-match match_id`, `/correct-match match_id
  [team_a_score] [team_b_score]`, both restricted via
  `@app_commands.checks.has_role("Admin")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cog_admin.py
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
from val_bot.bot.cogs.admin import void_match_callback, correct_match_callback
from val_bot.db.models import Player, Match
from val_bot.db.match_service import create_pending_match, confirm_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant

async def _confirmed_match_id(db_session):
    for d in ("1", "2", "3", "4"):
        db_session.add(Player(discord_id=d))
    await db_session.flush()
    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Pearl", source="manual",
        team_a_score=13, team_b_score=6, reported_by_discord_id="1",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="A"),
            NormalizedParticipant(discord_id="3", team="B"),
            NormalizedParticipant(discord_id="4", team="B"),
        ],
    )
    match = await create_pending_match(db_session, normalized)
    await confirm_match(db_session, match.id)
    await db_session.commit()
    return match.id

def _session_factory(db_session):
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return session_factory

async def test_void_match_callback_voids_and_responds(db_session):
    match_id = await _confirmed_match_id(db_session)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await void_match_callback(interaction, _session_factory(db_session), match_id)

    match = await db_session.get(Match, match_id)
    assert match.status == "voided"
    interaction.response.send_message.assert_awaited_once()

async def test_correct_match_callback_updates_scores(db_session):
    match_id = await _confirmed_match_id(db_session)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await correct_match_callback(
        interaction, _session_factory(db_session), match_id,
        team_a_score=13, team_b_score=11,
    )

    match = await db_session.get(Match, match_id)
    assert match.team_a_score == 13
    assert match.team_b_score == 11
    interaction.response.send_message.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cog_admin.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `cogs/admin.py`**

```python
# src/val_bot/bot/cogs/admin.py
import discord
from discord import app_commands
from discord.ext import commands
from val_bot.db.match_service import void_match, correct_match

async def void_match_callback(interaction, session_factory, match_id: int):
    async with session_factory() as session:
        await void_match(session, match_id)
        await session.commit()
    await interaction.response.send_message(
        f"Match #{match_id} voided. Downstream MMR has been recalculated.", ephemeral=True
    )

async def correct_match_callback(
    interaction, session_factory, match_id: int,
    team_a_score: int | None = None, team_b_score: int | None = None,
):
    async with session_factory() as session:
        await correct_match(session, match_id, team_a_score=team_a_score, team_b_score=team_b_score)
        await session.commit()
    await interaction.response.send_message(
        f"Match #{match_id} corrected. Downstream MMR has been recalculated.", ephemeral=True
    )

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="void-match", description="Void a match (Admin only)")
    @app_commands.checks.has_role("Admin")
    async def void_match_cmd(self, interaction: discord.Interaction, match_id: int):
        await void_match_callback(interaction, self.bot.session_factory, match_id)

    @app_commands.command(name="correct-match", description="Correct a match's scores (Admin only)")
    @app_commands.checks.has_role("Admin")
    async def correct_match_cmd(
        self, interaction: discord.Interaction, match_id: int,
        team_a_score: int | None = None, team_b_score: int | None = None,
    ):
        await correct_match_callback(
            interaction, self.bot.session_factory, match_id, team_a_score, team_b_score
        )

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
```

- [ ] **Step 4: Register the cog in `bot/main.py`**

```python
# in src/val_bot/bot/main.py, inside ValBot.setup_hook:
        from val_bot.bot.cogs.admin import setup as setup_admin
        await setup_admin(self)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cog_admin.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add src/val_bot/bot/cogs/admin.py src/val_bot/bot/main.py tests/test_cog_admin.py
git commit -m "feat: /void-match and /correct-match admin commands"
```

- [ ] **Step 7: Manual verification**

In your test Discord server, create an "Admin" role and assign it to
yourself. Confirm `/void-match` and `/correct-match` are usable, and confirm
a non-admin account gets Discord's built-in permission-denied response when
attempting them.

---

### Task 18: HenrikDev Source (Phase 2)

**Files:**
- Create: `src/val_bot/ingestion/henrikdev.py`
- Test: `tests/test_ingestion_henrikdev.py`

**Interfaces:**
- Consumes: `MatchDataSource`, `NormalizedMatch`, `NormalizedParticipant`
  from `val_bot.ingestion.base`; `Player` list (linked+consented) passed in
  at construction.
- Produces: `HenrikDevSource(api_key: str | None, consented_players:
  list[dict])` where each player dict is `{"discord_id": str, "puuid":
  str}`. `async def fetch_new_matches(self) -> list[NormalizedMatch]`
  queries each consented player's recent matches, filters to
  `provisioningFlowID == "CustomGame"`, keeps only matches where at least 6
  of the 10 participants are in `consented_players` (roster-match
  heuristic), and deduplicates by match ID before returning.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ingestion_henrikdev.py
import respx
import httpx
from val_bot.ingestion.henrikdev import HenrikDevSource

CONSENTED = [
    {"discord_id": "1", "puuid": "puuid-1"},
    {"discord_id": "2", "puuid": "puuid-2"},
]

MATCHLIST_RESPONSE = {
    "data": [{"metadata": {"matchid": "match-abc"}}],
}

MATCH_DETAILS_CUSTOM = {
    "data": {
        "metadata": {"matchid": "match-abc", "map": "Ascent", "mode": "Custom"},
        "players": [
            {"puuid": "puuid-1", "team_id": "Red", "stats": {"kills": 20, "deaths": 10, "assists": 5, "score": 250}},
            {"puuid": "puuid-2", "team_id": "Red", "stats": {"kills": 10, "deaths": 15, "assists": 3, "score": 150}},
            {"puuid": "puuid-3", "team_id": "Blue", "stats": {"kills": 12, "deaths": 12, "assists": 4, "score": 180}},
        ],
        "teams": {"red": {"has_won": True, "rounds_won": 13}, "blue": {"has_won": False, "rounds_won": 7}},
        "provisioningFlowID": "CustomGame",
    },
}

@respx.mock
async def test_fetch_new_matches_returns_normalized_custom_game():
    respx.get(url__regex=r".*/matches/.*/puuid-1$").mock(
        return_value=httpx.Response(200, json=MATCHLIST_RESPONSE)
    )
    respx.get(url__regex=r".*/matches/.*/puuid-2$").mock(
        return_value=httpx.Response(200, json=MATCHLIST_RESPONSE)
    )
    respx.get(url__regex=r".*/match/match-abc$").mock(
        return_value=httpx.Response(200, json=MATCH_DETAILS_CUSTOM)
    )

    source = HenrikDevSource(api_key=None, consented_players=CONSENTED)
    matches = await source.fetch_new_matches()

    assert len(matches) == 1
    match = matches[0]
    assert match.source == "henrikdev"
    assert match.external_match_id == "match-abc"
    assert match.map == "Ascent"
    p1 = next(p for p in match.participants if p.discord_id == "1")
    assert p1.team == "A"
    assert p1.combat_score == 250

@respx.mock
async def test_fetch_new_matches_skips_non_custom_provisioning():
    non_custom = {**MATCH_DETAILS_CUSTOM, "data": {**MATCH_DETAILS_CUSTOM["data"], "provisioningFlowID": "Matchmaking"}}
    respx.get(url__regex=r".*/matches/.*/puuid-1$").mock(
        return_value=httpx.Response(200, json=MATCHLIST_RESPONSE)
    )
    respx.get(url__regex=r".*/matches/.*/puuid-2$").mock(
        return_value=httpx.Response(200, json=MATCHLIST_RESPONSE)
    )
    respx.get(url__regex=r".*/match/match-abc$").mock(
        return_value=httpx.Response(200, json=non_custom)
    )

    source = HenrikDevSource(api_key=None, consented_players=CONSENTED)
    matches = await source.fetch_new_matches()
    assert matches == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingestion_henrikdev.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `henrikdev.py`**

```python
# src/val_bot/ingestion/henrikdev.py
from datetime import datetime, timezone
import httpx
from val_bot.ingestion.base import MatchDataSource, NormalizedMatch, NormalizedParticipant

BASE_URL = "https://api.henrikdev.xyz/valorant"

class HenrikDevSource(MatchDataSource):
    def __init__(self, api_key: str | None, consented_players: list[dict]):
        self.api_key = api_key
        self.consented_players = consented_players
        self._puuid_to_discord_id = {p["puuid"]: p["discord_id"] for p in consented_players}

    def _headers(self) -> dict:
        return {"Authorization": self.api_key} if self.api_key else {}

    async def _match_ids_for_puuid(self, client: httpx.AsyncClient, puuid: str) -> list[str]:
        resp = await client.get(f"{BASE_URL}/v4/by-puuid/matches/na/pc/{puuid}", headers=self._headers())
        resp.raise_for_status()
        return [m["metadata"]["matchid"] for m in resp.json().get("data", [])]

    async def _match_details(self, client: httpx.AsyncClient, match_id: str) -> dict:
        resp = await client.get(f"{BASE_URL}/v4/match/na/{match_id}", headers=self._headers())
        resp.raise_for_status()
        return resp.json()["data"]

    def _normalize(self, details: dict) -> NormalizedMatch | None:
        if details.get("provisioningFlowID") != "CustomGame":
            return None

        players = details["players"]
        known = [p for p in players if p["puuid"] in self._puuid_to_discord_id]
        if len(known) < 6:
            return None  # not enough of our roster in this match — likely not our pickup

        teams = details["teams"]
        red_won = teams["red"]["has_won"]

        participants = []
        for p in players:
            discord_id = self._puuid_to_discord_id.get(p["puuid"])
            if discord_id is None:
                continue
            team = "A" if p["team_id"] == "Red" else "B"
            stats = p["stats"]
            participants.append(NormalizedParticipant(
                discord_id=discord_id, team=team,
                kills=stats["kills"], deaths=stats["deaths"], assists=stats["assists"],
                combat_score=stats["score"],
            ))

        return NormalizedMatch(
            played_at=datetime.now(timezone.utc),
            map=details["metadata"]["map"],
            source="henrikdev",
            team_a_score=teams["red"]["rounds_won"],
            team_b_score=teams["blue"]["rounds_won"],
            reported_by_discord_id="auto",
            participants=participants,
            external_match_id=details["metadata"]["matchid"],
        )

    async def fetch_new_matches(self) -> list[NormalizedMatch]:
        results: dict[str, NormalizedMatch] = {}
        async with httpx.AsyncClient() as client:
            match_ids: set[str] = set()
            for player in self.consented_players:
                match_ids.update(await self._match_ids_for_puuid(client, player["puuid"]))

            for match_id in match_ids:
                details = await self._match_details(client, match_id)
                normalized = self._normalize(details)
                if normalized is not None:
                    results[normalized.external_match_id] = normalized

        return list(results.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingestion_henrikdev.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/val_bot/ingestion/henrikdev.py tests/test_ingestion_henrikdev.py
git commit -m "feat: HenrikDevSource for auto-detecting pickup matches"
```

---

### Task 19: `/sync-matches` Command

**Files:**
- Create: `src/val_bot/bot/cogs/sync.py`
- Modify: `src/val_bot/bot/main.py` (register the cog)
- Test: `tests/test_cog_sync.py`

**Interfaces:**
- Consumes: `HenrikDevSource` from `val_bot.ingestion.henrikdev`;
  `create_pending_match` from `val_bot.db.match_service`; `Player` from
  `val_bot.db.models`.
- Produces: `async def sync_matches(session, henrikdev_source_factory) ->
  list[int]` — returns the list of newly created pending `Match.id`s,
  skipping any `external_match_id` already present in the DB.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cog_sync.py
from unittest.mock import AsyncMock
from sqlalchemy import select
from val_bot.bot.cogs.sync import sync_matches
from val_bot.db.models import Player, Match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant
from datetime import datetime, timezone

def _fake_source(matches):
    source = AsyncMock()
    source.fetch_new_matches = AsyncMock(return_value=matches)
    return lambda: source

async def test_sync_matches_creates_pending_match_for_new_data(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()

    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Sunset", source="henrikdev",
        team_a_score=13, team_b_score=9, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
        external_match_id="ext-1",
    )
    ids = await sync_matches(db_session, _fake_source([normalized]))
    assert len(ids) == 1
    match = await db_session.get(Match, ids[0])
    assert match.status == "pending"
    assert match.external_match_id == "ext-1"

async def test_sync_matches_skips_already_ingested_external_id(db_session):
    for d in ("1", "2"):
        db_session.add(Player(discord_id=d, consented=True))
    await db_session.flush()

    normalized = NormalizedMatch(
        played_at=datetime.now(timezone.utc), map="Sunset", source="henrikdev",
        team_a_score=13, team_b_score=9, reported_by_discord_id="auto",
        participants=[
            NormalizedParticipant(discord_id="1", team="A"),
            NormalizedParticipant(discord_id="2", team="B"),
        ],
        external_match_id="ext-1",
    )
    first_ids = await sync_matches(db_session, _fake_source([normalized]))
    await db_session.commit()
    second_ids = await sync_matches(db_session, _fake_source([normalized]))
    assert len(first_ids) == 1
    assert second_ids == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cog_sync.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `cogs/sync.py`**

```python
# src/val_bot/bot/cogs/sync.py
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from val_bot.db.models import Player, Match
from val_bot.db.match_service import create_pending_match
from val_bot.ingestion.henrikdev import HenrikDevSource

async def sync_matches(session, henrikdev_source_factory) -> list[int]:
    source = henrikdev_source_factory()
    normalized_matches = await source.fetch_new_matches()

    existing = await session.execute(
        select(Match.external_match_id).where(Match.external_match_id.isnot(None))
    )
    existing_ids = {row[0] for row in existing}

    created_ids = []
    for normalized in normalized_matches:
        if normalized.external_match_id in existing_ids:
            continue
        match = await create_pending_match(session, normalized)
        created_ids.append(match.id)
    return created_ids

class SyncCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sync-matches", description="Check HenrikDev for new pickup matches (Admin only)")
    @app_commands.checks.has_role("Admin")
    async def sync_matches_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.session_factory() as session:
            result = await session.execute(select(Player).where(Player.consented.is_(True)))
            consented = [
                {"discord_id": p.discord_id, "puuid": p.riot_username}  # puuid populated once /link stores it (see note below)
                for p in result.scalars() if p.riot_username
            ]

            def source_factory():
                return HenrikDevSource(self.bot.henrikdev_api_key, consented)

            new_ids = await sync_matches(session, source_factory)
            await session.commit()

        if not new_ids:
            await interaction.followup.send("No new matches found.")
        else:
            await interaction.followup.send(
                f"Found {len(new_ids)} new match(es): {', '.join(f'#{i}' for i in new_ids)}. "
                "Each needs confirmation before MMR applies — check the pending matches."
            )

async def setup(bot):
    await bot.add_cog(SyncCog(bot))
```

Note: this task stores the player's *puuid* using the `riot_username` field
as a placeholder lookup key, which is a simplification — resolving a
Riot `username#tag` to a `puuid` requires one additional HenrikDev
account-lookup call. That resolution call is deliberately out of scope for
this plan (flagged here rather than silently glossed over): add a `puuid`
column to `Player` and populate it from `/link` via HenrikDev's account
endpoint before wiring `/sync-matches` into real production use.

- [ ] **Step 4: Register the cog in `bot/main.py`**

```python
# in src/val_bot/bot/main.py, inside ValBot.setup_hook:
        from val_bot.bot.cogs.sync import setup as setup_sync
        await setup_sync(self)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cog_sync.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add src/val_bot/bot/cogs/sync.py src/val_bot/bot/main.py tests/test_cog_sync.py
git commit -m "feat: /sync-matches command for HenrikDev auto-ingestion"
```

---

### Task 20: Docker Finalization + README

**Files:**
- Modify: `docker-compose.yml` (Alembic migration on startup)
- Create: `README.md`

**Interfaces:** None — this task wires up the deployment path so the WSL
dev environment and the Windows laptop run the identical container.

- [ ] **Step 1: Add a migration step to the container startup**

```dockerfile
# in Dockerfile, replace the CMD line with:
CMD ["sh", "-c", "alembic upgrade head && python -m val_bot.bot.main"]
```

- [ ] **Step 2: Write `README.md`**

```markdown
# Val Pick Ups Bot

## Setup (either machine — WSL dev or the Windows laptop running Docker Desktop)

1. Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN` (from
   https://discord.com/developers/applications) and, once you have one,
   `HENRIKDEV_API_KEY`.
2. `docker compose up --build`

That's the entire deployment step on both machines — build once on WSL to
develop, then `docker compose up --build` again on the Windows laptop with
Docker Desktop (WSL2 backend) to run it for real. `bot_data` is a named
Docker volume, so the SQLite file survives container restarts/rebuilds.

## Local development (outside Docker, for fast iteration)

```bash
pip install -e . && pip install -r requirements.txt
export $(cat .env | xargs)
alembic upgrade head
python -m val_bot.bot.main
```

## Tests

```bash
pytest -v
```

## Commands

- `/link <riot_username> <riot_tag>` — link your Discord account to your Riot ID
- `/mmr [@user]` — check MMR and rank
- `/leaderboard` — server leaderboard
- `/report-match` — report a pickup match result
- `/match-history [@user]` — recent matches, expandable to the full scoreboard
- `/void-match <match_id>`, `/correct-match <match_id>` — Admin role only
- `/sync-matches` — Admin role only; pulls new custom games from HenrikDev
  for linked, consented players
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml README.md
git commit -m "docs: README and container migration-on-startup"
```

---

## Self-Review Notes

- **Spec coverage:** architecture (Task 1, 10), data model (Task 2), rating
  algorithm (Task 3, 5), rank tiers (Task 4), `/link`/consent (Task 11),
  `/report-match` easiest-path flow + confirm/dispute (Task 12-13), `/mmr`
  (Task 14), `/leaderboard` with the `RiotUsername (@mention)` format (Task
  15), `/match-history` with expandable full-match view (Task 16),
  `/void-match`/`/correct-match` with full recompute cascade (Task 9, 17),
  HenrikDev Phase 2 ingestion with `CustomGame` filtering and roster-match
  heuristic (Task 18), `/sync-matches` wiring it into the same
  confirm/dispute pipeline as manual reports (Task 19), Docker portability
  between WSL and the Windows laptop (Task 1, 20) — all covered.
- **Known scope gap, called out explicitly rather than hidden:** Task 19's
  `/sync-matches` needs a real `puuid` resolution step (Riot `username#tag`
  → `puuid` via HenrikDev's account lookup) before it's production-ready;
  the plan flags this inline rather than silently shipping a broken lookup.
- **Type consistency:** `NormalizedMatch`/`NormalizedParticipant` (Task 6)
  are used identically by `ManualEntrySource` (Task 7) and `HenrikDevSource`
  (Task 18); `ParticipantInput`/`rate_match` (Task 5) is the sole rating
  entrypoint used by both `confirm_match` and `recompute_from` (Tasks 8-9);
  `session_factory` callable signature is consistent across every cog.
