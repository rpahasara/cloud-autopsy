"""PR #14 review regressions: path traversal, complete failure reporting, output layout, metadata schema.

Uses the public development fixture ca-scenario-001 and its pinned truth to exercise the tooling
only. No held-out scenario content is involved and nothing here is evaluation evidence.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heldout_kit as kit  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEV_FIXTURE = REPO / "prototype" / "fixtures" / "ca-scenario-001"
DEV_TRUTH = REPO / "prototype" / "truth" / "ca-scenario-001" / "ground-truth.json"
CANDIDATE = "c21b50dc5edd6cd07de55d2f3e0bce6103b4d952"


def metadata(sid, variants, **extra):
    doc = {"metadata_version": "ca-heldout-meta/0.1", "scenario_id": sid, "fixture_id": "ca-scenario-001",
           "coverage_category": "tooling self-test", "split": "held_out", "candidate_commit": CANDIDATE,
           "variants": list(variants), "source_allowlist": ["k8s-api", "loki", "prometheus"],
           "author": {"name": "a", "affiliation": "x", "attestation": "t"},
           "reviewer": {"name": "r", "affiliation": "x", "attestation": "t"},
           "prepublication_review": {"name": "p", "attestation": "public metadata reviewed; no answers"},
           "notes": ""}
    doc.update(extra)
    return doc


class Pr14TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        if kit.git_work_tree(self.tmp) is not None:
            self.skipTest("temporary directory is inside a Git work tree")
        self.pub = self.tmp / "pub"
        self.fx, self.truth = {}, {}

    def tearDown(self):
        self._tmp.cleanup()

    def family(self, sid, variants=("A", "B"), meta=None, fixture_edit=None):
        fx = self.tmp / "fixtures" / sid
        shutil.copytree(DEV_FIXTURE, fx)
        if fixture_edit:
            fixture_edit(fx)
            kit.write_manifest(fx, "ca-scenario-001", "0.1.0-spike")
        private = self.tmp / "private" / sid
        private.mkdir(parents=True)
        shutil.copyfile(DEV_TRUTH, private / "ground-truth.json")
        fam = self.pub / sid
        (fam / "metadata").mkdir(parents=True)
        (fam / "metadata" / "eval-metadata.json").write_text(json.dumps(meta or metadata(sid, variants)))
        (fam / "fixtures.freeze.json").write_text(json.dumps(kit.freeze(fx, "fixtures", sid)))
        (fam / "metadata.freeze.json").write_text(json.dumps(kit.freeze(fam / "metadata", "metadata", sid)))
        (fam / "truth.commitment.json").write_text(json.dumps(kit.commit_truth(private / "ground-truth.json",
                                                                               private / "salt.hex")))
        self.fx[sid] = fx
        self.truth[sid] = (private / "ground-truth.json", private / "salt.hex")
        return fx

    def seal(self):
        return kit.seal(self.pub, CANDIDATE, "author", "reviewer")

    def run_kit(self, seal_doc, out="pred", **kw):
        return kit.run(REPO, seal_doc, dict(self.fx), self.tmp / out, git_check=False, **kw)


class VariantAndPathValidationTests(Pr14TestCase):
    """P1: untrusted IDs must never become filesystem paths."""

    def test_seal_rejects_unsafe_variant_ids(self):
        for i, bad in enumerate(["../../outside", "/abs", "A/B", "..", "", "A A", "a\\b", 7, None]):
            with self.subTest(bad=bad):
                self.pub = self.tmp / f"pub{i}"
                self.fx = {}
                self.family(f"F{i}", meta=metadata(f"F{i}", ["A", bad]))
                with self.assertRaisesRegex(kit.KitError, "variant"):
                    self.seal()

    def test_seal_rejects_duplicate_variants_and_unsafe_fixture_id(self):
        self.family("F1", meta=metadata("F1", ["A", "A"]))
        with self.assertRaisesRegex(kit.KitError, "duplicate"):
            self.seal()
        shutil.rmtree(self.pub)
        shutil.rmtree(self.tmp / "fixtures")
        shutil.rmtree(self.tmp / "private")
        self.family("F1", meta=metadata("F1", ["A"], fixture_id="../x"))
        with self.assertRaisesRegex(kit.KitError, "fixture_id"):
            self.seal()

    def test_seal_rejects_variant_without_sealed_variant_file(self):
        self.family("F1", variants=["A", "NOPE"])
        with self.assertRaisesRegex(kit.KitError, "sealed fixture"):
            self.seal()

    def test_run_rejects_crafted_seal_before_any_filesystem_use(self):
        self.family("F1", variants=["A"])
        doc = copy.deepcopy(self.seal())
        outside = self.tmp / "fixtures" / "outside.json"
        outside.write_text(json.dumps({"variant": "X", "description": "x", "synthesis": {"mode": "disabled"},
                                       "ops": []}))
        doc["families"][0]["variants"] = ["../../outside"]
        with self.assertRaisesRegex(kit.KitError, "variant"):
            self.run_kit(doc)
        self.assertFalse((self.tmp / "pred").exists())
        self.assertFalse((self.tmp / "outside").exists())

    def test_variant_referencing_unsealed_stub_is_not_run(self):
        def edit(fx):
            (self.tmp / "outside-stub.json").write_text(json.dumps({"stub_version": "0.1", "behavior": "timeout"}))
            path = fx / "variants" / "C.json"
            doc = json.loads(path.read_bytes())
            doc["synthesis"]["stub"] = "../../../outside-stub.json"
            path.write_text(json.dumps(doc))
        self.family("F1", variants=["A", "C"], fixture_edit=edit)
        log, _ = self.run_kit(self.seal())
        rows = {v["variant"]: v for v in log["families"][0]["variants"]}
        self.assertEqual(rows["A"]["execution"], "completed")
        self.assertEqual(rows["C"]["execution"], "not_run")
        self.assertEqual(rows["C"]["reason"], "variant_references_unsealed_file")


class RunFailureReportingTests(Pr14TestCase):
    """P1: a damaged family is recorded as not_run and the other families still run."""

    def setUp(self):
        super().setUp()
        self.family("GOOD", variants=["A"])
        self.family("BAD", variants=["A", "B"])
        self.doc = self.seal()

    def assertBadNotRunGoodCompleted(self, log):
        fams = {f["scenario_id"]: f for f in log["families"]}
        self.assertEqual(fams["BAD"]["fixture_integrity"]["status"], "failed")
        self.assertEqual([v["execution"] for v in fams["BAD"]["variants"]], ["not_run", "not_run"])
        self.assertEqual(fams["GOOD"]["variants"][0]["execution"], "completed")

    def test_malformed_json_after_sealing(self):
        (self.fx["BAD"] / "observations.json").write_text("{not json")
        self.assertBadNotRunGoodCompleted(self.run_kit(self.doc)[0])

    def test_missing_fixture_directory(self):
        shutil.rmtree(self.fx["BAD"])
        self.assertBadNotRunGoodCompleted(self.run_kit(self.doc)[0])

    def test_link_inside_fixture_directory(self):
        target = self.fx["BAD"] / "observations.json"
        moved = self.tmp / "elsewhere.json"
        shutil.move(target, moved)
        try:
            os.symlink(moved, target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assertBadNotRunGoodCompleted(self.run_kit(self.doc)[0])


class ScoreFailureReportingTests(Pr14TestCase):
    """P1: truth custody errors become scoring_failed rows; nothing is dropped or disclosed."""

    MARKER = "PRIVATE-TRUTH-MARKER-7f3a"

    def setUp(self):
        super().setUp()
        self.family("GOOD", variants=["A"])
        self.family("BAD", variants=["A", "B"])
        self.doc = self.seal()
        self.log, self.record = self.run_kit(self.doc)

    def score(self, truth_sources, predictions_record=None):
        return kit.score(REPO, self.doc, self.tmp / "pred", predictions_record or self.record, truth_sources,
                         git_check=False)

    def assertBadScoringFailed(self, results, stage):
        fams = {f["scenario_id"]: f for f in results["families"]}
        self.assertEqual(results["variants_total"], 3)
        self.assertEqual(fams["GOOD"]["variants"][0]["classification"]["primary"], "correct_attribution")
        bad = fams["BAD"]["variants"]
        self.assertEqual([r["classification"]["primary"] for r in bad], ["scoring_failed", "scoring_failed"])
        self.assertEqual(bad[0]["detail"]["stage"], stage)
        self.assertNotIn(self.MARKER, json.dumps(results))

    def test_truth_not_matching_commitment(self):
        truth, salt = self.truth["BAD"]
        doc = json.loads(truth.read_bytes())
        doc["custody_note"] = self.MARKER
        truth.write_text(json.dumps(doc))
        self.assertBadScoringFailed(self.score(dict(self.truth)), "truth_commitment")

    def test_missing_truth_file_salt_and_mapping(self):
        truth, salt = self.truth["BAD"]
        self.assertBadScoringFailed(self.score(dict(self.truth, BAD=(self.tmp / "nope.json", salt))), "truth_open")
        self.assertBadScoringFailed(self.score(dict(self.truth, BAD=(truth, self.tmp / "nope.hex"))), "truth_open")
        self.assertBadScoringFailed(self.score({"GOOD": self.truth["GOOD"]}), "truth_not_supplied")

    def test_family_missing_from_execution_log_is_reported(self):
        log_path = self.tmp / "pred" / "execution-log.json"
        log = json.loads(log_path.read_bytes())
        log["families"] = [f for f in log["families"] if f["scenario_id"] != "BAD"]
        log_path.write_text(json.dumps(log))
        record = kit.freeze_predictions(self.tmp / "pred")
        results = self.score(dict(self.truth), predictions_record=record)
        fams = {f["scenario_id"]: f for f in results["families"]}
        self.assertEqual([r["classification"]["primary"] for r in fams["BAD"]["variants"]], ["not_run", "not_run"])
        self.assertEqual(results["variants_total"], 3)


class OutputLayoutTests(Pr14TestCase):
    """P2: refuse ambiguous or overlapping outputs before executing anything."""

    def setUp(self):
        super().setUp()
        self.family("F1", variants=["A"])
        self.doc = self.seal()

    def test_existing_record_out_refused_before_execution(self):
        record_out = self.tmp / "pred.freeze.json"
        record_out.write_text("{}")
        with self.assertRaisesRegex(kit.KitError, "already exists"):
            self.run_kit(self.doc, record_out=record_out)
        self.assertFalse((self.tmp / "pred").exists())

    def test_record_inside_predictions_or_output_inside_fixtures_refused(self):
        with self.assertRaisesRegex(kit.KitError, "inside"):
            self.run_kit(self.doc, record_out=self.tmp / "pred" / "record.json")
        with self.assertRaisesRegex(kit.KitError, "inside"):
            kit.run(REPO, self.doc, dict(self.fx), self.fx["F1"] / "pred", git_check=False,
                    record_out=self.tmp / "r.json")
        self.assertFalse((self.tmp / "pred").exists())

    def test_results_inside_predictions_refused(self):
        _, record = self.run_kit(self.doc, record_out=self.tmp / "r.json")
        with self.assertRaisesRegex(kit.KitError, "inside"):
            kit.score(REPO, self.doc, self.tmp / "pred", record, dict(self.truth), git_check=False,
                      results_out=self.tmp / "pred" / "results.json")


class MetadataSchemaTests(Pr14TestCase):
    """P2: public metadata has an explicit schema and a recorded human pre-publication review."""

    def check_rejected(self, meta, pattern, extra_file=False):
        self.family("F1", meta=meta) if not extra_file else None
        with self.assertRaisesRegex(kit.KitError, pattern):
            self.seal()

    def test_unknown_or_answer_like_fields_rejected(self):
        self.check_rejected(metadata("F1", ["A"], expected_outcome="resolved"), "unexpected field")

    def test_nested_and_type_errors_rejected(self):
        meta = metadata("F1", ["A"])
        meta["author"]["causal_change"] = "x"
        self.check_rejected(meta, "unexpected field")

    def test_wrong_types_rejected(self):
        self.check_rejected(metadata("F1", ["A"], notes=["x"]), "notes")

    def test_prepublication_review_required(self):
        meta = metadata("F1", ["A"])
        del meta["prepublication_review"]
        self.check_rejected(meta, "prepublication_review")

    def test_extra_file_in_public_metadata_rejected(self):
        self.family("F1", meta=metadata("F1", ["A"]))
        fam = self.pub / "F1"
        (fam / "metadata" / "answers.txt").write_text("x")
        (fam / "metadata.freeze.json").unlink()
        (fam / "metadata.freeze.json").write_text(json.dumps(kit.freeze(fam / "metadata", "metadata", "F1")))
        with self.assertRaisesRegex(kit.KitError, "only eval-metadata.json"):
            self.seal()


if __name__ == "__main__":
    unittest.main()
