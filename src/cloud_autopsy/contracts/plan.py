"""Run plan contract ``ca-run-plan/0.1-provisional`` (CA-CON-001, CA-P2-002d).

A plan pins everything a sealed input depends on: the source-registry digest, the expected
acquisitions (source and query pairs, each mandatory or optional), the investigation window,
the exact contract versions, opaque rule versions, the synthesis mode and finite resource
limits. It carries no run ID, wall-clock time, credential, URL, free-form query or ground
truth: run identity and timing are run state (CA-P2-003), and the plan digest must be the
same for every retry of the same plan.

Provisional ceilings follow the proposed CA-DEC-007 hard bounds (60-minute window, 100,000
records, 250 MB) and the 1 MiB canonical-document ceiling for a single batch. A plan may
choose lower limits, never higher ones.

Version history: 0.1-provisional had no bound on delivered records (duplicates and retries
included); 0.2-provisional adds ``max_batch_deliveries``.
"""

from dataclasses import dataclass

from . import canonical
from . import errors as E
from . import timeinterval as ti
from .errors import ManifestError, RecordError
from .sources import IDENTIFIER, SourceRegistry
from .versioning import check_envelope, validate_identifier

RUN_PLAN_VERSION = "ca-run-plan/0.2-provisional"
SYNTHESIS_MODES = ("disabled",)  # local synthesis is a later, separately approved amendment

# PROVISIONAL ceilings (CA-DEC-007 proposed hard bounds; unreviewed).
LIMIT_CEILINGS = {
    "max_window_ms": 3_600_000,
    "max_batches_per_acquisition": 1_000,
    "max_batch_deliveries": 10_000,  # every delivered record, duplicates included
    "max_observations_per_batch": 1_000,
    "max_observations_total": 100_000,
    "max_batch_bytes": canonical.CEILING_BYTES,
    "max_total_bytes": 250_000_000,
}
MAX_EXPECTED_ACQUISITIONS = 64
MAX_RULE_VERSIONS = 32
_FIELDS = ("plan_id", "registry_id", "registry_digest", "window", "expected_acquisitions", "contract_versions",
           "rule_versions", "synthesis_mode", "limits")


def _invalid(detail):
    return ManifestError(E.PLAN_INVALID, detail)


def exact_ms(raw, name):
    """Parse an RFC 3339 bound that must name an exact millisecond; return epoch milliseconds."""
    try:
        parsed = ti.parse_rfc3339(raw)
    except ti.TimeError:
        raise _invalid(f"{name} must be a valid RFC 3339 timestamp") from None
    if parsed.epoch_ns % ti.NS_PER_MS:
        raise _invalid(f"{name} must not have sub-millisecond digits")
    return parsed.epoch_ns // ti.NS_PER_MS


def required_contract_versions(kind_registry_version=None):
    """Exact contract versions a plan pins: the baseline (observation kinds 0.1) by default, or the
    profile with ``kind_registry_version`` (imported lazily to avoid an import cycle)."""
    from . import CONTRACT_PROFILES, CONTRACT_VERSIONS
    if kind_registry_version is None:
        return dict(CONTRACT_VERSIONS)
    for profile in CONTRACT_PROFILES:
        if profile["observation-kinds"] == kind_registry_version:
            return dict(profile)
    raise ManifestError(E.CONTRACT_VERSION_MISMATCH, "no contract profile pins that kind registry version")


def supported_contract_profiles():
    from . import CONTRACT_PROFILES
    return [dict(p) for p in CONTRACT_PROFILES]


