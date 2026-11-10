"""Bearer tokens with explicit run-level grants, ``ca-api-grants/0.1-provisional``.

A grants file is provisioned locally, outside any Git working tree, and holds only token hashes:

  {"contract_version": "ca-api-grants/0.1-provisional",
   "grants": [{"name": "demo-all", "token_sha256": "<64 hex>", "run_ids": ["<uuid>", ...]}, ...]}

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
    run_ids: frozenset

    def authorizes(self, run_id):
        return run_id in self.run_ids


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
    if record["contract_version"] != GRANTS_VERSION:
        raise GrantError("grants_version", "unsupported grants version")
    items = record["grants"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_GRANTS:
        raise GrantError("grants_invalid", f"grants must be a list of 1-{MAX_GRANTS} entries")
    grants, names, hashes = [], set(), set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"name", "token_sha256", "run_ids"}:
            raise GrantError("grants_invalid", "each grant has exactly name, token_sha256 and run_ids")
        name, digest, runs = item["name"], item["token_sha256"], item["run_ids"]
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            raise GrantError("grants_invalid", "grant names must be unique lowercase identifiers")
        if not isinstance(digest, str) or not HEX64.fullmatch(digest) or digest in hashes:
            raise GrantError("grants_invalid", "token hashes must be unique SHA-256 hex digests")
        if not isinstance(runs, list) or not 1 <= len(runs) <= MAX_RUNS_PER_GRANT \
                or not all(isinstance(r, str) and UUID.fullmatch(r) for r in runs) or len(set(runs)) != len(runs):
            raise GrantError("grants_invalid", "run_ids must list 1-1000 distinct lowercase UUIDs (no wildcard)")
        names.add(name)
        hashes.add(digest)
        grants.append(Grant(name, bytes.fromhex(digest), frozenset(runs)))
    return Grants(grants)


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


def issue(grant_runs):
    """``{name: [run_id, ...]}`` -> (grants record with hashes only, {name: token}). Tokens are shown once."""
    tokens = {name: secrets.token_urlsafe(32) for name in grant_runs}
    record = {"contract_version": GRANTS_VERSION,
              "grants": [{"name": name, "token_sha256": _sha256(tokens[name]).hex(), "run_ids": sorted(runs)}
                         for name, runs in sorted(grant_runs.items())]}
    parse(record)  # refuse anything load() would refuse
    return record, tokens


def write_private(path, data):
    """Create ``path`` (which must not exist) with mode 0600 and write ``data``."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
