from fastapi import APIRouter

from app.services import reconcile_service as svc

router = APIRouter(tags=["contracts"])


@router.get("/contracts")
def list_contracts():
    return svc.list_contracts()
