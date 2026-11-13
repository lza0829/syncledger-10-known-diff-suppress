from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.reconcile import compare_sides
from app.repositories import batches as batch_repo
from app.repositories import contracts as contract_repo
from app.repositories import pairs as pair_repo
from app.repositories import suppressions as suppression_repo
from app.repositories import tickets as ticket_repo
from app.seed import ensure_runtime_fixtures, init_db
from app.services import suppression_service


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_fixture(name: str) -> list[dict[str, Any]]:
    """Read the *runtime* copy so demo source changes are visible.

    Falls back to the shipped fixture when no runtime copy exists yet.
    """
    from app.config import RUNTIME_FIXTURES_DIR

    runtime_path = RUNTIME_FIXTURES_DIR / name
    path = runtime_path if runtime_path.exists() else FIXTURES_DIR / name
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"fixture {name} must be a JSON array")
    return data


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "pair_count": conn.execute("SELECT COUNT(*) c FROM reconcile_pairs").fetchone()["c"],
            "enabled_pairs": conn.execute(
                "SELECT COUNT(*) c FROM reconcile_pairs WHERE enabled=1"
            ).fetchone()["c"],
            "batch_count": conn.execute("SELECT COUNT(*) c FROM reconcile_batches").fetchone()["c"],
            "diff_count": conn.execute("SELECT COUNT(*) c FROM reconcile_diffs").fetchone()["c"],
            "open_dispositions": conn.execute(
                "SELECT COUNT(*) c FROM diff_tickets WHERE status IN ('open','claimed','in_progress')"
            ).fetchone()["c"],
            "suspended_dispositions": conn.execute(
                "SELECT COUNT(*) c FROM diff_tickets WHERE status='suspended_by_suppression'"
            ).fetchone()["c"],
            "policy": conn.execute(
                "SELECT value FROM settings WHERE key='default_policy'"
            ).fetchone()["value"],
            "active_suppressions": suppression_repo.active_count(conn),
            "suppressed_total": conn.execute(
                "SELECT COALESCE(SUM(suppressed_count),0) c FROM reconcile_batches"
            ).fetchone()["c"],
            "reactivated_total": conn.execute(
                "SELECT COALESCE(SUM(reactivated_count),0) c FROM reconcile_batches"
            ).fetchone()["c"],
        }
    finally:
        conn.close()


def list_pairs() -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = pair_repo.list_pairs(conn)
        for r in rows:
            r["policy_label"] = suppression_service.policy_label(r["suppression_ticket_policy"])
        return rows
    finally:
        conn.close()


def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = batch_repo.list_batches(conn, limit=limit)
        pairs = {p["id"]: p for p in pair_repo.list_pairs(conn)}
        for r in rows:
            p = pairs.get(r["pair_id"])
            r["pair_code"] = p["code"] if p else None
            r["pair_title"] = p["title"] if p else None
            r["pending_count"] = (r["diff_total"] or 0) - (r["suppressed_count"] or 0)
        return rows
    finally:
        conn.close()


