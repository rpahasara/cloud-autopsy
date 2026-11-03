"""Fixed CA-P2-002c vectors: identities and digests computed independently, relations, rejections, ledger."""

import unittest

import _evidence_support as S
from cloud_autopsy.contracts import evidence as ev
from cloud_autopsy.contracts import timeinterval as ti
from cloud_autopsy.contracts.errors import ALL_CODES, ContractError


class EvidenceVectorTests(unittest.TestCase):
    def test_vector_file_targets_these_contracts(self):
        self.assertEqual(S.DOC["contract"], ev.EVIDENCE_VERSION)
        self.assertIn(ev.ID_ALGORITHM, S.DOC["related_contracts"])
        self.assertIn(ev.CONTENT_ALGORITHM, S.DOC["related_contracts"])
        self.assertEqual(set(S.DOC["expected"]), set(S.DOC["observations"]))

    def test_identity_and_digest_match_independent_computation(self):
        for name, expected in S.DOC["expected"].items():
            with self.subTest(name):
                record = S.build(name)
                self.assertEqual(record.evidence_id, expected["evidence_id"])
                self.assertEqual(record.content_digest, expected["content_digest"])
                self.assertEqual(len(ev.parse_evidence_id(record.evidence_id)), 64)

    def test_relations(self):
        for rel in S.DOC["relations"]:
            with self.subTest(rel["id"]):
                a, b = S.build(rel["a"]), S.build(rel["b"])
                self.assertEqual(a.evidence_id == b.evidence_id, rel["same_evidence_id"])
                self.assertEqual(a.content_digest == b.content_digest, rel["same_content_digest"])

    def test_invalid_observations(self):
        for item in S.DOC["invalid"]:
            with self.subTest(item["id"]):
                self.assertIn(item["error"], ALL_CODES)
                source_id, observation = S.case(item["base"])
                S.apply(observation, item.get("set", ()), item.get("delete", ()))
                with self.assertRaises(ContractError) as ctx:
                    ev.observe(observation, source_id=item.get("source_id", source_id), registry=S.REGISTRY)
                self.assertEqual(ctx.exception.code, item["error"])

    def test_ledger_scenarios(self):
        for scenario in S.DOC["ledger"]:
            with self.subTest(scenario["id"]):
                ledger = ev.EvidenceLedger(S.REGISTRY)
                outcomes = [ledger.admit(S.build(name)).outcome for name in scenario["deliveries"]]
                self.assertEqual(outcomes, scenario["outcomes"])
                for name, state in scenario["final_state"].items():
                    self.assertEqual(ledger.state(S.build(name).evidence_id), state)

    def test_invalid_timestamp_is_retained_without_fabricated_time(self):
        record = S.build("cm-invalid-time")
        (stamp,) = record.times
        self.assertEqual((stamp.parse_status, stamp.raw), (ti.INVALID, "2026-02-30T08:10:00Z"))
        self.assertIsNone(stamp.epoch_ms)
        domains = {"k8s-apiserver": ti.clock_domain("k8s-apiserver", ti.DECLARED, 0, 0, ti.FIXTURE_DECLARED,
                                                    ti.CONTINUOUS)}
        other = S.build("cm").times[0]
        self.assertEqual(ti.compare(stamp, other, domains), ti.Ordering(ti.UNORDERED, ti.UNPARSED_TIMESTAMP))


if __name__ == "__main__":
    unittest.main()
