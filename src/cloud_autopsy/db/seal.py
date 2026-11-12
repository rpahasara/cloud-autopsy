"""Two-phase atomic sealing (transaction T3/T4 in docs/phase2/ca-p2-003/transactions.md).

Phase A freezes intake by moving the run from ``collecting`` to ``sealing`` with a compare-and-swap
on ``state_version`` and a lease. The pure contract seal (``frozen_input.seal``) then runs outside
any write transaction over the run's stored batches. Phase B publishes the root, every page and the
decoded rows in one transaction, re-verifies them from the database with ``verify_full`` and only
then moves the run to ``sealed``. Any failure rolls phase B back completely; the deterministic seal
makes a retry (or a lease takeover after expiry) publish byte-identical output.

Run lifecycle and recovery (CA-P2-004b, R4):

- **Deterministic failure** (a contract error from the pure seal or from re-verifying what phase B
  wrote, for example ``limit_exceeded``): repeating the seal gives the same error, so the worker
  moves the run to ``failed`` with the fixed reason ``seal:<contract code>`` and raises
  ``SealFailed``. The run never waits in ``sealing`` for its lease to expire.
- **Transient failure** (a database or connection error, or a crashed worker): the run stays
  ``sealing`` under its lease. After the lease expires, any worker may take it over and seal again;
  the output is byte-identical.
- **Bounded, durable retries:** every lease acquisition is a committed update that increases
  ``state_version`` by exactly one (enforced by ``ca.check_run_transition``), and a run in
  ``sealing`` is only ever updated by lease acquisition. So while a run is ``sealing``, its
  ``state_version`` *is* the number of lease acquisitions so far, and it survives any crash. A
  worker that would make acquisition ``MAX_SEAL_ATTEMPTS + 1`` instead moves the run to ``failed``
  with ``seal:attempts_exhausted``.
- **Fencing:** publication (phase B) and the move to ``failed`` both require, under ``FOR UPDATE``,
  that the run is still ``sealing`` at this worker's ``state_version``, owned by this worker, and
  that the lease has not expired (checked against ``clock_timestamp()``, not the transaction
  start). A worker whose lease expired or was taken over gets ``SealConflict`` and changes nothing.
- **A lease that expires during publication is safe.** The lease is checked once, but under a
  ``FOR UPDATE`` lock on the run row that phase B holds until it commits or rolls back. Every other
  change to the run (a takeover in phase A, or a move to ``failed``) must take the same row lock
  first, so none can happen while the publication transaction is open. If the lease expires
  mid-publication, a would-be taker waits on the lock (``lock_timeout``, then a bounded retry) and
  then sees either ``sealed`` (and gets ``SealConflict``) or, after a rollback, an expired
  ``sealing`` run it may take over. The lease bounds how long a *crashed* worker blocks recovery;
  the row lock is what serializes publication. A second check just before the final update would
  add nothing: no takeover can be committed in between. Tested in ``test_lifecycle``.
"""

import re
import uuid

from ..contracts import canonical
from ..contracts import frozen_input as fi
from ..contracts.errors import ContractError
from .adapter import with_retry

MAX_SEAL_ATTEMPTS = 3  # PROVISIONAL: lease acquisitions before a run left in 'sealing' is failed
ATTEMPTS_EXHAUSTED = "seal:attempts_exhausted"
_REASON = re.compile(r"seal:[a-z][a-z0-9_]{0,63}", re.ASCII)


class SealConflict(RuntimeError):
    """Another sealer holds the run, or the run is not in a sealable state."""


class SealFailed(RuntimeError):
    """The run was moved to ``failed``. ``reason`` is a fixed code (``seal:<code>``), never input content."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"run failed: {reason}")


class InjectedFailure(RuntimeError):
    """Raised only by tests through ``fail_before_commit`` to prove rollback."""


def failure_reason(exc):
    """The fixed reason recorded for a deterministic (contract) failure."""
    reason = f"seal:{getattr(exc, 'code', '')}"
    return reason if _REASON.fullmatch(reason) else "seal:contract_error"


def seal_run(sealer_db, run_id, plan, registry, worker=None, lease_seconds=300, fail_before_commit=False):
    """Seal the run, or take over a run whose lease expired.

    Raises ``SealConflict`` when another worker holds a live lease or the run is not sealable, and
    ``SealFailed`` when the run was moved to ``failed``. Any other exception is transient: the run
    stays ``sealing`` under this worker's lease and is recoverable once the lease expires."""
    worker = worker or f"sealer-{uuid.uuid4().hex[:12]}"
    version = with_retry(lambda: _phase_a(sealer_db, run_id, plan, worker, lease_seconds))
    if version is None:
        raise SealFailed(ATTEMPTS_EXHAUSTED)
    try:
        records = _load_batches(sealer_db, run_id)
        frozen = fi.seal(plan, registry, records)
        with_retry(lambda: _phase_b(sealer_db, run_id, plan, registry, worker, version, frozen, fail_before_commit))
    except ContractError as exc:  # deterministic: repeating the seal gives the same error
        reason = failure_reason(exc)
        with_retry(lambda: _mark_failed(sealer_db, run_id, worker, version, reason))
        raise SealFailed(reason) from None
    return frozen


