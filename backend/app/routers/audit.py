from fastapi import APIRouter, HTTPException

from app.services import reconcile_service as svc

router = APIRouter(tags=["audit"])


@router.get("/audit/batches/{batch_id}")
def audit_batch(batch_id: int):
    try:
        return svc.audit_summary(batch_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
