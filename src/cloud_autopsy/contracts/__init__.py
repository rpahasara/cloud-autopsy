"""Versioned evidence, time and manifest contracts (CA-P2-002). All versions are provisional.

Slice CA-P2-002a provides typed errors, exact-match versioning and the canonical JSON
profile; CA-P2-002b adds timestamp provenance and clock intervals; CA-P2-002c adds the
source registry, observation kinds, evidence identity and conflict classification.
Contracts perform no I/O beyond the bytes or values passed to them.
"""

from .canonical import CANON_VERSION, DIGEST_ALGORITHM
from .evidence import (CONTENT_ALGORITHM, EVIDENCE_VERSION, ID_ALGORITHM, KIND_REGISTRY_VERSION,
                       OBSERVATION_VERSION)
from .sources import SOURCE_REGISTRY_VERSION
from .timeinterval import TIME_VERSION

# Contract name -> exact version identifier implemented by this package.
CONTRACT_VERSIONS = {
    "canonical-json": CANON_VERSION,
    "canonical-digest": DIGEST_ALGORITHM,
    "time-interval": TIME_VERSION,
    "source-registry": SOURCE_REGISTRY_VERSION,
    "observation": OBSERVATION_VERSION,
    "observation-kinds": KIND_REGISTRY_VERSION,
    "evidence": EVIDENCE_VERSION,
    "evidence-id": ID_ALGORITHM,
    "evidence-content-digest": CONTENT_ALGORITHM,
}
CONTRACT_STATUS = "provisional: unreviewed; not RFC 8785 conformance evidence"
