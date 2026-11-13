from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import reconcile_service as svc

router = APIRouter(tags=["batches"])


class RunBody(BaseModel):
    pair_id: int
    note: str | None = None
    # Demo-only: hold the extract/align phases so the "edits locked while
    # running" rule can be observed in the UI.  Capped in the worker.
    hold_ms: int | None = None
    wait: bool = False


@router.get("/batches")
def list_batches(limit: int = 50):
    return svc.list_batches(limit=limit)


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int):
    try:
        return svc.get_batch(batch_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/diffs")
def list_diffs(batch_id: int | None = None, pair_id: int | None = None):
    return svc.list_diffs(batch_id=batch_id, pair_id=pair_id)


@router.post("/reconcile")
def run_reconcile(body: RunBody):
    try:
        if body.wait:
            return svc.run_reconcile(body.pair_id, body.note, body.hold_ms)
        return svc.start_reconcile(body.pair_id, body.note, body.hold_ms)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
