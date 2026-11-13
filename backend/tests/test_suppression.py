"""Regression tests for known-difference suppression.

Covers: unchanged fingerprint stays suppressed but still counted; source-side
value change invalidates the suppression; disposition-ticket conflicts under
both mutually-exclusive policies; and edits refused during extract/align.
"""

from __future__ import annotations

import sqlite3
import textwrap
import time

import pytest

from app.db import connect, DB_PATH
from app.seed import FIXTURES_DIR, init_db, ensure_runtime_fixtures, RUNTIME_FIXTURES_DIR
import app.services.demo_service as demo
from app.repositories import pairs as pair_repo
from app.services import reconcile_service as rs
from app.services import suppression_service as ss


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db)
    monkeypatch.setattr("app.config.RUNTIME_FIXTURES_DIR", tmp_path / "fixtures")
    monkeypatch.setattr("app.seed.BASELINE_DIR", tmp_path / "fixtures_baseline")
    init_db()
    ensure_runtime_fixtures()
    yield


def _run(pair_id=1, hold_ms=None):
    return rs.run_reconcile(pair_id, hold_ms=hold_ms)


def _diffs(batch_id):
    return rs.list_diffs(batch_id=batch_id)


def _pair(pair_id=1):
    conn = connect()
    try:
        return pair_repo.get_pair(conn, pair_id)
    finally:
        conn.close()


def _change(pair_id, side, align_key, changes):
    return demo.change_source(
        pair=_pair(pair_id), side=side, align_key=align_key, changes=changes
    )


def test_unchanged_fingerprint_is_suppressed_but_still_counted():
    first = _run()
    target = next(d for d in _diffs(first["id"]) if d["kind"] == "left_only")

    conn = connect()
    try:
        res = ss.register(conn, diff_id=target["id"])
    finally:
        conn.close()
    assert len(res["fingerprint"]) == 64

    second = _run()
    assert second["diff_total"] == first["diff_total"]
    assert second["suppressed_count"] == 1
    assert second["reactivated_count"] == 0

    rows = _diffs(second["id"])
    assert len(rows) == second["diff_total"], "suppressed rows must not vanish"
    states = {d["align_key"]["sku_id"]: d["suppression_state"] for d in rows}
    assert states["SKU-300"] == "suppressed"

    summary = rs.audit_summary(second["id"])
    assert summary["consistency"]["consistent"] is True
    assert summary["suppression"]["suppressed"] == 1
    assert summary["suppression"]["pending"] == second["diff_total"] - 1


def test_fingerprint_covers_compared_values_not_just_key():
    first = _run()
    fm = next(d for d in _diffs(first["id"]) if d["kind"] == "field_mismatch")
    conn = connect()
    try:
        res = ss.register(conn, diff_id=fm["id"])
        sup = conn.execute(
            "SELECT left_values_json, right_values_json FROM known_suppressions WHERE id=?",
            (res["suppression_id"],),
        ).fetchone()
    finally:
        conn.close()
    # qty participates, updated_at does not.
    assert '"qty"' in sup["left_values_json"]
    assert '"qty"' in sup["right_values_json"]
    assert "updated_at" not in sup["left_values_json"]


@pytest.mark.parametrize("side", ["left", "right"])
def test_source_value_change_reactivates(side):
    first = _run()
    fm = next(d for d in _diffs(first["id"]) if d["kind"] == "field_mismatch")
    conn = connect()
    try:
        ss.register(conn, diff_id=fm["id"])
    finally:
        conn.close()

    row = fm[side]
    new_qty = (row["qty"] or 0) + 1
    _change(1, side, fm["align_key"], {"qty": new_qty})

    second = _run()
    assert second["reactivated_count"] == 1
    assert second["suppressed_count"] == 0
    reactivated = [d for d in _diffs(second["id"]) if d["suppression_state"] == "reactivated"]
    assert len(reactivated) == 1
    assert reactivated[0]["kind"] == "field_mismatch"

    conn = connect()
    try:
        sup = conn.execute("SELECT * FROM known_suppressions").fetchone()
    finally:
        conn.close()
    assert sup["status"] == "invalidated"


