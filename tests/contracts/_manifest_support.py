"""Shared helpers for CA-P2-002d plan, batch and frozen-input tests."""

import copy
import json

import _evidence_support as ES
import _support
from cloud_autopsy.contracts import acquisition as acq, plan as pl
from cloud_autopsy.contracts import timeinterval as ti

VECTORS = _support.PACKAGE / "contracts" / "vectors" / "ca-frozen-input-0.1-provisional.json"
DOC = json.loads(VECTORS.read_bytes().decode("utf-8"))
REGISTRY = ES.REGISTRY


def plan_record(acquisitions, **overrides):
    base = copy.deepcopy(DOC["plan_base"])
    record = {"contract_version": pl.RUN_PLAN_VERSION, **base, "registry_id": REGISTRY.registry_id,
              "registry_digest": REGISTRY.digest, "contract_versions": pl.required_contract_versions(),
              "expected_acquisitions": [dict(DOC["acquisitions"][a]) for a in acquisitions]}
    record.update(overrides)
    return record


def make_plan(acquisitions, **overrides):
    return pl.RunPlan.from_record(plan_record(acquisitions, **overrides), REGISTRY)


def batch_record(name, plan, attempt=1):
    spec = copy.deepcopy(DOC["batches"][name])
    acquisition = DOC["acquisitions"][spec.pop("acquisition")]
    spec["observations"] = [ES.case(o)[1] for o in spec["observations"]]
    return {"contract_version": acq.BATCH_VERSION, "plan_digest": plan.digest,
            "source_id": acquisition["source_id"], "query_id": acquisition["query_id"], **spec,
            "delivery": {"attempt": attempt}}


def ms(raw):
    return ti.parse_rfc3339(raw).epoch_ns // ti.NS_PER_MS
