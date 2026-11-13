from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import connect
from app.repositories import pairs as pair_repo
from app.services import demo_service
from app.services import suppression_service as svc

router = APIRouter(tags=["suppressions"])


def _http(e: svc.SuppressionError) -> HTTPException:
    status = 404 if e.code == "not_found" else 400
    if e.code == "run_in_progress":
        status = 409
    detail = {"code": e.code, "message": e.message, **e.extra}
    return HTTPException(status, detail)


class RegisterBody(BaseModel):
    diff_id: int
    note: str | None = None


class RevokeBody(BaseModel):
    note: str | None = None


class PolicyBody(BaseModel):
    pair_id: int
    policy: str = Field(description="reject | allow_and_suspend")


class SourceChangeBody(BaseModel):
    pair_id: int
    side: str
    align_key: dict
    changes: dict


class ResetSourceBody(BaseModel):
    pair_id: int


@router.get("/suppressions")
def overview(pair_id: int):
    conn = connect()
    try:
        return svc.overview(conn, pair_id)
    except svc.SuppressionError as e:
        raise _http(e) from e
    finally:
        conn.close()


@router.post("/suppressions")
def register(body: RegisterBody):
    conn = connect()
    try:
        return svc.register(conn, diff_id=body.diff_id, note=body.note)
    except svc.SuppressionError as e:
        raise _http(e) from e
    finally:
        conn.close()


@router.post("/suppressions/{suppression_id}/revoke")
def revoke(suppression_id: int, body: RevokeBody | None = None):
    conn = connect()
    try:
        return svc.revoke(
            conn, suppression_id=suppression_id, note=(body.note if body else None)
        )
    except svc.SuppressionError as e:
        raise _http(e) from e
    finally:
        conn.close()


@router.post("/suppressions/policy")
def set_policy(body: PolicyBody):
    conn = connect()
    try:
        return svc.set_policy(conn, pair_id=body.pair_id, policy=body.policy)
    except svc.SuppressionError as e:
        raise _http(e) from e
    finally:
        conn.close()


@router.post("/demo/source-change")
def demo_source_change(body: SourceChangeBody):
    conn = connect()
    try:
        pair = pair_repo.get_pair(conn, body.pair_id)
        if pair is None:
            raise demo_service.DemoError("对账对不存在", code="not_found")
        return demo_service.change_source(
            pair=pair, side=body.side, align_key=body.align_key, changes=body.changes
        )
    except demo_service.DemoError as e:
        raise HTTPException(
            404 if e.code == "not_found" else 400, {"code": e.code, "message": e.message}
        ) from e
    finally:
        conn.close()


@router.post("/demo/source-reset")
def demo_source_reset(body: ResetSourceBody):
    conn = connect()
    try:
        pair = pair_repo.get_pair(conn, body.pair_id)
        if pair is None:
            raise demo_service.DemoError("对账对不存在", code="not_found")
        return demo_service.reset_source(pair=pair)
    except demo_service.DemoError as e:
        raise HTTPException(
            404 if e.code == "not_found" else 400, {"code": e.code, "message": e.message}
        ) from e
    finally:
        conn.close()


@router.get("/demo/source-state")
def demo_source_state(pair_id: int):
    conn = connect()
    try:
        pair = pair_repo.get_pair(conn, pair_id)
        if pair is None:
            raise demo_service.DemoError("对账对不存在", code="not_found")
        return demo_service.pair_source_state(pair)
    except demo_service.DemoError as e:
        raise HTTPException(
            404 if e.code == "not_found" else 400, {"code": e.code, "message": e.message}
        ) from e
    finally:
        conn.close()
