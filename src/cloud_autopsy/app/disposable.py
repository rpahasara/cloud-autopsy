"""A disposable, synthetic-only database session for the local demonstration.

Given the container's bootstrap credential (a file in a private per-session directory), it
creates the runtime roles with fresh random passwords (SCRAM verifiers only), creates a fresh
database, applies the checksummed migrations as ``ca_migrator``, checks that the database is
classified synthetic with this package's contract pins, and opens one connection per role.
The bootstrap superuser is used for nothing else. ``close()`` drops the database.
"""

import os
import uuid
from pathlib import Path

from ..db import bootstrap, ingest, migrate
from ..db.adapter import Database, Endpoint

RUNTIME_ROLES = ("ca_planner", "ca_ingest", "ca_sealer", "ca_engine", "ca_result_writer")


class DisposableDatabase:
    def __init__(self, secret_dir, host="127.0.0.1", port=55432, bootstrap_user="ca_bootstrap"):
        self.secret_dir = Path(secret_dir)
        self.host, self.port, self.bootstrap_user = host, int(port), bootstrap_user
        self.name = f"ca_demo_{uuid.uuid4().hex[:12]}"
        self._open = []
        admin = self._superuser("cloud_autopsy_synthetic")
        try:
            self.passwords = bootstrap.bootstrap_roles(admin, self.secret_dir)
            bootstrap.create_database(admin, self.name)
        finally:
            admin.close()
        admin = self._superuser(self.name)
        try:
            bootstrap.harden_database(admin)
        finally:
            admin.close()
        self.applied = migrate.apply(self.connect("ca_migrator"))
        self.roles = {role: self.connect(role) for role in RUNTIME_ROLES}
        for db in self.roles.values():
            ingest.check_environment(db)

    @classmethod
    def from_environment(cls):
        secret_dir = os.environ.get("CA_PG_SECRET_DIR")
        if not secret_dir:
            raise RuntimeError("CA_PG_SECRET_DIR is not set: no disposable PostgreSQL is configured")
        return cls(secret_dir, os.environ.get("CA_PG_HOST", "127.0.0.1"), os.environ.get("CA_PG_PORT", "55432"),
                   os.environ.get("CA_PG_BOOTSTRAP_USER", "ca_bootstrap"))

    def _superuser(self, database):
        password = (self.secret_dir / "bootstrap_password").read_text(encoding="ascii").strip()
        return Database(Endpoint(self.host, self.port, database), self.bootstrap_user, password)

    def connect(self, role):
        db = Database(Endpoint(self.host, self.port, self.name), role, self.passwords[role])
        self._open.append(db)
        return db

    def close(self):
        for db in self._open:
            db.close()
        admin = self._superuser("cloud_autopsy_synthetic")
        try:
            bootstrap.drop_database(admin, self.name)
        finally:
            admin.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
