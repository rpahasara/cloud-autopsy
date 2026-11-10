"""Clock-domain declaration ``ca-clock-declaration/0.1-provisional`` (CA-P2-006a; pure, no database)."""

import copy
import hashlib
import unittest

import _cross_scope as X
import _support as S
from cloud_autopsy.contracts import canonical
from cloud_autopsy.engine import clocks, inputs, result
from cloud_autopsy.synthetic import scenario_001 as scenario


def records():
    return scenario.clock_domain_records("config-cause")


class DeclarationTests(unittest.TestCase):
    def assert_code(self, code, fn):
        with self.assertRaises(clocks.ClockDeclarationError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)

    def test_declaration_is_canonical_and_digest_is_sha256_of_its_bytes(self):
        d = clocks.declare(scenario.registry(), list(reversed(records())))
        self.assertEqual(d.raw, canonical.canonical_bytes(canonical.loads(d.raw)))
        self.assertEqual(d.digest, "ca-clock-declaration-sha256/0.1-provisional:" + hashlib.sha256(d.raw).hexdigest())
        self.assertEqual([r["clock_domain_id"] for r in d.records], sorted(r["clock_domain_id"] for r in records()))
        again = clocks.ClockDeclaration.from_bytes(d.raw, scenario.registry(), expected_digest=d.digest)
        self.assertEqual((again.raw, again.digest), (d.raw, d.digest))

    def test_declaration_must_match_the_registry_exactly(self):
        reg = scenario.registry()
        self.assert_code("clock_domain_missing", lambda: clocks.declare(reg, records()[1:]))
        self.assert_code("clock_domain_duplicated", lambda: clocks.declare(reg, records() + records()[:1]))
        stray = dict(records()[0], clock_domain_id="node-z")
        self.assert_code("clock_domain_unregistered", lambda: clocks.declare(reg, records() + [stray]))

    def test_stored_bytes_are_strictly_checked(self):
        reg = scenario.registry()
        d = clocks.declare(reg, records())
        self.assert_code("clock_declaration_registry_mismatch",
                         lambda: clocks.ClockDeclaration.from_bytes(d.raw, X.registry()))
        self.assert_code("clock_declaration_digest_mismatch",
                         lambda: clocks.ClockDeclaration.from_bytes(d.raw, reg, expected_digest="x" + d.digest[1:]))
        self.assert_code("clock_declaration_invalid",
                         lambda: clocks.ClockDeclaration.from_bytes(d.raw + b" ", reg))
        doc = canonical.loads(d.raw)
        doc["clock_domains"] = list(reversed(doc["clock_domains"]))  # valid JSON, not canonical order
        self.assert_code("clock_declaration_invalid",
                         lambda: clocks.ClockDeclaration.from_bytes(canonical.canonical_bytes(doc), reg))
        doc = canonical.loads(d.raw)
        doc["contract_version"] = "ca-clock-declaration/0.2-provisional"
        self.assert_code("clock_declaration_version",
                         lambda: clocks.ClockDeclaration.from_bytes(canonical.canonical_bytes(doc), reg))

    def test_tampered_offset_changes_the_digest(self):
        reg = scenario.registry()
        d = clocks.declare(reg, records())
        doc = canonical.loads(d.raw)
        doc["clock_domains"][0]["offset_uncertainty_ms"] = 999_999
        tampered = canonical.canonical_bytes(doc)
        self.assert_code("clock_declaration_digest_mismatch",
                         lambda: clocks.ClockDeclaration.from_bytes(tampered, reg, expected_digest=d.digest))


class EngineBindingTests(unittest.TestCase):
    def test_result_carries_the_declaration_digest_and_different_clocks_give_a_different_result(self):
        plan, registry, frozen, evidence = S.sealed("config-cause")
        declared = clocks.declare(registry, records())
        res, raw = result.build(inputs.build_input(frozen, plan, registry, evidence, declared))
        self.assertEqual(res["inputs"]["clock_declaration_digest"], declared.digest)
        other = copy.deepcopy(records())
        for r in other:
            if r["clock_domain_id"] == "node-a":
                r["offset_ms"] = 2_500
        swapped = inputs.build_input(frozen, plan, registry, evidence, clocks.declare(registry, other))
        with self.assertRaises(inputs.InputError) as caught:  # the stored bytes do not replay on other clocks
            result.verify_result(raw, swapped)
        self.assertEqual(caught.exception.code, "replay_mismatch")

    def test_engine_refuses_incomplete_or_foreign_declarations(self):
        plan, registry, frozen, evidence = S.sealed("config-cause")
        with self.assertRaises(inputs.InputError) as caught:
            inputs.build_input(frozen, plan, registry, evidence, records()[1:])
        self.assertEqual(caught.exception.code, "clock_domain_missing")
        foreign = clocks.declare(X.registry(), records())
        with self.assertRaises(inputs.InputError) as caught:
            inputs.build_input(frozen, plan, registry, evidence, foreign)
        self.assertEqual(caught.exception.code, "clock_declaration_registry_mismatch")


if __name__ == "__main__":
    unittest.main()
