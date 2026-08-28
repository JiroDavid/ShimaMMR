"""One-time backfill of match_history.csv into the live bot.db.

Order of matches: match_id order (match_1..match_9), per the 2026-08-28
decision to trust match_id over the CSV's partial/contradictory `date`
column. `played_at` is therefore synthesized as strictly-increasing dates
in that order rather than taken from the CSV.

Discord handles were resolved to real Discord IDs by querying the live
guild's member list via the bot token (see session notes) - the mapping
below is a frozen snapshot of that lookup, not something to regenerate
automatically here.

Excluded rows (no resolvable Discord ID, cannot participate in the DB's
FK-constrained match_participants table):
  - match_1, match_2: riot_name "ADG konjutsu", notes "BANNED - exclude
    from bot"
  - match_5: riot_name "gabbo", notes "LEFT SERVER - no discord handle
    available"
"""
import asyncio
import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from val_bot.config import Config
from val_bot.db.session import make_engine, make_session_factory
from val_bot.db.models import Player
from val_bot.db.match_service import create_pending_match, confirm_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant

CSV_PATH = Path(__file__).resolve().parent.parent / "match_history.csv"

HANDLE_TO_DISCORD_ID = {
    "@.marz7.": "631941327289843732",
    "@4atomsk": "292457832937160704",
    "@jiroshima": "1018627087294279732",
    "@awde": "320176509048324098",
    "@bearably": "478993365262794754",
    "@enx0o": "899667601427415081",
    "@faxz__": "733978269962993696",
    "@ishox": "227043177389883393",
    "@keosxp": "133309049084182529",
    "@luvnochi": "1480207442489905376",
    "@marlsa": "646488865338818593",
    "@nope_yep_": "598536244175306753",
    "@noteyxo": "354990884225286156",
    "@paxeee": "398932304178708482",
    "@randmeow": "1342669048294539357",
    "@skullmanjack.": "1343684532628488232",
    "@streethunter": "367405221833342976",
    "@szbread_19": "1138115382562017422",
    "@tia0_o": "568478923688640530",
    "@travztmr": "440929871716286474",
    "@uvz": "635922467881484318",
    "@vixnvlr": "1260404887636938847",
    "@wordsbynoble": "834578755749806090",
    # CSV has a typo ("@555stephen"); the real Discord username is
    # "555tephen" (display name "xilly", matching this row's riot_name).
    "@555stephen": "186510359853662208",
}

TEAM_LABEL_TO_AB = {"team1": "A", "team2": "B", "teama": "A", "teamb": "B"}

EXCLUDE_NOTE_MARKERS = ("BANNED", "LEFT SERVER")

BASE_DATE = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


def _int(value: str) -> int:
    value = (value or "").strip()
    return int(value) if value else 0


def _team_score_pair(result_text: str) -> tuple[int, int]:
    rounds_match = re.search(r"(\d+)-(\d+)\s*rounds", result_text)
    if rounds_match:
        return int(rounds_match.group(1)), int(rounds_match.group(2))
    plain_match = re.search(r"(\d+)-(\d+)", result_text)
    if plain_match:
        return int(plain_match.group(1)), int(plain_match.group(2))
    raise ValueError(f"could not parse a score pair out of {result_text!r}")


def load_matches() -> list[tuple[str, NormalizedMatch]]:
    rows = list(csv.DictReader(open(CSV_PATH)))
    by_match: dict[str, list[dict]] = {}
    for row in rows:
        by_match.setdefault(row["match_id"], []).append(row)

    match_ids_in_order = sorted(by_match, key=lambda m: int(m.split("_")[1]))

    matches = []
    for index, match_id in enumerate(match_ids_in_order):
        csv_rows = by_match[match_id]
        kept_rows = [r for r in csv_rows if not any(m in r["notes"] for m in EXCLUDE_NOTE_MARKERS)]

        participants = []
        team_a_result_text = None
        for row in kept_rows:
            handle = row["discord_handle"].strip().lower()
            discord_id = HANDLE_TO_DISCORD_ID[handle]
            team = TEAM_LABEL_TO_AB[row["team"].strip().lower().replace(" ", "")]
            if team == "A":
                team_a_result_text = row["result"]
            participants.append(NormalizedParticipant(
                discord_id=discord_id,
                team=team,
                kills=_int(row["kills"]),
                deaths=_int(row["deaths"]),
                assists=_int(row["assists"]),
                combat_score=int(row["acs"]) if row["acs"].strip() else None,
            ))

        team_a_score, team_b_score = _team_score_pair(team_a_result_text)
        played_at = BASE_DATE + timedelta(days=index)

        matches.append((match_id, NormalizedMatch(
            played_at=played_at,
            map=kept_rows[0]["map"].strip() or "unknown",
            source="manual",
            team_a_score=team_a_score,
            team_b_score=team_b_score,
            reported_by_discord_id="csv-import",
            participants=participants,
        )))
    return matches


async def main():
    config = Config.from_env()
    engine = make_engine(config.db_path)
    session_factory = make_session_factory(engine)

    matches = load_matches()

    async with session_factory() as session:
        known_ids = set((await session.execute(select(Player.discord_id))).scalars().all())

        all_discord_ids = {p.discord_id for _, m in matches for p in m.participants}
        for discord_id in sorted(all_discord_ids - known_ids):
            session.add(Player(discord_id=discord_id))
        await session.flush()

        for csv_match_id, normalized in matches:
            pending = await create_pending_match(session, normalized)
            confirmed = await confirm_match(session, pending.id)
            print(
                f"{csv_match_id} -> db match #{confirmed.id}  "
                f"{normalized.map}  {normalized.team_a_score}-{normalized.team_b_score}  "
                f"{normalized.played_at.date()}  ({len(normalized.participants)} players)"
            )

        await session.commit()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
