"""Regressions from the PR #19 review: unresolved batches, unverified evidence and resource accounting.

At 3930740 an acquisition whose verified coverage spanned the window was reported complete even
when a partial, failed or out-of-chain batch also existed; observations from such batches became
members with no qualification; and conflicting batch variants were excluded before the total
limits were applied, so they were processed without being counted.
"""

import copy
import unittest

import _evidence_support as ES
import _manifest_support as M
from cloud_autopsy.contracts import acquisition as acq, canonical, errors, frozen_input as fi
from cloud_autopsy.contracts.errors import ContractError


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ContractError as exc:
        return exc.code
    return None


def extra_batch(plan, base, **changes):
    record = M.batch_record(base, plan)
    observations = changes.pop("observations", None)
    record.update(changes)
    if observations is not None:
        record["observations"] = [ES.case(n)[1] for n in observations]
    return record


def deployments_plan(**limits):
    record = M.plan_record(["deployments"])
    record["limits"] = {**record["limits"], **limits}
    return M.pl.RunPlan.from_record(record, M.REGISTRY)


def entries(sealed, collection):
    return fi.collection_items(sealed, collection)


class UnresolvedBatchTests(unittest.TestCase):
    def setUp(self):
        self.plan = deployments_plan()
        self.clean = [M.batch_record(n, self.plan) for n in ("deploy-1", "deploy-2")]

    def seal_with(self, extra):
        sealed = fi.seal(self.plan, M.REGISTRY, self.clean + [extra])
        (summary,) = sealed.root()["acquisitions"]
        return sealed, summary

    def assert_unresolved(self, extra, gap_type, reason):
        sealed, summary = self.seal_with(extra)
        self.assertEqual(sealed.status, fi.INCOMPLETE)
        self.assertNotIn(summary["status"], (acq.COMPLETE, acq.EMPTY))
        digest = acq.batch_digest(extra)
        gaps = [g for g in entries(sealed, "gaps") if digest in g["batch_digests"]]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["gap_type"], gap_type)
        self.assertIn(reason, gaps[0]["reasons"])
        self.assertIn("mandatory_acquisition_incomplete", sealed.root()["limitations"])
        return sealed

    def test_partial_batch_inside_fully_covered_window(self):
        extra = extra_batch(self.plan, "deploy-2", batch_key="deploy-3", sequence=3,
                            cursor={"before": "d2", "after": "d3"}, outcome="partial", reason="timeout",
                            coverage={"start": "2026-10-15T08:20:00Z", "end": "2026-10-15T08:30:00Z"},
                            observations=["rs"])
        self.assert_unresolved(extra, fi.UNVERIFIABLE, "timeout")

    def test_failed_batch_after_full_coverage(self):
        extra = extra_batch(self.plan, "deploy-2", batch_key="deploy-3", sequence=3,
                            cursor={"before": "d2", "after": "d3"}, outcome="failed", reason="source_unavailable",
                            coverage=None)
        self.assert_unresolved(extra, fi.FAILED, "source_unavailable")

    def test_out_of_chain_batch_after_full_coverage(self):
        extra = extra_batch(self.plan, "deploy-2", batch_key="deploy-9", sequence=9,
                            cursor={"before": "d8", "after": "d9"})
        self.assert_unresolved(extra, fi.UNVERIFIABLE, "cursor_discontinuity")

    def test_truncated_partial_batch(self):
        extra = extra_batch(self.plan, "deploy-2", batch_key="deploy-3", sequence=3,
                            cursor={"before": "d2", "after": "d3"}, outcome="partial", reason="page_limit",
                            truncation={"truncated": True, "reason": "page_limit", "omitted_count": None},
                            coverage={"start": "2026-10-15T08:20:00Z", "end": "2026-10-15T08:30:00Z"})
        self.assert_unresolved(extra, fi.TRUNCATED, "page_limit")


class EvidenceQualificationTests(unittest.TestCase):
    def test_members_carry_coverage_qualification_and_provenance(self):
        plan = M.make_plan(["configmaps", "logs"])
        records = [M.batch_record(n, plan) for n in ("cm-1", "log-1")]
        sealed = fi.seal(plan, M.REGISTRY, records)
        members = {m["evidence_id"]: m for m in entries(sealed, "evidence")}
        cm, log = members[ES.build("cm").evidence_id], members[ES.build("log").evidence_id]
        self.assertEqual(cm["coverage"], fi.VERIFIED)
        self.assertEqual(log["coverage"], fi.UNVERIFIED)
        self.assertEqual((cm["batch_count"], log["batch_count"]), (1, 1))
        provenance = {(p["evidence_id"], p["batch_digest"]) for p in entries(sealed, "evidence_provenance")}
        self.assertEqual(provenance, {(cm["evidence_id"], acq.batch_digest(records[0])),
                                      (log["evidence_id"], acq.batch_digest(records[1]))})
        self.assertIn("unverified_evidence_included", sealed.root()["limitations"])

    def test_evidence_seen_in_a_verified_batch_is_verified(self):
        plan = deployments_plan()
        clean = [M.batch_record(n, plan) for n in ("deploy-1", "deploy-2")]
        again = extra_batch(plan, "deploy-2", batch_key="deploy-3", sequence=3, cursor={"before": "d2", "after": "d3"},
                            outcome="partial", reason="timeout", observations=["deploy"],
                            coverage={"start": "2026-10-15T08:20:00Z", "end": "2026-10-15T08:30:00Z"})
        sealed = fi.seal(plan, M.REGISTRY, clean + [again])
        (member,) = entries(sealed, "evidence")
        self.assertEqual(member["coverage"], fi.VERIFIED)
        self.assertEqual(member["batch_count"], 2)
        self.assertEqual(len(entries(sealed, "evidence_provenance")), 2)

    def test_verified_coverage_and_availability_are_distinct(self):
        plan = M.make_plan(["logs"])
        sealed = fi.seal(plan, M.REGISTRY, [M.batch_record("log-1", plan)])
        (summary,) = sealed.root()["acquisitions"]
        self.assertEqual(summary["verified_ms"], 0)
        self.assertEqual(summary["observations_received"], 1)
        self.assertEqual(sealed.root()["availability_generation"], 0)


