"""PR #13 re-review: malformed model responses are rejected deterministically and never crash a run."""

import unittest

from ca_spike.synthesis import CONTRACT_VERSION, run_synthesis
from tests.helpers import RunTestCase


class SynthesisHardeningTests(RunTestCase):
    def setUp(self):
        super().setUp()
        self.run, self.store, self.bundle = self.run_variant("A")
        self.digest = self.run["bundle_digest"]
        self.sat = next(p for h in self.bundle["ledger"]["hypotheses"] for p in h["prerequisites"]
                        if p["result"] == "satisfied")

    def claim(self, **overrides):
        claim = {"claim_id": "c1", "kind": "observed", "text": "x", "evidence_ids": list(self.sat["evidence_ids"]),
                 "assertion_keys": [self.sat["assertion_key"]]}
        claim.update(overrides)
        return claim

    def response(self, claims=None, **overrides):
        response = {"contract_version": CONTRACT_VERSION, "bundle_digest": self.digest, "limitations": [],
                    "claims": [self.claim()] if claims is None else claims}
        response.update(overrides)
        return response

    def synth(self, response, stub=None):
        stub = {"behavior": "respond", "response": response} if stub is None else stub
        return run_synthesis("stub", stub, self.bundle, self.digest)

    def assertRejected(self, record, reason_fragment):
        self.assertEqual(record["status"], "rejected", record["reasons"])
        self.assertEqual(record["validated_claims"], [])
        self.assertTrue(any(reason_fragment in r for r in record["reasons"]), record["reasons"])
        self.assertTrue(all(isinstance(r, str) for r in record["reasons"]))

    def test_control_well_formed_response_validates(self):
        self.assertEqual(self.synth(self.response())["status"], "structurally_validated")

    def test_unhashable_claim_fields_are_rejected_not_raised(self):
        cases = {
            "kind": self.claim(kind=["observed"]),
            "kind_dict": self.claim(kind={"observed": True}),
            "evidence_ids": self.claim(evidence_ids=[{"id": self.sat["evidence_ids"][0]}]),
            "evidence_ids_nested": self.claim(evidence_ids=[list(self.sat["evidence_ids"])]),
            "assertion_keys": self.claim(assertion_keys=[[self.sat["assertion_key"]]]),
            "assertion_keys_dict": self.claim(assertion_keys=[{"k": 1}]),
        }
        for name, claim in cases.items():
            with self.subTest(name):
                self.assertRejected(self.synth(self.response([claim])), "claim[0]:invalid_")

    def test_wrong_scalar_types_are_rejected(self):
        cases = {
            "claim_id_dict": (self.claim(claim_id={"a": 1}), "invalid_claim_id"),
            "claim_id_int": (self.claim(claim_id=7), "invalid_claim_id"),
            "claim_id_empty": (self.claim(claim_id=""), "invalid_claim_id"),
            "evidence_ids_string": (self.claim(evidence_ids=self.sat["evidence_ids"][0]), "invalid_evidence_ids"),
            "evidence_id_int": (self.claim(evidence_ids=[1]), "invalid_evidence_ids"),
            "evidence_id_bool": (self.claim(evidence_ids=[True]), "invalid_evidence_ids"),
            "assertion_keys_string": (self.claim(assertion_keys=self.sat["assertion_key"]), "invalid_assertion_keys"),
            "text_list": (self.claim(text=["x"]), "invalid_text"),
            "kind_none": (self.claim(kind=None), "invalid_kind"),
        }
        for name, (claim, reason) in cases.items():
            with self.subTest(name):
                self.assertRejected(self.synth(self.response([claim])), reason)

    def test_duplicate_claim_ids_and_citations_are_rejected(self):
        self.assertRejected(self.synth(self.response([self.claim(), self.claim()])), "duplicate_claim_id")
        ids = list(self.sat["evidence_ids"])
        self.assertRejected(self.synth(self.response([self.claim(evidence_ids=ids + ids[:1])])),
                            "duplicate_citation")

    def test_limitations_must_be_list_of_strings(self):
        for bad in ("none", [{"x": 1}], [["x"]], [1], None):
            with self.subTest(bad=bad):
                self.assertRejected(self.synth(self.response(limitations=bad)), "invalid_limitations")

    def test_top_level_unhashable_and_odd_values(self):
        for name, response in {
                "claims_dict": self.response(claims={"0": self.claim()}),
                "contract_version_list": self.response(contract_version=[CONTRACT_VERSION]),
                "bundle_digest_dict": self.response(bundle_digest={"d": self.digest}),
                "response_list": [self.response()],
                "response_none": None,
                "response_string": "{}"}.items():
            with self.subTest(name):
                record = self.synth(response)
                self.assertEqual(record["status"], "rejected")
                self.assertEqual(record["validated_claims"], [])

    def test_non_json_python_values_are_rejected(self):
        # Defence in depth: values that cannot come from strict JSON parsing.
        for name, response in {
                "float": self.response(limitations=[1.5]),
                "set": self.response(limitations={"a"}),
                "tuple_claims": self.response(claims=(self.claim(),)),
                "bytes_text": self.response([self.claim(text=b"x")]),
                "int_key": {**self.response(), 1: "x"},
                "mixed_keys": {1: "a", "contract_version": CONTRACT_VERSION, None: "b"},
                "object": self.response(limitations=[object()])}.items():
            with self.subTest(name):
                record = self.synth(response)
                self.assertRejected(record, "malformed:")
                self.assertIsNone(record["response_digest"])

    def test_deeply_nested_response_is_rejected(self):
        deep = []
        node = deep
        for _ in range(5000):
            node.append([])
            node = node[0]
        record = self.synth(self.response(limitations=deep))
        self.assertRejected(record, "malformed:depth_exceeded")

    def test_stub_record_not_an_object_is_rejected(self):
        for stub in (["respond"], "respond", 3):
            with self.subTest(stub=stub):
                record = self.synth(None, stub=stub)
                self.assertEqual(record["status"], "rejected")
                self.assertIn("stub_not_object", record["reasons"])

    def test_rejection_is_deterministic(self):
        bad = self.response([self.claim(kind=["observed"], evidence_ids=[{"a": 1}], claim_id=None),
                             self.claim(assertion_keys=[["k"]])], limitations=[{"x": 1}])
        first, second = self.synth(bad), self.synth(bad)
        self.assertEqual(first, second)
        self.assertEqual(first["reasons"], sorted(set(first["reasons"]), key=first["reasons"].index))

    def test_malformed_response_never_crashes_the_investigation(self):
        for name, response in {"unhashable": self.response([self.claim(kind=["observed"])]),
                               "deep": self.response(limitations=[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]),
                               "non_json": self.response(limitations={"x"})}.items():
            with self.subTest(name):
                scenario = self.scenario("A")
                scenario["variant"]["synthesis"] = {"mode": "stub", "stub": "inline"}
                scenario["synthesis_stub"] = {"behavior": "respond", "response": response}
                run, store, bundle = self.run_scenario(scenario)
                self.assertEqual(run["synthesis_status"], "rejected")
                self.assertEqual(run["state"], "partial")
                self.assertEqual(bundle, self.bundle)  # deterministic outcome untouched
                self.assertEqual(store.get("synthesis.json")["validated_claims"], [])


if __name__ == "__main__":
    unittest.main()
