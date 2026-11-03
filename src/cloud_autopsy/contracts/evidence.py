"""Observation, evidence identity and conflict contracts (CA-P2-002c). All provisional.

Contracts:
  ``ca-observation/0.1-provisional``          untrusted observation input from an acquisition
  ``ca-evidence/0.1-provisional``             observed-evidence records and ledger snapshots
  ``ca-observation-kinds/0.1-provisional``    the kind registry and its bounded field schemas
  ``ca-evidence-id-sha256/0.1-provisional``   evidence identity algorithm
  ``ca-evidence-content-sha256/0.1-provisional`` content digest algorithm

Identity. ``evidence_id = <id algorithm>:<SHA-256 hex>`` of the canonical bytes of
``{algorithm, source_id, cluster_id, namespace, observation_kind, source_uid, source_version}``.
``cluster_id`` and ``namespace`` come from the source registry binding, never from the
observation. The same source object observed through a differently bound source is a
different identity. Prototype IDs (``ev:<class>:<24 hex>``) are never accepted.

Content. ``content_digest = <content algorithm>:<SHA-256 hex>`` of the canonical bytes of
``{algorithm, observation_kind, source_ref, source_uid, source_version, entity, times,
attributes}``. Times contribute only their source inputs (timestamp kind, raw text, clock
domain, declared precision), sorted by timestamp kind; parsed intervals are derived and
excluded. Set-valued attributes are sorted. Delivery metadata (query ID, batch ID, attempt)
is validated and then discarded: it is in neither the ID nor the digest. Registry binding
data is recorded on the evidence but is not content.

Conflicts. ``EvidenceLedger`` is a pure in-memory classifier. One identity with one content
digest is ``authoritative``; identical redelivery is a ``duplicate``. A second, different
digest for the same identity makes the identity ``conflicted``: every variant is retained
in quarantine and none is authoritative. The final state does not depend on delivery order.
This is not concurrency protection; atomic conflict handling in storage is CA-P2-003.

Observed versus derived. Only ``origin: observed`` records exist here. Derived evidence,
provenance edges and causal relations are later contracts.

Error messages name schema fields only; they never include observed values or unknown keys.
"""

import hashlib
import re
from dataclasses import dataclass
from types import MappingProxyType

from . import canonical
from . import errors as E
from . import timeinterval as ti
from .errors import EvidenceError, RecordError
from .sources import IDENTIFIER, NAMESPACE, SourceRegistry
from .versioning import check_envelope

OBSERVATION_VERSION = "ca-observation/0.1-provisional"
EVIDENCE_VERSION = "ca-evidence/0.1-provisional"
KIND_REGISTRY_VERSION = "ca-observation-kinds/0.1-provisional"
ID_ALGORITHM = "ca-evidence-id-sha256/0.1-provisional"
CONTENT_ALGORITHM = "ca-evidence-content-sha256/0.1-provisional"
ORIGIN_OBSERVED = "observed"

# PROVISIONAL bounds (unreviewed).
MAX_OBSERVATION_BYTES = 65_536
MAX_TIMES = 4
MAX_LIST_ITEMS = 32
MAX_LOG_FIELDS = 16
MAX_DELIVERY_ATTEMPT = 100

# C0/C1 controls, DEL, line/paragraph separators, bidirectional overrides and BOM.
_UNSAFE_TEXT = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff\ud800-\udfff]")
_CREDENTIAL_KEY = re.compile(r"passw|secret|token|api[_-]?key|credential|private[_-]?key|authori[sz]|bearer|"
                             r"session|cookie|signature", re.I)


def _attr_error(path, detail):
    return EvidenceError(E.ATTRIBUTE_INVALID, f"{path} {detail}")


