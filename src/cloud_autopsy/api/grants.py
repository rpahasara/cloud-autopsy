"""Bearer tokens with explicit run-level grants, ``ca-api-grants/0.1-provisional``.

A grants file is provisioned locally, outside any Git working tree, and holds only token hashes:

  {"contract_version": "ca-api-grants/0.1-provisional",
   "grants": [{"name": "demo-all", "token_sha256": "<64 hex>", "run_ids": ["<uuid>", ...]}, ...]}

``ca-api-grants/0.2-provisional`` (CA-P2-004b) adds ``status_run_ids`` to every grant: runs whose
**lifecycle status only** the token may read (``/v1/runs/{run_id}/status`` and the run's state in
``/v1/summaries``), for example a run whose creation failed. Status access never authorizes a
result, timeline, hypotheses, citations or evidence: those still need the run in ``run_ids`` and a
stored result that verifies on read. The two lists are disjoint and together name 1-1000 runs;
``run_ids`` may be empty in 0.2. Version 0.1 files are still accepted unchanged.

Rules:
- a token is 43-128 URL-safe characters (``issue`` makes 32 random bytes); only its SHA-256 is stored;
- every grant names its runs explicitly (lowercase canonical UUIDs, 1-1000 of them). There is
  no wildcard, so a valid token never authorizes every run;
- names and hashes are unique; unknown fields are refused;
- ``load`` refuses a file inside a Git working tree, a file readable by group or others (POSIX),
  a file over 64 KiB, and anything that is not exactly this schema.
Authentication hashes the presented token and compares it with every stored hash using
``hmac.compare_digest``, so timing does not depend on which grant matched.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

GRANTS_VERSION = "ca-api-grants/0.1-provisional"
GRANTS_VERSION_STATUS = "ca-api-grants/0.2-provisional"
_GRANT_KEYS = {GRANTS_VERSION: {"name", "token_sha256", "run_ids"},
               GRANTS_VERSION_STATUS: {"name", "token_sha256", "run_ids", "status_run_ids"}}
MAX_FILE_BYTES = 65_536
MAX_GRANTS = 100
MAX_RUNS_PER_GRANT = 1_000
TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}", re.ASCII)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.ASCII)
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}", re.ASCII)
HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)


class GrantError(ValueError):
    """The grants file was refused. ``code`` is stable; messages never echo file contents."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class Grant:
    name: str
    token_sha256: bytes
    run_ids: frozenset                       # results, timeline, hypotheses, citations, evidence
    status_run_ids: frozenset = frozenset()  # lifecycle status only

    def authorizes(self, run_id):
        """Result access: the run must still verify on read before anything is served."""
        return run_id in self.run_ids

    def may_view_status(self, run_id):
        """Lifecycle status access: the run's state and a fixed failure reason, nothing else."""
        return run_id in self.run_ids or run_id in self.status_run_ids

    @property
    def visible_run_ids(self):
        return self.run_ids | self.status_run_ids


def _sha256(token):
    return hashlib.sha256(token.encode("ascii")).digest()


class Grants:
    def __init__(self, grants):
        self._grants = tuple(grants)

    def __len__(self):
        return len(self._grants)

    def authenticate(self, authorization):
        """Return the ``Grant`` for an ``Authorization: Bearer <token>`` value, or None."""
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            return None
        token = authorization[len("Bearer "):]
        if not TOKEN.fullmatch(token):
            return None
        presented = _sha256(token)
        found = None
        for grant in self._grants:  # no early exit
            if hmac.compare_digest(presented, grant.token_sha256):
                found = grant
        return found


def _inside_git_tree(path):
    return any((parent / ".git").exists() for parent in path.parents)


def parse(record):
    if not isinstance(record, dict) or set(record) != {"contract_version", "grants"}:
        raise GrantError("grants_invalid", "grants file must have exactly contract_version and grants")
    version = record["contract_version"]
    if version not in _GRANT_KEYS:
        raise GrantError("grants_version", "unsupported grants version")
    items = record["grants"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_GRANTS:
        raise GrantError("grants_invalid", f"grants must be a list of 1-{MAX_GRANTS} entries")
    grants, names, hashes = [], set(), set()
    for item in items:
        if not isinstance(item, dict) or set(item) != _GRANT_KEYS[version]:
            raise GrantError("grants_invalid", "each grant has exactly the fields of its contract version")
        name, digest, runs = item["name"], item["token_sha256"], item["run_ids"]
        status_runs = item.get("status_run_ids", [])
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            raise GrantError("grants_invalid", "grant names must be unique lowercase identifiers")
        if not isinstance(digest, str) or not HEX64.fullmatch(digest) or digest in hashes:
            raise GrantError("grants_invalid", "token hashes must be unique SHA-256 hex digests")
        minimum = 1 if version == GRANTS_VERSION else 0
        if not _run_list(runs, minimum) or not _run_list(status_runs, 0) \
                or not 1 <= len(runs) + len(status_runs) <= MAX_RUNS_PER_GRANT or set(runs) & set(status_runs):
            raise GrantError("grants_invalid", "run_ids and status_run_ids must list 1-1000 distinct lowercase "
                                               "UUIDs in total, with no run in both (no wildcard)")
        names.add(name)
        hashes.add(digest)
        grants.append(Grant(name, bytes.fromhex(digest), frozenset(runs), frozenset(status_runs)))
    return Grants(grants)


def _run_list(runs, minimum):
    return (isinstance(runs, list) and minimum <= len(runs) <= MAX_RUNS_PER_GRANT and len(set(runs)) == len(runs)
            and all(isinstance(r, str) and UUID.fullmatch(r) for r in runs))


def load(path):
    path = Path(path).resolve()
    if _inside_git_tree(path):
        raise GrantError("grants_in_repository", "the grants file must be provisioned outside any Git working tree")
    info = path.stat()
    if os.name == "posix" and info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise GrantError("grants_permissions", "the grants file must not be accessible to group or others")
    if info.st_size > MAX_FILE_BYTES:
        raise GrantError("grants_too_large", "grants file is too large")
    try:
        record = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        raise GrantError("grants_invalid", "grants file is not valid JSON") from None
    return parse(record)


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def issue(grant_runs, status_runs=None):
    """``{name: [run_id, ...]}`` -> (grants record with hashes only, {name: token}). Tokens are shown once.

    ``status_runs`` (``{name: [run_id, ...]}``), when given, adds status-only runs to those grants
    and writes contract 0.2; without it the record is 0.1, exactly as before."""
    names = set(grant_runs) | set(status_runs or {})
    tokens = {name: secrets.token_urlsafe(32) for name in names}
    grants = []
    for name in sorted(names):
        entry = {"name": name, "token_sha256": _sha256(tokens[name]).hex(), "run_ids": sorted(grant_runs.get(name, []))}
        if status_runs is not None:
            entry["status_run_ids"] = sorted(status_runs.get(name, []))
        grants.append(entry)
    record = {"contract_version": GRANTS_VERSION if status_runs is None else GRANTS_VERSION_STATUS,
              "grants": grants}
    parse(record)  # refuse anything load() would refuse
    return record, tokens


def write_private(path, data):
    """Create ``path`` (which must not exist) with mode 0600 and write ``data``."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
