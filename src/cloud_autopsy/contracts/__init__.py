"""Versioned evidence, time and manifest contracts (CA-P2-002). All versions are provisional.

Slice CA-P2-002a provides typed errors, exact-match versioning and the canonical JSON
profile; CA-P2-002b adds timestamp provenance and clock intervals; CA-P2-002c adds the
source registry, observation kinds, evidence identity and conflict classification;
CA-P2-002d adds run plans, acquisition batches and frozen-input manifests.
Contracts perform no I/O beyond the bytes or values passed to them.
"""

from .acquisition import BATCH_VERSION, BATCH_VERSION_V2
from .canonical import CANON_VERSION, DIGEST_ALGORITHM
from .evidence import (CONTENT_ALGORITHM, EVIDENCE_VERSION, ID_ALGORITHM, KIND_REGISTRY_VERSION,
                       KIND_REGISTRY_VERSION_V2, KIND_REGISTRY_VERSION_V3, KIND_REGISTRY_VERSION_V4,
                       OBSERVATION_VERSION)
from .frozen_input import FROZEN_INPUT_VERSION, GAP_POLICY_VERSION, MANIFEST_ALGORITHM
from .plan import RUN_PLAN_VERSION
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
    "run-plan": RUN_PLAN_VERSION,
    "acquisition-batch": BATCH_VERSION,
    "frozen-input": FROZEN_INPUT_VERSION,
    "frozen-input-digest": MANIFEST_ALGORITHM,
    "gap-policy": GAP_POLICY_VERSION,
}
# CA-P2-004d: the exact contract-version sets a run plan may pin. ``CONTRACT_VERSIONS`` above is
# the baseline (observation kinds 0.1) and stays the default, so existing plans, frozen inputs and
# results are byte-identical. The only other profile differs in observation kinds alone (0.2).
# There is no mixing: a plan pins one whole profile, and its evidence is decoded under that profile.
# CA-P2-004f adds profile 3 (collector watch plans only): profile 2 with acquisition batch 0.2 and
# observation kinds 0.3. Profiles 1 and 2 are unchanged.
CONTRACT_PROFILES = (
    CONTRACT_VERSIONS,
    {**CONTRACT_VERSIONS, "observation-kinds": KIND_REGISTRY_VERSION_V2},
    {**CONTRACT_VERSIONS, "observation-kinds": KIND_REGISTRY_VERSION_V3, "acquisition-batch": BATCH_VERSION_V2},
    # CA-P2-002e: profile 4 is profile 3 with observation kinds 0.4 (pod logs from the Kubernetes API).
    {**CONTRACT_VERSIONS, "observation-kinds": KIND_REGISTRY_VERSION_V4, "acquisition-batch": BATCH_VERSION_V2},
)
# Versions a database must list as additionally supported (migrations 0006, 0008 and 0009), per contract.
ADDITIONAL_CONTRACT_VERSIONS = {"observation-kinds": (KIND_REGISTRY_VERSION_V2, KIND_REGISTRY_VERSION_V3,
                                                       KIND_REGISTRY_VERSION_V4),
                                "acquisition-batch": (BATCH_VERSION_V2,)}
CONTRACT_STATUS ="provisional: unreviewed; not RFC 8785 conformance evidence"
