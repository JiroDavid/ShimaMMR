<div align="center">
  <img src="assets/logo.svg" width="160" height="160" alt="ShimaMMR"/>

  <h1>ShimaMMR</h1>

  <p>A Discord bot that turns manually-tallied Valorant pickups into a real MMR-tracked leaderboard</p>

  [![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
  [![discord.py](https://img.shields.io/badge/discord.py-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discordpy.readthedocs.io)
  [![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org)
  [![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
  [![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com)
  [![HenrikDev API](https://img.shields.io/badge/HenrikDev%20API-FF4655?style=for-the-badge&logo=riotgames&logoColor=white)](https://docs.henrikdev.xyz)

</div>

---

Elo-based MMR for 10-man Valorant pickup customs, with a performance-adjusted
K-factor, rank tiers, and a real leaderboard. Matches can be reported
manually or auto-detected from the real Valorant API — either way, nothing
touches MMR until a participant (or admin) confirms it.

## Setup (either machine — WSL dev or the Windows laptop running Docker Desktop)

1. Copy `.env.example` to `.env` and fill in:
   - `DISCORD_TOKEN` — from https://discord.com/developers/applications
   - `HENRIKDEV_API_KEY` — a free "Basic" key from
     https://api.henrikdev.xyz/dashboard/ (required — the API 401s without one)
2. `docker compose up --build`

That's the entire deployment step on both machines — build once on WSL to
develop, then `docker compose up --build` again on the Windows laptop with
Docker Desktop (WSL2 backend) to run it for real. `bot.db` is bind-mounted
into the container (not a Docker-managed volume), so it's the exact same
file that's tracked in this git repo.

### Windows laptop setup (full walkthrough)

**Manual, one-time, needs a human at the keyboard** (Claude Code can't
click through a GUI installer or generate your API credentials for you):

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
   and make sure the **WSL2 backend** is enabled (Settings → General → "Use
   the WSL 2 based engine"). Docker Desktop will prompt to install WSL2 on
   first run if it isn't already there. **Launch Docker Desktop and leave it
   running** — `docker compose` commands fail if the Docker Desktop app
   itself isn't open.
2. Have these two values ready (or gather them now): your `DISCORD_TOKEN`
   (from https://discord.com/developers/applications) and a free HenrikDev
   "Basic" `HENRIKDEV_API_KEY` (from https://api.henrikdev.xyz/dashboard/).

**From here, hand this repo to Claude Code (or run it yourself) — every
step below is just terminal commands:**

1. Clone the repo (skip if it's already cloned — `git pull` instead):
   ```bash
   git clone git@github.com:JiroDavid/ShimaMMR.git
   cd ShimaMMR
   ```
2. Create `.env` from the template and fill in the three values from above:
   ```bash
   cp .env.example .env
   ```
   (`.env` is gitignored — `git pull` never brings this file down, it has
   to be created and filled in on every new machine.)
3. Build and start the bot, detached so it keeps running after the
   terminal closes:
   ```bash
   docker compose up -d --build
   ```
4. Verify it actually connected to Discord:
   ```bash
   docker compose logs bot
   ```
   Look for `discord.gateway: Shard ID None has connected to Gateway` with
   no error traceback after it. If `/ping` (or `v!ping`) doesn't get a
   `pong` back in Discord within a few seconds, something's wrong — check
   the logs above for the actual error.

It'll restart automatically on reboot or crash per `docker-compose.yml`'s
`restart: unless-stopped`, so this is a one-time setup, not something to
repeat every time the laptop turns on.

From then on, updating the laptop to the latest code/data is just:
```bash
docker compose down
git pull
docker compose up -d --build
```

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

Every command below works as both a slash command (`/whatever`) and a
`v!whatever` text command.

- `/link <riot_username> <riot_tag>` — link your Discord account to your Riot ID.
  Resolves your account against Riot's servers to enable automatic match
  detection; still succeeds (with a warning) if that lookup fails, e.g. a typo.
- `/mmr [@user]` — check MMR and rank
- `/leaderboard` — server leaderboard
- `/report-match` — report a pickup match result
- `/match-history [@user]` — recent matches, expandable to the full scoreboard
- `/void-match <match_id>`, `/correct-match <match_id>` — admin only
  (real Discord "Administrator" permission, not a specific role name)
- `/sync-matches [@user]` — admin only; checks HenrikDev for new custom
  games right now (run it right after a pickup finishes). Checks everyone
  linked by default, or pass a player to check just their recent matches
  instead — much faster and uses far less API quota, and still detects the
  whole match since one player's history includes the full roster. A
  detected match still needs a participant (or admin) to hit Confirm before
  MMR applies — same as a manually reported match. If a detected match
  includes players who aren't recognized, it posts a prompt asking who they
  are on Discord before the match can be created.
- `/reannounce-match <match_id>` — admin only; re-posts the confirm/dispute
  prompt for a match that's already saved as pending but never got a
  working announcement (e.g. a transient Discord API error).
