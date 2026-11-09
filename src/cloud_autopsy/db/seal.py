"""Two-phase atomic sealing (transaction T3/T4 in docs/phase2/ca-p2-003/transactions.md).

Phase A freezes intake by moving the run from ``collecting`` to ``sealing`` with a compare-and-swap
on ``state_version`` and a lease. The pure contract seal (``frozen_input.seal``) then runs outside
any write transaction over the run's stored batches. Phase B publishes the root, every page and the
decoded rows in one transaction, re-verifies them from the database with ``verify_full`` and only
then moves the run to ``sealed``. Any failure rolls phase B back completely; the deterministic seal
makes a retry (or a lease takeover after expiry) publish byte-identical output.
"""

import uuid

from ..contracts import canonical
from ..contracts import frozen_input as fi
from .adapter import with_retry


class SealConflict(RuntimeError):
    """Another sealer holds the run, or the run is not in a sealable state."""


class InjectedFailure(RuntimeError):
    """Raised only by tests through ``fail_before_commit`` to prove rollback."""


def seal_run(sealer_db, run_id, plan, registry, worker=None, lease_seconds=300, fail_before_commit=False):
    worker = worker or f"sealer-{uuid.uuid4().hex[:12]}"
    version = with_retry(lambda: _phase_a(sealer_db, run_id, plan, worker, lease_seconds))
    records = _load_batches(sealer_db, run_id)
    frozen = fi.seal(plan, registry, records)
    with_retry(lambda: _phase_b(sealer_db, run_id, plan, registry, worker, version, frozen, fail_before_commit))
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
        row = db.one("SELECT state, state_version, lease_owner FROM ca.run WHERE run_id = CAST(:r AS uuid) "
                     "FOR UPDATE", r=run_id)
        if row is None or tuple(row) != ("sealing", version, worker):
            raise SealConflict("lease lost before publication")
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
