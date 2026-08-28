"""One-time backfill of match_history_new.csv (match_10..match_12) into the
live bot.db, following on from scripts/import_csv_history.py's match_1..9
import.

Order: match_id order. match_10 and match_12 have real dates in the CSV
(2026-08-23 / 2026-08-26); match_11's date was cut off in the source
screenshot, so it's synthesized as 2026-08-24 - strictly between the other
two, per the 2026-08-28 decision to trust match_id order over the CSV's
partial `date` column (same approach as the original import).

Handle-to-Discord-ID mapping is copied from import_csv_history.py's frozen
snapshot (see that file for how it was resolved) plus one addition: these
rows use a blank discord_handle with riot_name "keep virginity" for the
same player as match_7/match_8 in the original CSV, which resolved that
riot_name to "@ishox" - reused here rather than re-resolved.
"""
import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from val_bot.config import Config
from val_bot.db.session import make_engine, make_session_factory
from val_bot.db.models import Player
from val_bot.db.match_service import create_pending_match, confirm_match
from val_bot.ingestion.base import NormalizedMatch, NormalizedParticipant

CSV_PATH = Path(__file__).resolve().parent.parent / "match_history_new.csv"

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
    "@555stephen": "186510359853662208",
}

# riot_name -> handle, for rows with a blank discord_handle. Only "keep
# virginity" (-> @ishox) has shown up so far; see module docstring.
RIOT_NAME_TO_HANDLE = {
    "keep virginity": "@ishox",
}

TEAM_LABEL_TO_AB = {"team1": "A", "team2": "B", "teama": "A", "teamb": "B"}

MATCH_DATES = {
    "match_10": datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc),
    "match_11": datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc),
    "match_12": datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc),
}


def _int(value: str) -> int:
    value = (value or "").strip()
    return int(value) if value else 0


def _discord_id_for(row: dict) -> str:
    handle = row["discord_handle"].strip().lower()
    if not handle:
        handle = RIOT_NAME_TO_HANDLE[row["riot_name"].strip()]
    return HANDLE_TO_DISCORD_ID[handle]


def load_matches() -> list[tuple[str, NormalizedMatch]]:
    rows = list(csv.DictReader(open(CSV_PATH)))
    by_match: dict[str, list[dict]] = {}
    for row in rows:
        by_match.setdefault(row["match_id"], []).append(row)

    match_ids_in_order = sorted(by_match, key=lambda m: int(m.split("_")[1]))

    matches = []
    for match_id in match_ids_in_order:
        csv_rows = by_match[match_id]

        participants = []
        team_scores: dict[str, int] = {}
        for row in csv_rows:
            discord_id = _discord_id_for(row)
            team = TEAM_LABEL_TO_AB[row["team"].strip().lower().replace(" ", "")]
            if team not in team_scores:
                won, lost = _team_score_pair(row["result"])
                # result text is from this row's own perspective (Win/Loss),
                # so its first number is always this row's team's score.
                team_scores[team] = won
                other = "B" if team == "A" else "A"
                team_scores.setdefault(other, lost)
            participants.append(NormalizedParticipant(
                discord_id=discord_id,
                team=team,
                kills=_int(row["kills"]),
                deaths=_int(row["deaths"]),
                assists=_int(row["assists"]),
                combat_score=int(row["acs"]) if row["acs"].strip() else None,
            ))

        matches.append((match_id, NormalizedMatch(
            played_at=MATCH_DATES[match_id],
            map=csv_rows[0]["map"].split(" (")[0].strip() or "unknown",
            source="manual",
            team_a_score=team_scores["A"],
            team_b_score=team_scores["B"],
            reported_by_discord_id="csv-import",
            participants=participants,
        )))
    return matches


def _team_score_pair(result_text: str) -> tuple[int, int]:
    import re
    rounds_match = re.search(r"(\d+)-(\d+)\s*rounds", result_text)
    if rounds_match:
        return int(rounds_match.group(1)), int(rounds_match.group(2))
    plain_match = re.search(r"(\d+)-(\d+)", result_text)
    if plain_match:
        return int(plain_match.group(1)), int(plain_match.group(2))
    raise ValueError(f"could not parse a score pair out of {result_text!r}")


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
