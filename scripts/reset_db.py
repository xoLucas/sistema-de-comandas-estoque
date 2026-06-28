#!/usr/bin/env python3
"""Reset the PostgreSQL database used by the Lads Beer app.

Drops all tables and optionally re-runs the seed routine.
Useful for clean local tests.
"""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import engine, Base, async_session
from app.core.seed import run_seed


async def reset_database(run_seed_after: bool = True) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("All tables dropped.")

    if run_seed_after:
        await run_seed()
        print("Seed completed.")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset the Lads Beer database for clean tests."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required flag to confirm database reset.",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Drop tables without re-running seed.",
    )
    args = parser.parse_args()

    if not args.force:
        print("WARNING: This will delete all data in the database.")
        print("Run again with --force to proceed.")
        return 1

    await reset_database(run_seed_after=not args.no_seed)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
