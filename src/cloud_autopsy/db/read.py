"""Engine read path: load one sealed run as ``ca_engine``, through sealed-only views.

CA-P2-005a added the sealed run; CA-P2-006a adds its frozen clock declaration.
Everything is read in one ``REPEATABLE READ READ ONLY`` transaction, so the root, pages,
configuration, clock declaration and evidence come from one snapshot. Nothing here is trusted:
the engine re-decodes the plan and registry, verifies the manifest with ``verify_full`` against
the manifest digest recorded for the run, re-derives every evidence record, and re-checks the
clock declaration bytes against their recorded digest and the registry.
"""

from dataclasses import dataclass

from ..contracts import canonical
from ..contracts import frozen_input as fi
from ..contracts.plan import RunPlan
from ..contracts.sources import SourceRegistry


class SealedRunUnavailable(RuntimeError):
    """The run does not exist, is not sealed, or is not visible to this role."""


@dataclass(frozen=True)
class SealedRun:
    run_id: str
    investigation_id: str
    manifest_digest: str
    plan: RunPlan
    registry: SourceRegistry
    frozen: fi.FrozenInput
    evidence_records: tuple          # canonical record bytes, ordered by evidence_id
    clock_declaration_digest: object  # str, or None when the run has no declaration
    clock_declaration_bytes: object   # bytes, or None


def load_sealed_run(engine_db, run_id):
    with engine_db.transaction(isolation="REPEATABLE READ", read_only=True):
        return read_sealed_run(engine_db, run_id)


def read_sealed_run(engine_db, run_id):
    """Read a sealed run inside the caller's (read-only, repeatable-read) transaction."""
    head = engine_db.one("SELECT manifest_digest, CAST(investigation_id AS text) FROM ca.sealed_run "
                         "WHERE run_id = CAST(:r AS uuid)", r=run_id)
    if head is None:
        raise SealedRunUnavailable("run is not sealed or not visible")
    config = engine_db.one("SELECT plan_bytes, registry_bytes FROM ca.sealed_run_configuration "
                           "WHERE run_id = CAST(:r AS uuid)", r=run_id)
    root = engine_db.one("SELECT root_bytes FROM ca.sealed_manifest_root WHERE run_id = CAST(:r AS uuid)",
                         r=run_id)
    pages = engine_db.run("SELECT page_bytes FROM ca.sealed_manifest_page WHERE run_id = CAST(:r AS uuid) "
                          "ORDER BY collection COLLATE \"C\", page_index", r=run_id)
    records = engine_db.run("SELECT record_bytes FROM ca.sealed_evidence_record WHERE run_id = CAST(:r AS uuid) "
                            "ORDER BY evidence_id COLLATE \"C\"", r=run_id)
    clocks = engine_db.one("SELECT declaration_digest, declaration_bytes FROM ca.sealed_clock_declaration "
                           "WHERE run_id = CAST(:r AS uuid)", r=run_id)
    registry = SourceRegistry.from_record(canonical.loads(bytes(config[1])))
    plan = RunPlan.from_record(canonical.loads(bytes(config[0])), registry)
    frozen = fi.FrozenInput(bytes(root[0]), tuple(bytes(p[0]) for p in pages))
    return SealedRun(run_id, head[1], head[0], plan, registry, frozen, tuple(bytes(r[0]) for r in records),
                     None if clocks is None else clocks[0], None if clocks is None else bytes(clocks[1]))
