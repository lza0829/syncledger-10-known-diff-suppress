from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.reconcile import compare_sides
from app.repositories import batches as batch_repo
from app.repositories import contracts as contract_repo
from app.repositories import pairs as pair_repo
from app.repositories import tickets as ticket_repo


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_fixture(name: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / name
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
                "SELECT COUNT(*) c FROM diff_tickets WHERE status='open'"
            ).fetchone()["c"],
            "policy": conn.execute(
                "SELECT value FROM settings WHERE key='default_policy'"
            ).fetchone()["value"],
        }
    finally:
        conn.close()


def list_pairs() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return pair_repo.list_pairs(conn)
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
        return rows
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


def run_reconcile(pair_id: int, note: str | None = None) -> dict[str, Any]:
    """Extract both fixtures, align, persist batch + diffs. No overwrite."""
    conn = connect()
    try:
        pair = pair_repo.get_pair(conn, pair_id)
        if not pair:
            raise ValueError("pair not found")
        if not pair["enabled"]:
            raise ValueError("pair disabled")

        left_rows = _load_fixture(pair["left_fixture"])
        right_rows = _load_fixture(pair["right_fixture"])
        result = compare_sides(
            left_rows,
            right_rows,
            align_keys=pair["align_keys"],
            compare_fields=pair["compare_fields"],
        )
        now = _now()
        seq = conn.execute("SELECT COUNT(*) c FROM reconcile_batches").fetchone()["c"] + 1
        batch_no = f"RB-{now[:10].replace('-', '')}-{seq:04d}"
        batch_id = batch_repo.insert_batch(
            conn,
            batch_no=batch_no,
            pair_id=pair_id,
            status="completed",
            counts=result["counts"],
            note=note,
            created_at=now,
        )
        for diff in result["diffs"]:
            if diff["kind"] == "matched":
                continue
            batch_repo.insert_diff(
                conn, batch_id=batch_id, pair_id=pair_id, diff=diff, created_at=now
            )
        conn.commit()
        batch = batch_repo.get_batch(conn, batch_id)
        assert batch is not None
        batch["pair_code"] = pair["code"]
        batch["pair_title"] = pair["title"]
        batch["policy"] = "record_only"
        batch["counts"] = result["counts"]
        batch["diff_preview"] = batch_repo.list_diffs(conn, batch_id=batch_id, limit=20)
        return batch
    finally:
        conn.close()


def audit_summary(batch_id: int) -> dict[str, Any]:
    """Lightweight audit view for a batch (export hooks left for later cuts)."""
    conn = connect()
    try:
        batch = batch_repo.get_batch(conn, batch_id)
        if not batch:
            raise ValueError("batch not found")
        pair = pair_repo.get_pair(conn, batch["pair_id"])
        diffs = batch_repo.list_diffs(conn, batch_id=batch_id)
        return {
            "batch": batch,
            "pair": pair,
            "diff_count": len(diffs),
            "kinds": {
                "left_only": sum(1 for d in diffs if d["kind"] == "left_only"),
                "right_only": sum(1 for d in diffs if d["kind"] == "right_only"),
                "field_mismatch": sum(1 for d in diffs if d["kind"] == "field_mismatch"),
            },
            "export_ready": False,
            "note": "底座仅提供摘要；审计包导出留给后题切口",
        }
    finally:
        conn.close()
