"""Typed contract errors with stable reason codes.

A reason code is part of the contract: callers and tests branch on ``code``, never on the
message. Messages never echo input content (keys, strings or numbers from the document),
only fixed text and numeric positions or limits.
"""

# Stable reason codes. Adding a code is a contract change; renaming or removing one is a
# breaking change and needs a new contract version.
INPUT_NOT_BYTES = "input_not_bytes"
DOCUMENT_TOO_LARGE = "document_too_large"
INVALID_UTF8 = "invalid_utf8"
BYTE_ORDER_MARK = "byte_order_mark"
MALFORMED_JSON = "malformed_json"
DUPLICATE_KEY = "duplicate_key"
FLOAT_NOT_PERMITTED = "float_not_permitted"
NON_FINITE_NUMBER = "non_finite_number"
INTEGER_OUT_OF_RANGE = "integer_out_of_range"
LONE_SURROGATE = "lone_surrogate"
NESTING_TOO_DEEP = "nesting_too_deep"
TOO_MANY_NODES = "too_many_nodes"
UNSUPPORTED_TYPE = "unsupported_type"
NON_STRING_KEY = "non_string_key"
CONTRACT_VERSION_MISSING = "contract_version_missing"
CONTRACT_VERSION_MALFORMED = "contract_version_malformed"
CONTRACT_VERSION_MISMATCH = "contract_version_mismatch"
DIGEST_MALFORMED = "digest_malformed"
DIGEST_ALGORITHM_MISMATCH = "digest_algorithm_mismatch"

CANONICAL_CODES = frozenset({
    INPUT_NOT_BYTES, DOCUMENT_TOO_LARGE, INVALID_UTF8, BYTE_ORDER_MARK, MALFORMED_JSON,
    DUPLICATE_KEY, FLOAT_NOT_PERMITTED, NON_FINITE_NUMBER, INTEGER_OUT_OF_RANGE, LONE_SURROGATE,
    NESTING_TOO_DEEP, TOO_MANY_NODES, UNSUPPORTED_TYPE, NON_STRING_KEY,
    DIGEST_MALFORMED, DIGEST_ALGORITHM_MISMATCH,
})
VERSION_CODES = frozenset({CONTRACT_VERSION_MISSING, CONTRACT_VERSION_MALFORMED, CONTRACT_VERSION_MISMATCH})
ALL_CODES = CANONICAL_CODES | VERSION_CODES


class ContractError(ValueError):
    """Base class for every contract rejection. ``code`` is one of ``ALL_CODES``."""

    def __init__(self, code, detail=""):
        if code not in ALL_CODES:
            raise AssertionError(f"unregistered contract error code {code!r}")
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class CanonicalError(ContractError):
    """Rejected JSON document or value under the canonical JSON profile."""


class VersionError(ContractError):
    """Missing, malformed or incompatible contract version."""
