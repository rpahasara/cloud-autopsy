"""Regression: accepted evidence must not be mutable after verification (PR #18 review, P1).

At 80d322c, ``ObservedEvidence`` was a frozen dataclass holding plain dicts and lists, and
``EvidenceLedger.authoritative()`` / ``quarantined()`` returned the internal objects. A caller
could change accepted content in place without its content digest changing.
"""

import unittest

import _evidence_support as S
from cloud_autopsy.contracts import canonical, evidence as ev


def try_mutate(action):
    """Run an in-place mutation; an immutability error counts as the mutation being refused."""
    try:
        action()
    except (TypeError, AttributeError):
        return False
    return True


class EvidenceImmutabilityTests(unittest.TestCase):
    def assert_intact(self, ledger, evidence_id, expected_bytes):
        held = ledger.authoritative(evidence_id)
        self.assertEqual(canonical.canonical_bytes(held.to_record()), expected_bytes)
        self.assertEqual(ev.ObservedEvidence.from_record(held.to_record(), S.REGISTRY).content_digest,
                         held.content_digest)

    def test_mutating_authoritative_evidence_does_not_change_ledger_content(self):
        ledger = ev.EvidenceLedger(S.REGISTRY)
        record = S.build("deploy")
        expected = canonical.canonical_bytes(record.to_record())
        ledger.admit(record)
        held = ledger.authoritative(record.evidence_id)
        try_mutate(lambda: held.attributes.__setitem__("image_after", "registry.invalid/evil:9"))
        try_mutate(lambda: held.attributes["config_refs_after"].append("evil-config"))
        try_mutate(lambda: held.entity.__setitem__("name", "other-deployment"))
        self.assert_intact(ledger, record.evidence_id, expected)

    def test_mutating_quarantined_variants_does_not_change_ledger_content(self):
        ledger = ev.EvidenceLedger(S.REGISTRY)
        original, changed = S.build("deploy"), S.build("deploy-changed")
        expected = {r.content_digest: canonical.canonical_bytes(r.to_record()) for r in (original, changed)}
        ledger.admit(original)
        ledger.admit(changed)
        for variant in ledger.quarantined(original.evidence_id):
            try_mutate(lambda v=variant: v.attributes.__setitem__("revision", "99"))
            try_mutate(lambda v=variant: v.attributes["changed_fields"].clear())
        for variant in ledger.quarantined(original.evidence_id):
            self.assertEqual(canonical.canonical_bytes(variant.to_record()), expected[variant.content_digest])

    def test_mutating_the_admitted_input_reference_does_not_change_ledger_content(self):
        ledger = ev.EvidenceLedger(S.REGISTRY)
        record = S.build("pod")
        expected = canonical.canonical_bytes(record.to_record())
        ledger.admit(record)
        try_mutate(lambda: record.attributes["configmap_volumes"][0].__setitem__("mount_path", "/evil"))
        try_mutate(lambda: record.attributes.__setitem__("restart_count", 7))
        self.assert_intact(ledger, record.evidence_id, expected)

    def test_mutating_to_record_output_does_not_change_the_evidence(self):
        record = S.build("log")
        before = canonical.canonical_bytes(record.to_record())
        exported = record.to_record()
        exported["attributes"]["message"] = "rewritten"
        exported["attributes"]["fields"]["pool"] = "evil"
        exported["entity"]["name"] = "evil"
        exported["times"][0]["raw"] = "1970-01-01T00:00:00Z"
        observation = record.observation()
        observation["attributes"]["fields"]["max"] = "999"
        self.assertEqual(canonical.canonical_bytes(record.to_record()), before)

    def test_evidence_values_are_read_only(self):
        record = S.build("deploy")
        self.assertFalse(try_mutate(lambda: record.attributes.__setitem__("x", 1)))
        self.assertFalse(try_mutate(lambda: record.attributes["changed_fields"].append("x")))
        self.assertFalse(try_mutate(lambda: record.entity.__setitem__("name", "x")))

    def test_constructing_evidence_directly_also_freezes_it(self):
        record = S.build("cm")
        attributes = dict(record.to_record()["attributes"])
        rebuilt = ev.ObservedEvidence(**{**{f: getattr(record, f) for f in record.__dataclass_fields__},
                                         "attributes": attributes})
        attributes["after_value"] = "40"
        self.assertEqual(rebuilt.attributes["after_value"], "4")
        self.assertFalse(try_mutate(lambda: rebuilt.attributes.__setitem__("after_value", "40")))

    def test_serialization_is_unchanged_by_freezing(self):
        for name, expected in S.DOC["expected"].items():
            with self.subTest(name):
                record = S.build(name)
                self.assertEqual((record.evidence_id, record.content_digest),
                                 (expected["evidence_id"], expected["content_digest"]))
                exported = record.to_record()
                self.assertIs(type(exported["attributes"]), dict)
                self.assertIs(type(exported["entity"]), dict)
                canonical.canonical_bytes(exported)


if __name__ == "__main__":
    unittest.main()
