# Val Pick Ups MMR/Leaderboard Discord Bot — Design

## Context

A Discord server runs 10-man Valorant pickup customs: queue → deathmatch to pick
2 captains → draft → custom match → results reported manually today. This spec
covers the design for a bot that ingests match results, computes a persistent
per-player MMR, maps it to visible rank tiers, and exposes it via Discord
commands. No implementation yet — this is the approved design to be turned into
an implementation plan next.

## Constraints

- **Budget: $0.** No paid hosting, no credit card on file.
- **Hosting**: a Windows laptop the user will run 24/7. Development happens on
  a separate WSL machine. The setup must be trivially transferable between the
  two (build once, run anywhere via Docker).
- **Scale**: a small, tight-knit pool (~20-40 regulars), pickups run most days.
  Ratings should converge fast per player since attendance is frequent.
- **Data source**: no official Riot API access yet (requires a production key
  + RSO integration, weeks-long review, not guaranteed). Manual reporting is
  the only source available on day one.

## Architecture

Single Python process running `discord.py`, SQLite (via SQLAlchemy) on a
mounted volume, one Docker container. `docker compose up` is the entire
deployment step on either machine — no environment drift between WSL dev and
the Windows laptop (Docker Desktop, WSL2 backend).

No web dashboard. Discord is the only UI: slash commands, buttons, modals, and
select menus cover both player-facing (report, view) and moderator-facing
(void, correct) needs. A public web leaderboard would require an
internet-reachable process running continuously on the laptop (e.g. a
Cloudflare Tunnel) for a feature Discord embeds already cover — not worth the
extra always-on surface area for a server that already lives in Discord. If a
public flex-page or history graphs are wanted later, `rating/` and
`ingestion/` are already isolated from the Discord layer, so it's additive,
not a rearchitecture.

Module boundaries:

- **`bot/`** — slash commands, buttons, modals, select menus, embeds. All
  Discord-facing UI.
- **`ingestion/`** — a `MatchDataSource` interface with one implementation
  today (`ManualEntrySource`) and two designed-for-later (`HenrikDevSource`,
  `RiotOfficialSource`), swapped via config. Normalizes whatever the source
  gives it into the internal match/participant schema.
- **`rating/`** — pure functions, no I/O. Given a match's participants and
  their current ratings, returns new ratings. Independently unit-testable,
  safe to re-tune without touching Discord or DB code.
- **`db/`** — SQLAlchemy models + Alembic migrations.

## Data Model

- **`players`** — `discord_id` (PK), `riot_username`, `riot_tag`, `consented`
  (bool, set by `/link`), `mmr` (current), `games_played`, `created_at`.
  Unlinked players can still be reported and rated; they just display without
  a Riot name until they link.
- **`matches`** — `id` (PK), `played_at`, `map`, `source`
  (`manual`/`henrikdev`/`riot`), `status` (`confirmed`/`voided`),
  `reported_by_discord_id`, `team_a_score`, `team_b_score`,
  `external_match_id` (nullable — lets API-sourced matches dedupe against a
  manual re-entry of the same game later).
- **`match_participants`** — `match_id` (FK), `discord_id` (FK), `team`
  (A/B), `kills`, `deaths`, `assists`, `combat_score` (nullable — not every
  source/report provides it), `won` (bool), `mmr_before`, `mmr_after`.

No separate MMR history table: `match_participants.mmr_before/after`, joined
against `matches.played_at`, already reconstructs full per-player history for
the match-report and expanded full-match views. No stored "captain" entity
either — it's an artifact of team formation the rating engine and UI never
need to query independently. Both were dropped per YAGNI; add them later only
if a real need for them shows up.

## Rating Algorithm

**Elo with a performance-adjusted K-factor**, chosen over Glicko-2 and
TrueSkill/TrueSkill2:

- TrueSkill2 folds individual performance into its Bayesian model, which
  sounds ideal, but has no maintained open-source implementation (only
  TrueSkill1, win/loss-only) — implementing it means reproducing research-paper
  factor-graph math from scratch. Its core strength, inferring skill for
  arbitrarily-matched teams, also isn't the bottleneck here since teams come
  from a human draft, not algorithmic matchmaking.
- Glicko-2 elegantly models per-player confidence (ratings deviation) for
  fast convergence on new/infrequent players, but isn't natively
  performance-aware — it would need the same performance-multiplier bolted on
  that Elo does anyway, on top of a harder-to-reason-about base (volatility
  updates require iterative solving). Its main advantage, uncertainty-aware
  matchmaking, doesn't apply since this isn't used to matchmake.
- Elo is a single transparent formula, no iterative solvers, and expresses
  "win/loss primary, performance as modifier" directly.

Per player per match:

1. Team-average Elo expectation: `E_i = 1 / (1 + 10^((opp_team_avg -
   own_team_avg) / 400))`.
2. Base delta: `K_i * (actual_score - E_i)`, `actual_score` = 1/0 for win/loss.
3. Performance modifier: a multiplier in `[0.5, 1.5]` derived from the
   player's combat score (or KDA, if that's all the source/report provides)
   relative to the match average. Defaults to `1.0` when no stats were
   submitted (the default "quick report" path — see Command Surface). Can
   scale a delta up or down but never flip a win into a loss or vice versa.
