"""Engine test setup: pure, no database. Builds verified inputs from the synthetic scenario."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cloud_autopsy.contracts import acquisition as acq  # noqa: E402
from cloud_autopsy.contracts import frozen_input as fi  # noqa: E402
from cloud_autopsy.engine import inputs  # noqa: E402
from cloud_autopsy.synthetic import scenario_001 as scenario  # noqa: E402


def sealed(variant, records=None):
    """(plan, registry, frozen, member evidence records) for a variant's deliveries."""
    plan, registry = scenario.plan(variant), scenario.registry()
    records = scenario.batches(variant) if records is None else records
    frozen = fi.seal(plan, registry, records)
    members = {(m["evidence_id"], m["content_digest"]) for m in fi.collection_items(frozen, "evidence")}
    evidence = {}
    for record in records:
        for item in acq.decode_batch(record, plan, registry).evidence:
            if (item.evidence_id, item.content_digest) in members:
                evidence[item.evidence_id] = item.to_record()
    return plan, registry, frozen, [evidence[k] for k in sorted(evidence)]


def build(variant, records=None, domains=None):
    plan, registry, frozen, evidence = sealed(variant, records)
    domains = scenario.clock_domain_records(variant) if domains is None else domains
    return inputs.build_input(frozen, plan, registry, evidence, domains)
