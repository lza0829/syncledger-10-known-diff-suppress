"""Known-difference fingerprints.

A fingerprint identifies a *particular* difference, not merely its row key:
kind + align key + a digest of the values of every compared field on both
sides.  If either side changes any compared value, the digest changes and the
fingerprint no longer matches, so a known-suppression expires.

Non-compared columns (e.g. ``updated_at``) deliberately do not participate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def canonical(obj: Any) -> str:
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def align_key_object(align_key: dict[str, Any], align_keys: Iterable[str] | None = None) -> dict[str, Any]:
    """Return the align-key object in a stable, complete shape."""
    if align_keys is None:
        return {str(k): align_key[k] for k in sorted(align_key)}
    return {k: align_key.get(k) for k in align_keys}


def field_values(row: dict[str, Any] | None, compare_fields: Iterable[str]) -> dict[str, Any] | None:
    if row is None:
        return None
    return {f: row.get(f) for f in compare_fields}


def build_fingerprint(
    *,
    kind: str,
    align_key: dict[str, Any],
    align_keys: Iterable[str] | None,
    compare_fields: Iterable[str],
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build fingerprint metadata for one observed difference state.

    The returned dict carries the public fingerprint plus the components it
    was derived from, so the registry/list can explain exactly what changed.
    ``kind`` is part of the fingerprint: a left_only row turning into a
    field_mismatch is a different difference.
    """
    fields = list(compare_fields)
    key_obj = align_key_object(align_key, align_keys)
    left_values = field_values(left, fields)
    right_values = field_values(right, fields)
    values_payload = canonical(
        {
            "compare_fields": sorted(fields),
            "left": left_values,
            "right": right_values,
        }
    )
    values_digest = sha256_text(values_payload)
    fingerprint = sha256_text(
        canonical(
            {
                "kind": kind,
                "align_key": key_obj,
                "values_digest": values_digest,
            }
        )
    )
    return {
        "fingerprint": fingerprint,
        "values_digest": values_digest,
        "align_key": key_obj,
        "compare_fields": fields,
        "left_values": left_values,
        "right_values": right_values,
    }


def fingerprint_short(fingerprint: str, width: int = 12) -> str:
    return fingerprint[:width]


def row_fingerprints(
    diffs: list[dict[str, Any]],
    *,
    align_keys: list[str],
    compare_fields: list[str],
) -> list[str]:
    """Fingerprint every diff in order-independent fashion."""
    return [
        build_fingerprint(
            kind=diff["kind"],
            align_key=diff["align_key"],
            align_keys=align_keys,
            compare_fields=compare_fields,
            left=diff.get("left"),
            right=diff.get("right"),
        )["fingerprint"]
        for diff in diffs
    ]
