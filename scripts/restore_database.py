#!/usr/bin/env python3
"""Restore a full Lads Beer PostgreSQL custom-format backup."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import DATABASE_URL


def _connection_args() -> tuple[list[str], dict[str, str], str]:
    url = make_url(DATABASE_URL)
    if not url.drivername.startswith("postgresql") or not url.database:
        raise ValueError("DATABASE_URL must point to a PostgreSQL database")

    args = ["--dbname", url.database]
    if url.host:
        args.extend(["--host", url.host])
    if url.port:
        args.extend(["--port", str(url.port)])
    if url.username:
        args.extend(["--username", url.username])

    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    return args, environment, url.database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore a complete Lads Beer PostgreSQL backup"
    )
    parser.add_argument("backup", type=Path, help="Path to the .dump backup file")
    parser.add_argument(
        "--confirm-database",
        required=True,
        help="Target database name, required as an explicit safety confirmation",
    )
    args = parser.parse_args()

    backup_path = args.backup.resolve()
    if not backup_path.is_file():
        print(f"Backup file not found: {backup_path}", file=sys.stderr)
        return 2

    try:
        connection_args, environment, database_name = _connection_args()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.confirm_database != database_name:
        print(
            "Safety confirmation does not match the DATABASE_URL database name",
            file=sys.stderr,
        )
        return 2

    validation = subprocess.run(
        ["pg_restore", "--list", str(backup_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if validation.returncode != 0:
        print("The selected file is not a valid PostgreSQL custom dump", file=sys.stderr)
        return 2

    restore = subprocess.run(
        [
            "pg_restore",
            *connection_args,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-acl",
            "--single-transaction",
            str(backup_path),
        ],
        env=environment,
        check=False,
    )
    if restore.returncode != 0:
        print("Database restore failed", file=sys.stderr)
        return restore.returncode

    print(f"Database '{database_name}' restored successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
