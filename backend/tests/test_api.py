from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import init_db, ensure_runtime_fixtures


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("app.config.RUNTIME_FIXTURES_DIR", tmp_path / "fixtures")
    monkeypatch.setattr("app.seed.BASELINE_DIR", tmp_path / "fixtures_baseline")
    init_db()
    ensure_runtime_fixtures()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _run(client):
    resp = client.post("/api/reconcile", json={"pair_id": 1, "wait": True})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_suppression_endpoints_round_trip(client):
    batch = _run(client)
    diff = client.get(f"/api/diffs?batch_id={batch['id']}").json()[0]

    reg = client.post("/api/suppressions", json={"diff_id": diff["id"]})
    assert reg.status_code == 200
    assert reg.json()["fingerprint"]

    overview = client.get("/api/suppressions?pair_id=1").json()
    assert overview["active_count"] == 1
    assert overview["mutations_allowed"] is True

    second = _run(client)
    assert second["suppressed_count"] == 1
    assert second["pending_count"] == second["diff_total"] - 1

    audit = client.get(f"/api/audit/batches/{second['id']}").json()
    assert audit["consistency"]["consistent"] is True
    assert audit["suppression"]["suppressed"] == 1


def test_run_in_progress_returns_409(client):
    first = _run(client)
    diff_id = client.get(f"/api/diffs?batch_id={first['id']}").json()[0]["id"]

    batch = client.post("/api/reconcile", json={"pair_id": 1, "hold_ms": 3000}).json()
    assert batch["status"] in ("extracting", "aligning")

    reg = client.post("/api/suppressions", json={"diff_id": diff_id})
    assert reg.status_code == 409
    assert reg.json()["detail"]["code"] == "run_in_progress"

    policy = client.post(
        "/api/suppressions/policy", json={"pair_id": 1, "policy": "allow_and_suspend"}
    )
    assert policy.status_code == 409

    overview = client.get("/api/suppressions?pair_id=1").json()
    assert overview["mutations_allowed"] is False
    assert overview["running"][0]["batch_no"] == batch["batch_no"]

    _run_after(client, batch["id"])


def test_ticket_conflict_endpoints(client):
    batch = _run(client)
    diff = client.get(f"/api/diffs?batch_id={batch['id']}").json()[0]

    ticket = client.post("/api/dispositions", json={"diff_id": diff["id"]})
    assert ticket.status_code == 200

    resp = client.post("/api/suppressions", json={"diff_id": diff["id"]})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "ticket_conflict"

    client.post(
        "/api/suppressions/policy",
        json={"pair_id": 1, "policy": "allow_and_suspend"},
    )
    resp = client.post("/api/suppressions", json={"diff_id": diff["id"]})
    assert resp.status_code == 200
    assert resp.json()["ticket_outcome"] == "allow_and_suspend"

    ticket_rows = client.get("/api/dispositions").json()
    assert ticket_rows[0]["status"] == "suspended_by_suppression"


def test_source_change_and_reset_endpoints(client):
    batch = _run(client)
    fm = next(
        d
        for d in client.get(f"/api/diffs?batch_id={batch['id']}").json()
        if d["kind"] == "field_mismatch"
    )
    client.post("/api/suppressions", json={"diff_id": fm["id"]})

    changed = client.post(
        "/api/demo/source-change",
        json={
            "pair_id": 1,
            "side": "right",
            "align_key": fm["align_key"],
            "changes": {"qty": fm["right"]["qty"] + 1},
        },
    )
    assert changed.status_code == 200
    assert client.get("/api/demo/source-state?pair_id=1").json()["changed"] is True

    second = _run(client)
    assert second["reactivated_count"] == 1

    reset = client.post("/api/demo/source-reset", json={"pair_id": 1})
    assert reset.status_code == 200
    assert client.get("/api/demo/source-state?pair_id=1").json()["changed"] is False


def _run_after(client, batch_id):
    import time

    deadline = time.time() + 15
    while time.time() < deadline:
        status = client.get(f"/api/batches/{batch_id}").json()["status"]
        if status not in ("extracting", "aligning"):
            break
        time.sleep(0.1)
    return client.get(f"/api/batches/{batch_id}").json()


def test_overview_lists_conflict_risk_with_align_key(client):
    batch = _run(client)
    diff = next(
        d
        for d in client.get(f"/api/diffs?batch_id={batch['id']}").json()
        if d["kind"] == "right_only"
    )
    client.post("/api/dispositions", json={"diff_id": diff["id"]})
    risk = client.get("/api/suppressions?pair_id=1").json()["open_ticket_conflicts"]
    assert risk and risk[0]["align_key"] == diff["align_key"]
    assert risk[0]["diff_kind"] == "right_only"
