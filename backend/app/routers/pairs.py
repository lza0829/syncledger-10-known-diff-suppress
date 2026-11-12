from fastapi import APIRouter

from app.services import reconcile_service as svc

router = APIRouter(tags=["pairs"])


@router.get("/pairs")
def list_pairs():
    return svc.list_pairs()
