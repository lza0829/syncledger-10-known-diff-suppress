"""Demo support: mutate the *runtime* fixture copies (source-side changes).

The shipped fixtures under ``app/fixtures`` are never touched; a frozen copy
lives under ``DATA_DIR/fixtures_baseline`` and the mutable copy under
``DATA_DIR/fixtures``.  This lets the demo show that a known suppression holds
until the source values change, without connecting to a live database.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import FIXTURES_DIR, RUNTIME_FIXTURES_DIR
from app.seed import baseline_dir, ensure_runtime_fixtures, init_db, sha256_text


class DemoError(Exception):
    def __init__(self, message: str, *, code: str = "bad_request"):
        super().__init__(message)
        self.message = message
        self.code = code


def _paths(name: str) -> tuple[Any, Any]:
    ensure_runtime_fixtures()
    from app.config import RUNTIME_FIXTURES_DIR

    runtime = RUNTIME_FIXTURES_DIR / name
    baseline = baseline_dir() / name
    if not baseline.exists():
        baseline = FIXTURES_DIR / name
    return runtime, baseline


def _read(path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise DemoError(f"fixture {path.name} 必须是 JSON 数组")
    return data


def _write(path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fixture_digests(name: str) -> dict[str, Any]:
    runtime, baseline = _paths(name)
    current = sha256_text(runtime.read_text(encoding="utf-8")) if runtime.exists() else None
    baseline_digest = sha256_text(baseline.read_text(encoding="utf-8")) if baseline.exists() else None
    return {
        "fixture": name,
        "current_digest": current,
        "baseline_digest": baseline_digest,
        "changed": current != baseline_digest,
    }


def pair_source_state(pair: dict[str, Any]) -> dict[str, Any]:
    left = fixture_digests(pair["left_fixture"])
    right = fixture_digests(pair["right_fixture"])
    return {
        "pair_id": pair["id"],
        "pair_code": pair["code"],
        "left": left,
        "right": right,
        "changed": bool(left["changed"] or right["changed"]),
    }


def _side_fixture(pair: dict[str, Any], side: str) -> str:
    if side == "left":
        return pair["left_fixture"]
    if side == "right":
        return pair["right_fixture"]
    raise DemoError("side 必须为 left 或 right")


def change_source(
    *,
    pair: dict[str, Any],
    side: str,
    align_key: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Update compared-field values on one runtime fixture row."""
    if not changes:
        raise DemoError("changes 不能为空")
    allowed = set(pair["compare_fields"])
    bad = [f for f in changes if f not in allowed]
    if bad:
        raise DemoError(
            f"仅可比对字段可改：{', '.join(sorted(allowed))}（收到 {', '.join(bad)}）"
        )

    name = _side_fixture(pair, side)
    runtime, _baseline = _paths(name)
    rows = _read(runtime)
    keys = pair["align_keys"]
    before = after = None
    for row in rows:
        if all(row.get(k) == align_key.get(k) for k in keys):
            before = dict(row)
            row.update(changes)
            after = dict(row)
            break
    if before is None:
        raise DemoError("未找到匹配该对齐键的源行", code="not_found")
    _write(runtime, rows)
    return {
        "pair_id": pair["id"],
        "side": side,
        "fixture": name,
        "align_key": align_key,
        "before": before,
        "after": after,
        "changed_fields": list(changes),
        "source_state": fixture_digests(name),
    }


def reset_source(*, pair: dict[str, Any]) -> dict[str, Any]:
    ensure_runtime_fixtures()
    restored = []
    for name in (pair["left_fixture"], pair["right_fixture"]):
        runtime, baseline = _paths(name)
        runtime.write_text(baseline.read_text(encoding="utf-8"), encoding="utf-8")
        restored.append(name)
    return {"pair_id": pair["id"], "restored": restored}


def ensure_demo_fixtures() -> None:
    init_db()
    ensure_runtime_fixtures()