def test_non_compared_field_change_keeps_suppression():
    first = _run()
    fm = next(d for d in _diffs(first["id"]) if d["kind"] == "field_mismatch")
    conn = connect()
    try:
        ss.register(conn, diff_id=fm["id"])
    finally:
        conn.close()

    # updated_at is not a compare field, so the fingerprint must not change.
    path = demo._paths(_pair()["left_fixture"])[0]
    import json

    rows = json.loads(path.read_text(encoding="utf-8"))
    for r in rows:
        if r.get("sku_id") == "SKU-100" and r.get("store_id") == "S01":
            r["updated_at"] = "2030-01-01T00:00:00Z"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    second = _run()
    assert second["suppressed_count"] == 1
    assert second["reactivated_count"] == 0


def test_ticket_conflict_reject_policy_blocks_registration():
    first = _run()
    target = next(d for d in _diffs(first["id"]) if d["kind"] == "right_only")
    conn = connect()
    try:
        from app.routers.dispositions import CreateBody, create_disposition

        ticket = create_disposition(CreateBody(diff_id=target["id"]))
        assert ticket["status"] == "open"
        with pytest.raises(ss.SuppressionError) as exc:
            ss.register(conn, diff_id=target["id"])
    finally:
        conn.close()
    assert exc.value.code == "ticket_conflict"
    assert exc.value.extra["tickets"][0]["id"] == ticket["id"]

    conn = connect()
    try:
        assert (
            conn.execute("SELECT COUNT(*) c FROM known_suppressions").fetchone()["c"] == 0
        )
        actions = [
            r["action"] for r in conn.execute("SELECT * FROM suppression_events").fetchall()
        ]
    finally:
        conn.close()
    assert "register_rejected_ticket_conflict" in actions


def test_ticket_conflict_allow_policy_suspends_ticket():
    first = _run()
    target = next(d for d in _diffs(first["id"]) if d["kind"] == "right_only")
    conn = connect()
    try:
        from app.routers.dispositions import CreateBody, create_disposition

        ticket = create_disposition(CreateBody(diff_id=target["id"]))
        ss.set_policy(conn, pair_id=1, policy=ss.POLICY_ALLOW)
        res = ss.register(conn, diff_id=target["id"])
        assert res["suspended_ticket_ids"] == [ticket["id"]]
        status = conn.execute(
            "SELECT status FROM diff_tickets WHERE id=?", (ticket["id"],)
        ).fetchone()["status"]
    finally:
        conn.close()
    assert status == "suspended_by_suppression"

    # Policy A must be mutually exclusive with B.
    conn = connect()
    try:
        policy = conn.execute(
            "SELECT suppression_ticket_policy p FROM reconcile_pairs WHERE id=1"
        ).fetchone()["p"]
    finally:
        conn.close()
    assert policy == ss.POLICY_ALLOW


def test_source_change_restores_suspended_ticket():
    first = _run()
    fm = next(d for d in _diffs(first["id"]) if d["kind"] == "field_mismatch")
    conn = connect()
    try:
        from app.routers.dispositions import CreateBody, create_disposition

        ticket = create_disposition(CreateBody(diff_id=fm["id"]))
        ss.set_policy(conn, pair_id=1, policy=ss.POLICY_ALLOW)
        ss.register(conn, diff_id=fm["id"])
    finally:
        conn.close()

    _change(1, "right", fm["align_key"], {"qty": (fm["right"]["qty"] or 0) + 5})
    second = _run()
    assert second["reactivated_count"] == 1

    conn = connect()
    try:
        status = conn.execute(
            "SELECT status FROM diff_tickets WHERE id=?", (ticket["id"],)
        ).fetchone()["status"]
    finally:
        conn.close()
    assert status == "open", "an expired suppression must un-park its ticket"


def test_revoke_restores_suspended_ticket_and_is_recorded():
    first = _run()
    target = next(d for d in _diffs(first["id"]) if d["kind"] == "right_only")
    conn = connect()
    try:
        from app.routers.dispositions import CreateBody, create_disposition

        ticket = create_disposition(CreateBody(diff_id=target["id"]))
        ss.set_policy(conn, pair_id=1, policy=ss.POLICY_ALLOW)
        res = ss.register(conn, diff_id=target["id"])
        revoked = ss.revoke(conn, suppression_id=res["suppression_id"])
        assert revoked["restored_ticket_ids"] == [ticket["id"]]
        status = conn.execute(
            "SELECT status FROM diff_tickets WHERE id=?", (ticket["id"],)
        ).fetchone()["status"]
        sup_status = conn.execute(
            "SELECT status FROM known_suppressions WHERE id=?", (res["suppression_id"],)
        ).fetchone()["status"]
    finally:
        conn.close()
    assert status == "open"
    assert sup_status == "revoked"


