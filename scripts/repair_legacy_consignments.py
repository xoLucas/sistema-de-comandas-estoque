#!/usr/bin/env python3
"""Repair legacy consignments whose product_total was left at zero.

Fills product_total/service_total and re-splits the already recorded payments
(product first) so their billed product is counted again. Idempotent and safe to
run multiple times. Use --preview to see how many consignments would change
without committing anything.
"""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session, engine
import app.core.seed  # noqa: F401  (registers every ORM model)
from app.services.financial_migration_service import (
    _repair_legacy_consignment_product_totals,
)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair legacy consignments with product_total = 0."
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Count affected consignments without committing changes.",
    )
    args = parser.parse_args()

    async with async_session() as session:
        repaired = await _repair_legacy_consignment_product_totals(session)
        if args.preview:
            await session.rollback()
            print(
                f"Preview: {repaired} consignment(s) would be repaired. "
                "No changes committed."
            )
        else:
            await session.commit()
            print(f"Repair applied: {repaired} consignment(s) repaired.")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
