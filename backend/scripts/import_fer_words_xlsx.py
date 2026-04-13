from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.database import get_db_context
from app.services.fer_words_service import import_fer_words_xlsx


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import 'ФЕР слова' XLSX into fer_words.entries")
    parser.add_argument("file", help="Path to XLSX file")
    args = parser.parse_args()

    path = Path(args.file).expanduser().resolve()
    async with get_db_context() as db:
        imported = await import_fer_words_xlsx(db, str(path))
    print(f"Imported {imported} rows from {path}")


if __name__ == "__main__":
    asyncio.run(main())
