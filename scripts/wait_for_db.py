import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:123456@db:5432/ladsbeer")


async def wait_for_db() -> None:
    engine = create_async_engine(DATABASE_URL)
    max_retries = 30
    retry_delay = 2

    for attempt in range(1, max_retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            print("Database is ready.")
            return
        except Exception as e:
            print(f"Waiting for database... attempt {attempt}/{max_retries} ({e})")
            await asyncio.sleep(retry_delay)

    print("Database did not become ready in time.")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(wait_for_db())
