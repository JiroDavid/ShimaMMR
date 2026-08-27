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
