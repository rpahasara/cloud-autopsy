"""Storage-independent evidence model (ca-evidence/0.1-spike).

Each record mirrors a relation of the proposed PostgreSQL logical model
(docs/architecture/phase1c/data-model.md) so a later storage adapter can map them
one-to-one: Evidence -> evidence + evidence_time, AcquisitionOutcome -> acquisition,
Gap -> gap, Relation -> provenance_edge (derived relations), Hypothesis -> hypothesis
+ hypothesis_evidence + hypothesis_gap.
"""

from dataclasses import asdict, dataclass

from .canonical import canonical_bytes, digest, sha256_hex
from .timemodel import EvidenceTime, build_time

SCHEMA_VERSION = "ca-evidence/0.1-spike"
IDENTITY_ALGORITHM = "ca-evid/0.1-spike"

EVIDENCE_CLASS = {
    "configmap_change": "K8S-CONFIG",
    "deployment_rollout": "K8S-DEPLOY",
    "replicaset": "K8S-DEPLOY",
    "pod": "K8S-POD",
    "log_line": "LOG",
    "metric_sample": "METRIC",
    "alert_firing": "ALERT",
}

ACQUISITION_STATUSES = ("complete", "partial", "empty", "failed", "denied", "truncated")


class NormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    evidence_class: str
    observation_kind: str
    schema_version: str
    source_id: str
    query_id: str
    source_ref: str
    source_uid: str
    source_version: str
    entity: dict
    times: tuple
    attributes: dict
    content_digest: str
    trust: str = "untrusted-source-data"

    def primary_time(self):
        return self.times[0] if self.times else None

    def time_of(self, type_):
        return next((t for t in self.times if t.type == type_), None)

    def record(self):
        return asdict(self)


@dataclass(frozen=True)
class AcquisitionOutcome:
    query_id: str
    source_id: str
    status: str
    reason: str
    window: dict
    observations_received: int
    observations_rejected: int


@dataclass(frozen=True)
class Gap:
    gap_id: str
    query_id: str
    source_id: str
    gap_type: str
    reason: str
    window: dict
    detector_rule: str
    affects_mechanisms: tuple


@dataclass(frozen=True)
class Relation:
    relation_id: str
    relation_type: str
    inputs: tuple
    rule_version: str
    attributes: dict


def evidence_identity(source_id, observation_kind, source_uid, source_version):
    return {"algorithm": IDENTITY_ALGORITHM, "source_id": source_id, "observation_kind": observation_kind,
            "source_uid": source_uid, "source_version": source_version}


def make_evidence_id(evidence_class, identity):
    return f"ev:{evidence_class}:{sha256_hex(canonical_bytes(identity))[:24]}"


def observation_payload(obs):
    """The source-observed content that the content digest covers."""
    keys = ("source_ref", "observation_kind", "source_uid", "source_version", "entity", "times", "attributes")
    return {k: obs.get(k) for k in keys}


def normalize(obs, query_id, source_id, clock_domains):
    """Normalize one untrusted fixture observation into an immutable Evidence record."""
    kind = obs.get("observation_kind")
    if kind not in EVIDENCE_CLASS:
        raise NormalizationError(f"unsupported observation kind {kind!r}")
    for field in ("source_ref", "source_uid", "source_version"):
        if not isinstance(obs.get(field), str) or not obs[field]:
            raise NormalizationError(f"missing {field}")
    if not isinstance(obs.get("entity"), dict) or not isinstance(obs.get("attributes"), dict):
        raise NormalizationError("entity and attributes must be objects")
    if not isinstance(obs.get("times"), list):
        raise NormalizationError("times must be a list")
    evidence_class = EVIDENCE_CLASS[kind]
    identity = evidence_identity(source_id, kind, obs["source_uid"], obs["source_version"])
    times = tuple(build_time(t, clock_domains) for t in obs["times"])
    return Evidence(
        evidence_id=make_evidence_id(evidence_class, identity), evidence_class=evidence_class,
        observation_kind=kind, schema_version=SCHEMA_VERSION, source_id=source_id, query_id=query_id,
        source_ref=obs["source_ref"], source_uid=obs["source_uid"], source_version=obs["source_version"],
        entity=obs["entity"], times=times, attributes=obs["attributes"],
        content_digest=digest(observation_payload(obs)))


def evidence_from_record(record):
    """Rehydrate a stored Evidence record (used by replay)."""
    data = dict(record)
    data["times"] = tuple(EvidenceTime(**t) for t in data["times"])
    return Evidence(**data)