class _Text:
    def __init__(self, max_len, pattern=None):
        self.max_len = max_len
        self.pattern = re.compile(pattern, re.ASCII) if pattern else None

    def check(self, value, path):
        if not isinstance(value, str) or not 1 <= len(value) <= self.max_len:
            raise _attr_error(path, f"must be a string of 1..{self.max_len} characters")
        if _UNSAFE_TEXT.search(value):
            raise _attr_error(path, "contains control, separator or bidirectional characters")
        if self.pattern and not self.pattern.fullmatch(value):
            raise _attr_error(path, "does not match its allowed character set")
        return value


class _Int:
    def __init__(self, low, high):
        self.low, self.high = low, high

    def check(self, value, path):
        if type(value) is not int or not self.low <= value <= self.high:
            raise _attr_error(path, f"must be an integer in {self.low}..{self.high}")
        return value


class _Bool:
    def check(self, value, path):
        if type(value) is not bool:
            raise _attr_error(path, "must be a boolean")
        return value


class _List:
    def __init__(self, item, max_items=MAX_LIST_ITEMS, as_set=False):
        self.item, self.max_items, self.as_set = item, max_items, as_set

    def check(self, value, path):
        if not isinstance(value, list) or len(value) > self.max_items:
            raise _attr_error(path, f"must be a list of at most {self.max_items} items")
        items = [self.item.check(v, f"{path}[]") for v in value]
        if self.as_set:  # set-valued: delivery order is not content
            if len(set(items)) != len(items):
                raise _attr_error(path, "has duplicate entries")
            items.sort()
        return items


class _Object:
    def __init__(self, fields):
        self.fields = fields  # name -> (spec, required)

    def check(self, value, path):
        if not isinstance(value, dict):
            raise _attr_error(path, "must be an object")
        for name, (_, required) in self.fields.items():
            if required and name not in value:
                raise EvidenceError(E.ATTRIBUTE_MISSING, f"{path}.{name} is required")
        if set(value) - set(self.fields):
            raise EvidenceError(E.ATTRIBUTE_UNKNOWN, f"{path} has an attribute outside its schema")
        return {name: self.fields[name][0].check(v, f"{path}.{name}") for name, v in value.items()}


class _Nullable:
    """``null`` or a value of the wrapped spec; ``null`` is part of the content, not an omission."""

    def __init__(self, spec):
        self.spec = spec

    def check(self, value, path):
        return None if value is None else self.spec.check(value, path)


class _LogFields:
    """Template fields of a log line: bounded string map with credential-like keys refused."""

    KEY = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
    VALUE = _Text(256)

    def check(self, value, path):
        if not isinstance(value, dict) or len(value) > MAX_LOG_FIELDS:
            raise _attr_error(path, f"must be an object of at most {MAX_LOG_FIELDS} fields")
        out = {}
        for key, item in value.items():
            if not self.KEY.fullmatch(key):
                raise _attr_error(path, "has a field name outside [a-z][a-z0-9_]{0,63}")
            if _CREDENTIAL_KEY.search(key):
                raise EvidenceError(E.ATTRIBUTE_FORBIDDEN, f"{path} has a credential-like field name")
            out[key] = self.VALUE.check(item, f"{path}.<field>")
        return out


K8S_NAME = _Text(253, r"[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?")
DIGITS = _Text(20, r"[0-9]{1,20}")
SHA256_HEX = _Text(64, r"[0-9a-f]{64}")
CONFIG_KEY = _Text(253, r"[A-Za-z0-9._-]{1,253}")
VALUE = _Text(256)
IMAGE = _Text(512, r"[A-Za-z0-9._/:@-]{1,512}")
FIELD_PATH = _Text(256, r"[A-Za-z0-9._/\[\]-]{1,256}")
ACTOR = _Text(128, r"[A-Za-z0-9._:@/-]{1,128}")
MOUNT_PATH = _Text(1024, r"/[A-Za-z0-9._/-]{0,1023}")
TEMPLATE = _Text(64, r"[A-Z][A-Z0-9_]{0,63}")
MESSAGE = _Text(1024)
METRIC = _Text(200, r"[a-zA-Z_:][a-zA-Z0-9_:]{0,199}")
LABELS = _Text(512, r"[A-Za-z0-9_=,.:/-]{1,512}")
DECIMAL = _Text(33, r"-?(0|[1-9][0-9]{0,15})(\.[0-9]{1,15})?")
RULE = _Text(128, r"[A-Za-z][A-Za-z0-9_]{0,127}")
DURATION = _Text(16, r"[0-9]{1,9}(ms|s|m|h)")
SOURCE_REF = _Text(512)
SOURCE_UID = _Text(256)
SOURCE_VERSION = _Text(128)

