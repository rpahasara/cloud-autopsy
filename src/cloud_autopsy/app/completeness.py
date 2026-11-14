"""Completeness classification for collector recordings 0.6 (CA-P2-004g, M12a-c). Pure and deterministic.

Inside one proven list + watch segment, a delivered change that the converter does not turn into evidence
counts against completeness (``changes_withheld``), as in CA-P2-004f -- except in the narrowly defined cases
below. Every classified change is counted with its provenance (UID, resourceVersion, class) in the report.
Nothing is filled in, and no change is dropped silently.

**M12a: Deployment updates that are not rollouts.** Within one segment (continuous by construction: a relist
starts a new one), each Deployment version is compared with the previous delivered version of the same UID
(the listed state or an earlier event):
- ``status_only``: the same generation, the same rollout revision, and the same digest of the spec without its
  pod template, all present. The desired state did not change.
- ``accounted_by_rollout``: the generation rose, the revision and the non-template spec digest did not change,
  and a later event of the same UID in the same segment and proof, at that same generation, carries a higher
  revision and converted into a rollout. The spec change *was* that rollout's template change.
- anything else -- a missing generation or digest, a changed non-template spec (a scale or a strategy change),
  no later rollout at that generation -- stays withheld.

**M12b: Pods first seen before they can be represented.** A Pod observation that cannot be converted because
its node or container statuses are not there yet is ``superseded`` only when all hold:
- it is ``Pending``; its spec has no init containers; no container or init container has started;
- a later observation of the same UID, in the same segment and within the same proof, converts;
- no observation of that UID in between was a deletion, or failed for another reason.
Otherwise it stays withheld.

**M12c: the listed state.** List items that convert, or whose only note is that a Deployment has no previous
revision (no rollout to describe), are the segment's starting state. Unconverted list items are withheld
unless M12b supersedes them.
"""

PENDING_REASONS = ("node_missing", "container_statuses_missing")
BENIGN_LIST_NOTES = ("no_previous_revision", "already_observed")


def _int(value):
    return value if type(value) is int else None


def deployment_facts(obj):
    meta = obj.get("metadata") or {}
    revision = (meta.get("annotations") or {}).get("deployment.kubernetes.io/revision")
    return {"generation": _int(meta.get("generation")), "revision": revision if isinstance(revision, str) else None,
            "spec_digest": obj.get("specDigest") if isinstance(obj.get("specDigest"), str) else None}


def _quiet(obj):
    """A Pod observation in which nothing can have run: Pending, no init containers, nothing started."""
    spec, status = obj.get("spec") or {}, obj.get("status") or {}
    if status.get("phase") != "Pending" or spec.get("initContainers"):
        return False
    for key in ("containerStatuses", "initContainerStatuses"):
        for s in status.get(key) or []:
            if not isinstance(s, dict) or s.get("started") is not False:
                return False
    return True


def classify(resource, steps):
    """``steps``: the segment's observations in delivery order, each a dict with ``uid``, ``rv``, ``event``
    (``LISTED`` / ``ADDED`` / ``MODIFIED`` / ``DELETED``), ``object`` (projected or None), ``reason`` (None when
    converted, else the unconverted code) and ``in_proof``. Returns {index: class} for the unconverted steps
    that are not withheld; every other unconverted step stays withheld."""
    classes = {}
    if resource == "deployments":
        previous = {}
        for i, step in enumerate(steps):
            obj, uid = step["object"], step["uid"]
            if obj is None or step["event"] == "DELETED":
                previous.pop(uid, None)
                continue
            facts = deployment_facts(obj)
            before = previous.get(uid)
            previous[uid] = facts
            if step["reason"] is None or not step["in_proof"]:
                continue
            if step["event"] == "LISTED" and step["reason"] in BENIGN_LIST_NOTES:
                classes[i] = "listed_state"
                continue
            if step["reason"] != "no_new_revision" or before is None or None in facts.values() \
                    or None in before.values():
                continue
            same_spec = facts["spec_digest"] == before["spec_digest"] and facts["revision"] == before["revision"]
            if same_spec and facts["generation"] == before["generation"]:
                classes[i] = "status_only"
            elif same_spec and facts["generation"] > before["generation"]:
                later = any(s["uid"] == uid and s["in_proof"] and s["reason"] is None and s["object"] is not None
                            and deployment_facts(s["object"])["generation"] == facts["generation"]
                            and _revision_int(deployment_facts(s["object"])["revision"]) > _revision_int(facts["revision"])
                            for s in steps[i + 1:])
                if later:
                    classes[i] = "accounted_by_rollout"
    elif resource == "pods":
        for i, step in enumerate(steps):
            if step["reason"] not in PENDING_REASONS or not step["in_proof"] or step["object"] is None \
                    or step["event"] == "DELETED" or not _quiet(step["object"]):
                continue
            for later in steps[i + 1:]:
                if later["uid"] != step["uid"]:
                    continue
                if later["event"] == "DELETED" or not later["in_proof"]:
                    break
                if later["reason"] is None:
                    classes[i] = "superseded"
                    break
                if later["reason"] not in PENDING_REASONS or later["object"] is None or not _quiet(later["object"]):
                    break
    else:
        for i, step in enumerate(steps):
            if step["event"] == "LISTED" and step["reason"] in BENIGN_LIST_NOTES and step["in_proof"]:
                classes[i] = "listed_state"
    return classes


def _revision_int(text):
    return int(text) if isinstance(text, str) and text.isdigit() else -1
