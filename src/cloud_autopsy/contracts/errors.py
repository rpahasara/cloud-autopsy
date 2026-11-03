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

# Timestamp and clock-domain codes (CA-P2-002b, provisional).
TIMESTAMP_NOT_STRING = "timestamp_not_string"
TIMESTAMP_TOO_LONG = "timestamp_too_long"
TIMESTAMP_MALFORMED = "timestamp_malformed"
FRACTION_TOO_LONG = "fraction_too_long"
INVALID_CALENDAR_DATE = "invalid_calendar_date"
INVALID_TIME_OF_DAY = "invalid_time_of_day"
INVALID_UTC_OFFSET = "invalid_utc_offset"
LEAP_SECOND_UNSUPPORTED = "leap_second_unsupported"
PRECISION_INVALID = "precision_invalid"
CLOCK_OFFSET_OUT_OF_RANGE = "clock_offset_out_of_range"
# Strict record decoding codes, shared by later record contracts.
RECORD_NOT_OBJECT = "record_not_object"
RECORD_FIELD_MISSING = "record_field_missing"
RECORD_FIELD_UNKNOWN = "record_field_unknown"
RECORD_FIELD_INVALID = "record_field_invalid"
RECORD_INCONSISTENT = "record_inconsistent"

# Source registry, observation and evidence codes (CA-P2-002c, provisional).
REGISTRY_INVALID = "registry_invalid"
SOURCE_UNKNOWN = "source_unknown"
SOURCE_SCOPE_MISMATCH = "source_scope_mismatch"
OBSERVATION_KIND_UNSUPPORTED = "observation_kind_unsupported"
OBSERVATION_TOO_LARGE = "observation_too_large"
ATTRIBUTE_MISSING = "attribute_missing"
ATTRIBUTE_UNKNOWN = "attribute_unknown"
ATTRIBUTE_INVALID = "attribute_invalid"
ATTRIBUTE_FORBIDDEN = "attribute_forbidden"
EVIDENCE_ID_MISMATCH = "evidence_id_mismatch"
CONTENT_DIGEST_MISMATCH = "content_digest_mismatch"

# Run plan, acquisition batch and frozen-input codes (CA-P2-002d, provisional).
PLAN_INVALID = "plan_invalid"
PLAN_MISMATCH = "plan_mismatch"
REGISTRY_MISMATCH = "registry_mismatch"
BATCH_INVALID = "batch_invalid"
LIMIT_EXCEEDED = "limit_exceeded"
MANIFEST_DIGEST_MISMATCH = "manifest_digest_mismatch"
REPLAY_MISMATCH = "replay_mismatch"

CANONICAL_CODES = frozenset({
    INPUT_NOT_BYTES, DOCUMENT_TOO_LARGE, INVALID_UTF8, BYTE_ORDER_MARK, MALFORMED_JSON,
    DUPLICATE_KEY, FLOAT_NOT_PERMITTED, NON_FINITE_NUMBER, INTEGER_OUT_OF_RANGE, LONE_SURROGATE,
    NESTING_TOO_DEEP, TOO_MANY_NODES, UNSUPPORTED_TYPE, NON_STRING_KEY,
    DIGEST_MALFORMED, DIGEST_ALGORITHM_MISMATCH,
})
VERSION_CODES = frozenset({CONTRACT_VERSION_MISSING, CONTRACT_VERSION_MALFORMED, CONTRACT_VERSION_MISMATCH})
TIME_CODES = frozenset({
    TIMESTAMP_NOT_STRING, TIMESTAMP_TOO_LONG, TIMESTAMP_MALFORMED, FRACTION_TOO_LONG,
    INVALID_CALENDAR_DATE, INVALID_TIME_OF_DAY, INVALID_UTC_OFFSET, LEAP_SECOND_UNSUPPORTED,
    PRECISION_INVALID, CLOCK_OFFSET_OUT_OF_RANGE,
})
RECORD_CODES = frozenset({RECORD_NOT_OBJECT, RECORD_FIELD_MISSING, RECORD_FIELD_UNKNOWN,
                          RECORD_FIELD_INVALID, RECORD_INCONSISTENT})
EVIDENCE_CODES = frozenset({
    REGISTRY_INVALID, SOURCE_UNKNOWN, SOURCE_SCOPE_MISMATCH, OBSERVATION_KIND_UNSUPPORTED,
    OBSERVATION_TOO_LARGE, ATTRIBUTE_MISSING, ATTRIBUTE_UNKNOWN, ATTRIBUTE_INVALID, ATTRIBUTE_FORBIDDEN,
    EVIDENCE_ID_MISMATCH, CONTENT_DIGEST_MISMATCH,
})
MANIFEST_CODES = frozenset({PLAN_INVALID, PLAN_MISMATCH, REGISTRY_MISMATCH, BATCH_INVALID, LIMIT_EXCEEDED,
                            MANIFEST_DIGEST_MISMATCH, REPLAY_MISMATCH})
ALL_CODES = CANONICAL_CODES | VERSION_CODES | TIME_CODES | RECORD_CODES | EVIDENCE_CODES | MANIFEST_CODES


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


class TimeError(ContractError):
    """Rejected timestamp text, precision or clock-domain declaration."""


class RecordError(ContractError):
    """Record that is not a strict, internally consistent instance of its contract."""


class EvidenceError(ContractError):
    """Rejected source registry, observation, attribute or evidence record."""


class ManifestError(ContractError):
    """Rejected run plan, acquisition batch, seal input or frozen-input manifest."""
