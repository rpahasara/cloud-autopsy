import unittest

from ca_spike.canonical import CanonicalError, canonical_bytes, digest, loads_strict


class CanonicalTests(unittest.TestCase):
    def test_vector_sorted_keys_compact_utf8(self):
        value = {"b": 1, "a": [True, None, "é"], "Z": {}}
        self.assertEqual(canonical_bytes(value), '{"Z":{},"a":[true,null,"é"],"b":1}'.encode("utf-8"))
        self.assertEqual(digest(value), digest({"Z": {}, "b": 1, "a": [True, None, "é"]}))

    def test_strings_are_not_unicode_normalized(self):
        self.assertNotEqual(digest({"k": "é"}), digest({"k": "é"}))

    def test_rejects_float_nan_and_lone_surrogate(self):
        for bad in (1.5, {"x": float("nan")}, ["\ud800"]):
            with self.assertRaises(CanonicalError):
                canonical_bytes(bad)

    def test_strict_parse_rejects_duplicates_floats_constants_bom_and_oversize(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":0.5}', b'{"a":NaN}', b'\xef\xbb\xbf{}', b'{"a":', b'\xff'):
            with self.assertRaises(CanonicalError, msg=raw):
                loads_strict(raw)
        with self.assertRaises(CanonicalError):
            loads_strict(b'{"a":"' + b"x" * 100 + b'"}', max_bytes=50)
        self.assertEqual(loads_strict(b'{"a":[1,"2"]}'), {"a": [1, "2"]})


if __name__ == "__main__":
    unittest.main()
