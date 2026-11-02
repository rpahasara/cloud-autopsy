"""Malformed input, resource ceilings, recursion and reason-code stability for the canonical profile."""

import time
import unittest

import _support  # noqa: F401  (adds src to the path)
from cloud_autopsy.contracts import canonical, errors
from cloud_autopsy.contracts.canonical import CanonicalError, Limits


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except CanonicalError as exc:
        return exc.code
    return None


class NestingTests(unittest.TestCase):
    def test_depth_ceiling_is_inclusive(self):
        ok = b"[" * 64 + b"]" * 64
        self.assertEqual(canonical.canonicalize(ok), ok)
        self.assertEqual(code_of(canonical.loads, b"[" * 65 + b"]" * 65), errors.NESTING_TOO_DEEP)
        obj = b'{"a":' * 64 + b"0" + b"}" * 64
        self.assertEqual(code_of(canonical.loads, obj), None)
        self.assertEqual(code_of(canonical.loads, b'{"a":' * 65 + b"0" + b"}" * 65), errors.NESTING_TOO_DEEP)

    def test_extreme_nesting_is_typed_not_recursion_error(self):
        # Regression for CA-P2-001-F1: the prototype let RecursionError escape at this depth.
        for n in (100_000, 500_000):
            with self.subTest(n=n):
                doc = b"[" * n + b"]" * n
                self.assertEqual(code_of(canonical.loads, doc), errors.NESTING_TOO_DEEP)
        unbalanced = b"[" * 400_000
        self.assertEqual(code_of(canonical.loads, unbalanced), errors.NESTING_TOO_DEEP)

    def test_brackets_inside_strings_do_not_count(self):
        doc = ('["' + "[{" * 1000 + '\\"' + "]}" + '"]').encode()
        self.assertEqual(canonical.loads(doc), ["[{" * 1000 + '"]}'])

    def test_in_memory_deep_value_rejected_without_recursion(self):
        value = []
        for _ in range(10_000):
            value = [value]
        self.assertEqual(code_of(canonical.canonical_bytes, value), errors.NESTING_TOO_DEEP)

    def test_self_referential_value_terminates(self):
        value = []
        value.append(value)
        self.assertEqual(code_of(canonical.canonical_bytes, value), errors.NESTING_TOO_DEEP)


