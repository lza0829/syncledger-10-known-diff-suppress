from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

from app.config import DATA_DIR, FIXTURES_DIR, RUNTIME_FIXTURES_DIR
from app.db import connect
from app.engines.fingerprint import sha256_text

BASELINE_DIR = DATA_DIR / "fixtures_baseline"

SUPPRESSION_TICKET_POLICY_REJECT = "reject"
SUPPRESSION_TICKET_POLICY_ALLOW = "allow_and_suspend"
SUPPRESSION_TICKET_POLICIES = (
    SUPPRESSION_TICKET_POLICY_REJECT,
    SUPPRESSION_TICKET_POLICY_ALLOW,
)


PAIR_SEEDS = [
    {
        "code": "inventory_hq_vs_store",
        "title": "总部库存 ↔ 门店库存",
        "domain": "inventory",
        "left_name": "总部库存夹具",
        "right_name": "门店库存夹具",
        "left_fixture": "inventory_hq.json",
        "right_fixture": "inventory_store.json",
        "align_keys": ["sku_id", "store_id"],
        "compare_fields": ["qty", "unit"],
        "enabled": 1,
    },
    {
        "code": "payment_vs_ledger",
        "title": "支付网关 ↔ 账务流水",
        "domain": "payment",
        "left_name": "支付网关夹具",
        "right_name": "账务流水夹具",
        "left_fixture": "payment_gateway.json",
        "right_fixture": "payment_ledger.json",
        "align_keys": ["txn_id"],
        "compare_fields": ["amount", "currency"],
        "enabled": 1,
    },
    {
        "code": "sku_catalog_a_vs_b",
        "title": "商品目录 A ↔ 目录 B",
        "domain": "catalog",
        "left_name": "目录 A 夹具",
        "right_name": "目录 B 夹具",
        "left_fixture": "sku_catalog_a.json",
        "right_fixture": "sku_catalog_b.json",
        "align_keys": ["sku_code"],
        "compare_fields": ["name", "category"],
        "enabled": 1,
    },
]

CONTRACT_SEEDS = [
    ("inventory_hq_vs_store", "left", ["sku_id", "store_id", "qty", "unit", "updated_at"]),
    ("inventory_hq_vs_store", "right", ["sku_id", "store_id", "qty", "unit", "updated_at"]),
    ("payment_vs_ledger", "left", ["txn_id", "amount", "currency", "paid_at"]),
    ("payment_vs_ledger", "right", ["txn_id", "amount", "currency", "booked_at"]),
    ("sku_catalog_a_vs_b", "left", ["sku_code", "name", "category", "updated_at"]),
    ("sku_catalog_a_vs_b", "right", ["sku_code", "name", "category", "updated_at"]),
]


def _migrate(conn) -> None:
    """In-place upgrades for databases created by earlier cuts."""

    def columns(table: str) -> set[str]:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    additions = {
        "reconcile_pairs": [
            ("suppression_ticket_policy", "TEXT NOT NULL DEFAULT 'reject'"),
        ],
        "reconcile_diffs": [
            ("fingerprint", "TEXT"),
            ("values_digest", "TEXT"),
            ("suppression_state", "TEXT NOT NULL DEFAULT 'pending'"),
            ("suppression_id", "INTEGER"),
        ],
        "known_suppressions": [
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("ticket_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("activated_at", "TEXT"),
            ("invalidated_at", "TEXT"),
            ("invalidated_batch_id", "INTEGER"),
            ("last_batch_id", "INTEGER"),
            ("last_matched_at", "TEXT"),
            ("applied_count", "INTEGER NOT NULL DEFAULT 0"),
            ("reactivation_count", "INTEGER NOT NULL DEFAULT 0"),
        ],
        "reconcile_batches": [
            ("suppressed_count", "INTEGER NOT NULL DEFAULT 0"),
            ("reactivated_count", "INTEGER NOT NULL DEFAULT 0"),
            ("started_at", "TEXT"),
            ("completed_at", "TEXT"),
        ],
    }
    for table, cols in additions.items():
        existing = columns(table)
        for name, ddl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_suppressions_pair_fp "
        "ON known_suppressions(pair_id, fingerprint)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_suppressions_batch ON batch_suppressions(batch_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_suppression_events_pair ON suppression_events(pair_id)"
    )


def runtime_fixtures_dir():
    """Late-bound so tests can repoint DATA_DIR at a temp directory."""
    from app.config import RUNTIME_FIXTURES_DIR as configured

    return configured


def baseline_dir():
    from app.seed import BASELINE_DIR as configured

    return configured


def ensure_runtime_fixtures() -> None:
    """Copy shipped fixtures into the writable data dir once (mutable viewpoint).

    Reconciliation reads runtime fixtures so the demo can change source values
    between runs without rebuilding the image.  The shipped copies stay
    untouched as the pristine baseline.
    """
    runtime_dir = runtime_fixtures_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(FIXTURES_DIR.glob("*.json")):
        dst = runtime_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)


def baseline_fixture_digest(name: str) -> str | None:
    path = baseline_dir() / name
    if not path.exists():
        return None
    return sha256_text(path.read_text(encoding="utf-8"))


