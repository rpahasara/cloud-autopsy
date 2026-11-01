"""PR #14 follow-up regressions: malformed sealed stub references and private salt creation.

Tooling tests on the public development fixture only; no held-out content, no evaluation evidence.
"""

import json
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heldout_kit as kit  # noqa: E402
from test_pr14_review import Pr14TestCase  # noqa: E402


class MalformedStubReferenceTests(Pr14TestCase):
    """A sealed variant whose synthesis.stub is not a string must not stop the evaluation."""

    def test_unhashable_or_wrong_type_stub_is_recorded_and_other_families_run(self):
        for i, bad in enumerate([["bad"], {"x": 1}, 7, True]):
            with self.subTest(stub=bad):
                self.pub, self.fx, self.truth = self.tmp / f"pub{i}", {}, {}

                def edit(fx, bad=bad):
                    path = fx / "variants" / "C.json"
                    doc = json.loads(path.read_bytes())
                    doc["synthesis"] = {"mode": "stub", "stub": bad}
                    path.write_text(json.dumps(doc))
                self.family(f"GOOD{i}", variants=["A"])
                self.family(f"BAD{i}", variants=["A", "C"], fixture_edit=edit)
                log, record = self.run_kit(self.seal(), out=f"pred{i}")
                fams = {f["scenario_id"]: {v["variant"]: v for v in f["variants"]} for f in log["families"]}
                self.assertEqual(fams[f"GOOD{i}"]["A"]["execution"], "completed")
                self.assertEqual(fams[f"BAD{i}"]["A"]["execution"], "completed")
                self.assertEqual(fams[f"BAD{i}"]["C"]["execution"], "not_run")
                self.assertEqual(fams[f"BAD{i}"]["C"]["reason"], "variant_file_malformed")
                results = kit.score(kit.Path(__file__).resolve().parents[2], self.seal(), self.tmp / f"pred{i}",
                                    record, dict(self.truth), git_check=False)
                self.assertEqual(results["variants_total"], 3)
                self.assertEqual(results["classification_counts"].get("not_run"), 1)


class PrivateSaltTests(Pr14TestCase):
    def setUp(self):
        super().setUp()
        self.truth_file = self.tmp / "private" / "ground-truth.json"
        self.truth_file.parent.mkdir()
        self.truth_file.write_text('{"answer": "x"}')
        self.salt = self.tmp / "private" / "salt.hex"

    def test_existing_salt_is_never_replaced_even_if_existence_check_races(self):
        self.salt.write_text("original\n")
        # Simulate the file appearing between an existence check and the write.
        with mock.patch.object(kit.Path, "exists", return_value=False):
            with self.assertRaisesRegex(kit.KitError, "already exists"):
                kit.commit_truth(self.truth_file, self.salt)
        self.assertEqual(self.salt.read_text(), "original\n")

    @unittest.skipIf(os.name != "posix", "POSIX permission bits")
    def test_salt_is_owner_only_on_posix(self):
        old = os.umask(0o022)
        try:
            kit.commit_truth(self.truth_file, self.salt)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(self.salt.stat().st_mode), 0o600)

    def test_salt_roundtrip_still_opens_commitment(self):
        record = kit.commit_truth(self.truth_file, self.salt)
        kit.open_truth(self.truth_file, self.salt, record["truth_commitment"])
        self.assertEqual(len(bytes.fromhex(self.salt.read_text().strip())), 32)


if __name__ == "__main__":
    unittest.main()
