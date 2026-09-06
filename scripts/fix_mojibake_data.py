#!/usr/bin/env python3
"""Fix CP437/CP850 mojibake in legacy text data (e.g. "COPÃ£O" -> "COPÃO").

Some production data was once imported through a Windows OEM codepage: the UTF-8
bytes of accented characters (0xC3 0xA3 = "ã") were decoded as CP437 and stored
as the box-drawing + Latin-1 pair "├â" (U+251C + U+00E2). This reverses that
corruption idempotently across every text column in the public schema.

Idempotent: only rows containing U+251C ("├") are touched; after a successful
run none remain, so running it again is a no-op.

Run from the host (DB exposed on localhost) or inside a container:
    DATABASE_URL=postgresql+asyncpg://postgres:123456@db:5432/ladsbeer \
        python scripts/fix_mojibake_data.py
"""
from __future__ import annotations

import asyncio
import re
import sys

from sqlalchemy import text

from app.core.database import engine

MOJI = chr(9500)  # "├" (U+251C) — lead glyph of any CP437-corrupted UTF-8 accent

# Explicit reversal for corruption variants whose second glyph is NOT
# representable in cp437 (e.g. "é" -> "├®", where "®" has no cp437 mapping).
PAIR_MAP = {
    "\u251c\u00ae": "é",  # ├® -> é
}


def _repl(match: re.Match) -> str:
    segment = match.group(0)
    try:
        recovered = segment.encode("cp437").decode("utf-8")
    except (UnicodeError, ValueError):
        return segment
    # Only accept if it actually produced accented characters.
    if any(ord(ch) > 127 for ch in recovered):
        return recovered
    return segment


def _fix_value(value: str) -> tuple[str, bool]:
    """Reverse the CP437 mojibake for a single value. Returns (new, changed)."""
    if MOJI not in value:
        return value, False

    fixed = value
    for wrong, right in PAIR_MAP.items():
        fixed = fixed.replace(wrong, right)
    fixed = re.sub(r"[\u0080-\uffff]+", _repl, fixed)
    return fixed, fixed != value


async def run() -> int:
    total = 0
    async with engine.connect() as conn:
        columns_result = await conn.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND data_type IN ('character varying', 'text', 'character', 'citext')
                  AND column_name NOT IN ('password_hash')
                ORDER BY table_name, ordinal_position
                """
            )
        )
        text_columns = [(t, c) for t, c in columns_result.all()]

        pk_result = await conn.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.key_column_usage
                WHERE table_schema = 'public' AND constraint_name LIKE '%pkey%'
                """
            )
        )
        pk_map: dict[str, str] = {}
        for table, column in pk_result.all():
            pk_map.setdefault(table, column)

        for table, column in text_columns:
            pk = pk_map.get(table)
            if not pk:
                continue
            tq = table.replace('"', '""')
            cq = column.replace('"', '""')
            pkq = pk.replace('"', '""')

            rows = await conn.execute(
                text(
                    f'SELECT "{pkq}", "{cq}" FROM "{tq}" '
                    f'WHERE position(chr(9500) in "{cq}") > 0'
                )
            )
            changed = 0
            for row_id, raw in rows.all():
                new_value, did_change = _fix_value(raw or "")
                if did_change:
                    await conn.execute(
                        text(f'UPDATE "{tq}" SET "{cq}" = :new WHERE "{pkq}" = :id'),
                        {"new": new_value, "id": row_id},
                    )
                    changed += 1
            if changed:
                total += changed
                print(f"{table}.{column}: {changed} corrigind(s)")

        await conn.commit()
    print(f"TOTAL CORRIGIDO: {total}")
    return total


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:  # pragma: no cover
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)