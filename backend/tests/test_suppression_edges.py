from __future__ import annotations

import json
import time

import pytest

from app.db import connect
from app.seed import init_db, ensure_runtime_fixtures, RUNTIME_FIXTURES_DIR
from app.repositories import pairs as pair_repo
from app.services import reconcile_service as rs
from app.services import suppression_service as ss
import app.services.demo_service as demo


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("app.config.RUNTIME_FIXTURES_DIR", tmp_path / "fixtures")
    monkeypatch.setattr("app.seed.BASELINE_DIR", tmp_path / "fixtures_baseline")
    init_db()
    ensure_runtime_fixtures()
    yield


def test_align_key_alone_is_not_enough_same_key_new_value_reactivates():
    """The heart of the requirement: a value change on the same key must not be swallowed."""
    first = rs.run_reconcile(1)
    left_only = next(d for d in rs.list_diffs(first["id"]) if d["kind"] == "left_only")
    fm = next(d for d in rs.list_diffs(first["id"]) if d["kind"] == "field_mismatch")

    conn = connect()
    try:
        ss.register(conn, diff_id=left_only["id"])
    finally:
        conn.close()

    # Add the missing right row for SKU-300 → left_only becomes field_mismatch.
    # Even though the align key is unchanged, the difference shape changed.
    path = demo._paths(pair_repo.get_pair(connect(), 1)["right_fixture"])[0]
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows.append({"sku_id": "SKU-300", "store_id": "S01", "qty": 999, "unit": "pcs"})
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    second = rs.run_reconcile(1)
    states = {d["align_key"]["sku_id"]: d for d in rs.list_diffs(second["id"])}
    assert states["SKU-300"]["kind"] == "field_mismatch"
    assert states["SKU-300"]["suppression_state"] == "reactivated", (
        "a different difference on the same key must not inherit the suppression"
    )

    conn = connect()
    try:
        sup = conn.execute("SELECT status FROM known_suppressions").fetchone()
    finally:
        conn.close()
    assert sup["status"] == "invalidated", (
        "a changed difference shape on the same key must retire the old suppression"
    )


def test_identical_duplicate_diff_rows_are_not_double_suppressed():
    pair = pair_repo.get_pair(connect(), 1)
    fake = [
        {
            "diff_id": 100,
            "kind": "right_only",
            "align_key": {"sku_id": "SKU-X", "store_id": "S01"},
            "left": None,
            "right": {"sku_id": "SKU-X", "store_id": "S01", "qty": 5, "unit": "pcs"},
        }
    ]
    conn = connect()
    try:
        # Batch row to attach to.
        from app.repositories import batches as batch_repo

        bid = batch_repo.insert_batch(
            conn,
            batch_no="RB-TEST-0001",
            pair_id=1,
            status="completed",
            counts={
                "left_rows": 0, "right_rows": 0, "matched": 0,
                "left_only": 0, "right_only": 1, "field_mismatch": 0, "diff_total": 1,
            },
            note=None,
            created_at=ss.now_iso(),
        )
        did = batch_repo.insert_diff(
            conn, batch_id=bid, pair_id=1, diff={
                "kind": "right_only", "align_key": {"sku_id": "SKU-X", "store_id": "S01"},
                "left": None,
                "right": {"sku_id": "SKU-X", "store_id": "S01", "qty": 5, "unit": "pcs"},
            }, created_at=ss.now_iso(),
        )
        ss.register(conn, diff_id=did)
        fake[0]["diff_id"] = did
        outcome = ss.apply_to_batch(
            conn, pair=pair, batch_id=bid, diffs=[fake[0], dict(fake[0])], created_at=ss.now_iso()
        )
    finally:
        conn.close()
    assert outcome["suppressed"] == 1, "one fingerprint hit must count once, not per duplicate row"
