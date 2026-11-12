"""CA-P2-004f offline: recording 0.4 conversion from hand-built recordings, with exact expected values.

The recording holds facts only; every outcome, coverage interval and basis is derived. Forged facts
are refused or downgraded, never trusted: a probe nothing reached, a resume from another
resourceVersion, regressing or invalid resourceVersions, causality that does not hold, unknown
fields, extra files, and a bundle edited after conversion.
"""

import copy
import hashlib
import json
import unittest
from pathlib import Path

import _fake_api as F

from cloud_autopsy.app import k8s_recording as K
from cloud_autopsy.app import k8s_watch_recording as W
from cloud_autopsy.contracts import acquisition as acq
from cloud_autopsy.contracts import canonical
from cloud_autopsy.contracts import evidence as ev
from cloud_autopsy.contracts import timeinterval as ti

ANCHOR = "2026-11-12T10:00:00.000000000Z"
ANCHOR_MS = 1_794_477_600_000  # 2026-11-12T10:00:00Z
MS = 1_000_000


def pod(name, rv, restarts=0):
    return {"metadata": {"name": name, "namespace": "ca-demo", "uid": f"uid-{name}", "resourceVersion": rv,
                         "creationTimestamp": "2026-11-12T09:00:00Z",
                         "ownerReferences": [{"controller": True, "kind": "ReplicaSet", "name": "api-7f", "uid": "uid-rs"}]},
            "spec": {"containers": [{"name": "api", "volumeMounts": []}], "volumes": [], "nodeName": "node-1"},
            "status": {"containerStatuses": [{"restartCount": restarts}]}}


def listing(seq, segment=1, rv="1000", items=None, sent=1 * MS, first=5 * MS, last=6 * MS):
    return {"seq": seq, "segment": segment, "type": "list", "sent_ns": sent, "first_page_ns": first,
            "last_page_ns": last, "outcome": "consistent", "http_status": 200, "error": None,
            "collection_resource_version": rv, "pages": 1, "restarts": 0,
            "items": items if items is not None else [pod("api-1", "990")], "withheld": 0}


def opened(seq, from_rv, segment=1, sent=7 * MS):
    return {"seq": seq, "segment": segment, "type": "watch_open", "sent_ns": sent, "from_resource_version": from_rv,
            "http_status": 200, "error": None}


def event(seq, rv, received, obj=None, kind="MODIFIED", segment=1, withheld=None):
    obj = obj if obj is not None or withheld else pod("api-1", rv, restarts=int(rv) % 7)
    return {"seq": seq, "segment": segment, "type": "event", "received_ns": received, "event": kind,
            "resource_version": rv, "object": obj, "withheld": withheld}


def bookmark(seq, rv, received, segment=1):
    return {"seq": seq, "segment": segment, "type": "bookmark", "received_ns": received, "resource_version": rv}


def probe(seq, rv, sent, segment=1, status=200):
    return {"seq": seq, "segment": segment, "type": "probe", "sent_ns": sent, "received_ns": sent + 2 * MS,
            "resource_version": rv if status == 200 else None, "http_status": status, "error": None}


def end(seq, at, code="session_end", segment=1):
    return {"seq": seq, "segment": segment, "type": "end", "at_ns": at, "code": code, "http_status": None}


def quiet(resource):
    """A stream for a resource with no changes and no proof: list, open, end."""
    return [listing(1, items=[]), opened(2, "1000"), end(3, 900 * MS)]


def write(directory, pods, step=False, others=None, extra_file=None):
    root = Path(directory)
    (root / "streams").mkdir(parents=True)
    streams = []
    for resource in ("deployments", "events", "pods", "replicasets"):
        entries = pods if resource == "pods" else (others or {}).get(resource) or quiet(resource)
        data = canonical.canonical_bytes({"resource": resource, "part": 1, "entries": entries})
        (root / "streams" / f"{resource}-0001.json").write_bytes(data)
        streams.append({"resource": resource, "parts": [{"file": f"streams/{resource}-0001.json",
                                                         "sha256": hashlib.sha256(data).hexdigest()}]})
    manifest = {"contract_version": K.RECORDING_VERSION_V4, "recording_id": "ca-watch-rec",
                "data_classification": "synthetic", "provenance": "collector", "source_id": "k8s-api",
                "cluster_id": "ca-kind-synthetic", "namespace": "ca-demo", "session_id": "ca-watch-rec",
                "rv_comparison": "k8s-1.37-decimal",
                "clocks": {"collector": {"clock_domain_id": "ca-collector", "anchor_wall": ANCHOR,
                                         "max_drift_ms": 300 if step else 3, "step_detected": step},
                           "api_server": {"clock_domain_id": "k8s-apiserver"}},
                "streams": streams}
    (root / K.MANIFEST).write_text(json.dumps(manifest))
    if extra_file:
        (root / extra_file).write_text("x")
    return root


