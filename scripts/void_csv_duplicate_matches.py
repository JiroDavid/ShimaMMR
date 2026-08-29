"""One-time cleanup: void matches 1,2,3,4,5,6,7,8,9,11.

The original CSV backfill (match_1..9) turned out to duplicate matches
later detected properly via HenrikDev sync - confirmed by identical
kills/deaths/assists per player across the pairs (3,18) (4,17) (5,14)
(6,23) (7,12) (8,20) (9,16), plus (11,13) from the second CSV import
duplicating match #13. Matches 1 and 2 have no identified duplicate but
share the same "unknown" map / garbage kill-count-as-score data quality
issue as the rest of that batch, so they're voided too per the
2026-08-29 decision to distrust the whole batch rather than salvage them.

Only matches #10 (Ascent) and #12 (Bind) from the CSV imports survive -
neither turned out to be duplicated.
"""
import asyncio
from val_bot.config import Config
from val_bot.db.session import make_engine, make_session_factory
from val_bot.db.match_service import void_match
from val_bot.db.models import Match

MATCH_IDS_TO_VOID = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]


async def main():
    config = Config.from_env()
    engine = make_engine(config.db_path)
    session_factory = make_session_factory(engine)

    async with session_factory() as session:
        for match_id in MATCH_IDS_TO_VOID:
            match = await session.get(Match, match_id)
            if match is None:
                print(f"match #{match_id} not found, skipping")
                continue
            if match.status == "voided":
                print(f"match #{match_id} already voided, skipping")
                continue
            await void_match(session, match_id)
            print(f"voided match #{match_id} ({match.map})")
        await session.commit()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
