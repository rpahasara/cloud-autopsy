"""Versioned fixture loading, integrity verification and variant overlays.

The engine may only read the fixture directory. Paths inside an evaluator truth
directory are refused even if passed explicitly.
"""

import copy
import hashlib
from pathlib import Path

from .canonical import loads_strict

MAX_FIXTURE_FILE_BYTES = 16 * 1024 * 1024


class FixtureIntegrityError(RuntimeError):
    pass


def _guard(path):
    resolved = Path(path).resolve()
    if any(part.lower() == "truth" for part in resolved.parts):
        raise PermissionError(f"engine may not read evaluator truth: {resolved}")
    return resolved


def read_json(path, max_bytes=MAX_FIXTURE_FILE_BYTES):
    return loads_strict(_guard(path).read_bytes(), max_bytes=max_bytes)


def verify_fixture_dir(fixture_dir):
    """Verify every file listed in fixture-manifest.json against its SHA-256 digest."""
    root = _guard(fixture_dir)
    manifest = read_json(root / "fixture-manifest.json")
    mismatches = []
    for rel, expected in sorted(manifest["files"].items()):
        path = _guard(root / rel)
        if not path.is_file():
            mismatches.append({"file": rel, "problem": "missing"})
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            mismatches.append({"file": rel, "problem": "digest_mismatch", "expected": expected, "actual": actual})
    if mismatches:
        raise FixtureIntegrityError({"fixture_dir": str(root), "mismatches": mismatches})
    return manifest


def _find_observation(doc, source_ref):
    for acq in doc["acquisitions"]:
        for i, obs in enumerate(acq["observations"]):
            if obs["source_ref"] == source_ref:
                return acq, i
    raise KeyError(source_ref)


def _find_acquisition(doc, query_id):
    for acq in doc["acquisitions"]:
        if acq["query_id"] == query_id:
            return acq
    raise KeyError(query_id)


def apply_variant(observations_doc, variant):
    doc = copy.deepcopy(observations_doc)
    for op in variant["ops"]:
        kind = op["op"]
        if kind == "remove_observation":
            acq, i = _find_observation(doc, op["source_ref"])
            del acq["observations"][i]
        elif kind == "add_observation":
            _find_acquisition(doc, op["query_id"])["observations"].append(copy.deepcopy(op["observation"]))
        elif kind == "set_acquisition_status":
            acq = _find_acquisition(doc, op["query_id"])
            acq["status"] = op["status"]
            acq["reason"] = op.get("reason")
        elif kind == "set_clock_domain":
            doc["clock_domains"][op["domain"]] = copy.deepcopy(op["clock"])
        elif kind == "set_time_raw":
            acq, i = _find_observation(doc, op["source_ref"])
            for entry in acq["observations"][i]["times"]:
                if entry["type"] == op["time_type"]:
                    entry["raw"] = op["raw"]
        else:
            raise ValueError(f"unknown variant op {kind!r}")
    return doc


def load_scenario(fixture_dir, variant_id):
    """Verify and load a fixture, returning the effective inputs for one variant."""
    root = _guard(fixture_dir)
    manifest = verify_fixture_dir(root)
    variant = read_json(root / "variants" / f"{variant_id}.json")
    observations = apply_variant(read_json(root / "observations.json"), variant)
    plan = read_json(root / "source-plan.json")
    stub = None
    if variant["synthesis"]["mode"] == "stub":
        stub = read_json(root / variant["synthesis"]["stub"])
    return {
        "fixture_manifest": manifest,
        "variant": variant,
        "observations": observations,
        "plan": plan,
        "synthesis_stub": stub,
    }
