"""Narrow database adapter: the only module that imports pg8000.

Connections use server-side parameter binding for every value (never ``pg8000.native.literal``).
Transactions are explicit. Driver errors are mapped to ``DbError`` with the SQLSTATE code, and
only serialization failures, deadlocks and lock timeouts are retried, a bounded number of times.
"""

import random
import time
from contextlib import contextmanager
from dataclasses import dataclass

import pg8000.native
from pg8000.exceptions import DatabaseError, InterfaceError

RETRYABLE_SQLSTATES = frozenset({"40001", "40P01", "55P03"})
MAX_ATTEMPTS = 5  # PROVISIONAL


class DbError(RuntimeError):
    """A database error with its SQLSTATE. ``str()`` carries the server message, never parameters."""

    def __init__(self, sqlstate, message):
        self.sqlstate = sqlstate
        super().__init__(f"{sqlstate}: {message}")

    @property
    def retryable(self):
        return self.sqlstate in RETRYABLE_SQLSTATES


def _map(exc):
    if isinstance(exc, DatabaseError) and exc.args and isinstance(exc.args[0], dict):
        info = exc.args[0]
        return DbError(info.get("C", "XX000"), info.get("M", "database error"))
    return DbError("08000", f"connection error: {type(exc).__name__}")


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    database: str


class Database:
    """One connection for one role. Not thread-safe: use one per thread."""

    def __init__(self, endpoint, user, password, timeout=10, application_name="cloud-autopsy"):
        try:
            self._con = pg8000.native.Connection(
                user=user, password=password, host=endpoint.host, port=endpoint.port,
                database=endpoint.database, timeout=timeout, application_name=application_name)
        except (DatabaseError, InterfaceError, OSError) as exc:
            raise _map(exc) from None
        self.user = user
        self._in_transaction = False

    def run(self, sql, **params):
        """Run one statement with bound parameters; with no parameters, a script may hold several."""
        try:
            return self._con.run(sql, **params)
        except (DatabaseError, InterfaceError) as exc:
            raise _map(exc) from None

    def one(self, sql, **params):
        rows = self.run(sql, **params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self, isolation="READ COMMITTED", read_only=False):
        if self._in_transaction:
            raise RuntimeError("nested transactions are not supported")
        if isolation not in ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"):
            raise ValueError("unsupported isolation level")
        self.run(f"BEGIN ISOLATION LEVEL {isolation}{' READ ONLY' if read_only else ''}")
        self._in_transaction = True
        try:
            yield self
        except BaseException:
            try:
                self._con.run("ROLLBACK")
            except (DatabaseError, InterfaceError):
                pass
            raise
        else:
            self.run("COMMIT")
        finally:
            self._in_transaction = False

    def close(self):
        try:
            self._con.close()
        except (DatabaseError, InterfaceError, OSError):
            pass


def with_retry(operation, attempts=MAX_ATTEMPTS, base_delay=0.02):
    """Run ``operation()`` and retry only retryable SQLSTATEs, with jittered exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except DbError as exc:
            if not exc.retryable or attempt == attempts:
                raise
            time.sleep(base_delay * (2 ** attempt) * (0.5 + random.random()))
