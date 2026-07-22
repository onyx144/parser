#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.session import SessionLocal
from app.services.parser import run_parser


async def main() -> None:
    config_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    async with SessionLocal() as db:
        run_id = await run_parser(db, config_id)
        print(f"run_id={run_id}")


if __name__ == "__main__":
    asyncio.run(main())
