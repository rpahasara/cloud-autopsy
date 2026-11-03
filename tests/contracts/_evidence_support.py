"""Shared helpers for CA-P2-002c evidence tests."""

import copy
import json

import _support
from cloud_autopsy.contracts import evidence as ev, sources

VECTORS = _support.PACKAGE / "contracts" / "vectors" / "ca-evidence-0.1-provisional.json"
DOC = json.loads(VECTORS.read_bytes().decode("utf-8"))
REGISTRY = sources.SourceRegistry.from_record(DOC["registry"])


def case(name):
    """Return a deep copy of (source_id, observation) for a named vector observation."""
    item = DOC["observations"][name]
    return item["source_id"], copy.deepcopy(item["observation"])


def build(name, registry=REGISTRY):
    source_id, observation = case(name)
    return ev.observe(observation, source_id=source_id, registry=registry)


def apply(observation, sets=(), deletes=()):
    for path, value in sets:
        target = observation
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    for path in deletes:
        target = observation
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return observation
