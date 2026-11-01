"""Self-tests for the held-out evaluation kit.

The end-to-end test uses the public development fixture ca-scenario-001 and its pinned truth to
exercise the tooling only. It is not a held-out evaluation and produces no evaluation evidence.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heldout_kit as kit  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "docs" / "evaluation" / "heldout" / "templates"
DEV_FIXTURE = REPO / "prototype" / "fixtures" / "ca-scenario-001"
DEV_TRUTH = REPO / "prototype" / "truth" / "ca-scenario-001" / "ground-truth.json"
CANDIDATE = "c21b50dc5edd6cd07de55d2f3e0bce6103b4d952"


class KitTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        if kit.git_work_tree(self.tmp) is not None:
            self.skipTest("temporary directory is inside a Git work tree")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path


class FreezeTests(KitTestCase):
    def test_blank_templates_cannot_be_frozen(self):
        for family in ("CA-SCENARIO-008", "CA-SCENARIO-009", "CA-SCENARIO-010"):
            for part, role in (("fixture", "fixtures"), ("metadata", "metadata")):
                copy = self.tmp / family / part
                shutil.copytree(TEMPLATES / family / part, copy)
                with self.assertRaisesRegex(kit.KitError, "placeholder|template"):
                    kit.collect(copy, role)

    def test_fixtures_inside_a_git_work_tree_are_refused(self):
        with self.assertRaisesRegex(kit.KitError, "outside any Git work tree"):
            kit.freeze(TEMPLATES / "CA-SCENARIO-008" / "fixture", "fixtures", "x")

    def test_truth_named_paths_are_refused_in_fixtures(self):
        self.write("fx/fixture-manifest.json", "{}")
        self.write("fx/ground-truth.json", "{}")
        with self.assertRaisesRegex(kit.KitError, "truth"):
            kit.freeze(self.tmp / "fx", "fixtures", "x")

    def test_strict_json_rules(self):
        for text, reason in (('{"a": 1, "a": 2}', "duplicate"), ('{"a": 1.5}', "float"), ('{"a": NaN}', "non-finite"),
                             ("﻿{}", "byte-order"), ("{", "malformed")):
            with self.subTest(reason):
                with self.assertRaisesRegex(kit.KitError, reason):
                    kit.strict_json(text.encode("utf-8"), "t")

    def test_verify_reports_changed_missing_and_extra_files(self):
        self.write("m/a.json", '{"x": "1"}')
        self.write("m/b.json", '{"y": "2"}')
        record = kit.freeze(self.tmp / "m", "metadata", "m")
        self.assertEqual(kit.verify(record, self.tmp / "m"), [])
        self.write("m/a.json", '{"x": "2"}')
        (self.tmp / "m" / "b.json").unlink()
        self.write("m/c.json", "{}")
        self.assertEqual(kit.verify(record, self.tmp / "m"), ["missing:b.json", "unexpected:c.json", "changed:a.json"])

    def test_manifest_matches_engine_format(self):
        copy = self.tmp / "fx"
        shutil.copytree(DEV_FIXTURE, copy)
        expected = json.loads((DEV_FIXTURE / "fixture-manifest.json").read_bytes())
        (copy / "fixture-manifest.json").unlink()
        (copy / "fixture-manifest.json").write_text("{}")  # collect() needs a JSON file in place
        produced = kit.write_manifest(copy, expected["fixture_id"], expected["fixture_version"])
        self.assertEqual(produced, expected)


class TruthCommitmentTests(KitTestCase):
    def test_commit_and_open_roundtrip(self):
        truth = self.write("t/ground-truth.json", '{"answer": "x"}')
        record = kit.commit_truth(truth, self.tmp / "t" / "salt.hex")
        self.assertNotIn("truth_sha256", record)
        kit.open_truth(truth, self.tmp / "t" / "salt.hex", record["truth_commitment"])
        self.write("t/ground-truth.json", '{"answer": "y"}')
        with self.assertRaisesRegex(kit.KitError, "does not match"):
            kit.open_truth(truth, self.tmp / "t" / "salt.hex", record["truth_commitment"])

    def test_salt_is_never_overwritten_and_truth_must_be_outside_git(self):
        truth = self.write("t/ground-truth.json", "{}")
        kit.commit_truth(truth, self.tmp / "t" / "salt.hex")
        with self.assertRaisesRegex(kit.KitError, "already exists"):
            kit.commit_truth(truth, self.tmp / "t" / "salt.hex")
        with self.assertRaisesRegex(kit.KitError, "outside any Git work tree"):
            kit.commit_truth(DEV_TRUTH, self.tmp / "t" / "salt2.hex")

    def test_commitments_differ_for_identical_truth(self):
        truth = self.write("t/ground-truth.json", "{}")
        a = kit.commit_truth(truth, self.tmp / "t" / "s1.hex")["truth_commitment"]
        b = kit.commit_truth(truth, self.tmp / "t" / "s2.hex")["truth_commitment"]
        self.assertNotEqual(a, b)


class EndToEndToolingTests(KitTestCase):
    """Tooling smoke test on public development data; not evaluation evidence."""

    def setUp(self):
        super().setUp()
        self.fixtures = self.tmp / "fixtures" / "DEV-SMOKE"
        shutil.copytree(DEV_FIXTURE, self.fixtures)
        # A sealed variant the candidate cannot execute (no synthesis block): must be recorded, not dropped.
        (self.fixtures / "variants" / "Z.json").write_text(json.dumps({"variant": "Z", "description": "x", "ops": []}))
        kit.write_manifest(self.fixtures, "ca-scenario-001", "0.1.0-spike")
        self.truth = self.tmp / "private" / "ground-truth.json"
        self.truth.parent.mkdir()
        shutil.copyfile(DEV_TRUTH, self.truth)
        pub = self.tmp / "pub" / "DEV-SMOKE"
        (pub / "metadata").mkdir(parents=True)
        person = {"name": "n", "affiliation": "a", "attestation": "t"}
        (pub / "metadata" / "eval-metadata.json").write_text(json.dumps({
            "metadata_version": "ca-heldout-meta/0.1", "scenario_id": "DEV-SMOKE", "fixture_id": "ca-scenario-001",
            "coverage_category": "tooling self-test", "split": "held_out", "candidate_commit": CANDIDATE,
            "variants": ["A", "B", "C", "D", "E", "Z"], "source_allowlist": ["k8s-api", "loki", "prometheus"],
            "author": person, "reviewer": person, "prepublication_review": {"name": "n", "attestation": "t"},
            "notes": ""}))
        (pub / "fixtures.freeze.json").write_text(json.dumps(kit.freeze(self.fixtures, "fixtures", "DEV-SMOKE")))
        (pub / "metadata.freeze.json").write_text(json.dumps(kit.freeze(pub / "metadata", "metadata", "DEV-SMOKE")))
        (pub / "truth.commitment.json").write_text(json.dumps(kit.commit_truth(self.truth, self.truth.parent / "salt")))
        self.seal = kit.seal(self.tmp / "pub", CANDIDATE, "test-author", "test-reviewer")

    def test_run_freeze_and_score_report_every_variant(self):
        out = self.tmp / "pred"
        log, record = kit.run(REPO, self.seal, {"DEV-SMOKE": self.fixtures}, out, git_check=False)
        status = {v["variant"]: v["execution"] for v in log["families"][0]["variants"]}
        self.assertEqual(status["Z"], "failed")  # unexecutable sealed variant: recorded, not dropped
        self.assertTrue(all(status[v] == "completed" for v in "ABCDE"))
        results = kit.score(REPO, self.seal, out, record,
                            {"DEV-SMOKE": (self.truth, self.truth.parent / "salt")}, git_check=False)
        primary = {r["variant"]: r["classification"]["primary"] for r in results["families"][0]["variants"]}
        self.assertEqual(primary["A"], "correct_attribution")
        self.assertEqual(primary["B"], "justified_abstention")
        self.assertEqual(primary["Z"], "execution_failed")
        self.assertEqual(results["variants_total"], 6)
        self.assertEqual(results["git_check"], "skipped")

    def test_score_refuses_predictions_changed_after_freezing(self):
        out = self.tmp / "pred"
        _, record = kit.run(REPO, self.seal, {"DEV-SMOKE": self.fixtures}, out, git_check=False)
        bundle = out / "DEV-SMOKE" / "A" / "bundle.json"
        bundle.write_bytes(bundle.read_bytes().replace(b"resolved", b"abstained"))
        with self.assertRaisesRegex(kit.KitError, "changed after freezing"):
            kit.score(REPO, self.seal, out, record, {"DEV-SMOKE": (self.truth, self.truth.parent / "salt")},
                      git_check=False)

    def test_tampered_fixture_archive_is_not_run(self):
        obs = self.fixtures / "observations.json"
        obs.write_bytes(obs.read_bytes() + b" ")
        log, _ = kit.run(REPO, self.seal, {"DEV-SMOKE": self.fixtures}, self.tmp / "pred", git_check=False)
        family = log["families"][0]
        self.assertEqual(family["fixture_integrity"]["status"], "failed")
        self.assertTrue(all(v["execution"] == "not_run" for v in family["variants"]))

    def test_seal_rejects_published_truth_fields_and_wrong_candidate(self):
        path = self.tmp / "pub" / "DEV-SMOKE" / "truth.commitment.json"
        doc = json.loads(path.read_text())
        path.write_text(json.dumps(dict(doc, truth_sha256="leak")))
        with self.assertRaisesRegex(kit.KitError, "unexpected fields"):
            kit.seal(self.tmp / "pub", CANDIDATE, "a", "r")
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(kit.KitError, "candidate_commit"):
            kit.seal(self.tmp / "pub", "0" * 40, "a", "r")

    def test_seal_digest_is_checked(self):
        path = self.tmp / "seal.json"
        path.write_text(json.dumps(dict(self.seal, reviewer="someone else")))
        with self.assertRaisesRegex(kit.KitError, "own digest"):
            kit.load_seal(path)


if __name__ == "__main__":
    unittest.main()
