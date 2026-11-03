"""Canonical JSON profile ``ca-jcs-profile/0.1-provisional`` (CA-P2-002a).

A restricted profile intended to be compatible with RFC 8785 (JSON Canonicalization Scheme)
for the values it accepts. Full RFC 8785 conformance is not claimed: the profile accepts
only integers, and its vectors have not yet been independently reviewed.

Accepted values: null, true, false, strings, integers within +/-(2**53 - 1), arrays and
objects with string keys. Larger integers and decimals must be carried as strings and
validated by the schema that defines the field.

Rejected (stable reason codes in ``errors``): input that is not bytes, documents over the
byte ceiling, a UTF-8 byte-order mark, invalid UTF-8, malformed JSON, duplicate object keys
(compared after unescaping), any number with a fraction or exponent, NaN/Infinity,
out-of-range integers, lone surrogates in strings or keys, nesting deeper than the depth
ceiling and documents with more values than the node ceiling.

Canonical form: no insignificant whitespace; object members sorted by the UTF-16 code
units of their keys; arrays keep their order; strings are emitted as UTF-8 without Unicode
normalization, escaping only '"', '\\', and U+0000..U+001F (\\b \\t \\n \\f \\r as short
escapes, others as lowercase \\u00xx); integers in plain decimal, so -0 becomes 0.

Error precedence when several problems exist: type, size, byte-order mark, UTF-8, nesting
depth (checked by a pre-scan before parsing), then parse-time problems in document order
(malformed, duplicate key, float, non-finite, integer range), then lone surrogates and the
node ceiling.

Digests are ``ca-jcs-profile-sha256/0.1-provisional:<64 hex>``. They are a new, separately
versioned identity: prototype ``sha256:`` digests (ca-canon/0.1-spike) are never accepted
or reinterpreted as this algorithm.
"""

import hashlib
import json
import re
from dataclasses import dataclass

from . import errors as E
from .errors import CanonicalError

CANON_VERSION = "ca-jcs-profile/0.1-provisional"
DIGEST_ALGORITHM = "ca-jcs-profile-sha256/0.1-provisional"
MAX_SAFE_INTEGER = 2**53 - 1  # IEEE-754 safe integer range

# PROVISIONAL parser safety ceilings (product-owner direction D8, 2026-11-02); unreviewed.
CEILING_BYTES = 1_048_576
CEILING_DEPTH = 64
CEILING_NODES = 100_000
LIMITS_STATUS = "provisional"


@dataclass(frozen=True)
class Limits:
    """Per-call limits. Callers may lower them, never raise them above the ceilings."""

    max_bytes: int = CEILING_BYTES
    max_depth: int = CEILING_DEPTH
    max_nodes: int = CEILING_NODES

    def __post_init__(self):
        for name, ceiling in (("max_bytes", CEILING_BYTES), ("max_depth", CEILING_DEPTH),
                              ("max_nodes", CEILING_NODES)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f"{name} must be an integer in 1..{ceiling}")


DEFAULT_LIMITS = Limits()

_BOM = b"\xef\xbb\xbf"
_STRING_LITERAL = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"', re.S)
_BRACKET = re.compile(r"[\[\]{}]")
_SURROGATE = re.compile("[\ud800-\udfff]")
_DIGEST = re.compile(r"([^:]+):([0-9a-f]{64})")
_MAX_INT_DIGITS = len(str(MAX_SAFE_INTEGER))

_ESCAPES = {0x22: '\\"', 0x5C: "\\\\", 0x08: "\\b", 0x09: "\\t", 0x0A: "\\n", 0x0C: "\\f", 0x0D: "\\r"}
for _c in range(0x20):
    _ESCAPES.setdefault(_c, f"\\u{_c:04x}")
del _c


def _check_depth(text, max_depth):
    """Bound nesting before the recursive standard-library parser runs."""
    depth = 0
    for match in _BRACKET.finditer(_STRING_LITERAL.sub("", text)):
        if match.group() in "[{":
            depth += 1
            if depth > max_depth:
                raise CanonicalError(E.NESTING_TOO_DEEP, f"nesting exceeds {max_depth}")
        else:
            depth -= 1


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise CanonicalError(E.DUPLICATE_KEY, "object has a duplicate key")
        obj[key] = value
    return obj


def _float(_text):
    raise CanonicalError(E.FLOAT_NOT_PERMITTED, "numbers with a fraction or exponent are not permitted")


def _constant(_text):
    raise CanonicalError(E.NON_FINITE_NUMBER, "NaN and Infinity are not permitted")


def _integer(text):
    if len(text.lstrip("-")) > _MAX_INT_DIGITS:
        raise CanonicalError(E.INTEGER_OUT_OF_RANGE, f"integer outside +/-{MAX_SAFE_INTEGER}")
    value = int(text)
    if abs(value) > MAX_SAFE_INTEGER:
        raise CanonicalError(E.INTEGER_OUT_OF_RANGE, f"integer outside +/-{MAX_SAFE_INTEGER}")
    return value


