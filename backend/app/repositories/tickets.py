from __future__ import annotations

import json
from typing import Any

import sqlite3


def list_tickets(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT t.*, d.kind AS diff_kind, d.align_key_json AS diff_align_key_json,
               d.fingerprint AS diff_fingerprint
          FROM diff_tickets t
          LEFT JOIN reconcile_diffs d ON d.id = t.diff_id
         ORDER BY t.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        raw_key = d.pop("diff_align_key_json", None)
        d["align_key"] = json.loads(raw_key) if raw_key else None
        out.append(d)
    return out


def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM diff_tickets WHERE id=?", (ticket_id,)).fetchone()
    return dict(row) if row is not None else None


def create_ticket(
    conn: sqlite3.Connection,
    *,
    pair_id: int,
    diff_id: int,
    title: str,
    assignee: str | None,
    note: str | None,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO diff_tickets(pair_id, diff_id, title, status, assignee, note, created_at, updated_at)
        VALUES (?,?,?, 'open', ?,?,?,?)
        """,
        (pair_id, diff_id, title, assignee, note, created_at, created_at),
    )
    return int(cur.lastrowid)


def set_status(
    conn: sqlite3.Connection,
    *,
    ticket_id: int,
    status: str,
    at: str,
    note: str | None = None,
) -> None:
    if note:
        conn.execute(
            "UPDATE diff_tickets SET status=?, updated_at=?, note=? WHERE id=?",
            (status, at, note, ticket_id),
        )
    else:
        conn.execute(
            "UPDATE diff_tickets SET status=?, updated_at=? WHERE id=?",
            (status, at, ticket_id),
        )


def open_tickets_for_pair(conn: sqlite3.Connection, pair_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT t.*, d.kind AS diff_kind, d.align_key_json AS diff_align_key_json
          FROM diff_tickets t
          JOIN reconcile_diffs d ON d.id = t.diff_id
         WHERE t.pair_id=?
           AND t.status IN ('open','claimed','in_progress')
         ORDER BY t.id
        """,
        (pair_id,),
    ).fetchall()
    return [dict(r) for r in rows]
