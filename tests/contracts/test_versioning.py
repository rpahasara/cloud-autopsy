"""Exact-match contract versioning."""

import unittest

import _support  # noqa: F401
from cloud_autopsy import contracts
from cloud_autopsy.contracts import errors, versioning
from cloud_autopsy.contracts.errors import VersionError


def code_of(fn, *args):
    try:
        fn(*args)
    except VersionError as exc:
        return exc.code
    return None


class VersioningTests(unittest.TestCase):
    def test_registered_versions_are_well_formed_and_provisional(self):
        for name, identifier in contracts.CONTRACT_VERSIONS.items():
            with self.subTest(name=name):
                self.assertEqual(versioning.validate_identifier(identifier), identifier)
                self.assertTrue(identifier.endswith("-provisional"))
        self.assertIn("provisional", contracts.CONTRACT_STATUS)

    def test_identifier_format(self):
        for good in ("ca-x/0.1", "ca-x/1.2.3", "ca-x/10.0-provisional", "a/0.0-rc.1"):
            with self.subTest(good=good):
                self.assertEqual(versioning.validate_identifier(good), good)
        for bad in ("", "CA-X/1.0", "ca-x/1", "ca-x/01.0", "ca-x/1.0-", "ca-x/1.0 ", "ca x/1.0",
                    "/1.0", "ca-x/1.0-Prov", None, 1.0, ["ca-x/1.0"]):
            with self.subTest(bad=bad):
                self.assertEqual(code_of(versioning.validate_identifier, bad), errors.CONTRACT_VERSION_MALFORMED)

    def test_exact_match_only(self):
        expected = "ca-jcs-profile/0.1-provisional"
        self.assertEqual(versioning.require_exact(expected, expected), expected)
        for other in ("ca-jcs-profile/0.1", "ca-jcs-profile/0.1.0-provisional", "ca-jcs-profile/0.2-provisional",
                      "ca-canon/0.1-spike"):
            with self.subTest(other=other):
                self.assertEqual(code_of(versioning.require_exact, other, expected),
                                 errors.CONTRACT_VERSION_MISMATCH)

    def test_envelope(self):
        expected = "ca-jcs-profile/0.1-provisional"
        self.assertEqual(versioning.check_envelope({"contract_version": expected}, expected), expected)
        self.assertEqual(code_of(versioning.check_envelope, {}, expected), errors.CONTRACT_VERSION_MISSING)
        self.assertEqual(code_of(versioning.check_envelope, [expected], expected), errors.CONTRACT_VERSION_MISSING)
        self.assertEqual(code_of(versioning.check_envelope, {"contract_version": 1}, expected),
                         errors.CONTRACT_VERSION_MALFORMED)
        self.assertEqual(code_of(versioning.check_envelope, {"contract_version": "ca-jcs-profile/9.9"}, expected),
                         errors.CONTRACT_VERSION_MISMATCH)

    def test_mismatch_message_does_not_echo_actual_value(self):
        with self.assertRaises(VersionError) as ctx:
            versioning.require_exact("canary-zz/1.0", "ca-x/1.0")
        self.assertNotIn("canary", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
