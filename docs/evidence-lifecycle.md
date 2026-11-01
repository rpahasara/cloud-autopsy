# Evidence expiry, provenance and replay contract (Proposed)

Owner: Security reviewer, with Architecture lead accountable for replay semantics. Approval status: no approval recorded. [CA-DEC-005](architecture/adr/CA-DEC-005.md) proposes the periods; this contract supplies acceptance semantics for CA-FR-002/005/010/012, CA-NFR-001/004/010 and CA-SEC-007/008. All remain draft.

| Artifact | Proposed retention | Expiry/deletion behavior |
|---|---|---|
| Reviewed synthetic fixtures and ground truth in Git | Versioned project lifetime; review at each gate | Never put sensitive data in Git. Retirement preserves version references; accidental sensitive commits require explicit history-cleanup handling. |
| Generated raw and normalized evidence, derived payloads, exports and cached model content | 30 days from run completion | Remove payloads and sensitive indexes/caches; invalidate dependent replay capability; retain only permitted minimized metadata below. |
| Manifests, content hashes, provenance edges, scores, approvals, security audits and tombstones | 180 days from run completion | Retain only non-sensitive metadata. Expire dependent payload-bearing fields at 30 days. After 180 days purge the run metadata and record only aggregate non-identifying lifecycle counts. |

An authorized deletion request overrides routine retention and is fulfilled within the proposed seven-day period, including derived copies and exports under repository control. The deletion inventory must cover each local store, cache and any future backup/export destination. A future backup policy must define deletion propagation before backups are introduced. External-provider retention is separately approved under CA-DEC-004 and is not covered by a local purge promise. No litigation hold or retention exception is assumed; any future exception needs explicit authority and revised scope.

At run creation, record retention-policy version, completion time, `expires_at` for each artifact class and dependency inventory. Purge work must be retryable and record pending/failed/completed status. A failed purge is an audit failure requiring review; it must not claim deletion completed. Evaluate expiry on access as well as on scheduled cleanup so overdue payloads cannot remain replayable simply because cleanup failed.

Before payload deletion, create a manifest-linked tombstone with opaque artifact/run IDs, content hash where non-sensitive, source type, schema/rule version, minimal provenance edges, lifecycle-policy version, expiry/deletion reason, requested/effective deletion times and authorized role/reference. Do not copy raw text, secret values, personal identifiers or sensitive source paths into tombstones. Hashes can disclose low-entropy values: retain a digest only when classification review permits it; otherwise record that the digest was removed for privacy. The original manifest remains immutable; a separate lifecycle overlay references its digest and records the changed availability. Tombstones expire with the 180-day metadata period, or earlier if authorized deletion requires it.

| Replay state | Required behavior |
|---|---|
| All required inputs retained and integrity verified | Permit deterministic replay with recorded versions and equivalence scoring; model narrative equivalence is not guaranteed. |
| Evidence expired or deleted, valid lifecycle record present | Return `incomplete_expired` or `incomplete_deleted`, identify affected dependencies and preserve inspectable minimized provenance. Do not mark equivalent or complete; do not infer absence or silently refetch. |
| Input unexpectedly missing, no valid tombstone | Return `missing_unexplained`; investigate retrieval/storage failure. Do not call it authorized expiry. |
| Content differs from trusted manifest | Return `integrity_mismatch`; reject affected replay/scoring even if a deletion record exists for another artifact. |
| Synthetic fixture can be reconstructed from Git | Explicitly start a new run referencing the old run and fixture version, subject to current approval and permissions. Never overwrite the original score or erase its expiry state. |
| Manifest/provenance has also expired | Report `replay_unavailable_metadata_expired`; make no verified historical equivalence claim. |

CA-TEST-FR-010 and CA-TEST-SEC-007 must cover each replay state, privacy-safe tombstones, purge retry/failure and the distinction between authorized deletion and unauthorized alteration. CA-TEST-SEC-008 checks lifecycle audit records and canary exclusion. Tests and their requirements reverse-link through the [matrix](requirement-matrix.md) and [STRIDE register](security/threat-model.md); these tests are planned and have not run.
