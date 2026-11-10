"""Engine read path (CA-P2-005a): load one sealed run as ``ca_engine``, through sealed-only views.

Everything is read in one ``REPEATABLE READ READ ONLY`` transaction, so the root, pages,
configuration and evidence come from one snapshot. Nothing here is trusted: the engine
re-decodes the plan and registry, verifies the manifest with ``verify_full`` against the
manifest digest recorded for the run, and re-derives every evidence record.
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
    manifest_digest: str
    plan: RunPlan
    registry: SourceRegistry
    frozen: fi.FrozenInput
    evidence_records: tuple  # canonical record bytes, ordered by evidence_id


def load_sealed_run(engine_db, run_id):
    with engine_db.transaction(isolation="REPEATABLE READ", read_only=True):
        head = engine_db.one("SELECT manifest_digest FROM ca.sealed_run WHERE run_id = CAST(:r AS uuid)", r=run_id)
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
    registry = SourceRegistry.from_record(canonical.loads(bytes(config[1])))
    plan = RunPlan.from_record(canonical.loads(bytes(config[0])), registry)
    frozen = fi.FrozenInput(bytes(root[0]), tuple(bytes(p[0]) for p in pages))
    return SealedRun(run_id, head[0], plan, registry, frozen, tuple(bytes(r[0]) for r in records))
