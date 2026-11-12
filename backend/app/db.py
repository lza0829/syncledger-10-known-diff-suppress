from __future__ import annotations

import sqlite3

from app.config import DATA_DIR, DB_FILENAME

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / DB_FILENAME


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
