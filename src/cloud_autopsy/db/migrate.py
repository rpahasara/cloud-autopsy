"""Forward-only, checksummed SQL migrations.

Files are ``NNNN_name.sql`` in ``migrations/``, applied in order, each in its own transaction as
``ca_migrator`` with ``SET LOCAL ROLE ca_owner``. The ledger ``ca_meta.schema_migration`` records
each file's SHA-256; the runner refuses to continue if an applied file changed, disappeared or
is out of order. Concurrent runners serialize on a ledger lock. There are no down migrations.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_FILE = re.compile(r"(\d{4})_[a-z0-9_]+\.sql")

LEDGER = """
CREATE SCHEMA IF NOT EXISTS ca_meta;
CREATE TABLE IF NOT EXISTS ca_meta.schema_migration (
  version integer PRIMARY KEY, filename text NOT NULL, sha256 text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now(), applied_by text NOT NULL)
"""


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    sha256: str
    sql: str


def discover(directory=MIGRATIONS_DIR):
    found = []
    for path in sorted(Path(directory).iterdir()):
        match = _FILE.fullmatch(path.name)
        if not match:
            continue
        data = path.read_bytes()
        found.append(Migration(int(match.group(1)), path.name, hashlib.sha256(data).hexdigest(),
                               data.decode("utf-8")))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError("migration versions must be contiguous from 0001")
    return found


def apply(migrator_db, directory=MIGRATIONS_DIR, applied_by="ca_migrator"):
    """Apply pending migrations; return the filenames applied in this call."""
    migrations = discover(directory)
    with migrator_db.transaction():
        migrator_db.run("SET LOCAL ROLE ca_owner")
        migrator_db.run(LEDGER)
    applied_now = []
    for migration in migrations:
        with migrator_db.transaction():
            migrator_db.run("SET LOCAL ROLE ca_owner")
            migrator_db.run("LOCK TABLE ca_meta.schema_migration IN EXCLUSIVE MODE")
            ledger = {row[0]: (row[1], row[2]) for row in
                      migrator_db.run("SELECT version, filename, sha256 FROM ca_meta.schema_migration")}
            _verify_ledger(ledger, migrations)
            if migration.version in ledger:
                continue
            if set(ledger) != set(range(1, migration.version)):
                raise MigrationError("ledger is missing an earlier migration")
            migrator_db.run(migration.sql)
            migrator_db.run("INSERT INTO ca_meta.schema_migration (version, filename, sha256, applied_by) "
                            "VALUES (:v, :f, :s, :b)", v=migration.version, f=migration.filename,
                            s=migration.sha256, b=applied_by)
            applied_now.append(migration.filename)
    return applied_now


def _verify_ledger(ledger, migrations):
    by_version = {m.version: m for m in migrations}
    for version, (filename, digest) in ledger.items():
        current = by_version.get(version)
        if current is None:
            raise MigrationError(f"applied migration {filename} is missing from the repository")
        if (current.filename, current.sha256) != (filename, digest):
            raise MigrationError(f"applied migration {filename} has changed (checksum mismatch)")
