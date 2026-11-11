"""The investigation engine on an in-memory seal: no database, no network (CA-P2-004a offline mode).

A result produced here is checked by the engine (citations and byte-identical replay of the same
input) but it is **not** database-verified: nothing was persisted, sealed by ``ca_sealer`` or read
back through the verify-on-read loader. Callers must label it as such.
"""

from ..contracts import acquisition as acq
from ..contracts import frozen_input as fi
from ..engine import inputs, result


def offline_from_records(plan, registry, records, clock_records):
    """The engine on an in-memory seal of ``records``: (verified result document, result bytes). No database."""
    records = list(records)
    frozen = fi.seal(plan, registry, records)
    members = {(m["evidence_id"], m["content_digest"]) for m in fi.collection_items(frozen, "evidence")}
    evidence = {}
    for record in records:
        for item in acq.decode_batch(record, plan, registry).evidence:
            if (item.evidence_id, item.content_digest) in members:
                evidence[item.evidence_id] = item.to_record()
    inp = inputs.build_input(frozen, plan, registry, list(evidence.values()), clock_records)
    _, result_bytes = result.build(inp)
    return result.verify_result(result_bytes, inp), result_bytes
