from fastapi import APIRouter

from app.services import reconcile_service as svc

router = APIRouter(tags=["dispositions"])


@router.get("/dispositions")
def list_dispositions():
    return svc.list_dispositions()
