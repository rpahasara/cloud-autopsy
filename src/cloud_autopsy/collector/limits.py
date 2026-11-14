"""Declared numeric limits (CA-P2-004g; plan section 6.2): the only container env values ever read.

A scope declaration names ``(container, env name, catalog key)``, for example
``("checkout-api", "DB_POOL_MAX", "pool.maxConnections")``. A value is kept only when the key is declared
for that container, set by a literal ``value`` (never ``valueFrom``), and is a canonical non-negative
integer of at most six digits. Everything else -- ``secretKeyRef``, ``configMapKeyRef``, ``fieldRef``,
``resourceFieldRef``, ``envFrom``, malformed integers, undeclared keys, declared keys of other containers --
is withheld and counted; it never yields a value.
"""

import re

from ..contracts.evidence import _CREDENTIAL_KEY

VALUE = re.compile(r"0|[1-9][0-9]{0,5}", re.ASCII)
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}", re.ASCII)
CONTAINER = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?", re.ASCII)
CONFIG_KEY = re.compile(r"[A-Za-z0-9._-]{1,253}", re.ASCII)
MAX_DECLARATIONS = 8


class LimitDeclarationError(ValueError):
    pass


def check_declarations(declarations):
    """Validated declarations as a sorted tuple of (container, env, config_key); refuses anything else."""
    if not isinstance(declarations, (list, tuple)) or len(declarations) > MAX_DECLARATIONS:
        raise LimitDeclarationError("declared limits must be a list of at most 8 entries")
    out = set()
    for item in declarations:
        if isinstance(item, dict):
            item = (item.get("container"), item.get("env"), item.get("config_key"))
        if not isinstance(item, (list, tuple)) or len(item) != 3 or not all(isinstance(v, str) for v in item):
            raise LimitDeclarationError("a declared limit is (container, env, config_key)")
        container, env, key = item
        if not CONTAINER.fullmatch(container) or not ENV_NAME.fullmatch(env) or not CONFIG_KEY.fullmatch(key):
            raise LimitDeclarationError("a declared limit has an invalid container, env name or catalog key")
        if _CREDENTIAL_KEY.search(env) or _CREDENTIAL_KEY.search(key):
            raise LimitDeclarationError("a credential-like name cannot be declared as a limit")
        out.add((container, env, key))
    if len({(c, e) for c, e, _ in out}) != len(out):
        raise LimitDeclarationError("an env name is declared twice for one container")
    return tuple(sorted(out))


def as_records(declarations):
    return [{"container": c, "env": e, "config_key": k} for c, e, k in declarations]


def project_env(container, name, declarations, counts):
    """``[{"name", "value"}]`` for the declared limits of the container called ``name``; the rest counted."""
    wanted = {e for c, e, _ in declarations if c == name}
    if not wanted:
        return []
    out, seen = [], set()
    env = container.get("env") if isinstance(container.get("env"), list) else []
    for entry in env:
        entry = entry if isinstance(entry, dict) else {}
        key = entry.get("name")
        if key not in wanted:
            continue
        value = entry.get("value")
        if "valueFrom" in entry or not isinstance(value, str) or not VALUE.fullmatch(value) or key in seen:
            counts["declared_limit_withheld"] = counts.get("declared_limit_withheld", 0) + 1
            continue
        seen.add(key)
        out.append({"name": key, "value": value})
    return sorted(out, key=lambda e: e["name"])
