from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import connect
from app.repositories import pairs as pair_repo
from app.repositories import tickets as ticket_repo
from app.services import reconcile_service as svc
from app.services.suppression_service import now_iso

router = APIRouter(tags=["dispositions"])


class CreateBody(BaseModel):
    diff_id: int
    title: str | None = None
    assignee: str | None = None
    note: str | None = None


@router.get("/dispositions")
def list_dispositions():
    return svc.list_dispositions()


@router.post("/dispositions")
def create_disposition(body: CreateBody):
    """Open a disposition record on a diff (demo: to exercise ticket conflicts)."""
    conn = connect()
    try:
        diff_row = conn.execute(
            "SELECT * FROM reconcile_diffs WHERE id=?", (body.diff_id,)
        ).fetchone()
        if diff_row is None:
            raise HTTPException(404, {"code": "not_found", "message": "差异行不存在"})
        diff = dict(diff_row)
        pair = pair_repo.get_pair(conn, diff["pair_id"])
        align_key = json.loads(diff["align_key_json"])
        title = body.title or (
            f"{pair['title'] if pair else '差异'} · {diff['kind']} · "
            f"{json.dumps(align_key, ensure_ascii=False, sort_keys=True)}"
        )
        ticket_id = ticket_repo.create_ticket(
            conn,
            pair_id=diff["pair_id"],
            diff_id=body.diff_id,
            title=title,
            assignee=body.assignee,
            note=body.note,
            created_at=now_iso(),
        )
        conn.commit()
        return ticket_repo.get_ticket(conn, ticket_id)
    finally:
        conn.close()
