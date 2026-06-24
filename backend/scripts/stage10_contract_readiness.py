from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.database import AsyncSessionLocal
from app.services.stage10_contract_readiness_service import Stage10ContractReadinessService


async def main() -> int:
    async with AsyncSessionLocal() as db:
        report = await Stage10ContractReadinessService(db).check()
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
