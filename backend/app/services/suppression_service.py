"""Known-difference suppression: registration, conflict policy, run-time application.

Invariants enforced here:

* A suppression is keyed by a *fingerprint* (kind + align key + digest of every
  compared field value on both sides), never by row key alone.
* A run never deletes, rewrites, or hides historical diffs.  A suppressed diff
  is still persisted in the batch, flagged ``suppressed``, and counted in the
  batch's ``suppressed_count`` so batch totals stay additive and checkable.
* If either side's compared values change, the fingerprint changes; during the
  next run the old suppression is invalidated and the diff is re-activated as
  pending (``reactivated_count``).
* Open disposition tickets on the same difference block registration when the
  pair policy is ``reject``; when the pair policy is ``allow_and_suspend`` the
  tickets are suspended automatically.  The two policies are mutually
  exclusive per pair.
* While a batch for the pair is in extraction/alignment, registrations and
  revocations are refused.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlite3

from app.engines.fingerprint import build_fingerprint
from app.repositories import batches as batch_repo
from app.repositories import pairs as pair_repo
from app.repositories import suppressions as suppression_repo

POLICY_REJECT = "reject"
POLICY_ALLOW = "allow_and_suspend"
POLICIES = (POLICY_REJECT, POLICY_ALLOW)
POLICY_LABELS = {
    POLICY_REJECT: "拒绝抑制：差异仍有未关处置单时不允许登记",
    POLICY_ALLOW: "允许抑制：未关处置单自动挂起（suspended_by_suppression）",
}

RUNNING_STATUSES = ("extracting", "aligning")
BATCH_STATUS_EXTRACTING = "extracting"
BATCH_STATUS_ALIGNING = "aligning"
BATCH_STATUS_COMPLETED = "completed"
BATCH_STATUS_FAILED = "failed"

OPEN_TICKET_STATUSES = ("open", "claimed", "in_progress")
TICKET_STATUS_SUSPENDED = "suspended_by_suppression"

RUN_STALE_SECONDS = 900

_pair_locks: dict[int, threading.Lock] = {}
_pair_locks_guard = threading.Lock()


class SuppressionError(Exception):
    """Business-rule violation carrying an HTTP-friendly shape."""

    def __init__(self, message: str, *, code: str = "conflict", extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra or {}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pair_lock(pair_id: int) -> threading.Lock:
    with _pair_locks_guard:
        lock = _pair_locks.get(pair_id)
        if lock is None:
            lock = threading.Lock()
            _pair_locks[pair_id] = lock
        return lock


def policy_for(pair: dict[str, Any]) -> str:
    policy = pair.get("suppression_ticket_policy") or POLICY_REJECT
    return policy if policy in POLICIES else POLICY_REJECT


def policy_label(policy: str) -> str:
    return POLICY_LABELS.get(policy, policy)


def reap_stale_runs(conn: sqlite3.Connection, pair_id: int | None = None) -> None:
    """Mark abandoned in-flight batches failed so they cannot block edits forever."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=RUN_STALE_SECONDS)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sql = "UPDATE reconcile_batches SET status=? WHERE status IN ('extracting','aligning') AND created_at < ?"
    args: list[Any] = [BATCH_STATUS_FAILED, cutoff]
    if pair_id is not None:
        sql += " AND pair_id=?"
        args.append(pair_id)
    conn.execute(sql, args)
    conn.commit()


