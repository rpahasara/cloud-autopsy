"""Pod-log line sanitizer (CA-P2-004g): the sequence envelope and the pinned template catalog.

Every line read from ``pods/log`` is reduced **in memory**, before anything is written, to one of:

- ``{"ts", "boot", "seq", "synced", "lag_ms", "template", "fields"}`` when the envelope and a catalog
  template both match, with every field value type-checked;
- the same with ``"template": None`` and ``"fields": {}`` when the envelope matches but the template is
  unknown or a field fails its type (the line still counts for continuity; its content is dropped);
- ``{"invalid": "<code>"}`` when the line has no valid timestamp or envelope (continuity breaks there).

Nothing else of a line survives: no free text, no unknown field, no value that fails its type. The raw
line is never returned, logged or written.

Line format (plan, section 4.2; ``timestamps=true`` adds the runtime's RFC 3339 timestamp)::

  <RFC 3339 runtime timestamp> CA1 boot=<8 hex> seq=<n> [synced=<n> lag_ms=<n>] <TEMPLATE>[ <key>=<value>]...

``synced`` and ``lag_ms`` are the workload's write-after-append handshake fields (plan section 4.9).
"""

import hashlib
import re

from ..contracts import canonical

CATALOG_VERSION = "ca-log-templates/0.1-provisional"
MAX_LINE_BYTES = 1024           # after the runtime timestamp
MAX_SEQ = 1_000_000_000

_TS = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z"
_LINE = re.compile(rf"({_TS}) (.*)", re.ASCII | re.DOTALL)
_ENVELOPE = re.compile(r"CA1 boot=([0-9a-f]{8}) seq=([1-9][0-9]{0,9})"
                       r"(?: synced=(0|[1-9][0-9]{0,9}) lag_ms=(0|[1-9][0-9]{0,6}))?"
                       r" ([A-Z][A-Z0-9_]{0,63})((?: [a-z][a-z0-9_]{0,63}=[^ ]{1,256})*)", re.ASCII)

# Field types: each value must match exactly. Integers are canonical decimal (no sign, no leading zero).
INT = r"0|[1-9][0-9]{0,8}"
NAME = r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# Free text is never a field type: a text value is either an enumerated literal or a structural
# identifier checked against the request (``container``) or the watch (``pod_uid``) by the converter.
POOL = r"checkout-db"
CONFIG_KEY = r"pool\.maxConnections"
# The catalog: template -> ordered (field, pattern). The order is part of the template.
CATALOG = {
    "STARTED": (("pod_uid", UUID), ("container", NAME)),
    "HEARTBEAT": (),
    "CONFIG_LOADED": (("key", CONFIG_KEY), ("value", INT)),
    "POOL_EXHAUSTED": (("pool", POOL), ("in_use", INT), ("max", INT)),
    "REQUEST_OK": (),
    "STOPPED": (),
}
_COMPILED = {t: tuple((k, re.compile(p, re.ASCII)) for k, p in fields) for t, fields in CATALOG.items()}


def catalog_record():
    return {"version": CATALOG_VERSION,
            "templates": {t: [[k, p] for k, p in fields] for t, fields in sorted(CATALOG.items())}}


def catalog_digest():
    return "sha256:" + hashlib.sha256(canonical.canonical_bytes(catalog_record())).hexdigest()


def _fields(template, rest):
    """The typed fields of ``template`` from `` k=v`` pairs, or None if they do not match exactly."""
    spec = _COMPILED.get(template)
    if spec is None:
        return None
    pairs = [p.split("=", 1) for p in rest.split(" ")[1:]] if rest else []
    if [k for k, _ in pairs] != [k for k, _ in spec]:
        return None
    out = {}
    for (key, value), (_, pattern) in zip(pairs, spec):
        if not pattern.fullmatch(value):
            return None
        out[key] = value
    return out


def sanitize(raw):
    """``raw``: one complete line as bytes, without its newline. Returns the sanitized dict."""
    if not isinstance(raw, (bytes, bytearray)):
        return {"invalid": "not_bytes"}
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    try:
        text = bytes(raw).decode("ascii")
    except UnicodeDecodeError:
        return {"invalid": "not_ascii"}
    match = _LINE.fullmatch(text)
    if not match:
        return {"invalid": "timestamp"}
    ts, body = match.groups()
    if len(body) > MAX_LINE_BYTES:
        return {"invalid": "too_long"}
    env = _ENVELOPE.fullmatch(body)
    if not env:
        return {"invalid": "envelope"}
    boot, seq, synced, lag, template, rest = env.groups()
    seq = int(seq)
    synced = int(synced) if synced is not None else None
    if seq > MAX_SEQ or (synced is not None and synced > MAX_SEQ):
        return {"invalid": "envelope"}
    fields = _fields(template, rest)
    out = {"ts": ts, "boot": boot, "seq": seq, "synced": synced,
           "lag_ms": int(lag) if lag is not None else None, "template": template if fields is not None else None,
           "fields": fields or {}}
    return out