@dataclass(frozen=True)
class RunPlan:
    plan_id: str
    registry_id: str
    registry_digest: str
    window_start: str
    window_end: str
    window_start_ms: int
    window_end_ms: int
    expected_acquisitions: tuple  # (source_id, query_id, mandatory), sorted
    contract_versions: tuple      # (name, version), sorted
    rule_versions: tuple          # (name, version), sorted
    synthesis_mode: str
    limits: tuple                 # (name, value), sorted

    def limit(self, name):
        return dict(self.limits)[name]

    def expects(self, source_id, query_id):
        return any(s == source_id and q == query_id for s, q, _ in self.expected_acquisitions)

    @property
    def kind_registry_version(self):
        """The observation-kind registry this plan pins; its evidence is decoded under exactly this."""
        return dict(self.contract_versions)["observation-kinds"]

    def to_record(self):
        return {"contract_version": RUN_PLAN_VERSION, "plan_id": self.plan_id, "registry_id": self.registry_id,
                "registry_digest": self.registry_digest,
                "window": {"start": self.window_start, "end": self.window_end},
                "expected_acquisitions": [{"source_id": s, "query_id": q, "mandatory": m}
                                          for s, q, m in self.expected_acquisitions],
                "contract_versions": dict(self.contract_versions), "rule_versions": dict(self.rule_versions),
                "synthesis_mode": self.synthesis_mode, "limits": dict(self.limits)}

    @property
    def digest(self):
        return canonical.digest(self.to_record())

    @classmethod
    def from_record(cls, record, registry):
        """Strictly decode a plan and check it against the registry it pins."""
        if not isinstance(registry, SourceRegistry):
            raise RecordError(E.RECORD_FIELD_INVALID, "a SourceRegistry is required")
        if not isinstance(record, dict):
            raise RecordError(E.RECORD_NOT_OBJECT, "run plan must be an object")
        check_envelope(record, RUN_PLAN_VERSION)
        missing = [f for f in _FIELDS if f not in record]
        if missing:
            raise RecordError(E.RECORD_FIELD_MISSING, f"RunPlan.{missing[0]} is required")
        if set(record) - set(_FIELDS) - {"contract_version"}:
            raise RecordError(E.RECORD_FIELD_UNKNOWN, "run plan has an unknown field")
        canonical.canonical_bytes(record)  # canonical-profile values only

        for name in ("plan_id", "registry_id"):
            if not isinstance(record[name], str) or not IDENTIFIER.fullmatch(record[name]):
                raise _invalid(f"{name} must be a lowercase identifier")
        if record["registry_id"] != registry.registry_id or record["registry_digest"] != registry.digest:
            raise ManifestError(E.REGISTRY_MISMATCH, "plan does not pin this source registry")

        limits = record["limits"]
        if not isinstance(limits, dict) or set(limits) != set(LIMIT_CEILINGS):
            raise _invalid("limits must set exactly the provisional limit names")
        for name, ceiling in LIMIT_CEILINGS.items():
            if type(limits[name]) is not int or not 1 <= limits[name] <= ceiling:
                raise _invalid(f"limits.{name} must be an integer in 1..{ceiling}")

        window = record["window"]
        if not isinstance(window, dict) or set(window) != {"start", "end"}:
            raise _invalid("window must have exactly start and end")
        start_ms, end_ms = exact_ms(window["start"], "window.start"), exact_ms(window["end"], "window.end")
        if not start_ms < end_ms:
            raise _invalid("window.start must be before window.end")
        if end_ms - start_ms > limits["max_window_ms"]:
            raise ManifestError(E.LIMIT_EXCEEDED, "window exceeds limits.max_window_ms")

        expected = record["expected_acquisitions"]
        if not isinstance(expected, list) or not 1 <= len(expected) <= MAX_EXPECTED_ACQUISITIONS:
            raise _invalid(f"expected_acquisitions must list 1..{MAX_EXPECTED_ACQUISITIONS} entries")
        rows = []
        for item in expected:
            if not isinstance(item, dict) or set(item) != {"source_id", "query_id", "mandatory"} \
                    or type(item["mandatory"]) is not bool:
                raise _invalid("expected acquisition needs source_id, query_id and boolean mandatory")
            source = registry.get(item["source_id"])
            if item["query_id"] not in source.query_ids:
                raise ManifestError(E.SOURCE_SCOPE_MISMATCH, "expected query is not bound to its source")
            rows.append((item["source_id"], item["query_id"], item["mandatory"]))
        if len({(s, q) for s, q, _ in rows}) != len(rows):
            raise _invalid("expected acquisitions must be unique")

        if record["contract_versions"] not in supported_contract_profiles():
            raise ManifestError(E.CONTRACT_VERSION_MISMATCH,
                                "contract_versions must pin exactly one of this package's contract profiles")
        rules = record["rule_versions"]
        if not isinstance(rules, dict) or len(rules) > MAX_RULE_VERSIONS:
            raise _invalid(f"rule_versions must be an object of at most {MAX_RULE_VERSIONS} entries")
        for name, version in rules.items():
            if not IDENTIFIER.fullmatch(name):
                raise _invalid("rule_versions names must be lowercase identifiers")
            validate_identifier(version)
        if record["synthesis_mode"] not in SYNTHESIS_MODES:
            raise _invalid("synthesis_mode must be disabled")

        return cls(record["plan_id"], record["registry_id"], record["registry_digest"], window["start"],
                   window["end"], start_ms, end_ms, tuple(sorted(rows)),
                   tuple(sorted(record["contract_versions"].items())), tuple(sorted(rules.items())),
                   record["synthesis_mode"], tuple(sorted(limits.items())))