def _phase_a(db, run_id, plan, worker, lease_seconds):
    with db.transaction():
        row = db.one("SELECT state, state_version, lease_owner, lease_expires_at < now(), plan_digest "
                     "FROM ca.run WHERE run_id = CAST(:r AS uuid) FOR UPDATE", r=run_id)
        if row is None:
            raise SealConflict("run does not exist")
        state, version, owner, expired, plan_digest = row
        if plan_digest != plan.digest:
            raise SealConflict("plan differs from the run's plan")
        if state == "sealing" and (owner == worker or expired) and version >= MAX_SEAL_ATTEMPTS:
            # The durable bound: while a run is sealing, state_version counts its lease acquisitions.
            db.run("UPDATE ca.run SET state = 'failed', state_version = state_version + 1, lease_owner = NULL, "
                   "lease_expires_at = NULL, failure_reason = :f WHERE run_id = CAST(:r AS uuid) "
                   "AND state_version = :v", f=ATTEMPTS_EXHAUSTED, r=run_id, v=version)
            return None
        if state == "collecting" or (state == "sealing" and (owner == worker or expired)):
            db.run("UPDATE ca.run SET state = 'sealing', state_version = state_version + 1, lease_owner = :w, "
                   "lease_expires_at = now() + make_interval(secs => :s) WHERE run_id = CAST(:r AS uuid) "
                   "AND state_version = :v", w=worker, s=lease_seconds, r=run_id, v=version)
            return version + 1
        raise SealConflict(f"run is {state}" + (" and leased by another sealer" if state == "sealing" else ""))


def _load_batches(db, run_id):
    with db.transaction(isolation="REPEATABLE READ", read_only=True):
        rows = db.run("SELECT record_bytes FROM ca.acquisition_batch WHERE run_id = CAST(:r AS uuid) "
                      "ORDER BY source_id, query_id, batch_key, batch_digest", r=run_id)
    # The delivery attempt is volatile and excluded from batch digests; the seal ignores it.
    return [{**canonical.loads(bytes(row[0])), "delivery": {"attempt": 1}} for row in rows]


def _phase_b(db, run_id, plan, registry, worker, version, frozen, fail_before_commit):
    root = frozen.root()
    with db.transaction():
        _hold_lease(db, run_id, worker, version, "publication")
        db.run("INSERT INTO ca.frozen_input (run_id, plan_digest, contract_version, manifest_digest, status, "
               "root_bytes) VALUES (CAST(:r AS uuid), :p, :v, :d, :s, :b)", r=run_id, p=plan.digest,
               v=root["contract_version"], d=root["manifest_digest"], s=root["status"], b=frozen.root_bytes)
        for blob in frozen.page_bytes:
            page = canonical.loads(blob)
            db.run("INSERT INTO ca.manifest_page (run_id, collection, page_index, page_digest, item_count, "
                   "page_bytes) VALUES (CAST(:r AS uuid), :c, :i, :d, :n, :b)", r=run_id, c=page["collection"],
                   i=page["page_index"], d=fi.page_digest(blob), n=len(page["items"]), b=blob)
        _insert_decoded(db, run_id, plan, root, frozen)
        _verify_published(db, run_id, plan, registry, frozen)
        if fail_before_commit:
            raise InjectedFailure("injected failure after publishing rows, before commit")
        db.run("UPDATE ca.run SET state = 'sealed', state_version = state_version + 1, lease_owner = NULL, "
               "lease_expires_at = NULL WHERE run_id = CAST(:r AS uuid) AND state_version = :v", r=run_id, v=version)


def _hold_lease(db, run_id, worker, version, action):
    """Inside a transaction: lock the run and require this worker's live lease at this version."""
    row = db.one("SELECT state, state_version, lease_owner, lease_expires_at > clock_timestamp() "
                 "FROM ca.run WHERE run_id = CAST(:r AS uuid) FOR UPDATE", r=run_id)
    if row is None or tuple(row[:3]) != ("sealing", version, worker):
        raise SealConflict(f"lease lost before {action}")
    if row[3] is not True:
        raise SealConflict(f"lease expired before {action}")