_VALUE_CHANGE = {"before_value": (VALUE, True), "after_value": (VALUE, True),
                 "before_value_sha256": (SHA256_HEX, True), "after_value_sha256": (SHA256_HEX, True)}


@dataclass(frozen=True)
class KindSpec:
    observation_kind: str
    evidence_class: str
    source_kind: str
    entity_kind: str
    required_times: tuple
    optional_times: tuple
    attributes: _Object


KINDS = {spec.observation_kind: spec for spec in (
    KindSpec("configmap_change", "K8S-CONFIG", "kubernetes_api", "ConfigMap", ("event",), (), _Object({
        "data_key": (CONFIG_KEY, True), **_VALUE_CHANGE,
        "previous_resource_version": (DIGITS, True), "actor": (ACTOR, False)})),
    KindSpec("deployment_rollout", "K8S-DEPLOY", "kubernetes_api", "Deployment", ("event",), ("completed",), _Object({
        "revision": (DIGITS, True), "previous_revision": (DIGITS, False),
        "changed_fields": (_List(FIELD_PATH, as_set=True), True),
        "image_before": (IMAGE, True), "image_after": (IMAGE, True),
        "config_refs_before": (_List(K8S_NAME, as_set=True), True),
        "config_refs_after": (_List(K8S_NAME, as_set=True), True),
        "old_replicaset": (K8S_NAME, True), "new_replicaset": (K8S_NAME, True), "actor": (ACTOR, False),
        "field_changes": (_List(_Object({"field": (FIELD_PATH, True), "config_key": (CONFIG_KEY, True),
                                         **_VALUE_CHANGE})), False)})),
    KindSpec("replicaset", "K8S-DEPLOY", "kubernetes_api", "ReplicaSet", ("event",), (), _Object({
        "owner_deployment": (K8S_NAME, True), "revision": (DIGITS, True), "image": (IMAGE, True)})),
    KindSpec("pod", "K8S-POD", "kubernetes_api", "Pod", ("event",), ("terminated",), _Object({
        "owner_replicaset": (K8S_NAME, True), "node": (K8S_NAME, True),
        "restart_count": (_Int(0, 1_000_000), True),
        "configmap_volumes": (_List(_Object({"configmap": (K8S_NAME, True), "mount_path": (MOUNT_PATH, True),
                                             "sub_path": (_Bool(), True)})), True)})),
    KindSpec("log_line", "LOG", "loki", "Pod", ("event",), (), _Object({
        "pod": (K8S_NAME, True), "template": (_Nullable(TEMPLATE), True), "fields": (_LogFields(), True),
        "message": (MESSAGE, True)})),
    KindSpec("metric_sample", "METRIC", "prometheus", "Service", ("event",), (), _Object({
        "series": (METRIC, True), "labels": (LABELS, True), "value": (DECIMAL, True)})),
    KindSpec("alert_firing", "ALERT", "prometheus", "Service", ("event",), ("active_since",), _Object({
        "rule": (RULE, True), "rule_version": (DIGITS, True), "expr_series": (METRIC, True),
        "threshold": (DECIMAL, True), "for": (DURATION, True)})),
)}

_OBSERVATION_FIELDS = ("source_ref", "observation_kind", "source_uid", "source_version", "entity", "times",
                       "attributes")
_TIME_FIELDS = ("timestamp_kind", "raw", "clock_domain_id", "declared_precision_ns")
_DELIVERY_FIELDS = ("query_id", "batch_id", "attempt")


