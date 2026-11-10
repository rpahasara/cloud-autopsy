"""Database-layer checks that need no PostgreSQL server (run everywhere)."""

import base64
import hashlib
import hmac
import shutil
import tempfile
import unittest
from pathlib import Path

import _db  # noqa: F401  (path setup)
from cloud_autopsy.db import bootstrap, migrate


class ScramVerifierTests(unittest.TestCase):
    def test_rfc7677_example(self):
        # RFC 7677 section 3: user "user", password "pencil", salt W22ZaJ0SNY7soEsUEjb6gQ==, 4096 iterations.
        salt = base64.b64decode("W22ZaJ0SNY7soEsUEjb6gQ==")
        verifier = bootstrap.scram_verifier("pencil", salt=salt)
        _, rest = verifier.split("$", 1)
        _, keys = rest.split("$")
        stored_key, server_key = (base64.b64decode(k) for k in keys.split(":"))
        auth_message = (b"n=user,r=rOprNGfwEbeRWgbNEkqO,"
                        b"r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,s=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096,"
                        b"c=biws,r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0")
        server_signature = hmac.new(server_key, auth_message, hashlib.sha256).digest()
        self.assertEqual(base64.b64encode(server_signature).decode(), "6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4=")
        client_signature = hmac.new(stored_key, auth_message, hashlib.sha256).digest()
        proof = base64.b64decode("dHzbZapWIk4jUhN+Ute9ytag9zjfMHgsqmmiz7AndVQ=")
        client_key = bytes(a ^ b for a, b in zip(proof, client_signature))
        self.assertEqual(hashlib.sha256(client_key).digest(), stored_key)

    def test_verifier_format_is_safe_to_embed(self):
        verifier = bootstrap.scram_verifier("x" * 43)
        self.assertRegex(verifier, bootstrap._VERIFIER)
        self.assertNotIn("'", verifier)

    def test_database_names_are_validated(self):
        with self.assertRaises(ValueError):
            bootstrap.create_database(None, "bad; DROP DATABASE x")


class MigrationDiscoveryTests(unittest.TestCase):
    def test_discovery_and_contiguity(self):
        found = migrate.discover()
        self.assertEqual([m.filename for m in found], ["0001_core.sql", "0002_ingest_requires_collecting.sql"])
        for m in found:
            self.assertEqual(len(m.sha256), 64)
            self.assertTrue(m.sql.isascii())
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copy(migrate.MIGRATIONS_DIR / "0001_core.sql", tmp / "0001_core.sql")
        (tmp / "0003_later.sql").write_text("SELECT 1;")
        with self.assertRaises(migrate.MigrationError):
            migrate.discover(tmp)


if __name__ == "__main__":
    unittest.main()
