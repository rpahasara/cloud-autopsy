import copy
import tempfile
import unittest
from pathlib import Path

from ca_spike.fixtures import load_scenario
from ca_spike.pipeline import run_investigation
from ca_spike.store import FileArtifactStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "ca-scenario-001"
CM_REF = "k8s:configmap/ca-demo/checkout-db-pool@1002"


class RunTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._count = 0

    def tearDown(self):
        self._tmp.cleanup()

    def scenario(self, variant="A"):
        return copy.deepcopy(load_scenario(FIXTURES, variant))

    def run_scenario(self, scenario, **kwargs):
        self._count += 1
        store = FileArtifactStore(self.tmp / f"run-{self._count}")
        run = run_investigation(scenario, store, **kwargs)
        return run, store, store.get("bundle.json")["bundle"]

    def run_variant(self, variant, **kwargs):
        return self.run_scenario(self.scenario(variant), **kwargs)


def hypothesis(bundle, mechanism):
    return next(h for h in bundle["ledger"]["hypotheses"] if h["mechanism"] == mechanism)


def prereq(hyp, key):
    return next(p for p in hyp["prerequisites"] if p["key"] == key)


def evidence_id(store, source_ref):
    return next(e["evidence_id"] for e in store.get("evidence.json") if e["source_ref"] == source_ref)


def acquisition(scenario, query_id):
    return next(a for a in scenario["observations"]["acquisitions"] if a["query_id"] == query_id)
