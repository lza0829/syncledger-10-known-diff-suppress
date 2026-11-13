from fastapi import APIRouter

from app.routers import (
    audit,
    batches,
    contracts,
    dashboard,
    dispositions,
    pairs,
    settings,
    suppressions,
)

api = APIRouter(prefix="/api")
api.include_router(dashboard.router)
api.include_router(pairs.router)
api.include_router(batches.router)
api.include_router(dispositions.router)
api.include_router(contracts.router)
api.include_router(audit.router)
api.include_router(settings.router)
api.include_router(suppressions.router)
