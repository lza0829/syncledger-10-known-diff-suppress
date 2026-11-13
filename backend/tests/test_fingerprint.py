from __future__ import annotations

from app.engines.fingerprint import build_fingerprint


def fp(kind="field_mismatch", left=None, right=None, fields=("qty", "unit")):
    return build_fingerprint(
        kind=kind,
        align_key={"sku_id": "SKU-100", "store_id": "S01"},
        align_keys=["sku_id", "store_id"],
        compare_fields=list(fields),
        left=left,
        right=right,
    )


LEFT = {"sku_id": "SKU-100", "store_id": "S01", "qty": 120, "unit": "pcs"}
RIGHT = {"sku_id": "SKU-100", "store_id": "S01", "qty": 118, "unit": "pcs"}


def test_key_order_does_not_change_fingerprint():
    a = fp(left=LEFT, right=RIGHT)
    b = build_fingerprint(
        kind="field_mismatch",
        align_key={"store_id": "S01", "sku_id": "SKU-100"},
        align_keys=["store_id", "sku_id"],
        compare_fields=["unit", "qty"],
        left=dict(reversed(list(LEFT.items()))),
        right=dict(reversed(list(RIGHT.items()))),
    )
    assert a["fingerprint"] == b["fingerprint"]


def test_non_compared_columns_are_ignored():
    left2 = dict(LEFT, updated_at="2020-01-01T00:00:00Z")
    right2 = dict(RIGHT, updated_at="2020-01-01T00:00:00Z")
    assert fp(left=left2, right=right2)["fingerprint"] == fp(left=LEFT, right=RIGHT)["fingerprint"]


def test_any_compared_value_change_breaks_match():
    right2 = dict(RIGHT, qty=119)
    assert fp(left=LEFT, right=right2)["fingerprint"] != fp(left=LEFT, right=RIGHT)["fingerprint"]
    left2 = dict(LEFT, unit="box")
    assert fp(left=left2, right=RIGHT)["fingerprint"] != fp(left=LEFT, right=RIGHT)["fingerprint"]


def test_kind_and_align_key_are_part_of_fingerprint():
    assert fp(kind="left_only", left=LEFT)["fingerprint"] != fp(kind="right_only", right=LEFT)["fingerprint"]
    other = build_fingerprint(
        kind="field_mismatch",
        align_key={"sku_id": "SKU-100", "store_id": "S02"},
        align_keys=["sku_id", "store_id"],
        compare_fields=["qty", "unit"],
        left=LEFT,
        right=RIGHT,
    )
    assert other["fingerprint"] != fp(left=LEFT, right=RIGHT)["fingerprint"]


def test_absence_participates_in_fingerprint():
    # left_only vs a "right row that is null with same values" must differ.
    assert fp(kind="left_only", left=LEFT, right=None)["fingerprint"] != fp(
        kind="left_only", left=LEFT, right={}
    )["fingerprint"]