def test_edits_refused_while_batch_extracting_or_aligning():
    first = _run()
    target = _diffs(first["id"])[0]
    conn = connect()
    try:
        started = ss.register(conn, diff_id=target["id"])
        batch = rs.start_reconcile(1, hold_ms=2500)
    finally:
        conn.close()
    assert batch["status"] in ("extracting", "aligning")

    for action in ("register", "revoke", "policy"):
        conn = connect()
        try:
            with pytest.raises(ss.SuppressionError) as exc:
                if action == "register":
                    other = next(
                        d for d in _diffs(first["id"]) if d["id"] != target["id"]
                    )
                    ss.register(conn, diff_id=other["id"])
                elif action == "revoke":
                    ss.revoke(conn, suppression_id=started["suppression_id"])
                else:
                    ss.set_policy(conn, pair_id=1, policy=ss.POLICY_ALLOW)
        finally:
            conn.close()
        assert exc.value.code == "run_in_progress"

    # Wait for the in-flight run, then edits are accepted again.
    deadline = time.time() + 15
    while time.time() < deadline:
        status = rs.get_batch(batch["id"])["status"]
        if status not in ("extracting", "aligning"):
            break
        time.sleep(0.2)
    assert status == "completed"

    conn = connect()
    try:
        ss.revoke(conn, suppression_id=started["suppression_id"])
    finally:
        conn.close()


def test_second_run_refused_while_one_in_flight():
    conn = connect()
    batch = rs.start_reconcile(1, hold_ms=1500)
    conn.close()
    with pytest.raises(ValueError):
        rs.start_reconcile(1)
    deadline = time.time() + 15
    while time.time() < deadline and rs.get_batch(batch["id"])["status"] in (
        "extracting",
        "aligning",
    ):
        time.sleep(0.2)


def test_batch_suppression_totals_are_additive_across_runs():
    first = _run()
    diffs = _diffs(first["id"])
    conn = connect()
    try:
        for d in diffs:
            ss.register(conn, diff_id=d["id"])
    finally:
        conn.close()

    total_suppressed = 0
    for _ in range(2):
        b = _run()
        total_suppressed += b["suppressed_count"]
        assert b["suppressed_count"] + b["pending_count"] == b["diff_total"]
        assert b["suppressed_count"] == b["diff_total"]
        summary = rs.audit_summary(b["id"])
        assert summary["consistency"]["consistent"]

    conn = connect()
    try:
        stats = rs.dashboard_stats()
    finally:
        conn.close()
    assert stats["suppressed_total"] == total_suppressed
    assert stats["active_suppressions"] == len(diffs)


def test_migration_upgrades_legacy_schema(tmp_path, monkeypatch):
    """An old DB (no suppression columns/tables) must upgrade in place."""
    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    conn.executescript(
        textwrap.dedent(
            """
            CREATE TABLE reconcile_pairs(
                id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                domain TEXT NOT NULL, left_name TEXT NOT NULL, right_name TEXT NOT NULL,
                left_fixture TEXT NOT NULL, right_fixture TEXT NOT NULL,
                align_keys_json TEXT NOT NULL, compare_fields_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE reconcile_batches(
                id INTEGER PRIMARY KEY, batch_no TEXT NOT NULL UNIQUE, pair_id INTEGER NOT NULL,
                status TEXT NOT NULL, left_rows INTEGER NOT NULL, right_rows INTEGER NOT NULL,
                matched INTEGER NOT NULL, left_only INTEGER NOT NULL, right_only INTEGER NOT NULL,
                field_mismatch INTEGER NOT NULL, diff_total INTEGER NOT NULL, note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE reconcile_diffs(
                id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL, pair_id INTEGER NOT NULL,
                kind TEXT NOT NULL, align_key_json TEXT NOT NULL, left_json TEXT, right_json TEXT,
                mismatched_fields_json TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'medium',
                created_at TEXT NOT NULL
            );
            CREATE TABLE diff_tickets(
                id INTEGER PRIMARY KEY, pair_id INTEGER, diff_id INTEGER,
                title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                assignee TEXT, note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE endpoint_contracts(
                id INTEGER PRIMARY KEY, pair_code TEXT NOT NULL, side TEXT NOT NULL,
                fields_json TEXT NOT NULL, version TEXT NOT NULL DEFAULT 'v1',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("app.db.DB_PATH", legacy)
    init_db()
    conn = connect()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(reconcile_diffs)")}
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert {"fingerprint", "suppression_state", "suppression_id"} <= cols
    assert {"known_suppressions", "batch_suppressions", "suppression_events"} <= tables
