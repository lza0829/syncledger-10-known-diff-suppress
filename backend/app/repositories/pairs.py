from __future__ import annotations

import json
from typing import Any

import sqlite3


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    d["align_keys"] = json.loads(d.pop("align_keys_json"))
    d["compare_fields"] = json.loads(d.pop("compare_fields_json"))
    d["enabled"] = bool(d["enabled"])
    return d


def list_pairs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM reconcile_pairs ORDER BY id").fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def get_pair(conn: sqlite3.Connection, pair_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM reconcile_pairs WHERE id=?", (pair_id,)).fetchone())


def get_pair_by_code(conn: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM reconcile_pairs WHERE code=?", (code,)).fetchone())
