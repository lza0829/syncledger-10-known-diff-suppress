from __future__ import annotations

import json
from typing import Any

import sqlite3


def list_contracts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM endpoint_contracts ORDER BY pair_code, side"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["fields"] = json.loads(d.pop("fields_json"))
        out.append(d)
    return out