def running_batches(conn: sqlite3.Connection, pair_id: int) -> list[dict[str, Any]]:
    reap_stale_runs(conn, pair_id)
    rows = conn.execute(
        """
        SELECT * FROM reconcile_batches
         WHERE pair_id=? AND status IN ('extracting','aligning')
         ORDER BY id
        """,
        (pair_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def guard_no_run(conn: sqlite3.Connection, pair_id: int, action: str) -> None:
    runs = running_batches(conn, pair_id)
    if runs:
        b = runs[0]
        raise SuppressionError(
            f"对账批次 {b['batch_no']} 正处于 {b['status']} 阶段，禁止{action}抑制（避免本趟统计中途被改）",
            code="run_in_progress",
            extra={"batch_no": b["batch_no"], "batch_status": b["status"]},
        )


def diff_fingerprint(
    pair: dict[str, Any],
    *,
    kind: str,
    align_key: dict[str, Any],
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    return build_fingerprint(
        kind=kind,
        align_key=align_key,
        align_keys=pair["align_keys"],
        compare_fields=pair["compare_fields"],
        left=left,
        right=right,
    )


def _key_identity(align_key: dict[str, Any], align_keys: list[str]) -> str:
    return json.dumps(
        {k: align_key.get(k) for k in align_keys}, ensure_ascii=False, sort_keys=True, default=str
    )


def ticket_conflicts(
    conn: sqlite3.Connection,
    *,
    pair_id: int,
    kind: str,
    align_key: dict[str, Any],
) -> list[dict[str, Any]]:
    """Open disposition tickets on the same difference (kind + align key)."""
    placeholders = ",".join("?" for _ in OPEN_TICKET_STATUSES)
    rows = conn.execute(
        f"""
        SELECT t.*, d.kind AS diff_kind, d.align_key_json AS diff_align_key_json
          FROM diff_tickets t
          JOIN reconcile_diffs d ON d.id = t.diff_id
         WHERE t.pair_id = ? AND t.status IN ({placeholders})
        """,
        (pair_id, *OPEN_TICKET_STATUSES),
    ).fetchall()
    wanted = _key_identity(align_key, sorted(align_key))
    out = []
    for r in rows:
        if r["diff_kind"] != kind:
            continue
        stored = json.loads(r["diff_align_key_json"])
        if _key_identity(stored, sorted(stored)) != wanted:
            continue
        d = dict(r)
        d.pop("diff_kind", None)
        d.pop("diff_align_key_json", None)
        out.append(d)
    return out


def _restore_suspended_tickets(
    conn: sqlite3.Connection, suppression: dict[str, Any], *, at: str
) -> list[int]:
    """Un-suspend tickets this suppression had parked, now that it expired."""
    restored: list[int] = []
    for ticket_id in suppression.get("ticket_ids") or []:
        row = conn.execute("SELECT status FROM diff_tickets WHERE id=?", (ticket_id,)).fetchone()
        if row is not None and row["status"] == TICKET_STATUS_SUSPENDED:
            conn.execute(
                "UPDATE diff_tickets SET status='open', updated_at=? WHERE id=?", (at, ticket_id)
            )
            restored.append(int(ticket_id))
    return restored


def register(
    conn: sqlite3.Connection, *, diff_id: int, note: str | None = None
) -> dict[str, Any]:
    """Register the known-difference fingerprint of an existing diff row."""
    row = conn.execute("SELECT * FROM reconcile_diffs WHERE id=?", (diff_id,)).fetchone()
    if row is None:
        raise SuppressionError("差异行不存在", code="not_found")
    diff = dict(row)
    diff["align_key"] = json.loads(diff.pop("align_key_json"))
    diff["left"] = json.loads(diff["left_json"]) if diff.get("left_json") else None
    diff["right"] = json.loads(diff["right_json"]) if diff.get("right_json") else None
    pair = pair_repo.get_pair(conn, diff["pair_id"])
    if pair is None:
        raise SuppressionError("对账对不存在", code="not_found")
    policy = policy_for(pair)

    with pair_lock(pair["id"]):
        guard_no_run(conn, pair["id"], "登记")

        meta = diff_fingerprint(
            pair,
            kind=diff["kind"],
            align_key=diff["align_key"],
            left=diff["left"],
            right=diff["right"],
        )
        existing = suppression_repo.get_active_by_fingerprint(conn, pair["id"], meta["fingerprint"])
        if existing is not None:
            raise SuppressionError(
                "该差异指纹已在抑制中，无需重复登记",
                code="already_suppressed",
                extra={"suppression_id": existing["id"]},
            )

        conflicts = ticket_conflicts(
            conn, pair_id=pair["id"], kind=diff["kind"], align_key=meta["align_key"]
        )
        at = now_iso()
        if conflicts and policy == POLICY_REJECT:
            suppression_repo.insert_event(
                conn,
                pair_id=pair["id"],
                suppression_id=None,
                batch_id=diff["batch_id"],
                fingerprint=meta["fingerprint"],
                action="register_rejected_ticket_conflict",
                fingerprint_state=None,
                ticket_policy=policy,
                ticket_ids=[int(t["id"]) for t in conflicts],
                note=note,
                created_at=at,
            )
            conn.commit()
            raise SuppressionError(
                "对应差异仍有未关闭处置单，当前策略为「拒绝抑制」；本次未登记",
                code="ticket_conflict",
                extra={
                    "ticket_policy": policy,
                    "policy_label": policy_label(policy),
                    "tickets": [
                        {"id": t["id"], "title": t["title"], "status": t["status"]}
                        for t in conflicts
                    ],
                },
            )

        suspended_ids: list[int] = []
        for t in conflicts:
            display = f"已知差异抑制自动挂起（指纹 {meta['fingerprint'][:12]}）"
            conn.execute(
                """
                UPDATE diff_tickets
                   SET status=?, updated_at=?,
                       note = CASE WHEN note IS NULL OR note='' THEN ? ELSE note || ' / ' || ? END
                 WHERE id=?
                """,
                (TICKET_STATUS_SUSPENDED, at, display, display, t["id"]),
            )
            suspended_ids.append(int(t["id"]))

        suppression_id, reused = suppression_repo.upsert_active_suppression(
            conn,
            pair_id=pair["id"],
            fingerprint=meta["fingerprint"],
            kind=diff["kind"],
            align_key=meta["align_key"],
            compare_fields=meta["compare_fields"],
            values_digest=meta["values_digest"],
            left_values=meta["left_values"],
            right_values=meta["right_values"],
            ticket_policy=policy,
            ticket_ids=suspended_ids,
            note=note,
            created_at=at,
        )
        suppression_repo.mark_matched(
            conn, suppression_id=suppression_id, batch_id=diff["batch_id"], at=at
        )
        suppression_repo.insert_event(
            conn,
            pair_id=pair["id"],
            suppression_id=suppression_id,
            batch_id=diff["batch_id"],
            fingerprint=meta["fingerprint"],
            action="registered",
            fingerprint_state=None,
            ticket_policy=policy,
            ticket_ids=suspended_ids,
            note=note,
            created_at=at,
        )
        conn.commit()
        return {
            "registered": True,
            "suppression_id": suppression_id,
            "reused_existing": reused,
            "fingerprint": meta["fingerprint"],
            "kind": diff["kind"],
            "align_key": meta["align_key"],
            "values_digest": meta["values_digest"],
            "values": {"left": meta["left_values"], "right": meta["right_values"]},
            "ticket_policy": policy,
            "policy_label": policy_label(policy),
            "suspended_ticket_ids": suspended_ids,
            "ticket_outcome": "allow_and_suspend" if suspended_ids else "no_open_tickets",
        }


def revoke(conn: sqlite3.Connection, *, suppression_id: int, note: str | None = None) -> dict[str, Any]:
    suppression = suppression_repo.get_suppression(conn, suppression_id)
    if suppression is None:
        raise SuppressionError("抑制登记不存在", code="not_found")
    if suppression["status"] != suppression_repo.SUPPRESSION_ACTIVE:
        raise SuppressionError(
            f"仅可撤销生效中的抑制（当前状态：{suppression['status']}）", code="not_active"
        )
    with pair_lock(suppression["pair_id"]):
        guard_no_run(conn, suppression["pair_id"], "撤销")
        at = now_iso()
        restored = _restore_suspended_tickets(conn, suppression, at=at)
        suppression_repo.mark_revoked(conn, suppression_id=suppression_id, at=at)
        suppression_repo.insert_event(
            conn,
            pair_id=suppression["pair_id"],
            suppression_id=suppression_id,
            batch_id=None,
            fingerprint=suppression["fingerprint"],
            action="revoked",
            fingerprint_state=None,
            ticket_policy=suppression["ticket_policy"],
            ticket_ids=restored,
            note=note,
            created_at=at,
        )
        conn.commit()
        return {"revoked": True, "suppression_id": suppression_id, "restored_ticket_ids": restored}


def set_policy(conn: sqlite3.Connection, *, pair_id: int, policy: str) -> dict[str, Any]:
    if policy not in POLICIES:
        raise SuppressionError(
            f"未知的处置单策略：{policy}；仅支持 {', '.join(POLICIES)}", code="bad_policy"
        )
    if pair_repo.get_pair(conn, pair_id) is None:
        raise SuppressionError("对账对不存在", code="not_found")
    with pair_lock(pair_id):
        guard_no_run(conn, pair_id, "修改策略")
        conn.execute(
            "UPDATE reconcile_pairs SET suppression_ticket_policy=? WHERE id=?", (policy, pair_id)
        )
        conn.commit()
    return {"pair_id": pair_id, "policy": policy, "label": policy_label(policy)}


def apply_to_batch(
    conn: sqlite3.Connection,
    *,
    pair: dict[str, Any],
    batch_id: int,
    diffs: list[dict[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    """Flag persisted diffs as suppressed / reactivated for one run.

    ``diffs`` items are engine dicts plus the persisted ``diff_id``.  Diff rows
    are otherwise untouched; suppressed ones stay in the batch and its totals.

    Rules:
    * Suppress only on an exact fingerprint match.  A diff on the same align
      key whose values differ (or whose kind changed) is NOT suppressed: the
      stale suppression for that key is invalidated and the row is re-activated.
    * Active suppressions whose align key does not appear in this run are
      reported as "not observed" but left active (the row may return later;
      only an observed value change is proof that the known diff changed).
    """
    active = suppression_repo.list_active(conn, pair["id"])
    active_by_fp = {s["fingerprint"]: s for s in active}
    active_by_key: dict[str, list[dict[str, Any]]] = {}
    for s in active:
        active_by_key.setdefault(
            _key_identity(s["align_key"], pair["align_keys"]), []
        ).append(s)

    used: set[str] = set()
    suppressed = 0
    reactivated = 0
    reactivated_details: list[dict[str, Any]] = []
    not_observed: list[int] = []

    def _invalidate_stale(stale: list[dict[str, Any]], meta: dict[str, Any], diff: dict[str, Any]):
        nonlocal reactivated
        if not stale:
            return
        for s in stale:
            used.add(s["fingerprint"])
            suppression_repo.mark_invalidated(
                conn, suppression_id=s["id"], batch_id=batch_id, at=created_at
            )
            restored = _restore_suspended_tickets(conn, s, at=created_at)
            suppression_repo.insert_event(
                conn,
                pair_id=pair["id"],
                suppression_id=s["id"],
                batch_id=batch_id,
                fingerprint=s["fingerprint"],
                action="invalidated_fingerprint_changed",
                fingerprint_state=suppression_repo.BATCH_STATE_REACTIVATED,
                ticket_policy=s["ticket_policy"],
                ticket_ids=restored,
                note=(
                    f"指纹 {s['fingerprint'][:12]} → {meta['fingerprint'][:12]}"
                    f"（{s['kind']} → {diff['kind']}）"
                ),
                created_at=created_at,
            )
            reactivated_details.append(
                {
                    "suppression_id": s["id"],
                    "old_fingerprint": s["fingerprint"],
                    "new_fingerprint": meta["fingerprint"],
                    "old_kind": s["kind"],
                    "new_kind": diff["kind"],
                    "align_key": meta["align_key"],
                }
            )
        reactivated += 1
        conn.execute(
            "UPDATE reconcile_diffs SET suppression_state='reactivated' WHERE id=?",
            (diff["diff_id"],),
        )
        suppression_repo.insert_batch_application(
            conn,
            batch_id=batch_id,
            pair_id=pair["id"],
            diff_id=diff["diff_id"],
            fingerprint=meta["fingerprint"],
            fingerprint_state=suppression_repo.BATCH_STATE_REACTIVATED,
            kind=diff["kind"],
            align_key=meta["align_key"],
            compare_fields=meta["compare_fields"],
            left_values=meta["left_values"],
            right_values=meta["right_values"],
            suppression_id=None,
            reactivates_suppression_id=stale[0]["id"],
            note=None,
            created_at=created_at,
        )

    for diff in diffs:
        meta = diff_fingerprint(
            pair,
            kind=diff["kind"],
            align_key=diff["align_key"],
            left=diff["left"],
            right=diff["right"],
        )
        diff["fingerprint"] = meta["fingerprint"]
        diff["values_digest"] = meta["values_digest"]

        match = active_by_fp.get(meta["fingerprint"])
        if match is not None and match["fingerprint"] not in used:
            used.add(match["fingerprint"])
            suppressed += 1
            conn.execute(
                """
                UPDATE reconcile_diffs
                   SET fingerprint=?, values_digest=?, suppression_state='suppressed', suppression_id=?
                 WHERE id=?
                """,
                (meta["fingerprint"], meta["values_digest"], match["id"], diff["diff_id"]),
            )
            suppression_repo.insert_batch_application(
                conn,
                batch_id=batch_id,
                pair_id=pair["id"],
                diff_id=diff["diff_id"],
                fingerprint=meta["fingerprint"],
                fingerprint_state=suppression_repo.BATCH_STATE_SUPPRESSED,
                kind=diff["kind"],
                align_key=meta["align_key"],
                compare_fields=meta["compare_fields"],
                left_values=meta["left_values"],
                right_values=meta["right_values"],
                suppression_id=match["id"],
                reactivates_suppression_id=None,
                note=None,
                created_at=created_at,
            )
            suppression_repo.mark_matched(
                conn, suppression_id=match["id"], batch_id=batch_id, at=created_at
            )
            continue

        conn.execute(
            "UPDATE reconcile_diffs SET fingerprint=?, values_digest=?, suppression_state='pending' WHERE id=?",
            (meta["fingerprint"], meta["values_digest"], diff["diff_id"]),
        )

        key_id = _key_identity(meta["align_key"], pair["align_keys"])
        stale = [
            s for s in active_by_key.get(key_id, []) if s["fingerprint"] not in used
        ]
        _invalidate_stale(stale, meta, diff)

    for s in active:
        if s["fingerprint"] not in used:
            not_observed.append(s["id"])

    conn.execute(
        "UPDATE reconcile_batches SET suppressed_count=?, reactivated_count=? WHERE id=?",
        (suppressed, reactivated, batch_id),
    )
    return {
        "suppressed": suppressed,
        "reactivated": reactivated,
        "reactivated_details": reactivated_details,
        "active_suppressions_not_observed": not_observed,
    }


def _registration_risk_summary(
    conn: sqlite3.Connection, pair: dict[str, Any]
) -> list[dict[str, Any]]:
    """Which latest-batch diffs would hit an open ticket if registered now."""
    rows = conn.execute(
        """
        SELECT t.id AS ticket_id, t.title, t.status, t.diff_id,
               d.kind AS diff_kind, d.align_key_json AS diff_align_key_json
          FROM diff_tickets t
          JOIN reconcile_diffs d ON d.id = t.diff_id
         WHERE t.pair_id=?
           AND t.status IN ('open','claimed','in_progress')
         ORDER BY t.id
        """,
        (pair["id"],),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["align_key"] = json.loads(d.pop("diff_align_key_json"))
        out.append(d)
    return out


def overview(conn: sqlite3.Connection, pair_id: int) -> dict[str, Any]:
    pair = pair_repo.get_pair(conn, pair_id)
    if pair is None:
        raise SuppressionError("对账对不存在", code="not_found")
    policy = policy_for(pair)
    runs = running_batches(conn, pair_id)
    items = suppression_repo.list_suppressions(conn, pair_id=pair_id)
    events = suppression_repo.list_events(conn, pair_id=pair_id, limit=40)

    last_batch = conn.execute(
        "SELECT * FROM reconcile_batches WHERE pair_id=? ORDER BY id DESC LIMIT 1", (pair_id,)
    ).fetchone()
    latest_diffs: list[dict[str, Any]] = []
    applications: list[dict[str, Any]] = []
    if last_batch is not None:
        latest_diffs = batch_repo.list_diffs(conn, batch_id=last_batch["id"], limit=100000)
        applications = suppression_repo.list_batch_applications(conn, batch_id=last_batch["id"])

    suppressed_total = 0
    reactivated_total = 0
    for b in conn.execute(
        "SELECT suppressed_count, reactivated_count FROM reconcile_batches WHERE pair_id=?",
        (pair_id,),
    ).fetchall():
        suppressed_total += b["suppressed_count"] or 0
        reactivated_total += b["reactivated_count"] or 0

    latest_counts = None
    if last_batch is not None:
        lb = dict(last_batch)
        latest_counts = {
            "diff_total": lb["diff_total"],
            "suppressed": lb["suppressed_count"],
            "reactivated": lb["reactivated_count"],
            "pending": lb["diff_total"] - lb["suppressed_count"],
        }

    risk = _registration_risk_summary(conn, pair)
    return {
        "pair": pair,
        "policy": policy,
        "policy_label": policy_label(policy),
        "policies": [{"value": p, "label": policy_label(p)} for p in POLICIES],
        "open_ticket_conflicts": risk,
        "running": [
            {"batch_no": b["batch_no"], "status": b["status"], "created_at": b["created_at"]}
            for b in runs
        ],
        "mutations_allowed": not runs,
        "active_count": suppression_repo.active_count(conn, pair_id),
        "suppressions": items,
        "events": events,
        "latest_batch": dict(last_batch) if last_batch is not None else None,
        "latest_counts": latest_counts,
        "latest_diffs": latest_diffs,
        "latest_batch_applications": applications,
        "totals": {
            "suppressed": suppressed_total,
            "reactivated": reactivated_total,
            "active": suppression_repo.active_count(conn, pair_id),
        },
    }