def healthy():
    """List at 1000 (first page received at 5 ms), events at 1002 and 1005, probes at 1003 (sent 100 ms)
    and 1006 (sent 400 ms), bookmark 1006 at 450 ms proves the second probe."""
    return [listing(1), opened(2, "1000"), event(3, "1002", 50 * MS), probe(4, "1003", 100 * MS),
            event(5, "1005", 300 * MS), probe(6, "1006", 400 * MS), bookmark(7, "1006", 450 * MS),
            event(8, "1008", 500 * MS), end(9, 600 * MS)]


class Derivation(unittest.TestCase):
    def convert(self, entries, **kw):
        root = write(F.tempdir(self, "ca-watch-rec-") / "rec", entries, **kw)
        return root, K.convert(root, ev.KIND_REGISTRY_VERSION_V3)

    def pods_batches(self, conversion):
        return [b for b in conversion.batch_records if b["query_id"] == "k8s.pods"]

    def test_coverage_is_exactly_first_page_receipt_to_the_latest_proven_probe(self):
        _, conversion = self.convert(healthy())
        batches = self.pods_batches(conversion)
        self.assertEqual([(b["outcome"], b["reason"]) for b in batches],
                         [(acq.PARTIAL, "continuity_lost"), (acq.COMPLETE, None), (acq.PARTIAL, "continuity_unproven")])
        complete = batches[1]
        self.assertEqual(complete["coverage"], {"start": K._ms_text(ANCHOR_MS + 5), "end": K._ms_text(ANCHOR_MS + 400)})
        basis = complete["coverage_basis"]
        self.assertEqual((basis["start_anchor"]["resource_version"], basis["end_anchor"]["resource_version"],
                          basis["end_anchor"]["proven_by_resource_version"]), ("1000", "1006", "1006"))
        self.assertEqual(complete["cursor"]["after"], "rv:1006")
        self.assertEqual([o["source_version"] for o in complete["observations"]], ["1002", "1005"])
        self.assertEqual([o["source_version"] for o in batches[2]["observations"]], ["1008"])
        pods = next(a for a in conversion.report["acquisitions"] if a["query_id"] == "k8s.pods")
        self.assertEqual(pods["verified_coverage_ms"], 395)

    def test_observed_brackets_are_exact(self):
        _, conversion = self.convert(healthy())
        times = {o["source_version"]: next(t for t in o["times"] if t["timestamp_kind"] == "observed")
                 for b in self.pods_batches(conversion) for o in b["observations"] if o["source_version"] != "990"}
        # 1002: after the list (sent 1 ms), received 50 ms; 1005: after probe 1003 (sent 100 ms), received 300 ms;
        # 1008: after probe 1006 (sent 400 ms), received 500 ms.
        expected = {"1002": (1 * MS, 50 * MS), "1005": (100 * MS, 300 * MS), "1008": (400 * MS, 500 * MS)}
        for version, (lower, upper) in expected.items():
            with self.subTest(version=version):
                stamp = times[version]
                self.assertEqual(stamp["raw"], f"2026-11-12T10:00:00.{lower:09d}Z")
                self.assertEqual(stamp["declared_precision_ns"], upper - lower)
                self.assertEqual(stamp["clock_domain_id"], "ca-collector")
                parsed = ti.source_timestamp(stamp["raw"], timestamp_kind="observed", clock_domain_id="ca-collector",
                                             declared_precision_ns=stamp["declared_precision_ns"])
                self.assertEqual((parsed.local_lower_ms, parsed.local_upper_ms),
                                 (ANCHOR_MS + lower // MS, ANCHOR_MS + -(-upper // MS) - 1))

    def test_list_state_has_no_observed_time_and_keeps_its_label(self):
        _, conversion = self.convert(healthy())
        baseline = self.pods_batches(conversion)[0]["observations"]
        self.assertEqual([t["timestamp_kind"] for t in baseline[0]["times"]], ["event"])

    def test_a_probe_that_nothing_reached_proves_nothing(self):
        entries = [listing(1), opened(2, "1000"), event(3, "1002", 50 * MS), probe(4, "1003", 100 * MS),
                   bookmark(5, "1002", 150 * MS), end(6, 600 * MS)]
        _, conversion = self.convert(entries)
        self.assertNotIn(acq.COMPLETE, {b["outcome"] for b in self.pods_batches(conversion)})
        self.assertEqual(conversion.report["verified_coverage_ms"], 0)

    def test_a_withheld_change_inside_the_proof_is_not_complete(self):
        entries = healthy()
        entries[2] = event(3, "1002", 50 * MS, obj=None, withheld="secret_event")
        _, conversion = self.convert(entries)
        reasons = [(b["outcome"], b["reason"]) for b in self.pods_batches(conversion)]
        self.assertIn((acq.PARTIAL, "changes_withheld"), reasons)
        self.assertNotIn(acq.COMPLETE, {o for o, _ in reasons})
        self.assertEqual(conversion.report["verified_coverage_ms"], 0)

    def test_empty_only_when_no_change_at_all_arrived(self):
        entries = [listing(1), opened(2, "1000"), probe(3, "1003", 100 * MS), bookmark(4, "1003", 150 * MS),
                   end(5, 600 * MS)]
        _, conversion = self.convert(entries)
        self.assertIn(acq.EMPTY, {b["outcome"] for b in self.pods_batches(conversion)})
        entries.insert(2, event(3, "1001", 50 * MS, obj=None, withheld="secret_event"))
        for n, e in enumerate(entries, 1):
            e["seq"] = n
        _, conversion = self.convert(entries)
        self.assertNotIn(acq.EMPTY, {b["outcome"] for b in self.pods_batches(conversion)})

    def test_a_deletion_is_evidence_with_its_observed_time(self):
        entries = healthy()
        entries[4] = event(5, "1005", 300 * MS, obj=pod("api-1", "1005"), kind="DELETED")
        _, conversion = self.convert(entries)
        deleted = [o for b in self.pods_batches(conversion) for o in b["observations"]
                   if o["observation_kind"] == "k8s_object_deleted"]
        self.assertEqual(len(deleted), 1)
        self.assertEqual({t["timestamp_kind"] for t in deleted[0]["times"]}, {"event", "observed"})

    def test_a_relist_leaves_a_gap(self):
        entries = [listing(1), opened(2, "1000"), probe(3, "1003", 100 * MS), bookmark(4, "1003", 150 * MS),
                   end(5, 200 * MS, "expired"), listing(6, segment=2, rv="1050", sent=300 * MS, first=310 * MS,
                                                        last=311 * MS),
                   opened(7, "1050", segment=2, sent=312 * MS), probe(8, "1060", 400 * MS, segment=2),
                   bookmark(9, "1060", 450 * MS, segment=2), end(10, 600 * MS, segment=2)]
        _, conversion = self.convert(entries)
        covered = [(b["coverage"]["start"], b["coverage"]["end"]) for b in self.pods_batches(conversion)
                   if b["outcome"] in (acq.COMPLETE, acq.EMPTY)]
        self.assertEqual(covered, [(K._ms_text(ANCHOR_MS + 5), K._ms_text(ANCHOR_MS + 100)),
                                   (K._ms_text(ANCHOR_MS + 310), K._ms_text(ANCHOR_MS + 400))])

    def test_a_long_resource_version_needs_no_integer_width(self):
        big = "1" + "0" * 30
        entries = [listing(1, rv=big), opened(2, big), probe(3, big[:-1] + "3", 100 * MS),
                   bookmark(4, big[:-1] + "3", 150 * MS), end(5, 600 * MS)]
        _, conversion = self.convert(entries)
        self.assertIn(acq.EMPTY, {b["outcome"] for b in self.pods_batches(conversion)})

    def test_a_detected_clock_step_is_declared(self):
        _, conversion = self.convert(healthy(), step=True)
        collector = next(c for c in conversion.clock_records if c["clock_domain_id"] == "ca-collector")
        self.assertEqual(collector["continuity"], ti.STEP_DECLARED)
        _, conversion = self.convert(healthy())
        collector = next(c for c in conversion.clock_records if c["clock_domain_id"] == "ca-collector")
        self.assertEqual((collector["status"], collector["continuity"]), (ti.UNKNOWN, ti.CONTINUOUS))

    def test_kinds_0_3_and_recording_0_4_go_together(self):
        root, _ = self.convert(healthy())
        with self.assertRaises(K.RecordingError) as ctx:
            K.convert(root, ev.KIND_REGISTRY_VERSION_V2)
        self.assertEqual(ctx.exception.code, "recording_kinds_unsupported")


class Forgery(unittest.TestCase):
    def refused(self, entries, code="recording_stream_invalid", **kw):
        root = write(F.tempdir(self, "ca-watch-forged-") / "rec", entries, **kw)
        with self.assertRaises(K.RecordingError) as ctx:
            K.convert(root, ev.KIND_REGISTRY_VERSION_V3)
        self.assertEqual(ctx.exception.code, code)

    def mutated(self, n, **changes):
        entries = healthy()
        entries[n] = {**entries[n], **changes}
        return entries

    def test_a_resume_from_another_resource_version_is_refused(self):
        self.refused(self.mutated(1, from_resource_version="999"))

    def test_regressing_or_repeated_resource_versions_are_refused(self):
        self.refused(self.mutated(4, resource_version="1001", object=pod("api-1", "1001")))
        self.refused(self.mutated(4, resource_version="1002", object=pod("api-1", "1002")))

    def test_invalid_resource_versions_are_refused(self):
        for value in ("01005", "1005a", "1" * 129):
            with self.subTest(value=value[:8]):
                self.refused(self.mutated(4, resource_version=value, object=pod("api-1", value)))

    def test_an_object_that_disagrees_with_its_entry_is_refused(self):
        self.refused(self.mutated(4, object=pod("api-1", "1004")))

    def test_an_object_outside_the_namespace_is_refused(self):
        other = pod("api-1", "1005")
        other["metadata"]["namespace"] = "ca-other"
        self.refused(self.mutated(4, object=other), "recording_namespace_mismatch")

    def test_causality_must_hold(self):
        self.refused(self.mutated(4, received_ns=20 * MS))      # received before an earlier entry
        self.refused(self.mutated(3, received_ns=99 * MS))      # a probe received before it was sent

    def test_unknown_fields_and_entry_types_are_refused(self):
        entries = healthy()
        entries[2]["coverage"] = {"start": "x"}
        self.refused(entries)
        entries = healthy()
        entries[2]["type"] = "claim"
        self.refused(entries)

    def test_a_missing_end_is_refused(self):
        self.refused(healthy()[:-1])

    def test_extra_files_are_refused(self):
        self.refused(healthy(), "recording_unexpected_entry", extra_file="notes.txt")

    def test_an_edited_bundle_fails_the_replay_check(self):
        tmp = F.tempdir(self, "ca-watch-replay-")
        root = write(tmp / "rec", healthy())
        conversion = K.convert(root, ev.KIND_REGISTRY_VERSION_V3)
        conversion.write_bundle(tmp / "bundle")
        W.verify_bundle(root, tmp / "bundle")
        target = next(p for p in sorted((tmp / "bundle" / "batches").iterdir())
                      if b"continuity_unproven" in p.read_bytes())
        target.write_bytes(target.read_bytes().replace(b"continuity_unproven", b"continuity_lost"))
        with self.assertRaises(K.RecordingError) as ctx:
            W.verify_bundle(root, tmp / "bundle")
        self.assertEqual(ctx.exception.code, "replay_mismatch")

    def test_deterministic_replay(self):
        tmp = F.tempdir(self, "ca-watch-det-")
        root = write(tmp / "rec", healthy())
        a = K.convert(root, ev.KIND_REGISTRY_VERSION_V3)
        b = K.convert(root, ev.KIND_REGISTRY_VERSION_V3)
        self.assertEqual([canonical.canonical_bytes(r) for r in a.batch_records],
                         [canonical.canonical_bytes(r) for r in b.batch_records])
        self.assertEqual(a.report_bytes(), b.report_bytes())


if __name__ == "__main__":
    unittest.main()