class DuplicateDeliveryTests(unittest.TestCase):
    def test_duplicates_never_create_gaps(self):
        for scenario in M.DOC["scenarios"]:
            plan = M.make_plan(scenario["acquisitions"])
            once = fi.seal(plan, M.REGISTRY, [M.batch_record(n, plan) for n in scenario["batches"]])
            twice = fi.seal(plan, M.REGISTRY, [M.batch_record(n, plan, attempt=a) for n in scenario["batches"]
                                               for a in (1, 2, 3)])
            with self.subTest(scenario["id"]):
                self.assertEqual(twice.root_bytes, once.root_bytes)
                self.assertEqual(twice.page_bytes, once.page_bytes)


class ResourceAccountingTests(unittest.TestCase):
    def sizes(self, plan, names):
        return [len(canonical.canonical_bytes(M.batch_record(n, plan))) for n in names]

    def test_conflicting_variants_count_toward_total_bytes(self):
        probe = M.make_plan(["configmaps", "deployments"])
        cm, conflict, deploy = self.sizes(probe, ["cm-1", "cm-1-conflict", "deploy-1"])
        plan = deployments_plan()
        record = M.plan_record(["configmaps", "deployments"])
        record["limits"] = {**record["limits"], "max_total_bytes": cm + deploy + conflict // 2}
        plan = M.pl.RunPlan.from_record(record, M.REGISTRY)
        records = [M.batch_record(n, plan) for n in ("cm-1", "cm-1-conflict", "deploy-1")]
        self.assertEqual(code_of(fi.seal, plan, M.REGISTRY, records), errors.LIMIT_EXCEEDED)

    def test_conflicting_variants_count_toward_total_observations(self):
        record = M.plan_record(["configmaps", "deployments"])
        record["limits"] = {**record["limits"], "max_observations_total": 2}
        plan = M.pl.RunPlan.from_record(record, M.REGISTRY)
        records = [M.batch_record(n, plan) for n in ("cm-1", "cm-1-conflict", "deploy-1")]
        self.assertEqual(code_of(fi.seal, plan, M.REGISTRY, records), errors.LIMIT_EXCEEDED)

    def test_conflicting_variants_count_toward_batches_per_acquisition(self):
        record = M.plan_record(["configmaps"])
        record["limits"] = {**record["limits"], "max_batches_per_acquisition": 1}
        plan = M.pl.RunPlan.from_record(record, M.REGISTRY)
        records = [M.batch_record(n, plan) for n in ("cm-1", "cm-1-conflict")]
        self.assertEqual(code_of(fi.seal, plan, M.REGISTRY, records), errors.LIMIT_EXCEEDED)

    def test_repeated_deliveries_are_bounded_before_decoding(self):
        plan = deployments_plan(max_batch_deliveries=10)
        record = M.batch_record("deploy-1", plan)
        self.assertIsNotNone(fi.seal(plan, M.REGISTRY, [copy.deepcopy(record) for _ in range(10)]))
        flood = [copy.deepcopy(record) for _ in range(10)] + [{"not": "a batch"}]
        self.assertEqual(code_of(fi.seal, plan, M.REGISTRY, flood), errors.LIMIT_EXCEEDED)

    def test_delivery_iterables_are_consumed_lazily_and_bounded(self):
        plan = deployments_plan(max_batch_deliveries=5)
        record = M.batch_record("deploy-1", plan)
        produced = []

        def endless():
            # Fail fast instead of hanging if the delivery bound ever regresses.
            while len(produced) < 1_000:
                produced.append(1)
                yield copy.deepcopy(record)
            raise AssertionError("seal consumed deliveries past max_batch_deliveries")

        self.assertEqual(code_of(fi.seal, plan, M.REGISTRY, endless()), errors.LIMIT_EXCEEDED)
        self.assertEqual(len(produced), 6)


if __name__ == "__main__":
    unittest.main()
