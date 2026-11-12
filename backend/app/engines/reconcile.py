"""Align two endpoint snapshots by composite key and classify diffs.

Base behavior: record mismatches only — never auto-overwrite either side.
"""

from __future__ import annotations

from typing import Any


DIFF_LEFT_ONLY = "left_only"
DIFF_RIGHT_ONLY = "right_only"
DIFF_FIELD_MISMATCH = "field_mismatch"
DIFF_MATCHED = "matched"


def _key_tuple(row: dict[str, Any], align_keys: list[str]) -> tuple:
    return tuple(row.get(k) for k in align_keys)


def _index(rows: list[dict[str, Any]], align_keys: list[str]) -> dict[tuple, dict[str, Any]]:
    out: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        out[_key_tuple(row, align_keys)] = row
    return out


def compare_sides(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    *,
    align_keys: list[str],
    compare_fields: list[str],
) -> dict[str, Any]:
    left_idx = _index(left_rows, align_keys)
    right_idx = _index(right_rows, align_keys)
    all_keys = sorted(set(left_idx) | set(right_idx), key=lambda t: tuple(str(x) for x in t))

    diffs: list[dict[str, Any]] = []
    counts = {
        "left_rows": len(left_rows),
        "right_rows": len(right_rows),
        "matched": 0,
        "left_only": 0,
        "right_only": 0,
        "field_mismatch": 0,
        "diff_total": 0,
    }

    for key in all_keys:
        left = left_idx.get(key)
        right = right_idx.get(key)
        key_obj = {k: key[i] for i, k in enumerate(align_keys)}
        if left is not None and right is None:
            counts["left_only"] += 1
            diffs.append(
                {
                    "kind": DIFF_LEFT_ONLY,
                    "align_key": key_obj,
                    "left": left,
                    "right": None,
                    "mismatched_fields": [],
                }
            )
        elif right is not None and left is None:
            counts["right_only"] += 1
            diffs.append(
                {
                    "kind": DIFF_RIGHT_ONLY,
                    "align_key": key_obj,
                    "left": None,
                    "right": right,
                    "mismatched_fields": [],
                }
            )
        else:
            mismatched = [
                f
                for f in compare_fields
                if (left or {}).get(f) != (right or {}).get(f)
            ]
            if mismatched:
                counts["field_mismatch"] += 1
                diffs.append(
                    {
                        "kind": DIFF_FIELD_MISMATCH,
                        "align_key": key_obj,
                        "left": left,
                        "right": right,
                        "mismatched_fields": mismatched,
                    }
                )
            else:
                counts["matched"] += 1

    counts["diff_total"] = (
        counts["left_only"] + counts["right_only"] + counts["field_mismatch"]
    )
    return {"counts": counts, "diffs": diffs}