4. Final delta = base delta × performance modifier, capped at **±40 MMR per
   match**.
5. **Provisional K-factor**: `K=40` for a player's first 10 games, `K=20`
   after. New players converge to their real level fast; veterans move
   slowly and stably.
6. **Soft floor**: on a 3+ game losing streak, loss magnitude is dampened by
   ~30-40%, so a bad stretch doesn't crater a rank.

All constants above (`K` values, the `±40` cap, the `[0.5, 1.5]` modifier
band, the streak-damping percentage) are named constants in `rating/`, not
hardcoded inline — expect to retune them after watching a few weeks of real
play.

### Correcting a past match

Because Elo is sequential, correcting an old match's stats invalidates every
subsequent match's ratings for the players involved — and transitively, for
anyone who played *against* or *with* them in any later match, since team
averages depend on ratings at match time. `/correct-match` therefore triggers
a **full recompute**: edit the target match's stored data, then replay every
match chronologically from that match forward to now, recalculating
`mmr_before`/`mmr_after` for all participants along the way. At this scale
(a small pool, a bounded match history) this replay is cheap — no performance
concern, just worth documenting since the ripple effect isn't obvious from
the command name alone.

## Rank Tiers

Real Valorant's Iron→Radiant has 3 sub-divisions per tier (27 buckets total)
and gates Radiant by regional percentile (top 500). Neither fits a 20-40
person pool — sub-divisions would average ~1 person each, and a percentile
gate would leave Radiant permanently empty. So: flat tiers, no sub-divisions,
Radiant as a fixed threshold instead of a percentile cutoff.

Gaps are intentionally tight (75 MMR per tier, vs. an initial 150 MMR draft)
so that with a ±40-per-match cap, one strong match can visibly move a
player's rank — climbing should feel earned but achievable on a small server,
not grindy.

| Tier | MMR |
|---|---|
| Iron | < 500 |
| Bronze | 500-574 |
| Silver | 575-649 |
| Gold | 650-724 |
| Platinum | 725-799 |
| Diamond | 800-874 |
| Ascendant | 875-949 |
| Immortal | 950-1099 |
| Radiant | 1100+ |

Starting MMR: **700** (mid-Gold) — new players start as an average, unknown
quantity, and the provisional K-factor moves them toward their true level
quickly over their first 10 games.

## Command Surface

All Discord-native — buttons, modals, and select menus, never raw
argument-typing:

- **`/link <riot_username> <riot_tag>`** — links Discord↔Riot ID, sets
  `consented=true`. Required to show a Riot name on the leaderboard; also the
  hook Phase 2/3 ingestion uses to know who's opted in to automated pulls.
- **`/mmr [@user]`** — current MMR, tier, recent form (last 5 W/L).
- **`/leaderboard`** — paginated embed, rows formatted as `RiotUsername
  (@DiscordMention)`, sorted by MMR, with Next/Prev buttons.
- **`/report-match`** — the default, easiest path: one modal (map, Team A
  score, Team B score) → two select menus to pick each team's 5 players from
  the server roster. No stat entry required. An optional "Add stats" button
  is offered afterward for anyone who wants the performance modifier to be
  more than the 1.0× default. Submission requires a confirm click from the
  opposing side (or a moderator) before MMR is applied, to prevent
  unilateral false reports.
- **`/match-history [@user]`** — recent matches as embeds; each has a "View
  Full Match" button expanding to show all 10 participants' K/D/A and MMR
  delta for that match.
- **`/void-match`**, **`/correct-match`** — role-gated to a
  Captain/Admin Discord role. `/correct-match` triggers the full recompute
  cascade described above.

## Data Ingestion Phasing

The `MatchDataSource` interface makes each phase a swap-in, not a rewrite.
The `consented` flag set by `/link` is the through-line connecting all three
phases — it's what gates whether a linked Riot ID is ever used for anything
beyond display.

1. **Phase 1 (build now) — `ManualEntrySource`.** Backs `/report-match`
   directly. Zero external dependency.
2. **Phase 2 (later) — `HenrikDevSource`.** An actively-maintained unofficial
   API (v4.5.0, 163 commits at time of writing); no key required for basic
   use (30 req/min by IP, 90 req/min with a free key from their Discord),
   comfortably covering a 10-man community. It exposes match details
   filterable by `provisioningFlowID == "CustomGame"`, so pickups are
   distinguishable from ranked/unrated play. It only auto-pulls for
   linked+consented players, matched against the server's known roster to
   detect "this was one of our pickups" — and still runs through the same
   confirm/dispute step before finalizing, since that auto-detection isn't
   perfectly reliable. Their terms discourage large analytics projects
   *without user consent* — the `consented` flag exists partly to respect
   that, not just as prep for Phase 3.
3. **Phase 3 (later, optional) — `RiotOfficialSource`.** Same interface,
   swapped in once a production key is granted. RSO login replaces `/link`
   as the formal (OAuth) consent mechanism instead of a self-asserted flag.
   Riot's docs list Discord bots with community leaderboards as an approved
   use case category.

## Open Items For The Implementation Plan

None outstanding — every design question raised during brainstorming was
resolved above. The next step is `writing-plans` to turn this into a
step-by-step implementation plan.
