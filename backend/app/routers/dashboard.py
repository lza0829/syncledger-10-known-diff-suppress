from fastapi import APIRouter

from app.services import reconcile_service as svc

router = APIRouter(tags=["dashboard"])


@router.get("/health")
def health():
    return {"ok": True, "project": "syncledger"}


@router.get("/dashboard")
def dashboard():
    return svc.dashboard_stats()
