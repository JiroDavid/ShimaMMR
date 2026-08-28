# Val Pick Ups Bot

## Setup (either machine — WSL dev or the Windows laptop running Docker Desktop)

1. Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN` (from
   https://discord.com/developers/applications) and, once you have one,
   `HENRIKDEV_API_KEY`.
2. `docker compose up --build`

That's the entire deployment step on both machines — build once on WSL to
develop, then `docker compose up --build` again on the Windows laptop with
Docker Desktop (WSL2 backend) to run it for real. `bot.db` is bind-mounted
into the container (not a Docker-managed volume), so it's the exact same
file that's tracked in this git repo.

### Moving between machines

`bot.db` is committed to this repo so switching machines is just a normal
`git push` / `git pull` — the rankings, match history, and links travel
with the code. **SQLite files don't merge.** The bot must only run in ONE
place at a time:

1. Stop the bot on the machine you're leaving (`docker compose down`, or
   Ctrl-C for local dev).
2. `git add bot.db && git commit -m "..." && git push` from that machine.
3. `git pull` on the other machine, *then* start the bot there.

If both machines ever run the bot at the same time against their own
local `bot.db` and both get committed, whichever pushes second will
silently overwrite the other's data on the next pull — git treats `bot.db`
as an ordinary binary file, so there's no merge conflict to warn you.

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
