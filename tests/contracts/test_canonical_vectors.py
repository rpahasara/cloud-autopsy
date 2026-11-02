"""Hand-derived canonical JSON vectors (cross-checked with an independent JavaScript implementation)."""

import hashlib
import unittest

import _support
from cloud_autopsy.contracts import canonical
from cloud_autopsy.contracts.errors import ALL_CODES, CanonicalError


class VectorFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = _support.load_vectors()

    def test_vector_file_targets_this_contract(self):
        self.assertEqual(self.doc["contract"], canonical.CANON_VERSION)
        self.assertIn("Provisional", self.doc["status"])
        ids = [v["id"] for v in self.doc["valid"] + self.doc["invalid"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(self.doc["sha256_of_canonical"]), {v["id"] for v in self.doc["valid"]})

    def test_valid_vectors_produce_expected_bytes(self):
        for v in self.doc["valid"]:
            with self.subTest(v["id"]):
                expected = v["canonical"].encode("utf-8")
                self.assertEqual(canonical.canonicalize(_support.vector_input(v)), expected)

    def test_canonical_output_is_a_fixed_point(self):
        for v in self.doc["valid"]:
            with self.subTest(v["id"]):
                expected = v["canonical"].encode("utf-8")
                self.assertEqual(canonical.canonicalize(expected), expected)

    def test_digests_match_independently_computed_values(self):
        for v in self.doc["valid"]:
            with self.subTest(v["id"]):
                hexdigest = self.doc["sha256_of_canonical"][v["id"]]
                self.assertEqual(hashlib.sha256(v["canonical"].encode("utf-8")).hexdigest(), hexdigest)
                value = canonical.loads(_support.vector_input(v))
                self.assertEqual(canonical.digest(value), f"{canonical.DIGEST_ALGORITHM}:{hexdigest}")

    def test_invalid_vectors_raise_their_stable_code(self):
        for v in self.doc["invalid"]:
            with self.subTest(v["id"]):
                self.assertIn(v["error"], ALL_CODES)
                with self.assertRaises(CanonicalError) as ctx:
                    canonical.loads(_support.vector_input(v))
                self.assertEqual(ctx.exception.code, v["error"])

    def test_utf16_order_differs_from_code_point_order(self):
        # Regression for CA-P2-001-F2: the prototype sorted by code point.
        value = {"｡": 2, "\U0001F600": 1}
        self.assertEqual(canonical.canonical_bytes(value), '{"\U0001F600":1,"｡":2}'.encode("utf-8"))
        self.assertNotEqual(sorted(value), sorted(value, key=lambda k: k.encode("utf-16-be")))


if __name__ == "__main__":
    unittest.main()
