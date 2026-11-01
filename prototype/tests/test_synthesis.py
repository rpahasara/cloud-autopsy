import unittest

from ca_spike.synthesis import CONTRACT_VERSION, run_synthesis, validate_response
from tests.helpers import RunTestCase, hypothesis, prereq


class SynthesisValidatorTests(RunTestCase):
    def setUp(self):
        super().setUp()
        self.run, self.store, self.bundle = self.run_variant("A")
        self.digest = self.run["bundle_digest"]
        p = prereq(hypothesis(self.bundle, "config_value_change"), "change_observed")
        self.assertion = p

    def response(self, **claim_overrides):
        claim = {"claim_id": "k1", "kind": "observed", "text": "The ConfigMap pool limit changed from 50 to 4.",
                 "evidence_ids": self.assertion["evidence_ids"], "assertion_keys": [self.assertion["assertion_key"]]}
        claim.update(claim_overrides)
        return {"contract_version": CONTRACT_VERSION, "bundle_digest": self.digest, "claims": [claim],
                "limitations": ["synthetic fixture"]}

    def test_valid_grounded_claim_is_accepted(self):
        validated, reasons, count = validate_response(self.response(), self.bundle, self.digest)
        self.assertEqual((reasons, count, len(validated)), ([], 1, 1))

    def test_rejections(self):
        cases = {
            "prohibited_field": dict(self.response(), actions=[{"command": "kubectl delete"}]),
            "prohibited_kind": self.response(kind="confirmed_cause"),
            "citation_not_in_bundle": self.response(evidence_ids=["ev:LOG:fabricated"]),
            "citation_not_in_assertion": self.response(evidence_ids=self.bundle["evidence_ids"][:1] + ["x"]),
            "unknown_assertion_key": self.response(assertion_keys=["hyp:0#invented"]),
            "bundle_digest_mismatch": dict(self.response(), bundle_digest="sha256:other"),
            "unexpected_field": self.response(url="http://example.invalid"),
        }
        for expected, response in cases.items():
            with self.subTest(case=expected):
                validated, reasons, _ = validate_response(response, self.bundle, self.digest)
                self.assertEqual(validated, [])
                self.assertTrue(any(expected in r for r in reasons), reasons)

    def test_modes(self):
        self.assertEqual(run_synthesis("disabled", None, self.bundle, self.digest)["status"], "disabled")
        self.assertEqual(run_synthesis("external", None, self.bundle, self.digest)["reasons"], ["mode_not_permitted"])
        self.assertEqual(run_synthesis("stub", {"behavior": "unavailable"}, self.bundle, self.digest)["status"],
                         "unavailable")
        ok = run_synthesis("stub", {"behavior": "respond", "response": self.response()}, self.bundle, self.digest)
        self.assertEqual(ok["status"], "validated")

    def test_synthesis_never_mutates_the_bundle(self):
        before = repr(self.bundle)
        run_synthesis("stub", {"behavior": "respond", "response": self.response(kind="confirmed_cause")},
                      self.bundle, self.digest)
        self.assertEqual(repr(self.bundle), before)


if __name__ == "__main__":
    unittest.main()
