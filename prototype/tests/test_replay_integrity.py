import shutil
import unittest

from ca_eval.scorer import TruthIntegrityError, load_truth
from ca_spike.fixtures import FixtureIntegrityError, verify_fixture_dir
from ca_spike.pipeline import replay
from ca_spike.store import FileArtifactStore
from tests.helpers import FIXTURES, ROOT, RunTestCase


class ReplayTests(RunTestCase):
    def _copy(self, store, name):
        dest = self.tmp / name
        shutil.copytree(store.run_dir, dest)
        return FileArtifactStore(dest)

    def test_replay_is_equivalent_for_all_variants(self):
        for v in "ABCDE":
            run, store, _ = self.run_variant(v)
            result = replay(store)
            self.assertEqual(result["state"], "equivalent", v)
            self.assertEqual(result["bundle_digest"], run["bundle_digest"])

    def test_edited_artifacts_are_integrity_mismatch(self):
        _, store, _ = self.run_variant("A")
        cases = {
            "evidence.json": lambda d: d[0]["attributes"].update(actor="someone-else"),
            "inputs.json": lambda d: d["deliveries"][0]["observation"]["attributes"].update(extra="x"),
            "bundle.json": lambda d: d["bundle"]["outcome"].update(status="abstained"),
            "manifest.json": lambda d: d["manifest"]["evidence"].pop(),
        }
        for name, edit in cases.items():
            with self.subTest(artifact=name):
                copy = self._copy(store, f"tamper-{name}")
                data = copy.get(name)
                edit(data)
                copy.put(name, data)
                self.assertEqual(replay(copy)["state"], "integrity_mismatch")

    def test_missing_artifact_is_missing_unexplained(self):
        _, store, _ = self.run_variant("B")
        copy = self._copy(store, "missing")
        (copy.run_dir / "evidence.json").unlink()
        self.assertEqual(replay(copy)["state"], "missing_unexplained")

    def test_version_change_is_explicit_incompatibility(self):
        _, store, _ = self.run_variant("A")
        copy = self._copy(store, "version")
        data = copy.get("manifest.json")
        data["manifest"]["versions"]["ledger_rule"] = "ca-ledger/0.0-old"
        copy.put("manifest.json", data)
        self.assertEqual(replay(copy)["state"], "version_incompatible")


class FrozenInputTests(RunTestCase):
    def test_fixture_byte_change_is_detected(self):
        fx = self.tmp / "fixtures"
        shutil.copytree(FIXTURES, fx)
        verify_fixture_dir(fx)
        path = fx / "variants" / "B.json"
        path.write_bytes(path.read_bytes().replace(b"connector_timeout", b"connector_timeouT"))
        with self.assertRaises(FixtureIntegrityError):
            verify_fixture_dir(fx)

    def test_truth_byte_change_is_detected(self):
        root = self.tmp / "root"
        shutil.copytree(ROOT / "truth", root / "truth")
        (root / "ca_eval").mkdir(parents=True)
        shutil.copy(ROOT / "ca_eval" / "truth-pins.json", root / "ca_eval" / "truth-pins.json")
        load_truth(root, "ca-scenario-001")
        path = root / "truth" / "ca-scenario-001" / "ground-truth.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(TruthIntegrityError):
            load_truth(root, "ca-scenario-001")


if __name__ == "__main__":
    unittest.main()
