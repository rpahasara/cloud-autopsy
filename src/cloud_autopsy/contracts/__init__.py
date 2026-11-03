"""Versioned evidence, time and manifest contracts (CA-P2-002). All versions are provisional.

Slice CA-P2-002a provides typed errors, exact-match versioning and the canonical JSON
profile; CA-P2-002b adds timestamp provenance and clock intervals. Contracts perform no
I/O beyond the bytes or values passed to them.
"""

from .canonical import CANON_VERSION, DIGEST_ALGORITHM
from .timeinterval import TIME_VERSION

# Contract name -> exact version identifier implemented by this package.
CONTRACT_VERSIONS = {
    "canonical-json": CANON_VERSION,
    "canonical-digest": DIGEST_ALGORITHM,
    "time-interval": TIME_VERSION,
}
CONTRACT_STATUS = "provisional: unreviewed; not RFC 8785 conformance evidence"
