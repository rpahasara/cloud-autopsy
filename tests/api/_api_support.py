"""Offline API test setup: verified results built in memory from the synthetic scenario (no database)."""

import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "src", REPO / "tests" / "engine"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import _support as engine_support  # noqa: E402  (tests/engine)
from cloud_autopsy.api import grants as G  # noqa: E402
from cloud_autopsy.api.service import ApiService, BackendDown, Unavailable, Unverifiable  # noqa: E402
from cloud_autopsy.engine import result  # noqa: E402
from cloud_autopsy.synthetic import scenario_001 as scenario  # noqa: E402

RUNS = {variant: str(uuid.uuid5(uuid.NAMESPACE_URL, f"ca-api-test/{variant}")) for variant in scenario.VARIANTS}
TAMPERED = str(uuid.uuid5(uuid.NAMESPACE_URL, "ca-api-test/tampered"))
DOWN = str(uuid.uuid5(uuid.NAMESPACE_URL, "ca-api-test/down"))
UNKNOWN = str(uuid.uuid5(uuid.NAMESPACE_URL, "ca-api-test/unknown"))


def verified(variant):
    inp = engine_support.build(variant)
    doc, raw = result.build(inp)
    return SimpleNamespace(result_digest=doc["result_digest"], result=result.verify_result(raw, inp),
                           result_bytes=raw,
                           evidence={m.evidence.evidence_id: {"coverage": m.coverage, "record": m.evidence.to_record()}
                                     for m in inp.members})


class FakeBackend:
    """Stands in for ``server.database_backend``: verified results, or the loader's error types."""

    def __init__(self):
        self.results = {RUNS[v]: verified(v) for v in scenario.VARIANTS}
        self.calls, self.ready = [], True

    def load_verified(self, run_id):
        self.calls.append(run_id)
        if run_id == TAMPERED:
            raise Unverifiable("replay_mismatch")
        if run_id == DOWN:
            raise BackendDown()
        if run_id not in self.results:
            raise Unavailable()
        return self.results[run_id]

    def check_ready(self):
        if not self.ready:
            raise BackendDown()


def provision(grant_runs):
    """Issue tokens and write the grants file into a fresh private directory outside the repository."""
    directory = Path(tempfile.mkdtemp(prefix="ca-api-grants-"))
    record, tokens = G.issue(grant_runs)
    path = directory / "grants.json"
    G.write_private(path, G.json.dumps(record).encode("utf-8"))
    return path, tokens


def service(grant_runs=None):
    grant_runs = grant_runs or {"all": list(RUNS.values()) + [TAMPERED, DOWN, UNKNOWN],
                                "one": [RUNS["config-cause"]]}
    path, tokens = provision(grant_runs)
    backend = FakeBackend()
    return ApiService(G.load(path), backend.load_verified, backend.check_ready), tokens, backend
