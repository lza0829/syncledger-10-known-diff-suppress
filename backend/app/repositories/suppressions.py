"""Persistence for known-difference suppressions and their audit trail."""

from __future__ import annotations

import json
from typing import Any

import sqlite3

SUPPRESSION_ACTIVE = "active"
SUPPRESSION_INVALIDATED = "invalidated"
SUPPRESSION_REVOKED = "revoked"

BATCH_STATE_SUPPRESSED = "suppressed"
BATCH_STATE_REACTIVATED = "reactivated"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d["align_key"] = json.loads(d.pop("align_key_json"))
    d["compare_fields"] = json.loads(d.pop("compare_fields_json"))
    d["left_values"] = json.loads(d["left_values_json"]) if d.get("left_values_json") else None
    d["right_values"] = json.loads(d["right_values_json"]) if d.get("right_values_json") else None
    d["ticket_ids"] = json.loads(d.get("ticket_ids_json") or "[]")
    return d


def _decode_application(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["align_key"] = json.loads(d.pop("align_key_json"))
    d["compare_fields"] = json.loads(d.pop("compare_fields_json"))
    d["left_values"] = json.loads(d["left_values_json"]) if d.get("left_values_json") else None
    d["right_values"] = json.loads(d["right_values_json"]) if d.get("right_values_json") else None
    return d


def list_suppressions(conn: sqlite3.Connection, *, pair_id: int | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM known_suppressions WHERE 1=1"
    args: list[Any] = []
    if pair_id is not None:
        sql += " AND pair_id=?"
        args.append(pair_id)
    sql += " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'invalidated' THEN 1 ELSE 2 END, id DESC"
    return [_decode(r) for r in conn.execute(sql, args).fetchall()]  # type: ignore[misc]


def get_suppression(conn: sqlite3.Connection, suppression_id: int) -> dict[str, Any] | None:
    return _decode(
        conn.execute("SELECT * FROM known_suppressions WHERE id=?", (suppression_id,)).fetchone()
    )


def get_active_by_fingerprint(
    conn: sqlite3.Connection, pair_id: int, fingerprint: str
) -> dict[str, Any] | None:
    return _decode(
        conn.execute(
            "SELECT * FROM known_suppressions WHERE pair_id=? AND fingerprint=? AND status='active'",
            (pair_id, fingerprint),
        ).fetchone()
    )


def get_any_by_fingerprint(
    conn: sqlite3.Connection, pair_id: int, fingerprint: str
) -> dict[str, Any] | None:
    return _decode(
        conn.execute(
            "SELECT * FROM known_suppressions WHERE pair_id=? AND fingerprint=?",
            (pair_id, fingerprint),
        ).fetchone()
    )


def list_active(conn: sqlite3.Connection, pair_id: int) -> list[dict[str, Any]]:
    return [
        _decode(r)
        for r in conn.execute(
            "SELECT * FROM known_suppressions WHERE pair_id=? AND status='active' ORDER BY id",
            (pair_id,),
        ).fetchall()
    ]  # type: ignore[misc]


def upsert_active_suppression(
    conn: sqlite3.Connection,
    *,
    pair_id: int,
    fingerprint: str,
    kind: str,
    align_key: dict[str, Any],
    compare_fields: list[str],
    values_digest: str,
    left_values: dict[str, Any] | None,
    right_values: dict[str, Any] | None,
    ticket_policy: str,
    ticket_ids: list[int],
    note: str | None,
    created_at: str,
) -> tuple[int, bool]:
    """Insert a new active suppression or reactivate an existing dormant row.

    Returns (suppression_id, reused_existing).
    """
    existing = conn.execute(
        "SELECT id FROM known_suppressions WHERE pair_id=? AND fingerprint=?",
        (pair_id, fingerprint),
    ).fetchone()
    if existing is not None:
        sid = int(existing["id"])
        conn.execute(
            """
            UPDATE known_suppressions
               SET status='active', kind=?, align_key_json=?, compare_fields_json=?,
                   values_digest=?, left_values_json=?, right_values_json=?,
                   ticket_policy=?, ticket_ids_json=?, note=?,
                   activated_at=?, invalidated_at=NULL, invalidated_batch_id=NULL
             WHERE id=?
            """,
            (
                kind,
                _json(align_key),
                _json(compare_fields),
                values_digest,
                _json(left_values) if left_values is not None else None,
                _json(right_values) if right_values is not None else None,
                ticket_policy,
                _json(ticket_ids),
                note,
                created_at,
                sid,
            ),
        )
        return sid, True
    cur = conn.execute(
        """
        INSERT INTO known_suppressions(
            pair_id, fingerprint, kind, align_key_json, compare_fields_json,
            values_digest, left_values_json, right_values_json,
            status, ticket_policy, ticket_ids_json, note, created_at, activated_at
        ) VALUES (?,?,?,?,?,?,?,?, 'active', ?,?,?,?,?)
        """,
        (
            pair_id,
            fingerprint,
            kind,
            _json(align_key),
            _json(compare_fields),
            values_digest,
            _json(left_values) if left_values is not None else None,
            _json(right_values) if right_values is not None else None,
            ticket_policy,
            _json(ticket_ids),
            note,
            created_at,
            created_at,
        ),
    )
    return int(cur.lastrowid), False


def mark_invalidated(
    conn: sqlite3.Connection,
    *,
    suppression_id: int,
    batch_id: int,
    at: str,
) -> None:
    conn.execute(
        """
        UPDATE known_suppressions
           SET status='invalidated', invalidated_at=?, invalidated_batch_id=?,
               reactivation_count=reactivation_count + 1
         WHERE id=?
        """,
        (at, batch_id, suppression_id),
    )


def mark_revoked(conn: sqlite3.Connection, *, suppression_id: int, at: str) -> None:
    conn.execute(
        "UPDATE known_suppressions SET status='revoked', invalidated_at=? WHERE id=?",
        (at, suppression_id),
    )


def mark_matched(conn: sqlite3.Connection, *, suppression_id: int, batch_id: int, at: str) -> None:
    conn.execute(
        """
        UPDATE known_suppressions
           SET last_batch_id=?, last_matched_at=?, applied_count=applied_count + 1
         WHERE id=?
        """,
        (batch_id, at, suppression_id),
    )


def set_tickets(conn: sqlite3.Connection, *, suppression_id: int, ticket_ids: list[int]) -> None:
    conn.execute(
        "UPDATE known_suppressions SET ticket_ids_json=? WHERE id=?",
        (_json(ticket_ids), suppression_id),
    )


def insert_event(
    conn: sqlite3.Connection,
    *,
    pair_id: int,
    suppression_id: int | None,
    batch_id: int | None,
    fingerprint: str,
    action: str,
    fingerprint_state: str | None,
    ticket_policy: str | None,
    ticket_ids: list[int],
    note: str | None,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO suppression_events(
            pair_id, suppression_id, batch_id, fingerprint, action,
            fingerprint_state, ticket_policy, ticket_ids_json, note, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            pair_id,
            suppression_id,
            batch_id,
            fingerprint,
            action,
            fingerprint_state,
            ticket_policy,
            _json(ticket_ids),
            note,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def list_events(
    conn: sqlite3.Connection, *, pair_id: int | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM suppression_events WHERE 1=1"
    args: list[Any] = []
    if pair_id is not None:
        sql += " AND pair_id=?"
        args.append(pair_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in conn.execute(sql, args).fetchall():
        d = dict(r)
        d["ticket_ids"] = json.loads(d.pop("ticket_ids_json") or "[]")
        out.append(d)
    return out


def insert_batch_application(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    pair_id: int,
    diff_id: int | None,
    fingerprint: str,
    fingerprint_state: str,
    kind: str,
    align_key: dict[str, Any],
    compare_fields: list[str],
    left_values: dict[str, Any] | None,
    right_values: dict[str, Any] | None,
    suppression_id: int | None,
    reactivates_suppression_id: int | None,
    note: str | None,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO batch_suppressions(
            batch_id, pair_id, diff_id, fingerprint, fingerprint_state, kind,
            align_key_json, compare_fields_json, left_values_json, right_values_json,
            suppression_id, reactivates_suppression_id, note, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            batch_id,
            pair_id,
            diff_id,
            fingerprint,
            fingerprint_state,
            kind,
            _json(align_key),
            _json(compare_fields),
            _json(left_values) if left_values is not None else None,
            _json(right_values) if right_values is not None else None,
            suppression_id,
            reactivates_suppression_id,
            note,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def list_batch_applications(conn: sqlite3.Connection, *, batch_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM batch_suppressions WHERE batch_id=? ORDER BY id", (batch_id,)
    ).fetchall()
    return [_decode_application(r) for r in rows]


def batch_state_counts(conn: sqlite3.Connection, batch_id: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT fingerprint_state, COUNT(*) c FROM batch_suppressions WHERE batch_id=? GROUP BY fingerprint_state",
        (batch_id,),
    ).fetchall()
    counts = {BATCH_STATE_SUPPRESSED: 0, BATCH_STATE_REACTIVATED: 0}
    for r in rows:
        counts[r["fingerprint_state"]] = r["c"]
    return counts


def active_count(conn: sqlite3.Connection, pair_id: int | None = None) -> int:
    if pair_id is None:
        return conn.execute(
            "SELECT COUNT(*) c FROM known_suppressions WHERE status='active'"
        ).fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) c FROM known_suppressions WHERE status='active' AND pair_id=?",
        (pair_id,),
    ).fetchone()["c"]