def _seed_baseline_fixtures() -> None:
    """Freeze the pristine shipped fixtures as the source-drift baseline."""

    base = baseline_dir()
    base.mkdir(parents=True, exist_ok=True)
    for src in sorted(FIXTURES_DIR.glob("*.json")):
        dst = base / src.name
        if not dst.exists():
            shutil.copy2(src, dst)


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reconcile_pairs(
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                left_name TEXT NOT NULL,
                right_name TEXT NOT NULL,
                left_fixture TEXT NOT NULL,
                right_fixture TEXT NOT NULL,
                align_keys_json TEXT NOT NULL,
                compare_fields_json TEXT NOT NULL,
                suppression_ticket_policy TEXT NOT NULL DEFAULT 'reject',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reconcile_batches(
                id INTEGER PRIMARY KEY,
                batch_no TEXT NOT NULL UNIQUE,
                pair_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                left_rows INTEGER NOT NULL,
                right_rows INTEGER NOT NULL,
                matched INTEGER NOT NULL,
                left_only INTEGER NOT NULL,
                right_only INTEGER NOT NULL,
                field_mismatch INTEGER NOT NULL,
                diff_total INTEGER NOT NULL,
                suppressed_count INTEGER NOT NULL DEFAULT 0,
                reactivated_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(pair_id) REFERENCES reconcile_pairs(id)
            );
            CREATE TABLE IF NOT EXISTS reconcile_diffs(
                id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                pair_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                align_key_json TEXT NOT NULL,
                left_json TEXT,
                right_json TEXT,
                mismatched_fields_json TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'medium',
                fingerprint TEXT,
                values_digest TEXT,
                suppression_state TEXT NOT NULL DEFAULT 'pending',
                suppression_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES reconcile_batches(id),
                FOREIGN KEY(pair_id) REFERENCES reconcile_pairs(id)
            );
            CREATE TABLE IF NOT EXISTS diff_tickets(
                id INTEGER PRIMARY KEY,
                pair_id INTEGER,
                diff_id INTEGER,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                assignee TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(pair_id) REFERENCES reconcile_pairs(id),
                FOREIGN KEY(diff_id) REFERENCES reconcile_diffs(id)
            );
            CREATE TABLE IF NOT EXISTS endpoint_contracts(
                id INTEGER PRIMARY KEY,
                pair_code TEXT NOT NULL,
                side TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT 'v1',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS known_suppressions(
                id INTEGER PRIMARY KEY,
                pair_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                kind TEXT NOT NULL,
                align_key_json TEXT NOT NULL,
                compare_fields_json TEXT NOT NULL,
                values_digest TEXT NOT NULL,
                left_values_json TEXT,
                right_values_json TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                ticket_policy TEXT NOT NULL,
                ticket_ids_json TEXT NOT NULL DEFAULT '[]',
                note TEXT,
                created_at TEXT NOT NULL,
                activated_at TEXT,
                invalidated_at TEXT,
                invalidated_batch_id INTEGER,
                last_batch_id INTEGER,
                last_matched_at TEXT,
                applied_count INTEGER NOT NULL DEFAULT 0,
                reactivation_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(pair_id, fingerprint),
                FOREIGN KEY(pair_id) REFERENCES reconcile_pairs(id)
            );
            CREATE TABLE IF NOT EXISTS batch_suppressions(
                id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                pair_id INTEGER NOT NULL,
                diff_id INTEGER,
                fingerprint TEXT NOT NULL,
                fingerprint_state TEXT NOT NULL,
                kind TEXT NOT NULL,
                align_key_json TEXT NOT NULL,
                compare_fields_json TEXT NOT NULL,
                left_values_json TEXT,
                right_values_json TEXT,
                suppression_id INTEGER,
                reactivates_suppression_id INTEGER,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES reconcile_batches(id),
                FOREIGN KEY(pair_id) REFERENCES reconcile_pairs(id),
                FOREIGN KEY(diff_id) REFERENCES reconcile_diffs(id)
            );
            CREATE TABLE IF NOT EXISTS suppression_events(
                id INTEGER PRIMARY KEY,
                pair_id INTEGER NOT NULL,
                suppression_id INTEGER,
                batch_id INTEGER,
                fingerprint TEXT NOT NULL,
                action TEXT NOT NULL,
                fingerprint_state TEXT,
                ticket_policy TEXT,
                ticket_ids_json TEXT NOT NULL DEFAULT '[]',
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(pair_id) REFERENCES reconcile_pairs(id),
                FOREIGN KEY(batch_id) REFERENCES reconcile_batches(id)
            );
            """
        )
        _migrate(conn)
        _seed_baseline_fixtures()
        ensure_runtime_fixtures()
        if conn.execute("SELECT COUNT(*) c FROM reconcile_pairs").fetchone()["c"] == 0:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            for p in PAIR_SEEDS:
                conn.execute(
                    """
                    INSERT INTO reconcile_pairs(
                        code, title, domain, left_name, right_name,
                        left_fixture, right_fixture, align_keys_json, compare_fields_json,
                        enabled, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        p["code"],
                        p["title"],
                        p["domain"],
                        p["left_name"],
                        p["right_name"],
                        p["left_fixture"],
                        p["right_fixture"],
                        json.dumps(p["align_keys"], ensure_ascii=False),
                        json.dumps(p["compare_fields"], ensure_ascii=False),
                        p["enabled"],
                        now,
                    ),
                )
        if conn.execute("SELECT COUNT(*) c FROM endpoint_contracts").fetchone()["c"] == 0:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            for pair_code, side, fields in CONTRACT_SEEDS:
                conn.execute(
                    """
                    INSERT INTO endpoint_contracts(pair_code, side, fields_json, version, updated_at)
                    VALUES (?,?,?,?,?)
                    """,
                    (pair_code, side, json.dumps(fields, ensure_ascii=False), "v1", now),
                )
        if conn.execute("SELECT COUNT(*) c FROM settings").fetchone()["c"] == 0:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("default_policy", "record_only"),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("auto_overwrite", "false"),
            )
        conn.commit()
    finally:
        conn.close()
