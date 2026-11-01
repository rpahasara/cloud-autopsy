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
        # PR #13: structural validation is named as such; it is not semantic validation of prose
        self.assertEqual(ok["status"], "structurally_validated")
        self.assertEqual(ok["semantic_validation"], "not_performed")

    def test_empty_citation_list_is_rejected(self):
        _, reasons, _ = validate_response(self.response(evidence_ids=[]), self.bundle, self.digest)
        self.assertIn("claim[0]:empty_citation", reasons)

    def test_factual_claim_on_unsatisfied_assertion_is_rejected(self):
        p = prereq(hypothesis(self.bundle, "deployment_rollout"), "changed_field_mapped")
        self.assertEqual(p["result"], "unsatisfied")
        response = self.response(text="The rollout changed a pool setting.", evidence_ids=p["evidence_ids"],
                                 assertion_keys=[p["assertion_key"]])
        _, reasons, _ = validate_response(response, self.bundle, self.digest)
        self.assertIn("claim[0]:assertion_not_satisfied", reasons)

    def test_unresolved_claim_must_cite_a_non_satisfied_assertion(self):
        p = prereq(hypothesis(self.bundle, "deployment_rollout"), "changed_field_mapped")
        ok = self.response(kind="unresolved", text="No mechanism maps the rollout's changed fields.",
                           evidence_ids=p["evidence_ids"], assertion_keys=[p["assertion_key"]])
        self.assertEqual(validate_response(ok, self.bundle, self.digest)[1], [])
        _, reasons, _ = validate_response(self.response(kind="unresolved"), self.bundle, self.digest)
        self.assertIn("claim[0]:unresolved_claim_on_satisfied_assertion", reasons)

    def test_citations_must_exactly_match_the_assertion_evidence(self):
        partial = self.response(evidence_ids=self.assertion["evidence_ids"][:0] or [])
        full = prereq(hypothesis(self.bundle, "config_value_change"), "consumed_by_symptomatic_pods")
        subset = self.response(evidence_ids=full["evidence_ids"][:1], assertion_keys=[full["assertion_key"]])
        _, reasons, _ = validate_response(subset, self.bundle, self.digest)
        self.assertIn("claim[0]:citation_set_differs_from_assertion", reasons)
        self.assertIn("claim[0]:empty_citation", validate_response(partial, self.bundle, self.digest)[1])

    def test_contradictory_prose_is_never_presented_as_a_supported_fact(self):
        lie = self.response(text="The Deployment checkout-api is the confirmed root cause.")
        record = run_synthesis("stub", {"behavior": "respond", "response": lie}, self.bundle, self.digest)
        self.assertEqual(record["status"], "structurally_validated")
        claim = record["validated_claims"][0]
        self.assertEqual(claim["semantic_status"], "unverified_model_text")
        self.assertNotIn("Deployment", claim["supported_fact"])
        self.assertIn("change_observed", claim["supported_fact"])
        self.assertNotIn("text", claim)  # model prose is only exposed under an explicitly untrusted key
        self.assertEqual(claim["text_untrusted"], lie["claims"][0]["text"])

    def test_synthesis_never_mutates_the_bundle(self):
        before = repr(self.bundle)
        run_synthesis("stub", {"behavior": "respond", "response": self.response(kind="confirmed_cause")},
                      self.bundle, self.digest)
        self.assertEqual(repr(self.bundle), before)


if __name__ == "__main__":
    unittest.main()
