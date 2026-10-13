#!/usr/bin/env python3
"""
Copy the engine database to data/engine/backups/underline-YYYY-MM-DD.db.

The running app also writes this copy. Use this script from Task Scheduler if you
want the backup even when you start the app some other way. Safe while the app is open.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from engine.store import Store, write_daily_backup  # noqa: E402


def _db_path() -> str:
    raw = os.getenv("ENGINE_DB_PATH", "data/engine/underline.db").strip()
    path = raw if os.path.isabs(raw) else os.path.join(ROOT, raw)
    return path


def main() -> None:
    path = _db_path()
    if not os.path.isfile(path):
        raise SystemExit(f"No engine database at {path}. Start the app once, then back up.")
    dest = write_daily_backup(Store(path), path)
    print(dest or f"Today's backup is already in {os.path.dirname(path)}\\backups")


if __name__ == "__main__":
    main()
