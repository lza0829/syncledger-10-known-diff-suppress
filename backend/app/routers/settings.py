from fastapi import APIRouter

from app.services import reconcile_service as svc

router = APIRouter(tags=["settings"])


@router.get("/settings")
def get_settings():
    return svc.list_settings()