def get_batch(batch_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        batch = batch_repo.get_batch(conn, batch_id)
        if not batch:
            raise ValueError("batch not found")
        pair = pair_repo.get_pair(conn, batch["pair_id"])
        batch["pair_code"] = pair["code"] if pair else None
        batch["pair_title"] = pair["title"] if pair else None
        batch["pending_count"] = (batch["diff_total"] or 0) - (batch["suppressed_count"] or 0)
        return batch
    finally:
        conn.close()


def list_diffs(batch_id: int | None = None, pair_id: int | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_diffs(conn, batch_id=batch_id, pair_id=pair_id)
    finally:
        conn.close()


def list_dispositions() -> list[dict[str, Any]]:
    """Difference disposition records (not a customer-service ticket desk)."""
    conn = connect()
    try:
        return ticket_repo.list_tickets(conn)
    finally:
        conn.close()


def list_contracts() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return contract_repo.list_contracts(conn)
    finally:
        conn.close()


def list_settings() -> dict[str, str]:
    conn = connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()


def _batch_no(conn, now: str) -> str:
    seq = conn.execute("SELECT COUNT(*) c FROM reconcile_batches").fetchone()["c"] + 1
    return f"RB-{now[:10].replace('-', '')}-{seq:04d}"


def _execute_run(pair_id: int, batch_id: int, pair: dict[str, Any], note: str | None, hold_ms: int) -> None:
    """Background worker: extract -> align -> apply suppressions -> complete."""
    conn = connect()
    try:
        # --- extraction -----------------------------------------------------
        left_rows = _load_fixture(pair["left_fixture"])
        right_rows = _load_fixture(pair["right_fixture"])
        if hold_ms:
            time.sleep(min(hold_ms, 30_000) / 1000 / 2)
        conn.execute(
            "UPDATE reconcile_batches SET status=?, left_rows=?, right_rows=? WHERE id=?",
            (suppression_service.BATCH_STATUS_ALIGNING, len(left_rows), len(right_rows), batch_id),
        )
        conn.commit()
        if hold_ms:
            time.sleep(min(hold_ms, 30_000) / 1000 / 2)

        # --- alignment ------------------------------------------------------
        result = compare_sides(
            left_rows,
            right_rows,
            align_keys=pair["align_keys"],
            compare_fields=pair["compare_fields"],
        )
        counts = result["counts"]
        now = _now()
        diff_rows: list[dict[str, Any]] = []
        for diff in result["diffs"]:
            if diff["kind"] == "matched":
                continue
            diff_id = batch_repo.insert_diff(
                conn, batch_id=batch_id, pair_id=pair_id, diff=diff, created_at=now
            )
            item = dict(diff)
            item["diff_id"] = diff_id
            diff_rows.append(item)

        # --- known-difference suppressions ---------------------------------
        with suppression_service.pair_lock(pair_id):
            outcome = suppression_service.apply_to_batch(
                conn,
                pair=pair,
                batch_id=batch_id,
                diffs=diff_rows,
                created_at=now,
            )
            conn.execute(
                """
                UPDATE reconcile_batches
                   SET status=?, matched=?, left_only=?, right_only=?, field_mismatch=?,
                       diff_total=?, suppressed_count=?, reactivated_count=?,
                       completed_at=?, note=COALESCE(note, ?)
                 WHERE id=?
                """,
                (
                    suppression_service.BATCH_STATUS_COMPLETED,
                    counts["matched"],
                    counts["left_only"],
                    counts["right_only"],
                    counts["field_mismatch"],
                    counts["diff_total"],
                    outcome["suppressed"],
                    outcome["reactivated"],
                    now,
                    note,
                    batch_id,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - surface failure on the batch row
        try:
            conn.execute(
                "UPDATE reconcile_batches SET status=?, note=?, completed_at=? WHERE id=?",
                (
                    suppression_service.BATCH_STATUS_FAILED,
                    f"run failed: {exc}",
                    _now(),
                    batch_id,
                ),
            )
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()


def start_reconcile(
    pair_id: int, note: str | None = None, hold_ms: int | None = None
) -> dict[str, Any]:
    """Start a run: extract both fixtures, align, persist batch + diffs.

    The batch is inserted as ``extracting`` before work begins, so suppression
    edits are refused while statistics are still being computed.  Diff rows are
    always persisted, including suppressed ones — suppression never removes
    them from batch totals.
    """
    init_db()  # idempotent: also ensures runtime fixtures for an older data dir
    ensure_runtime_fixtures()
    conn = connect()
    try:
        pair = pair_repo.get_pair(conn, pair_id)
        if not pair:
            raise ValueError("pair not found")
        if not pair["enabled"]:
            raise ValueError("pair disabled")

        with suppression_service.pair_lock(pair_id):
            running = suppression_service.running_batches(conn, pair_id)
            if running:
                raise ValueError(
                    f"对账批次 {running[0]['batch_no']} 尚未结束，请稍后再发起"
                )
            now = _now()
            batch_no = _batch_no(conn, now)
            batch_id = batch_repo.insert_batch(
                conn,
                batch_no=batch_no,
                pair_id=pair_id,
                status=suppression_service.BATCH_STATUS_EXTRACTING,
                counts={
                    "left_rows": 0,
                    "right_rows": 0,
                    "matched": 0,
                    "left_only": 0,
                    "right_only": 0,
                    "field_mismatch": 0,
                    "diff_total": 0,
                },
                note=note,
                created_at=now,
            )
            conn.execute(
                "UPDATE reconcile_batches SET started_at=? WHERE id=?", (now, batch_id)
            )
            conn.commit()

        worker = threading.Thread(
            target=_execute_run,
            args=(pair_id, batch_id, pair, note, int(hold_ms or 0)),
            name=f"reconcile-{batch_id}",
            daemon=True,
        )
        worker.start()

        batch = batch_repo.get_batch(conn, batch_id)
        assert batch is not None
        batch["pair_code"] = pair["code"]
        batch["pair_title"] = pair["title"]
        batch["policy"] = "record_only"
        batch["pending_count"] = 0
        return batch
    finally:
        conn.close()


def run_reconcile(pair_id: int, note: str | None = None, hold_ms: int | None = None) -> dict[str, Any]:
    """Backwards-compatible alias that blocks until the run finishes."""
    batch = start_reconcile(pair_id, note, hold_ms)
    deadline = time.time() + 60
    while time.time() < deadline:
        current = get_batch(batch["id"])
        if current["status"] not in suppression_service.RUNNING_STATUSES:
            current["diff_preview"] = list_diffs(batch_id=batch["id"])[:20]
            return current
        time.sleep(0.15)
    raise ValueError("reconcile timed out")


def audit_summary(batch_id: int) -> dict[str, Any]:
    """Lightweight audit view for a batch (export hooks left for later cuts)."""
    conn = connect()
    try:
        batch = batch_repo.get_batch(conn, batch_id)
        if not batch:
            raise ValueError("batch not found")
        pair = pair_repo.get_pair(conn, batch["pair_id"])
        diffs = batch_repo.list_diffs(conn, batch_id=batch_id, limit=100000)
        applications = suppression_repo.list_batch_applications(conn, batch_id=batch_id)

        suppressed_from_diffs = sum(
            1 for d in diffs if d.get("suppression_state") == "suppressed"
        )
        reactivated_from_diffs = sum(
            1 for d in diffs if d.get("suppression_state") == "reactivated"
        )
        suppressed_from_applications = sum(
            1
            for a in applications
            if a["fingerprint_state"] == suppression_repo.BATCH_STATE_SUPPRESSED
        )
        reactivated_from_applications = sum(
            1
            for a in applications
            if a["fingerprint_state"] == suppression_repo.BATCH_STATE_REACTIVATED
        )

        checks = {
            "diff_rows_match_total": len(diffs) == (batch["diff_total"] or 0),
            "suppressed_count_matches_rows": (batch["suppressed_count"] or 0)
            == suppressed_from_diffs,
            "reactivated_count_matches_rows": (batch["reactivated_count"] or 0)
            == reactivated_from_diffs,
            "suppressed_count_matches_registry": (batch["suppressed_count"] or 0)
            == suppressed_from_applications,
            "reactivated_count_matches_registry": (batch["reactivated_count"] or 0)
            == reactivated_from_applications,
        }
        return {
            "batch": batch,
            "pair": pair,
            "diff_count": len(diffs),
            "kinds": {
                "left_only": sum(1 for d in diffs if d["kind"] == "left_only"),
                "right_only": sum(1 for d in diffs if d["kind"] == "right_only"),
                "field_mismatch": sum(1 for d in diffs if d["kind"] == "field_mismatch"),
            },
            "suppression": {
                "suppressed": batch["suppressed_count"] or 0,
                "reactivated": batch["reactivated_count"] or 0,
                "pending": (batch["diff_total"] or 0) - (batch["suppressed_count"] or 0),
                "active_suppressions": suppression_repo.active_count(conn, batch["pair_id"]),
            },
            "consistency": {"consistent": all(checks.values()), "checks": checks},
            "suppression_applications": applications,
            "export_ready": False,
            "note": "底座仅提供摘要；审计包导出留给后题切口",
        }
    finally:
        conn.close()
