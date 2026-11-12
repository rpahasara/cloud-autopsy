"""Create investigations from evidence bundles (CA-P2-004a).

Two modes, one engine:

- ``investigate_offline(bundle)`` runs the engine on an in-memory seal of the bundle. Nothing is
  persisted. The result is **engine-checked but not database-verified** and is labelled so.
- ``create_in_database(roles, bundle)`` first runs the offline investigation; a bundle the engine
  cannot process never reaches the database. It then persists, freezes clocks, ingests, seals,
  investigates and stores the result once, each step as its least-privileged role. Finally it
  reads the result back through the verify-on-read loader, and requires the stored bytes to
  equal the offline bytes. Only then does it return a ``DatabaseInvestigation``.

  Any failure raises ``CreationFailed`` with the stage and, once created, the run ID. A run
  that fails part-way is never presented as successful:
  - before sealing, it stays ``collecting``;
  - a failed seal leaves it unsealed (see R4);
  - without a stored, verified result the API answers ``404 run_not_found``; a failure after
    storing (``verify_on_read``, ``compare_offline``) leaves a stored result that is still
    verified on every read, but the creation is reported as failed;
  - no grant is ever issued for it.

``issue_private_grant`` accepts only ``DatabaseInvestigation`` objects, so a browser token is
never created for an offline-only, unverified or failed run.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from ..api import grants as G
from . import offline
from .private_dir import make_private_dir

OFFLINE_LABEL = "offline: engine-checked, not database-verified"
DATABASE_LABEL = "database-verified: stored once and re-verified on read (byte-identical replay)"


@dataclass(frozen=True)
class OfflineInvestigation:
    bundle_id: str
    manifest_sha256: str
    result: dict
    result_bytes: bytes
    verified = False
    label = OFFLINE_LABEL

    @property
    def result_digest(self):
        return self.result["result_digest"]


@dataclass(frozen=True)
class DatabaseInvestigation:
    bundle_id: str
    manifest_sha256: str
    run_id: str
    frozen_input_digest: str
    result_digest: str
    result_bytes: bytes
    verified = True
    label = DATABASE_LABEL


class CreationFailed(RuntimeError):
    """Creation stopped at ``stage``. ``run_id`` is set once the run exists. ``reason`` is an
    error class name or a fixed code, never input content."""

    def __init__(self, stage, run_id, reason):
        self.stage, self.run_id, self.reason = stage, run_id, reason
        where = f" (run {run_id} left unfinished; it is not served and has no grant)" if run_id else ""
        super().__init__(f"creation failed at {stage}: {reason}{where}")


def investigate_offline(bundle):
    result, result_bytes = offline.offline_from_records(bundle.plan, bundle.registry, bundle.batches,
                                                        list(bundle.clock_records))
    return OfflineInvestigation(bundle.bundle_id, bundle.manifest_sha256, result, result_bytes)


def create_in_database(roles, bundle, verify_db=None):
    """``roles``: connections for ca_planner, ca_ingest, ca_sealer, ca_engine and ca_result_writer.
    ``verify_db``: an optional separate ``ca_engine`` connection for the verify-on-read check."""
    try:
        from . import pipeline  # needs the database driver; the offline mode does not
        from ..db import results, seal
    except ImportError as exc:
        raise CreationFailed("start", None, type(exc).__name__) from exc

    try:
        expected = investigate_offline(bundle)
    except Exception as exc:  # noqa: BLE001 -- reported with its class only
        raise CreationFailed("offline_validation", None, type(exc).__name__) from exc
    progress = {}
    try:
        run_id, frozen_digest, _ = pipeline.persist_records(
            roles, bundle.plan, bundle.registry, list(bundle.clock_records), bundle.batches,
            bundle.scenario_id, progress)
        progress["stage"] = "record_result"
        stored, _ = pipeline.record_result(roles["ca_engine"], roles["ca_result_writer"], run_id)
        if stored != results.STORED:
            raise CreationFailed("record_result", run_id, "result_not_newly_stored")
        progress["stage"] = "verify_on_read"
        verified = pipeline.replay_stored(verify_db or roles["ca_engine"], run_id)
    except CreationFailed:
        raise
    except seal.SealFailed as exc:  # the run is now 'failed' with this fixed reason (CA-P2-004b)
        raise CreationFailed("seal", progress.get("run_id"), exc.reason) from exc
    except Exception as exc:  # noqa: BLE001 -- the stage and class are reported; nothing is marked successful
        raise CreationFailed(progress.get("stage", "start"), progress.get("run_id"), type(exc).__name__) from exc
    if verified.result_bytes != expected.result_bytes or verified.result_digest != expected.result_digest:
        raise CreationFailed("compare_offline", run_id, "database_result_differs_from_offline")
    return DatabaseInvestigation(bundle.bundle_id, bundle.manifest_sha256, run_id, frozen_digest,
                                 verified.result_digest, verified.result_bytes)


@dataclass(frozen=True)
class GrantFiles:
    directory: Path
    grants_path: Path
    token_path: Path


def issue_private_grant(investigations, directory=None, name="bundle-runs", failed=()):
    """A bearer token granting exactly these database-verified runs, written to a new private
    directory outside Git (``grants.json`` holds only the token hash; ``token`` holds the token).

    ``failed`` (CA-P2-004b): ``CreationFailed`` errors whose run exists. Their runs are granted
    **status only** (grants contract 0.2): the token can read their lifecycle state and fixed
    failure reason, never a result or evidence."""
    investigations, failed = list(investigations), list(failed)
    if not all(isinstance(i, DatabaseInvestigation) for i in investigations):
        raise TypeError("result grants are issued only for database-verified investigations")
    if not all(isinstance(f, CreationFailed) and f.run_id for f in failed):
        raise TypeError("status-only grants are issued only for failed creations whose run exists")
    if not investigations and not failed:
        raise TypeError("nothing to grant")
    runs = {name: [i.run_id for i in investigations]}
    record, tokens = G.issue(runs, {name: [f.run_id for f in failed]} if failed else None)
    target = make_private_dir(directory, prefix="ca-grant-")
    grants_path, token_path = target / "grants.json", target / "token"
    G.write_private(grants_path, json.dumps(record).encode("utf-8"))
    G.write_private(token_path, tokens[name].encode("ascii"))
    G.load(grants_path)  # the API must accept exactly what was written
    return GrantFiles(target, grants_path, token_path)
