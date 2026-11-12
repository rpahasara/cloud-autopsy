"""Kubernetes resourceVersion comparison for the watch continuity proof (CA-P2-004f, F3 rev. 2).

Basis: the Kubernetes v1.37 API documentation, as reviewed by the product owner (2026-11-12): the
resourceVersions of objects of the **same resource type** are ordered and may be compared as
**arbitrary-size decimal integers**. Recordings and batch coverage bases name this rule as
``RV_COMPARISON``.

Rules:
- a valid value is a non-empty ASCII decimal string with no leading zero (``[1-9][0-9]*``);
  values are never converted to a fixed-width integer;
- comparison: the longer string is greater; strings of equal length compare lexicographically
  (for such strings that is numeric order);
- values are compared only within one resource type and one collector session. This module
  compares two strings; callers keep values of different types or sessions apart and never pass
  them here together;
- a separate input limit, ``MAX_RV_CHARS`` (the evidence contract's ``source_version`` bound),
  bounds memory and parsing: a longer value is refused (fail closed). It does not describe what an
  API server may send.

resourceVersions never order evidence and never set chronology: the engine and the time contract
do not use this module.
"""

import re

RV_COMPARISON = "k8s-1.37-decimal"
MAX_RV_CHARS = 128
_DECIMAL = re.compile(r"[1-9][0-9]*", re.ASCII)


class ResourceVersionError(ValueError):
    """A value is not a comparable resourceVersion. ``code`` is fixed; the value is never echoed."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def is_valid(value):
    return isinstance(value, str) and 0 < len(value) <= MAX_RV_CHARS and _DECIMAL.fullmatch(value) is not None


def check(value):
    """Return ``value`` when it is a valid, comparable resourceVersion; raise otherwise."""
    if not isinstance(value, str) or not value:
        raise ResourceVersionError("rv_missing")
    if len(value) > MAX_RV_CHARS:
        raise ResourceVersionError("rv_too_long")
    if not _DECIMAL.fullmatch(value):
        raise ResourceVersionError("rv_not_decimal")
    return value


def compare(a, b):
    """-1, 0 or 1 as ``a`` is below, equal to or above ``b`` (both must be valid)."""
    check(a)
    check(b)
    if len(a) != len(b):
        return -1 if len(a) < len(b) else 1
    if a == b:
        return 0
    return -1 if a < b else 1


def at_least(a, b):
    """True when ``a`` >= ``b``."""
    return compare(a, b) >= 0