def _validate(value, limits):
    """Iteratively check types, ranges, surrogates, depth and node count of a value."""
    nodes = 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > limits.max_nodes:
            raise CanonicalError(E.TOO_MANY_NODES, f"more than {limits.max_nodes} values")
        if item is None or item is True or item is False:
            continue
        if isinstance(item, str):
            if _SURROGATE.search(item):
                raise CanonicalError(E.LONE_SURROGATE, "string contains a lone surrogate")
            continue
        if type(item) is int:
            if abs(item) > MAX_SAFE_INTEGER:
                raise CanonicalError(E.INTEGER_OUT_OF_RANGE, f"integer outside +/-{MAX_SAFE_INTEGER}")
            continue
        if isinstance(item, float):
            raise CanonicalError(E.FLOAT_NOT_PERMITTED, "float values are not permitted")
        if isinstance(item, (list, tuple, dict)):
            if depth + 1 > limits.max_depth:
                raise CanonicalError(E.NESTING_TOO_DEEP, f"nesting exceeds {limits.max_depth}")
            if isinstance(item, dict):
                for key in item:
                    if not isinstance(key, str):
                        raise CanonicalError(E.NON_STRING_KEY, "object keys must be strings")
                    if _SURROGATE.search(key):
                        raise CanonicalError(E.LONE_SURROGATE, "object key contains a lone surrogate")
                children = item.values()
            else:
                children = item
            stack.extend((child, depth + 1) for child in children)
            continue
        raise CanonicalError(E.UNSUPPORTED_TYPE, f"type {type(item).__name__} is not a JSON value")


def loads(data, limits=DEFAULT_LIMITS):
    """Parse untrusted JSON bytes under the profile; raise ``CanonicalError`` on any rejection."""
    if not isinstance(data, (bytes, bytearray)):
        raise CanonicalError(E.INPUT_NOT_BYTES, "input must be bytes")
    if len(data) > limits.max_bytes:
        raise CanonicalError(E.DOCUMENT_TOO_LARGE, f"document exceeds {limits.max_bytes} bytes")
    data = bytes(data)
    if data.startswith(_BOM):
        raise CanonicalError(E.BYTE_ORDER_MARK, "UTF-8 byte-order mark is not permitted")
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise CanonicalError(E.INVALID_UTF8, f"invalid UTF-8 at byte {exc.start}") from None
    _check_depth(text, limits.max_depth)
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_float=_float,
                           parse_constant=_constant, parse_int=_integer)
    except CanonicalError:
        raise
    except json.JSONDecodeError as exc:
        raise CanonicalError(E.MALFORMED_JSON, f"{exc.msg} at character {exc.pos}") from None
    except RecursionError:  # defensive: the pre-scan should make this unreachable
        raise CanonicalError(E.NESTING_TOO_DEEP, f"nesting exceeds {limits.max_depth}") from None
    except ValueError:
        raise CanonicalError(E.MALFORMED_JSON, "unparseable JSON value") from None
    _validate(value, limits)
    return value


_NEEDS_ESCAPE = re.compile("[" + "".join(re.escape(chr(code)) for code in sorted(_ESCAPES)) + "]")


def _string(text):
    if _NEEDS_ESCAPE.search(text) is None:  # fast path: nothing to escape (output is identical)
        return '"' + text + '"'
    return '"' + text.translate(_ESCAPES) + '"'


def _utf16_key(key):
    return key.encode("utf-16-be")  # big-endian bytes sort in UTF-16 code-unit order


def _serialize(value, out):
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        out.append(_string(value))
    elif type(value) is int:
        out.append(str(value))
    elif isinstance(value, dict):
        out.append("{")
        for i, key in enumerate(sorted(value, key=_utf16_key)):
            if i:
                out.append(",")
            out.append(_string(key))
            out.append(":")
            _serialize(value[key], out)
        out.append("}")
    else:
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _serialize(item, out)
        out.append("]")


def canonical_bytes(value, limits=DEFAULT_LIMITS):
    """Return the canonical UTF-8 encoding of an in-memory JSON value."""
    _validate(value, limits)
    out = []
    _serialize(value, out)  # recursion is bounded by the validated depth
    encoded = "".join(out).encode("utf-8")
    if len(encoded) > limits.max_bytes:
        raise CanonicalError(E.DOCUMENT_TOO_LARGE, f"canonical form exceeds {limits.max_bytes} bytes")
    return encoded


def canonicalize(data, limits=DEFAULT_LIMITS):
    """Parse untrusted JSON bytes and return their canonical bytes."""
    return canonical_bytes(loads(data, limits), limits)


def digest(value, limits=DEFAULT_LIMITS):
    """Return the versioned SHA-256 digest of the canonical encoding."""
    return f"{DIGEST_ALGORITHM}:{hashlib.sha256(canonical_bytes(value, limits)).hexdigest()}"


def parse_digest(text):
    """Return the hex part of a digest of this algorithm; reject any other algorithm."""
    match = _DIGEST.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise CanonicalError(E.DIGEST_MALFORMED, "digest must be <algorithm>:<64 lowercase hex>")
    if match.group(1) != DIGEST_ALGORITHM:
        raise CanonicalError(E.DIGEST_ALGORITHM_MISMATCH, f"expected {DIGEST_ALGORITHM}")
    return match.group(2)