def _exact_fields(record, names, what):
    if not isinstance(record, dict):
        raise RecordError(E.RECORD_NOT_OBJECT, f"{what} must be an object")
    missing = [n for n in names if n not in record]
    if missing:
        raise RecordError(E.RECORD_FIELD_MISSING, f"{what}.{missing[0]} is required")
    if set(record) - set(names):
        raise RecordError(E.RECORD_FIELD_UNKNOWN, f"{what} has an unknown field")


def _freeze(value):
    """Deep read-only copy: objects become read-only mappings, lists become tuples."""
    if isinstance(value, (dict, MappingProxyType)):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    """Fresh plain dict/list copy of a frozen value, for serialization and callers."""
    if isinstance(value, (dict, MappingProxyType)):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _sha_id(algorithm, material):
    return f"{algorithm}:{hashlib.sha256(canonical.canonical_bytes(material)).hexdigest()}"


def identity_material(source, observation_kind, source_uid, source_version):
    """The exact identity input; ``source`` is a registry ``SourceDefinition``."""
    return {"algorithm": ID_ALGORITHM, "source_id": source.source_id, "cluster_id": source.cluster_id,
            "namespace": source.namespace, "observation_kind": observation_kind,
            "source_uid": source_uid, "source_version": source_version}


def content_material(observation_kind, source_ref, source_uid, source_version, entity, time_inputs, attributes):
    """The exact content-digest input. ``time_inputs`` are source inputs, sorted by timestamp kind."""
    return {"algorithm": CONTENT_ALGORITHM, "observation_kind": observation_kind, "source_ref": source_ref,
            "source_uid": source_uid, "source_version": source_version, "entity": entity,
            "times": sorted(time_inputs, key=lambda t: t["timestamp_kind"]), "attributes": attributes}


def parse_evidence_id(text):
    """Return the hex part of an evidence ID of this algorithm; reject any other format."""
    match = re.fullmatch(r"([^:]+):([0-9a-f]{64})", text) if isinstance(text, str) else None
    if not match:
        raise EvidenceError(E.EVIDENCE_ID_MISMATCH, "evidence ID must be <algorithm>:<64 lowercase hex>")
    if match.group(1) != ID_ALGORITHM:
        raise EvidenceError(E.EVIDENCE_ID_MISMATCH, f"evidence ID algorithm must be {ID_ALGORITHM}")
    return match.group(2)


def validate_delivery(delivery, source):
    """Check transient delivery metadata against the source binding; it never reaches the record."""
    _exact_fields(delivery, _DELIVERY_FIELDS, "delivery")
    if delivery["query_id"] not in source.query_ids:
        raise EvidenceError(E.SOURCE_SCOPE_MISMATCH, "query_id is not bound to this source")
    if not isinstance(delivery["batch_id"], str) or not IDENTIFIER.fullmatch(delivery["batch_id"]):
        raise RecordError(E.RECORD_FIELD_INVALID, "delivery.batch_id must be a lowercase identifier")
    if type(delivery["attempt"]) is not int or not 1 <= delivery["attempt"] <= MAX_DELIVERY_ATTEMPT:
        raise RecordError(E.RECORD_FIELD_INVALID, f"delivery.attempt must be an integer in 1..{MAX_DELIVERY_ATTEMPT}")


