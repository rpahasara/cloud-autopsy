"""Versioned evidence, time and manifest contracts (CA-P2-002). All versions are provisional.

Slice CA-P2-002a provides typed errors, exact-match versioning and the canonical JSON
profile. Contracts perform no I/O beyond the bytes or values passed to them.
"""

from .canonical import CANON_VERSION, DIGEST_ALGORITHM

# Contract name -> exact version identifier implemented by this package.
CONTRACT_VERSIONS = {
    "canonical-json": CANON_VERSION,
    "canonical-digest": DIGEST_ALGORITHM,
}
CONTRACT_STATUS = "provisional: unreviewed; not RFC 8785 conformance evidence"