class SizeAndNodeTests(unittest.TestCase):
    def test_document_byte_ceiling_is_inclusive(self):
        limit = canonical.CEILING_BYTES
        body = b'"' + b"a" * (limit - 2) + b'"'
        self.assertEqual(len(canonical.loads(body)), limit - 2)
        self.assertEqual(code_of(canonical.loads, body + b" "), errors.DOCUMENT_TOO_LARGE)

    def test_size_checked_before_decoding_or_parsing(self):
        huge = b"\xff" * (canonical.CEILING_BYTES + 1)
        self.assertEqual(code_of(canonical.loads, huge), errors.DOCUMENT_TOO_LARGE)

    def test_node_ceiling_is_inclusive(self):
        n = canonical.CEILING_NODES
        ok = b"[" + b",".join([b"0"] * (n - 1)) + b"]"  # one array plus n-1 integers
        self.assertEqual(len(canonical.loads(ok)), n - 1)
        over = b"[" + b",".join([b"0"] * n) + b"]"
        self.assertEqual(code_of(canonical.loads, over), errors.TOO_MANY_NODES)

    def test_wide_object_counts_values(self):
        n = canonical.CEILING_NODES
        members = b",".join(b'"%d":0' % i for i in range(n))  # n member values plus the object
        doc = b"{" + members + b"}"
        self.assertLessEqual(len(doc), canonical.CEILING_BYTES)
        self.assertEqual(code_of(canonical.loads, doc), errors.TOO_MANY_NODES)

    def test_canonical_output_size_is_bounded(self):
        value = ["\u0000" * 200_000]  # 6 bytes per character once escaped
        self.assertEqual(code_of(canonical.canonical_bytes, value), errors.DOCUMENT_TOO_LARGE)

    def test_lower_limits_apply_and_ceilings_cannot_be_raised(self):
        tight = Limits(max_bytes=8, max_depth=2, max_nodes=3)
        self.assertEqual(code_of(canonical.loads, b"[1,2,3]  ", tight), errors.DOCUMENT_TOO_LARGE)
        self.assertEqual(code_of(canonical.loads, b"[[[0]]]", tight), errors.NESTING_TOO_DEEP)
        self.assertEqual(code_of(canonical.loads, b"[1,2,3]", tight), errors.TOO_MANY_NODES)
        for bad in ({"max_bytes": canonical.CEILING_BYTES + 1}, {"max_depth": 0}, {"max_nodes": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Limits(**bad)

    def test_large_inputs_finish_quickly(self):
        cases = [
            (b"[" * 1_000_000, errors.NESTING_TOO_DEEP),
            (b"9" * 1_000_000, errors.INTEGER_OUT_OF_RANGE),
            (b'"' + b"\\\\" * 500_000 + b'"', None),  # valid: one long string of backslashes
            (b'"' + b"\\" * 1_000_000, errors.MALFORMED_JSON),  # unterminated string
            (b"[" + b"0," * 400_000 + b"0]", errors.TOO_MANY_NODES),
        ]
        for doc, expected in cases:
            with self.subTest(expected=expected):
                start = time.perf_counter()
                self.assertEqual(code_of(canonical.loads, doc), expected)
                self.assertLess(time.perf_counter() - start, 5.0)


class IntegerAndTypeTests(unittest.TestCase):
    def test_huge_integer_literal_is_typed(self):
        # Python's int-string limit raises a plain ValueError above 4300 digits.
        for digits in (17, 4301, 100_000):
            with self.subTest(digits=digits):
                self.assertEqual(code_of(canonical.loads, b"1" * digits), errors.INTEGER_OUT_OF_RANGE)

    def test_in_memory_value_types(self):
        cases = {
            errors.FLOAT_NOT_PERMITTED: [1.0, float("nan"), {"a": [0.5]}],
            errors.INTEGER_OUT_OF_RANGE: [2**53, -(2**53), [2**80]],
            errors.UNSUPPORTED_TYPE: [b"x", {1, 2}, object(), {"a": bytearray()}],
            errors.NON_STRING_KEY: [{1: "a"}, {None: 0}, {("t",): 0}],
            errors.LONE_SURROGATE: ["\ud800", {"\udc00": 1}, ["ok", "\udfff"]],
        }
        for code, values in cases.items():
            for value in values:
                with self.subTest(code=code, value=repr(value)):
                    self.assertEqual(code_of(canonical.canonical_bytes, value), code)

    def test_booleans_are_not_integers_and_tuples_are_arrays(self):
        self.assertEqual(canonical.canonical_bytes([True, False, 1, 0]), b"[true,false,1,0]")
        self.assertEqual(canonical.canonical_bytes((1, "a")), b'[1,"a"]')

    def test_non_bytes_input_rejected(self):
        for value in ("{}", None, 1, memoryview(b"{}")):
            with self.subTest(value=repr(value)):
                self.assertEqual(code_of(canonical.loads, value), errors.INPUT_NOT_BYTES)
        self.assertEqual(canonical.loads(bytearray(b"[1]")), [1])

    def test_error_precedence(self):
        bom_and_bad = b"\xef\xbb\xbf\xff"
        self.assertEqual(code_of(canonical.loads, bom_and_bad), errors.BYTE_ORDER_MARK)
        self.assertEqual(code_of(canonical.loads, b"[" * 65 + b"1.5"), errors.NESTING_TOO_DEEP)
        self.assertEqual(code_of(canonical.loads, b'{"\\ud800":1,"\\ud800":2}'), errors.DUPLICATE_KEY)
        self.assertEqual(code_of(canonical.loads, b'[1.5, NaN]'), errors.FLOAT_NOT_PERMITTED)


class ReasonCodeTests(unittest.TestCase):
    PINNED = {
        "input_not_bytes", "document_too_large", "invalid_utf8", "byte_order_mark", "malformed_json",
        "duplicate_key", "float_not_permitted", "non_finite_number", "integer_out_of_range",
        "lone_surrogate", "nesting_too_deep", "too_many_nodes", "unsupported_type", "non_string_key",
        "contract_version_missing", "contract_version_malformed", "contract_version_mismatch",
        "digest_malformed", "digest_algorithm_mismatch",
    }

    def test_reason_codes_are_pinned(self):
        self.assertEqual(set(errors.ALL_CODES), self.PINNED)

    def test_unregistered_code_cannot_be_raised(self):
        with self.assertRaises(AssertionError):
            CanonicalError("made_up_code")

    def test_messages_never_echo_document_content(self):
        canary = "CANARY-7f3e"
        docs = [
            ('{"%s":1,"%s":2}' % (canary, canary)).encode(),
            ('["%s", 1.5]' % canary).encode(),
            ('{"%s": 99999999999999999}' % canary).encode(),
            ('["%s\\ud800"]' % canary).encode(),
            ('{"%s": tru}' % canary).encode(),
            ('[1e%s]' % ("9" * 30)).encode(),
        ]
        for doc in docs:
            with self.subTest(doc=doc[:20]):
                with self.assertRaises(CanonicalError) as ctx:
                    canonical.loads(doc)
                self.assertNotIn(canary, str(ctx.exception))
                self.assertNotIn("9" * 20, str(ctx.exception))
                self.assertIn(ctx.exception.code, errors.CANONICAL_CODES)


class DigestTests(unittest.TestCase):
    def test_digest_format_and_round_trip(self):
        d = canonical.digest({"b": 1, "a": [True, None]})
        self.assertTrue(d.startswith(canonical.DIGEST_ALGORITHM + ":"))
        self.assertEqual(len(canonical.parse_digest(d)), 64)

    def test_prototype_digests_are_not_reinterpreted(self):
        prototype_style = "sha256:" + "d" * 64  # ca-canon/0.1-spike format
        self.assertEqual(code_of(canonical.parse_digest, prototype_style), errors.DIGEST_ALGORITHM_MISMATCH)
        self.assertNotEqual(canonical.CANON_VERSION, "ca-canon/0.1-spike")

    def test_malformed_digests(self):
        for text in ("", "abc", canonical.DIGEST_ALGORITHM + ":" + "A" * 64,
                     canonical.DIGEST_ALGORITHM + ":" + "a" * 63, None, 5):
            with self.subTest(text=text):
                self.assertEqual(code_of(canonical.parse_digest, text), errors.DIGEST_MALFORMED)


if __name__ == "__main__":
    unittest.main()