@dataclass(frozen=True)
class ObservedEvidence:
    """Immutable observed evidence. ``entity`` and ``attributes`` are deep read-only views;
    ``to_record`` and ``observation`` return fresh plain copies, so nothing a caller holds can
    change accepted content after its digest was verified."""

    evidence_id: str
    origin: str
    source_id: str
    cluster_id: str
    namespace: str
    source_binding_digest: str
    kind_registry_version: str
    observation_kind: str
    evidence_class: str
    source_ref: str
    source_uid: str
    source_version: str
    entity: dict
    times: tuple  # ti.SourceTimestamp, sorted by timestamp kind
    attributes: dict
    content_digest: str

    def __post_init__(self):
        object.__setattr__(self, "entity", _freeze(self.entity))
        object.__setattr__(self, "attributes", _freeze(self.attributes))
        object.__setattr__(self, "times", tuple(self.times))

    def to_record(self):
        return {"contract_version": EVIDENCE_VERSION, "evidence_id": self.evidence_id, "origin": self.origin,
                "source_id": self.source_id, "cluster_id": self.cluster_id, "namespace": self.namespace,
                "source_binding_digest": self.source_binding_digest,
                "kind_registry_version": self.kind_registry_version, "observation_kind": self.observation_kind,
                "evidence_class": self.evidence_class, "source_ref": self.source_ref,
                "source_uid": self.source_uid, "source_version": self.source_version, "entity": _thaw(self.entity),
                "times": [t.to_record() for t in self.times], "attributes": _thaw(self.attributes),
                "content_digest": self.content_digest}

    def observation(self):
        """The observation input this record was built from (inverse of ``observe``)."""
        return {"contract_version": OBSERVATION_VERSION, "source_ref": self.source_ref,
                "observation_kind": self.observation_kind, "source_uid": self.source_uid,
                "source_version": self.source_version, "entity": _thaw(self.entity),
                "times": [_time_input(t) for t in self.times], "attributes": _thaw(self.attributes)}

    @classmethod
    def from_record(cls, record, registry):
        """Strictly decode a stored record and re-derive identity, digest and every derived field."""
        if not isinstance(registry, SourceRegistry):
            raise RecordError(E.RECORD_FIELD_INVALID, "a SourceRegistry is required")
        if not isinstance(record, dict):
            raise RecordError(E.RECORD_NOT_OBJECT, "evidence record must be an object")
        check_envelope(record, EVIDENCE_VERSION)
        names = tuple(n for n in cls.__dataclass_fields__)
        _exact_fields({k: v for k, v in record.items() if k != "contract_version"}, names, "ObservedEvidence")
        if record["origin"] != ORIGIN_OBSERVED:
            raise RecordError(E.RECORD_FIELD_INVALID, "origin must be observed; derived evidence is not supported")
        if not isinstance(record["times"], list):
            raise RecordError(E.RECORD_FIELD_INVALID, "times must be a list")
        stored_times = [ti.SourceTimestamp.from_record(t) for t in record["times"]]
        rebuilt = observe(
            {"contract_version": OBSERVATION_VERSION, "source_ref": record["source_ref"],
             "observation_kind": record["observation_kind"], "source_uid": record["source_uid"],
             "source_version": record["source_version"], "entity": record["entity"],
             "times": [_time_input(t) for t in stored_times], "attributes": record["attributes"]},
            source_id=record["source_id"], registry=registry)
        if record["evidence_id"] != rebuilt.evidence_id:
            raise EvidenceError(E.EVIDENCE_ID_MISMATCH, "evidence_id does not match the identity fields")
        if record["content_digest"] != rebuilt.content_digest:
            raise EvidenceError(E.CONTENT_DIGEST_MISMATCH, "content_digest does not match the content fields")
        if canonical.canonical_bytes(record) != canonical.canonical_bytes(rebuilt.to_record()):
            raise RecordError(E.RECORD_INCONSISTENT, "binding, class or derived fields do not match")
        return rebuilt


def _time_input(timestamp):
    return {"timestamp_kind": timestamp.timestamp_kind, "raw": timestamp.raw,
            "clock_domain_id": timestamp.clock_domain_id, "declared_precision_ns": timestamp.declared_precision_ns}


