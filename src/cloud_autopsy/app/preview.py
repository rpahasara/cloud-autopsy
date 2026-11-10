"""Labelled synthetic preview of the read-only dashboard (CA-P2-006c). No database.

For frontend development where PostgreSQL is unavailable. It serves the same dashboard and the
same ``ApiService`` (routes, limits, bearer token, explicit per-run grants, concurrency gates)
on 127.0.0.1, but the results are computed in memory by the engine from the six synthetic
fixture variants. They are NOT read from or verified against a sealed database run, so every
``/v1`` envelope says ``"verified": false`` and ``"data_source": "synthetic-preview"``, and the
dashboard labels them as a preview. Real verified results come only from ``api.server``.

  python -I tools/dashboard_preview.py [--port 8766]

A disposable token is generated per start and written, with the grants file (hashes only), to a
new private directory under the system temporary directory, outside any Git working tree. The
token is never printed; the path of its file is. The directory is removed on exit.
"""

import argparse
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

from ..api import grants as G
from ..api import ui
from ..api.service import ApiService, Unavailable
from ..api.transport import LOOPBACK, LoopbackServer
from ..contracts import acquisition as acq
from ..contracts import frozen_input as fi
from ..engine import inputs, result
from ..synthetic import scenario_001 as scenario

RUNS = {variant: str(uuid.uuid5(uuid.NAMESPACE_URL, f"ca-dashboard-preview/{variant}"))
        for variant in scenario.VARIANTS}


def _computed(variant):
    """The engine's result for a fixture variant, built and replay-checked in memory."""
    plan, registry = scenario.plan(variant), scenario.registry()
    records = scenario.batches(variant)
    frozen = fi.seal(plan, registry, records)
    members = {(m["evidence_id"], m["content_digest"]) for m in fi.collection_items(frozen, "evidence")}
    evidence = {}
    for record in records:
        for item in acq.decode_batch(record, plan, registry).evidence:
            if (item.evidence_id, item.content_digest) in members:
                evidence[item.evidence_id] = item.to_record()
    inp = inputs.build_input(frozen, plan, registry, [evidence[k] for k in sorted(evidence)],
                             scenario.clock_domain_records(variant))
    doc, raw = result.build(inp)
    return SimpleNamespace(result_digest=doc["result_digest"], result=result.verify_result(raw, inp),
                           evidence={m.evidence.evidence_id: {"coverage": m.coverage,
                                                              "record": m.evidence.to_record()}
                                     for m in inp.members})


def backend():
    results = {RUNS[v]: _computed(v) for v in scenario.VARIANTS}

    def load(run_id):
        if run_id not in results:
            raise Unavailable()
        return results[run_id]

    def ready():
        return None

    return load, ready


def start(port=0, quiet=False, extra_assets=None):
    """Start the preview server. Returns (server, token, secret_dir); the caller removes secret_dir."""
    secret_dir = Path(tempfile.mkdtemp(prefix="ca-dashboard-preview-"))
    record, tokens = G.issue({"preview": list(RUNS.values())})
    grants_path = secret_dir / "grants.json"
    G.write_private(grants_path, json.dumps(record).encode("utf-8"))
    G.write_private(secret_dir / "preview.token", tokens["preview"].encode("ascii"))
    load, ready = backend()
    assets = ui.load_assets()
    assets.update(extra_assets or {})
    service = ApiService(G.load(grants_path), load, ready, ui=assets, preview=True)
    return LoopbackServer(service, port, quiet=quiet), tokens["preview"], secret_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic dashboard preview (127.0.0.1 only, not verified)")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    server, _token, secret_dir = start(args.port)
    out = sys.stderr
    out.write(f"SYNTHETIC PREVIEW (not database-verified): http://{LOOPBACK}:{server.port}/\n")
    out.write(f"token file (private, removed on exit): {secret_dir / 'preview.token'}\n")
    out.write("run IDs:\n")
    for variant, run_id in RUNS.items():
        out.write(f"  {run_id}  {variant}\n")
    out.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        shutil.rmtree(secret_dir, ignore_errors=True)
    return 0
