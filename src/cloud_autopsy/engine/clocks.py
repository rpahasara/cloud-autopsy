"""Clock-domain declaration ``ca-clock-declaration/0.1-provisional`` (CA-P2-006a).

The clock assumptions an investigation uses (offset, uncertainty, continuity per clock domain)
are part of its input, so they are frozen as one canonical document bound to the run:

  {"contract_version": "ca-clock-declaration/0.1-provisional",
   "registry_digest": <the run's source-registry digest>,
   "clock_domains": [<ca-time-interval clock-domain record>, ...]}   sorted by clock_domain_id

Rules:
- exactly the clock domains bound to the registry's sources, each declared once: nothing
  missing, nothing extra, nothing duplicated;
- every record is strictly decoded by the time-interval contract;
- the digest is ``ca-clock-declaration-sha256/0.1-provisional:`` + SHA-256 of the exact
  canonical bytes, so the database can recompute it without parsing JSON.
``from_bytes`` refuses non-canonical bytes, another registry, and a digest that does not match.
Pure: no I/O.
"""

import hashlib
from dataclasses import dataclass

from ..contracts import canonical
from ..contracts import timeinterval as ti
from ..contracts.errors import ContractError
from . import CLOCK_DECLARATION_ALGORITHM, CLOCK_DECLARATION_VERSION

MAX_CLOCK_DOMAINS = 64
MAX_BYTES = 65_536


class ClockDeclarationError(ValueError):
    """A clock declaration was refused. ``code`` is stable; messages never echo values."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _digest(raw):
    return f"{CLOCK_DECLARATION_ALGORITHM}:{hashlib.sha256(raw).hexdigest()}"


@dataclass(frozen=True)
class ClockDeclaration:
    registry_digest: str
    domains: dict          # clock_domain_id -> ti.ClockDomain
    records: tuple         # canonical clock-domain records, sorted by clock_domain_id
    raw: bytes             # exact canonical bytes
    digest: str

    @classmethod
    def from_bytes(cls, raw, registry, expected_digest=None):
        raw = bytes(raw)
        if len(raw) > MAX_BYTES:
            raise ClockDeclarationError("clock_declaration_invalid", "declaration is too large")
        try:
            record = canonical.loads(raw)
            reencoded = canonical.canonical_bytes(record)
        except ContractError:
            raise ClockDeclarationError("clock_declaration_invalid", "declaration is not canonical JSON") from None
        if reencoded != raw:
            raise ClockDeclarationError("clock_declaration_invalid", "declaration bytes are not canonical")
        if not isinstance(record, dict) or set(record) != {"contract_version", "registry_digest", "clock_domains"}:
            raise ClockDeclarationError("clock_declaration_invalid", "declaration has the wrong fields")
        if record["contract_version"] != CLOCK_DECLARATION_VERSION:
            raise ClockDeclarationError("clock_declaration_version", "unsupported declaration version")
        if record["registry_digest"] != registry.digest:
            raise ClockDeclarationError("clock_declaration_registry_mismatch",
                                        "declaration was made for a different source registry")
        declaration = declare(registry, record["clock_domains"])
        if declaration.raw != raw:
            raise ClockDeclarationError("clock_declaration_invalid", "declaration is not in canonical order")
        if expected_digest is not None and declaration.digest != expected_digest:
            raise ClockDeclarationError("clock_declaration_digest_mismatch",
                                        "declaration digest differs from the recorded one")
        return declaration


def declare(registry, clock_domain_records):
    """Validate declared clock domains against ``registry`` and freeze them."""
    if not isinstance(clock_domain_records, (list, tuple)):
        raise ClockDeclarationError("clock_declaration_invalid", "clock domains must be a list")
    if len(clock_domain_records) > MAX_CLOCK_DOMAINS:
        raise ClockDeclarationError("limit_exceeded", f"more than {MAX_CLOCK_DOMAINS} clock domains")
    registered = {d for source in registry.sources for d in source.clock_domain_ids}
    domains = {}
    for record in clock_domain_records:
        domain = ti.ClockDomain.from_record(record)
        if domain.clock_domain_id in domains:
            raise ClockDeclarationError("clock_domain_duplicated", "a clock domain was declared twice")
        if domain.clock_domain_id not in registered:
            raise ClockDeclarationError("clock_domain_unregistered",
                                        "a clock domain is not bound to any registered source")
        domains[domain.clock_domain_id] = domain
    if set(domains) != registered:
        raise ClockDeclarationError("clock_domain_missing", "a registered clock domain has no declaration")
    records = tuple(domains[k].to_record() for k in sorted(domains))
    raw = canonical.canonical_bytes({"contract_version": CLOCK_DECLARATION_VERSION,
                                     "registry_digest": registry.digest, "clock_domains": list(records)})
    if len(raw) > MAX_BYTES:
        raise ClockDeclarationError("limit_exceeded", "declaration is too large")
    return ClockDeclaration(registry.digest, domains, records, raw, _digest(raw))
