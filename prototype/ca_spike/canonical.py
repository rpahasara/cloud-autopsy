"""Canonical JSON encoding and digests (ca-canon/0.1-spike).

Rules: UTF-8; object keys sorted by Unicode code point; no insignificant whitespace;
integers, strings, booleans, null, arrays and objects only. Floats, NaN/Infinity and
duplicate keys are rejected; decimals are carried as strings. Strings are not
Unicode-normalized, so the raw source text is preserved.
"""

import hashlib
import json

CANON_VERSION = "ca-canon/0.1-spike"


class CanonicalError(ValueError):
    pass


def _reject_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise CanonicalError(f"duplicate key: {key!r}")
        obj[key] = value
    return obj


def _reject_float(text):
    raise CanonicalError(f"float not permitted: {text}")


def _reject_constant(text):
    raise CanonicalError(f"non-finite constant not permitted: {text}")


def loads_strict(data, max_bytes=None):
    """Parse untrusted JSON bytes, rejecting oversize input, duplicate keys and floats."""
    if not isinstance(data, (bytes, bytearray)):
        raise CanonicalError("input must be bytes")
    if max_bytes is not None and len(data) > max_bytes:
        raise CanonicalError(f"input exceeds {max_bytes} bytes")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalError(f"invalid UTF-8: {exc}") from None
    if text.startswith("﻿"):
        raise CanonicalError("byte-order mark not permitted")
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicates,
                          parse_float=_reject_float, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise CanonicalError(f"malformed JSON: {exc}") from None


def _check(value, path="$"):
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise CanonicalError(f"unencodable string at {path}") from None
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise CanonicalError(f"float not permitted at {path}")
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _check(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError(f"non-string key at {path}")
            _check(item, f"{path}.{key}")
        return
    raise CanonicalError(f"unsupported type {type(value).__name__} at {path}")


def canonical_bytes(value):
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    """Return a prefixed SHA-256 digest of the canonical encoding."""
    return "sha256:" + sha256_hex(canonical_bytes(value))
