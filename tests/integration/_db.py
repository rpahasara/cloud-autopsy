"""Harness for integration tests against a real, disposable, synthetic-only PostgreSQL.

Configured only through the environment (nothing secret is committed):
  CA_PG_HOST          loopback host of the test container (default 127.0.0.1)
  CA_PG_PORT          published port (default 55432)
  CA_PG_SECRET_DIR    private directory holding bootstrap_password, generated per session
When CA_PG_SECRET_DIR is unset the tests are reported as skipped, never as passed.
Each test class gets its own freshly migrated database, dropped afterwards.
"""

import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "src", REPO / "tests" / "contracts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

SECRET_DIR = os.environ.get("CA_PG_SECRET_DIR")
AVAILABLE = bool(SECRET_DIR)
SKIP_REASON = "CA_PG_SECRET_DIR not set: no disposable PostgreSQL available (see db/README.md)"
if os.environ.get("CA_PG_REQUIRE") == "1" and not AVAILABLE:
    raise RuntimeError("CA_PG_REQUIRE=1 but no database is configured; refusing to report skipped tests as a pass")

_roles = {}


def endpoint(database):
    from cloud_autopsy.db.adapter import Endpoint
    return Endpoint(os.environ.get("CA_PG_HOST", "127.0.0.1"), int(os.environ.get("CA_PG_PORT", "55432")), database)


def bootstrap_user():
    return os.environ.get("CA_PG_BOOTSTRAP_USER", "ca_bootstrap")


def superuser(database="cloud_autopsy_synthetic"):
    """The container's initialization superuser: used only to create and drop roles and databases."""
    from cloud_autopsy.db.adapter import Database
    password = (Path(SECRET_DIR) / "bootstrap_password").read_text(encoding="ascii").strip()
    return Database(endpoint(database), bootstrap_user(), password)


def ensure_roles():
    """Create the eight roles once per test process, with fresh random passwords."""
    from cloud_autopsy.db import bootstrap
    if not _roles:
        admin = superuser()
        try:
            _roles.update(bootstrap.bootstrap_roles(admin, SECRET_DIR))
        finally:
            admin.close()
    return _roles


class Fixture:
    """A freshly created and migrated database, plus per-role connections."""

    def __init__(self):
        from cloud_autopsy.db import bootstrap, migrate
        self.passwords = ensure_roles()
        self.name = f"ca_it_{uuid.uuid4().hex[:12]}"
        admin = superuser()
        try:
            bootstrap.create_database(admin, self.name)
        finally:
            admin.close()
        admin = superuser(self.name)
        try:
            bootstrap.harden_database(admin)
        finally:
            admin.close()
        self._open = []
        self.applied = migrate.apply(self.connect("ca_migrator"))

    def connect(self, role):
        from cloud_autopsy.db.adapter import Database
        db = Database(endpoint(self.name), role, self.passwords[role])
        self._open.append(db)
        return db

    def close(self):
        from cloud_autopsy.db import bootstrap
        for db in self._open:
            db.close()
        admin = superuser()
        try:
            bootstrap.drop_database(admin, self.name)
        finally:
            admin.close()
