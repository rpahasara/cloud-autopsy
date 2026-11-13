"""CA-P2-004g: the pod-log sanitizer keeps only the envelope and typed catalog fields (plan sections 4.2, 7)."""

import unittest

import _fake_api  # noqa: F401  (adds src to the path)
from cloud_autopsy.collector import logline as L

TS = b"2026-11-13T10:00:00.123456789Z "
UID = "6f1c2a7e-0000-4000-8000-000000000001"
PLANTED = (b"hunter2", b"Bearer abc.def.ghi", b"alice@example.com", b"eyJhbGciOiJIUzI1NiJ9.e30.sig",
           b"free text error", b"PLANTED-SECRET")


def line(body):
    return TS + body


class Sanitize(unittest.TestCase):
    def test_a_matched_line_keeps_only_typed_fields(self):
        out = L.sanitize(line(b"CA1 boot=0a1b2c3d seq=7 synced=6 lag_ms=3 POOL_EXHAUSTED pool=checkout-db in_use=8 max=4"))
        self.assertEqual(out, {"ts": "2026-11-13T10:00:00.123456789Z", "boot": "0a1b2c3d", "seq": 7, "synced": 6,
                               "lag_ms": 3, "template": "POOL_EXHAUSTED",
                               "fields": {"pool": "checkout-db", "in_use": "8", "max": "4"}})

    def test_started_carries_the_pod_identity(self):
        out = L.sanitize(line(f"CA1 boot=0a1b2c3d seq=1 STARTED pod_uid={UID} container=checkout-api".encode()))
        self.assertEqual((out["seq"], out["synced"], out["template"], out["fields"]["pod_uid"]), (1, None, "STARTED", UID))

    def test_runtime_timestamps_without_a_fraction_or_with_fewer_digits_parse(self):
        for ts in (b"2026-11-13T10:00:00Z ", b"2026-11-13T10:00:00.5Z "):
            self.assertEqual(L.sanitize(ts + b"CA1 boot=0a1b2c3d seq=2 HEARTBEAT")["template"], "HEARTBEAT")

    def test_an_unknown_template_or_a_bad_field_keeps_the_envelope_only(self):
        for body in (b"CA1 boot=0a1b2c3d seq=9 DEBUG_DUMP password=hunter2",
                     b"CA1 boot=0a1b2c3d seq=9 POOL_EXHAUSTED pool=checkout-db in_use=08 max=4",
                     b"CA1 boot=0a1b2c3d seq=9 POOL_EXHAUSTED pool=checkout-db in_use=8",
                     b"CA1 boot=0a1b2c3d seq=9 POOL_EXHAUSTED in_use=8 pool=checkout-db max=4",
                     b"CA1 boot=0a1b2c3d seq=9 POOL_EXHAUSTED pool=checkout-db in_use=8 max=4 token=x",
                     b"CA1 boot=0a1b2c3d seq=9 HEARTBEAT note=Bearer"):
            with self.subTest(body=body):
                out = L.sanitize(line(body))
                self.assertEqual((out["boot"], out["seq"], out["template"], out["fields"]), ("0a1b2c3d", 9, None, {}))
                self.assertNotIn("hunter2", repr(out))

    def test_anything_without_a_valid_envelope_is_invalid_and_carries_nothing(self):
        cases = {b"": "timestamp", b"no timestamp": "timestamp", line(b"plain text password=hunter2"): "envelope",
                 line(b"CA1 boot=0A1B2C3D seq=1 HEARTBEAT"): "envelope", line(b"CA1 boot=0a1b2c3d seq=0 HEARTBEAT"): "envelope",
                 line(b"CA1 boot=0a1b2c3d seq=01 HEARTBEAT"): "envelope",
                 line(b"CA1 boot=0a1b2c3d seq=2 synced=1 HEARTBEAT"): "envelope",
                 line(b"CA1 boot=0a1b2c3d seq=2  HEARTBEAT"): "envelope",
                 line("CA1 boot=0a1b2c3d seq=2 HEARTBEAT pool=š".encode()): "not_ascii",
                 line(b"CA1 boot=0a1b2c3d seq=2 HEARTBEAT\x1b[31m"): "envelope",
                 line(b"CA1 boot=0a1b2c3d seq=2 HEARTBEAT\nCA1 boot=0a1b2c3d seq=3 HEARTBEAT"): "envelope",
                 line(b"CA1 boot=0a1b2c3d seq=2 HEARTBEAT " + b"x" * 2000): "too_long",
                 TS.replace(b"Z", b"+00:00") + b"CA1 boot=0a1b2c3d seq=2 HEARTBEAT": "timestamp"}
        for raw, code in cases.items():
            with self.subTest(raw=raw[:60]):
                self.assertEqual(L.sanitize(raw), {"invalid": code})

    def test_no_planted_value_survives_any_shape(self):
        for needle in PLANTED:
            for body in (b"CA1 boot=0a1b2c3d seq=3 DEBUG msg=" + needle.replace(b" ", b"_"),
                         b"CA1 boot=0a1b2c3d seq=3 " + needle, needle,
                         b"CA1 boot=0a1b2c3d seq=3 POOL_EXHAUSTED pool=" + needle.replace(b" ", b"-") + b" in_use=1 max=1"):
                out = L.sanitize(line(body))
                self.assertNotIn(needle.decode(errors="replace").split(" ")[0], repr(out), body)

    def test_text_fields_are_enumerated_not_free(self):
        for body in (b"CA1 boot=0a1b2c3d seq=4 POOL_EXHAUSTED pool=other-db in_use=1 max=1",
                     b"CA1 boot=0a1b2c3d seq=4 CONFIG_LOADED key=db.password value=1"):
            self.assertIsNone(L.sanitize(line(body))["template"])
        self.assertEqual(L.sanitize(line(b"CA1 boot=0a1b2c3d seq=4 CONFIG_LOADED key=pool.maxConnections value=4"))["fields"],
                         {"key": "pool.maxConnections", "value": "4"})

    def test_the_catalog_is_pinned(self):
        self.assertEqual(L.CATALOG_VERSION, "ca-log-templates/0.1-provisional")
        self.assertTrue(L.catalog_digest().startswith("sha256:"))
        self.assertEqual(set(L.CATALOG), {"STARTED", "HEARTBEAT", "CONFIG_LOADED", "POOL_EXHAUSTED", "REQUEST_OK", "STOPPED"})


if __name__ == "__main__":
    unittest.main()
