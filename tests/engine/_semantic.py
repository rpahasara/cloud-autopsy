"""A version-independent view of an investigation result, for preservation checks (test-only).

Result, plan and manifest digests legitimately change when a contract version is bumped (the
plan pins rule versions, batches carry the plan digest, and gap IDs digest their batches).
This view keeps everything the investigation *concluded*: the timeline, every hypothesis with
its prerequisites, citations, orderings and contradictions, the gaps by kind, and the outcome.
Evidence and hypothesis IDs do not depend on the plan, so they are kept exactly; gap IDs are
replaced by a description of the gap they name.
"""

import copy

from cloud_autopsy.contracts import canonical


def view(result):
    gaps = {g["gap_id"]: [g["subject"], g["gap_type"], sorted(g["reasons"]), g["source_id"], g["query_id"],
                          g["mandatory"], g["evidence_id"], g["interval_ms"]] for g in result["gaps"]}

    def describe(ids):
        return sorted((gaps[i] for i in ids), key=canonical.canonical_bytes)

    hypotheses = copy.deepcopy(result["hypotheses"])
    for h in hypotheses:
        h["limiting_gap_ids"] = describe(h["limiting_gap_ids"])
        for p in h["prerequisites"]:
            p["gap_ids"] = describe(p["gap_ids"])
    outcome = dict(result["outcome"], gap_ids=describe(result["outcome"]["gap_ids"]))
    gap_views = sorted(([*gaps[g["gap_id"]], sorted(g["affects_hypothesis_ids"])] for g in result["gaps"]),
                       key=canonical.canonical_bytes)
    inputs = result["inputs"]
    return {"timeline": result["timeline"], "hypotheses": hypotheses, "gaps": gap_views, "outcome": outcome,
            "mechanism_catalog": result["mechanism_catalog"], "synthesis": result["synthesis"],
            "inputs": {k: inputs[k] for k in ("manifest_status", "manifest_limitations", "window", "clock_domains",
                                              "evidence_count", "unverified_evidence_ids")}}


def view_digest(result):
    return canonical.digest(view(result))
