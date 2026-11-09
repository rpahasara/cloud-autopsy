"""Development and test bootstrap for a disposable synthetic database (never for shared databases).

Run once per session as the container's bootstrap superuser. It creates the eight roles with
random per-session passwords written to a private directory outside Git, and creates a database
owned by ``ca_owner``. Passwords are sent to the server only as SCRAM-SHA-256 verifiers computed
here, so no plaintext password appears in any SQL statement or server log.
"""

import base64
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

ROLES = {
    # role: (login, member of ca_owner for SET ROLE only)
    "ca_owner": (False, False),
    "ca_migrator": (True, True),
    "ca_planner": (True, False),
    "ca_ingest": (True, False),
    "ca_sealer": (True, False),
    "ca_reader": (True, False),
    "ca_evaluator": (True, False),
    "ca_lifecycle": (True, False),
}
RUNTIME_SETTINGS = {"search_path": "ca, pg_catalog", "statement_timeout": "30s", "lock_timeout": "5s",
                    "idle_in_transaction_session_timeout": "60s"}
_VERIFIER = re.compile(r"SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+")
_DB_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}")
SCRAM_ITERATIONS = 4096


def scram_verifier(password, salt=None, iterations=SCRAM_ITERATIONS):
    """RFC 5802 / RFC 7677 SCRAM-SHA-256 verifier in PostgreSQL's stored format."""
    salt = salt or secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def _write_secret(directory, name, value):
    path = Path(directory) / f"{name}.password"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(value)
    return path


def bootstrap_roles(superuser_db, secret_dir):
    """Create or reset the eight roles; return {role: password} (also written to ``secret_dir``)."""
    passwords = {}
    for role, (login, owner_member) in ROLES.items():
        exists = superuser_db.one("SELECT 1 FROM pg_roles WHERE rolname = :r", r=role)
        attrs = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT " + \
            ("LOGIN" if login else "NOLOGIN")
        superuser_db.run(f"{'ALTER' if exists else 'CREATE'} ROLE {role} WITH {attrs}")
        if login:
            password = secrets.token_urlsafe(32)
            verifier = scram_verifier(password)
            if not _VERIFIER.fullmatch(verifier):
                raise RuntimeError("unexpected verifier format")
            superuser_db.run(f"ALTER ROLE {role} WITH PASSWORD '{verifier}'")
            passwords[role] = password
            _write_secret(secret_dir, role, password)
        if owner_member:
            superuser_db.run(f"GRANT ca_owner TO {role} WITH INHERIT FALSE, SET TRUE")
    return passwords


def create_database(superuser_db, name):
    """Create a fresh database owned by ca_owner and restrict who may connect."""
    if not _DB_NAME.fullmatch(name):
        raise ValueError("database name must match [a-z][a-z0-9_]{0,62}")
    superuser_db.run(f"CREATE DATABASE {name} OWNER ca_owner ENCODING 'UTF8' TEMPLATE template0")
    superuser_db.run(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC")
    runtime = [r for r, (login, _) in ROLES.items() if login]
    superuser_db.run(f"GRANT CONNECT ON DATABASE {name} TO {', '.join(runtime)}")
    for role in runtime:
        for key, value in RUNTIME_SETTINGS.items():
            superuser_db.run(f"ALTER ROLE {role} IN DATABASE {name} SET {key} = '{value}'")


def harden_database(superuser_db_in_new_database):
    """Run inside the new database: nobody but the owner may create objects in public."""
    superuser_db_in_new_database.run("REVOKE ALL ON SCHEMA public FROM PUBLIC")


def drop_database(superuser_db, name):
    if not _DB_NAME.fullmatch(name):
        raise ValueError("invalid database name")
    superuser_db.run(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