def _mark_failed(db, run_id, worker, version, reason):
    """Move a sealing run this worker still holds to ``failed`` with a fixed reason code."""
    if not _REASON.fullmatch(reason):
        raise ValueError("failure reasons are fixed codes")
    with db.transaction():
        _hold_lease(db, run_id, worker, version, "marking the run failed")
        db.run("UPDATE ca.run SET state = 'failed', state_version = state_version + 1, lease_owner = NULL, "
               "lease_expires_at = NULL, failure_reason = :f WHERE run_id = CAST(:r AS uuid) AND state_version = :v",
               f=reason, r=run_id, v=version)


def _insert_decoded(db, run_id, plan, root, frozen):
    for item in fi.collection_items(frozen, "evidence"):
        db.run("INSERT INTO ca.run_evidence (run_id, evidence_id, content_digest, coverage, batch_count) "
               "VALUES (CAST(:r AS uuid), :e, :d, :c, :n)", r=run_id, e=item["evidence_id"],
               d=item["content_digest"], c=item["coverage"], n=item["batch_count"])
    for gap in fi.collection_items(frozen, "gaps"):
        interval = gap["interval_ms"] or {"start": None, "end": None}
        db.run("INSERT INTO ca.run_gap (run_id, gap_id, subject, gap_type, reasons, source_id, query_id, evidence_id, "
               "interval_start_ms, interval_end_ms, mandatory, variant_count, batch_digests) VALUES (CAST(:r AS uuid), "
               ":g, :su, :t, CAST(:re AS text[]), :s, :q, :e, :a, :b, :m, :vc, CAST(:bd AS text[]))", r=run_id, g=gap["gap_id"], su=gap["subject"],
               t=gap["gap_type"], re=gap["reasons"], s=gap["source_id"], q=gap["query_id"], e=gap["evidence_id"],
               a=interval["start"], b=interval["end"], m=gap["mandatory"], vc=gap["variant_count"],
               bd=gap["batch_digests"])
    for cov in fi.collection_items(frozen, "coverage"):
        db.run("INSERT INTO ca.run_coverage (run_id, source_id, query_id, start_ms, end_ms) "
               "VALUES (CAST(:r AS uuid), :s, :q, :a, :b)", r=run_id, s=cov["source_id"], q=cov["query_id"],
               a=cov["start"], b=cov["end"])
    for acq_summary in root["acquisitions"]:
        db.run("INSERT INTO ca.run_acquisition (run_id, plan_digest, source_id, query_id, mandatory, status, "
               "batch_count, conflicting_batch_keys, observations_received, verified_ms, gap_count) VALUES "
               "(CAST(:r AS uuid), :p, :s, :q, :m, :st, :bc, :cb, :o, :vm, :gc)", r=run_id, p=plan.digest,
               s=acq_summary["source_id"], q=acq_summary["query_id"], m=acq_summary["mandatory"],
               st=acq_summary["status"], bc=acq_summary["batch_count"], cb=acq_summary["conflicting_batch_keys"],
               o=acq_summary["observations_received"], vm=acq_summary["verified_ms"], gc=acq_summary["gap_count"])


def _verify_published(db, run_id, plan, registry, frozen):
    """Re-read what this transaction wrote and verify it fully before commit (I10)."""
    stored = read_frozen_input(db, run_id)
    fi.verify_full(stored.root(), stored.pages(), plan, registry, frozen.digest)
    counts = db.one("SELECT (SELECT count(*) FROM ca.run_evidence WHERE run_id = CAST(:r AS uuid)), "
                    "(SELECT count(*) FROM ca.run_gap WHERE run_id = CAST(:r AS uuid)), "
                    "(SELECT count(*) FROM ca.run_coverage WHERE run_id = CAST(:r AS uuid)), "
                    "(SELECT count(*) FROM ca.run_acquisition WHERE run_id = CAST(:r AS uuid))", r=run_id)
    collections = frozen.root()["collections"]
    expected = (collections["evidence"]["item_count"], collections["gaps"]["item_count"],
                collections["coverage"]["item_count"], len(frozen.root()["acquisitions"]))
    if tuple(counts) != expected:
        raise fi.ManifestError(fi.E.REPLAY_MISMATCH, "decoded rows differ from the published pages")


def read_frozen_input(db, run_id):
    """Load a sealed root and its pages, ordered as the seal produced them."""
    root = db.one("SELECT root_bytes FROM ca.frozen_input WHERE run_id = CAST(:r AS uuid)", r=run_id)
    if root is None:
        return None
    pages = db.run("SELECT page_bytes FROM ca.manifest_page WHERE run_id = CAST(:r AS uuid) "
                   "ORDER BY collection, page_index", r=run_id)
    return fi.FrozenInput(bytes(root[0]), tuple(bytes(p[0]) for p in pages))
