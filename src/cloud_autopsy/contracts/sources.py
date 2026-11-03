"""Source registry ``ca-source-registry/0.1-provisional`` (CA-P2-002c).

The registry is reviewed configuration, not caller input. It binds each ``source_id`` to its
source kind, an opaque cluster identity, one namespace, the clock domains the source may
report and the query IDs it may answer. Evidence identity takes ``cluster_id`` and
``namespace`` from this binding only; an observation can never assert its own cluster.
Pinning the registry digest into a run plan (CA-CON-001) is later work.
"""

import re
from dataclasses import dataclass

from . import canonical
from . import errors as E
from .errors import EvidenceError, RecordError
from .versioning import check_envelope

SOURCE_REGISTRY_VERSION = "ca-source-registry/0.1-provisional"
SOURCE_KINDS = ("kubernetes_api", "prometheus", "loki")
MAX_SOURCES = 64        # PROVISIONAL
MAX_BOUND_IDS = 64      # PROVISIONAL: clock domains or query IDs per source

IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}", re.ASCII)
NAMESPACE = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?", re.ASCII)
_DEFINITION_FIELDS = ("source_id", "source_kind", "cluster_id", "namespace", "clock_domain_ids", "query_ids")


def _invalid(detail):
    return EvidenceError(E.REGISTRY_INVALID, detail)


def _id_list(value, name):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_BOUND_IDS:
        raise _invalid(f"{name} must list 1..{MAX_BOUND_IDS} identifiers")
    if not all(isinstance(v, str) and IDENTIFIER.fullmatch(v) for v in value):
        raise _invalid(f"{name} entries must be lowercase identifiers")
    if len(set(value)) != len(value):
        raise _invalid(f"{name} has duplicate entries")
    return tuple(sorted(value))


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    source_kind: str
    cluster_id: str
    namespace: str
    clock_domain_ids: tuple
    query_ids: tuple

    def to_record(self):
        return {"source_id": self.source_id, "source_kind": self.source_kind, "cluster_id": self.cluster_id,
                "namespace": self.namespace, "clock_domain_ids": list(self.clock_domain_ids),
                "query_ids": list(self.query_ids)}

    @property
    def binding_digest(self):
        """Digest of the whole binding, recorded on evidence so registry changes are traceable."""
        return canonical.digest(self.to_record())


def source_definition(record):
    if not isinstance(record, dict):
        raise RecordError(E.RECORD_NOT_OBJECT, "source definition must be an object")
    missing = [f for f in _DEFINITION_FIELDS if f not in record]
    if missing:
        raise RecordError(E.RECORD_FIELD_MISSING, f"SourceDefinition.{missing[0]} is required")
    if set(record) - set(_DEFINITION_FIELDS):
        raise RecordError(E.RECORD_FIELD_UNKNOWN, "source definition has an unknown field")
    for name in ("source_id", "cluster_id"):
        if not isinstance(record[name], str) or not IDENTIFIER.fullmatch(record[name]):
            raise _invalid(f"{name} must be a lowercase identifier")
    if record["source_kind"] not in SOURCE_KINDS:
        raise _invalid("source_kind is not supported")
    if not isinstance(record["namespace"], str) or not NAMESPACE.fullmatch(record["namespace"]):
        raise _invalid("namespace must be a DNS-1123 label")
    return SourceDefinition(record["source_id"], record["source_kind"], record["cluster_id"], record["namespace"],
                            _id_list(record["clock_domain_ids"], "clock_domain_ids"),
                            _id_list(record["query_ids"], "query_ids"))


@dataclass(frozen=True)
class SourceRegistry:
    registry_id: str
    sources: tuple  # SourceDefinition, sorted by source_id

    def get(self, source_id):
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise EvidenceError(E.SOURCE_UNKNOWN, "source is not in the registry")

    def to_record(self):
        return {"contract_version": SOURCE_REGISTRY_VERSION, "registry_id": self.registry_id,
                "sources": [s.to_record() for s in self.sources]}

    @property
    def digest(self):
        return canonical.digest(self.to_record())

    @classmethod
    def from_record(cls, record):
        if not isinstance(record, dict):
            raise RecordError(E.RECORD_NOT_OBJECT, "source registry must be an object")
        check_envelope(record, SOURCE_REGISTRY_VERSION)
        expected = {"contract_version", "registry_id", "sources"}
        if expected - set(record):
            raise RecordError(E.RECORD_FIELD_MISSING, "source registry needs registry_id and sources")
        if set(record) - expected:
            raise RecordError(E.RECORD_FIELD_UNKNOWN, "source registry has an unknown field")
        if not isinstance(record["registry_id"], str) or not IDENTIFIER.fullmatch(record["registry_id"]):
            raise _invalid("registry_id must be a lowercase identifier")
        sources = record["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
            raise _invalid(f"sources must list 1..{MAX_SOURCES} definitions")
        definitions = [source_definition(s) for s in sources]
        if len({d.source_id for d in definitions}) != len(definitions):
            raise _invalid("source_id values must be unique")
        return cls(record["registry_id"], tuple(sorted(definitions, key=lambda d: d.source_id)))