def observe(observation, *, source_id, registry, delivery=None):
    """Validate an untrusted observation for a registered source and build its evidence record.

    ``delivery`` (query_id, batch_id, attempt) is validated against the source binding when
    given and then discarded. Invalid timestamp text is retained with its parse status; it
    never produces a parsed instant or an ordering.
    """
    if not isinstance(registry, SourceRegistry):
        raise RecordError(E.RECORD_FIELD_INVALID, "a SourceRegistry is required")
    if not isinstance(observation, dict):
        raise RecordError(E.RECORD_NOT_OBJECT, "observation must be an object")
    try:
        canonical.canonical_bytes(observation, canonical.Limits(max_bytes=MAX_OBSERVATION_BYTES))
    except canonical.CanonicalError as exc:
        if exc.code == E.DOCUMENT_TOO_LARGE:
            raise EvidenceError(E.OBSERVATION_TOO_LARGE,
                                f"observation exceeds {MAX_OBSERVATION_BYTES} canonical bytes") from None
        raise
    check_envelope(observation, OBSERVATION_VERSION)
    _exact_fields({k: v for k, v in observation.items() if k != "contract_version"}, _OBSERVATION_FIELDS,
                  "observation")
    spec = KINDS.get(observation["observation_kind"]) if isinstance(observation["observation_kind"], str) else None
    if spec is None:
        raise EvidenceError(E.OBSERVATION_KIND_UNSUPPORTED, f"observation_kind is not in {KIND_REGISTRY_VERSION}")
    source = registry.get(source_id)
    if source.source_kind != spec.source_kind:
        raise EvidenceError(E.SOURCE_SCOPE_MISMATCH, "observation_kind is not produced by this source kind")
    if delivery is not None:
        validate_delivery(delivery, source)

    source_ref = SOURCE_REF.check(observation["source_ref"], "source_ref")
    source_uid = SOURCE_UID.check(observation["source_uid"], "source_uid")
    source_version = SOURCE_VERSION.check(observation["source_version"], "source_version")

    entity = observation["entity"]
    _exact_fields(entity, ("kind", "namespace", "name"), "entity")
    if entity["kind"] != spec.entity_kind:
        raise _attr_error("entity.kind", f"must be {spec.entity_kind} for this observation kind")
    if not isinstance(entity["namespace"], str) or not NAMESPACE.fullmatch(entity["namespace"]):
        raise _attr_error("entity.namespace", "must be a DNS-1123 label")
    if entity["namespace"] != source.namespace:
        raise EvidenceError(E.SOURCE_SCOPE_MISMATCH, "entity.namespace is outside the source binding")
    entity = {"kind": entity["kind"], "namespace": entity["namespace"],
              "name": K8S_NAME.check(entity["name"], "entity.name")}

    times = observation["times"]
    if not isinstance(times, list) or not 1 <= len(times) <= MAX_TIMES:
        raise RecordError(E.RECORD_FIELD_INVALID, f"times must list 1..{MAX_TIMES} timestamps")
    stamps = []
    for item in times:
        _exact_fields(item, _TIME_FIELDS, "times[]")
        if item["timestamp_kind"] not in spec.required_times + spec.optional_times:
            raise _attr_error("times[].timestamp_kind", "is not allowed for this observation kind")
        if item["clock_domain_id"] not in source.clock_domain_ids:
            raise EvidenceError(E.SOURCE_SCOPE_MISMATCH, "clock_domain_id is not bound to this source")
        stamps.append(ti.source_timestamp(item["raw"], timestamp_kind=item["timestamp_kind"],
                                          clock_domain_id=item["clock_domain_id"],
                                          declared_precision_ns=item["declared_precision_ns"]))
    kinds = [s.timestamp_kind for s in stamps]
    if len(set(kinds)) != len(kinds):
        raise _attr_error("times", "has a repeated timestamp_kind")
    if set(spec.required_times) - set(kinds):
        raise EvidenceError(E.ATTRIBUTE_MISSING, "times is missing a required timestamp_kind")
    stamps.sort(key=lambda s: s.timestamp_kind)

    attributes = spec.attributes.check(observation["attributes"], "attributes")
    _cross_checks(spec, entity, attributes)

    content = content_material(spec.observation_kind, source_ref, source_uid, source_version, entity,
                               [_time_input(s) for s in stamps], attributes)
    return ObservedEvidence(
        evidence_id=_sha_id(ID_ALGORITHM, identity_material(source, spec.observation_kind, source_uid,
                                                            source_version)),
        origin=ORIGIN_OBSERVED, source_id=source.source_id, cluster_id=source.cluster_id,
        namespace=source.namespace, source_binding_digest=source.binding_digest,
        kind_registry_version=KIND_REGISTRY_VERSION, observation_kind=spec.observation_kind,
        evidence_class=spec.evidence_class, source_ref=source_ref, source_uid=source_uid,
        source_version=source_version, entity=entity, times=tuple(stamps), attributes=attributes,
        content_digest=_sha_id(CONTENT_ALGORITHM, content))


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cross_checks(spec, entity, attributes):
    changes = [attributes] if spec.observation_kind == "configmap_change" else attributes.get("field_changes", [])
    for change in changes:
        for side in ("before", "after"):
            if _sha256_text(change[f"{side}_value"]) != change[f"{side}_value_sha256"]:
                raise _attr_error(f"attributes.{side}_value_sha256", "does not match the value")
    if spec.observation_kind == "log_line":
        if attributes["pod"] != entity["name"]:
            raise _attr_error("attributes.pod", "must equal entity.name")
        if attributes["template"] is None and attributes["fields"]:
            raise _attr_error("attributes.fields", "must be empty when no log template matched")


ACCEPTED_NEW = "accepted_new"
DUPLICATE = "duplicate"
CONFLICT_QUARANTINED = "conflict_quarantined"
AUTHORITATIVE = "authoritative"
CONFLICTED = "conflicted"


@dataclass(frozen=True)
class Admission:
    outcome: str
    evidence_id: str
    content_digest: str
    state: str


class EvidenceLedger:
    """Order-independent in-memory duplicate/conflict classifier; not a concurrency control."""

    def __init__(self, registry):
        if not isinstance(registry, SourceRegistry):
            raise RecordError(E.RECORD_FIELD_INVALID, "a SourceRegistry is required")
        self._registry = registry
        self._variants = {}    # evidence_id -> {content_digest: ObservedEvidence}
        self._deliveries = {}  # evidence_id -> delivery count

    def admit(self, evidence):
        """Classify one delivery. The record is re-verified, so a tampered digest is rejected."""
        if not isinstance(evidence, ObservedEvidence):
            raise RecordError(E.RECORD_FIELD_INVALID, "admit requires an ObservedEvidence record")
        verified = ObservedEvidence.from_record(evidence.to_record(), self._registry)
        variants = self._variants.setdefault(verified.evidence_id, {})
        known = verified.content_digest in variants
        variants.setdefault(verified.content_digest, verified)
        self._deliveries[verified.evidence_id] = self._deliveries.get(verified.evidence_id, 0) + 1
        if len(variants) > 1:
            outcome = CONFLICT_QUARANTINED
        else:
            outcome = DUPLICATE if known else ACCEPTED_NEW
        return Admission(outcome, verified.evidence_id, verified.content_digest, self.state(verified.evidence_id))

    def state(self, evidence_id):
        variants = self._variants.get(evidence_id)
        if not variants:
            return None
        return AUTHORITATIVE if len(variants) == 1 else CONFLICTED

    def authoritative(self, evidence_id):
        """The single accepted record, or ``None`` if unknown or conflicted."""
        variants = self._variants.get(evidence_id, {})
        return next(iter(variants.values())) if len(variants) == 1 else None

    def quarantined(self, evidence_id):
        """Every retained variant of a conflicted identity, ordered by content digest."""
        variants = self._variants.get(evidence_id, {})
        return tuple(variants[d] for d in sorted(variants)) if len(variants) > 1 else ()

    def snapshot(self):
        """Canonical-compatible summary; identical for any delivery order of the same deliveries."""
        return {"contract_version": EVIDENCE_VERSION, "ledger": "in-memory-classifier",
                "entries": [{"evidence_id": eid, "state": self.state(eid),
                             "content_digests": sorted(self._variants[eid]),
                             "deliveries": self._deliveries[eid]}
                            for eid in sorted(self._variants)]}
