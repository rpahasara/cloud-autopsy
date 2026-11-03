"""CA-P2-002d: run plans, acquisition batches and frozen-input manifests."""

import copy
import random
import unittest

import _evidence_support as ES
import _manifest_support as M
from cloud_autopsy.contracts import acquisition as acq, canonical, errors, frozen_input as fi, plan as pl
from cloud_autopsy.contracts import sources
from cloud_autopsy.contracts.errors import ContractError


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ContractError as exc:
        return exc.code
    return None


def seal_scenario(scenario, order=None, attempts=None):
    plan = M.make_plan(scenario["acquisitions"])
    names = list(order or scenario["batches"])
    records = [M.batch_record(n, plan, attempt=(attempts or {}).get(n, 1)) for n in names]
    return plan, fi.seal(plan, M.REGISTRY, records)


class ScenarioVectorTests(unittest.TestCase):
    def test_vector_file_targets_these_contracts(self):
        self.assertEqual(M.DOC["contract"], fi.FROZEN_INPUT_VERSION)
        self.assertEqual(set(M.DOC["related_contracts"]), {pl.RUN_PLAN_VERSION, acq.BATCH_VERSION,
                                                           fi.GAP_POLICY_VERSION, fi.PAGE_VERSION})

    def test_scenarios(self):
        for scenario in M.DOC["scenarios"]:
            with self.subTest(scenario["id"]):
                plan, sealed = seal_scenario(scenario)
                root = sealed.root()
                self.assertEqual(root["status"], scenario["status"])
                self.assertEqual(root["limitations"], scenario["limitations"])
                members = {m["evidence_id"]: m for m in fi.collection_items(sealed, "evidence")}
                expected = {ES.build(n).evidence_id: (ES.build(n).content_digest, q)
                            for n, q in scenario["members"].items()}
                self.assertEqual({k: (m["content_digest"], m["coverage"]) for k, m in members.items()}, expected)
                statuses = {(a["source_id"], a["query_id"]): a["status"] for a in root["acquisitions"]}
                for name, status in scenario["acquisition_status"].items():
                    spec = M.DOC["acquisitions"][name]
                    self.assertEqual(statuses[(spec["source_id"], spec["query_id"])], status, name)
                gaps = fi.collection_items(sealed, "gaps")
                self.assertEqual(len(gaps), len(scenario["gaps"]))
                for want in scenario["gaps"]:
                    self.assertEqual(sum(self.gap_matches(g, want, plan) for g in gaps), 1, want)

    def gap_matches(self, gap, expected, plan):
        if (gap["subject"], gap["gap_type"], gap["reasons"]) != (expected["subject"], expected["gap_type"],
                                                                 expected["reasons"]):
            return False
        if expected["subject"] == "identity":
            return (gap["evidence_id"], gap["variant_count"]) == (ES.build(expected["evidence"]).evidence_id,
                                                                  expected["variant_count"])
        spec = M.DOC["acquisitions"][expected["acquisition"]]
        if (gap["source_id"], gap["query_id"], gap["mandatory"]) != (spec["source_id"], spec["query_id"],
                                                                      spec["mandatory"]):
            return False
        names = expected.get("batches") or ([expected["batch"]] if "batch" in expected else [])
        digests = sorted(acq.batch_digest(M.batch_record(n, plan)) for n in names)
        if gap["batch_digests"] != digests:
            return False
        interval = expected["interval"]
        if interval is None:
            return gap["interval_ms"] is None
        bounds = (plan.window_start_ms, plan.window_end_ms) if interval == "window" else tuple(map(M.ms, interval))
        return gap["interval_ms"] == {"start": bounds[0], "end": bounds[1]}


class DeterminismTests(unittest.TestCase):
    def test_order_duplicates_and_retries_give_identical_manifests(self):
        rng = random.Random(41)
        for scenario in M.DOC["scenarios"]:
            _, reference = seal_scenario(scenario)
            for _ in range(25):
                order = scenario["batches"] + rng.choices(scenario["batches"], k=rng.randint(0, 3))
                rng.shuffle(order)
                attempts = {n: rng.randint(1, 5) for n in scenario["batches"]}
                with self.subTest(scenario["id"], order=order):
                    _, sealed = seal_scenario(scenario, order, attempts)
                    self.assertEqual((sealed.root_bytes, sealed.page_bytes),
                                     (reference.root_bytes, reference.page_bytes))

    def test_manifest_digest_regression_pins_are_stable(self):
        digests = {s["id"]: seal_scenario(s)[1].digest for s in M.DOC["scenarios"]}
        self.assertEqual(len(set(digests.values())), len(digests))
        self.assertEqual(digests, M.DOC["manifest_digest_pins"])
        for digest in digests.values():
            self.assertTrue(digest.startswith(fi.MANIFEST_ALGORITHM + ":"))

    def test_no_volatile_raw_or_truth_content_in_manifest(self):
        scenario = M.DOC["scenarios"][1]
        _, sealed = seal_scenario(scenario, attempts={n: 97 for n in scenario["batches"]})
        root = sealed.root()
        self.assertIn("run_id", root["excluded_from_digest"])
        self.assertIn("batch.delivery.attempt", root["excluded_from_digest"])
        del root["excluded_from_digest"]
        text = canonical.canonical_bytes(root).decode("utf-8") + b"".join(sealed.page_bytes).decode("utf-8")
        for forbidden in ("kubectl delete", "ignore previous", "attempt", "ops-config-sync", "registry.invalid",
                          "truth", "password", "token", "run_id", "wall"):
            self.assertNotIn(forbidden, text)

    def test_frozen_input_is_immutable(self):
        _, sealed = seal_scenario(M.DOC["scenarios"][0])
        root, pages = sealed.root(), sealed.pages()
        root["status"] = "forged"
        pages[0]["items"].clear()
        self.assertEqual(sealed.root()["status"], fi.COMPLETE)
        self.assertTrue(sealed.pages()[0]["items"])
        with self.assertRaises(AttributeError):
            sealed.root_bytes = b"{}"


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.scenario = M.DOC["scenarios"][1]
        self.plan, self.sealed = seal_scenario(self.scenario)
        self.records = [M.batch_record(n, self.plan) for n in self.scenario["batches"]]

    def test_verify_root_full_and_replay(self):
        root, pages = self.sealed.root(), self.sealed.pages()
        self.assertEqual(fi.verify_root(root, self.plan, M.REGISTRY), root)
        self.assertEqual(fi.verify_full(root, list(reversed(pages)), self.plan, M.REGISTRY), root)
        resealed = fi.verify_replay(root, pages, self.plan, M.REGISTRY, list(reversed(self.records)))
        self.assertEqual(resealed.root_bytes, self.sealed.root_bytes)

    def test_tampered_roots(self):
        root = self.sealed.root()
        cases = [
            ({"status": "complete"}, errors.MANIFEST_DIGEST_MISMATCH),
            ({"limitations": []}, errors.MANIFEST_DIGEST_MISMATCH),
            ({"acquisitions": root["acquisitions"][1:]}, errors.MANIFEST_DIGEST_MISMATCH),
            ({"collections": {**root["collections"], "gaps": {"item_count": 0, "pages": []}}},
             errors.MANIFEST_DIGEST_MISMATCH),
            ({"manifest_digest": "sha256:" + "0" * 64}, errors.MANIFEST_DIGEST_MISMATCH),
            ({"contract_version": "ca-frozen-input/0.1-provisional"}, errors.CONTRACT_VERSION_MISMATCH),
            ({"ground_truth": {"cause": "x"}}, errors.RECORD_FIELD_UNKNOWN),
        ]
        for change, code in cases:
            with self.subTest(change=list(change)):
                self.assertEqual(code_of(fi.verify_root, {**root, **change}, self.plan, M.REGISTRY), code)
        missing = dict(root)
        del missing["collections"]
        self.assertEqual(code_of(fi.verify_root, missing, self.plan, M.REGISTRY), errors.RECORD_FIELD_MISSING)

    def test_wrong_plan_registry_and_replay_inputs(self):
        root, pages = self.sealed.root(), self.sealed.pages()
        other_plan = M.make_plan(self.scenario["acquisitions"], plan_id="another-plan")
        self.assertEqual(code_of(fi.verify_root, root, other_plan, M.REGISTRY), errors.PLAN_MISMATCH)
        moved = copy.deepcopy(ES.DOC["registry"])
        moved["sources"][0]["cluster_id"] = "ca-kind-moved"
        moved_registry = sources.SourceRegistry.from_record(moved)
        self.assertEqual(code_of(fi.verify_root, root, self.plan, moved_registry), errors.REGISTRY_MISMATCH)
        self.assertEqual(code_of(fi.seal, self.plan, moved_registry, self.records), errors.REGISTRY_MISMATCH)
        self.assertEqual(code_of(fi.verify_replay, root, pages, self.plan, M.REGISTRY, self.records[:-1]),
                         errors.REPLAY_MISMATCH)


class PlanTests(unittest.TestCase):
    ACQ = ["configmaps", "deployments"]

    def test_round_trip_and_digest_stability(self):
        plan = M.make_plan(self.ACQ)
        again = pl.RunPlan.from_record(canonical.loads(canonical.canonical_bytes(plan.to_record())), M.REGISTRY)
        self.assertEqual(again, plan)
        reordered = M.plan_record(list(reversed(self.ACQ)))
        self.assertEqual(pl.RunPlan.from_record(reordered, M.REGISTRY).digest, plan.digest)

    def test_invalid_plans(self):
        base = M.plan_record(self.ACQ)
        limits = dict(base["limits"])
        cases = [
            ({"registry_digest": canonical.DIGEST_ALGORITHM + ":" + "0" * 64}, errors.REGISTRY_MISMATCH),
            ({"window": {"start": "2026-10-15T08:30:00Z", "end": "2026-10-15T08:00:00Z"}}, errors.PLAN_INVALID),
            ({"window": {"start": "2026-10-15T08:00:00.0001Z", "end": "2026-10-15T08:30:00Z"}}, errors.PLAN_INVALID),
            ({"window": {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T09:30:00Z"}}, errors.LIMIT_EXCEEDED),
            ({"limits": {**limits, "max_window_ms": 3_600_001}}, errors.PLAN_INVALID),
            ({"limits": {**limits, "max_observations_total": 0}}, errors.PLAN_INVALID),
            ({"limits": {k: v for k, v in limits.items() if k != "max_total_bytes"}}, errors.PLAN_INVALID),
            ({"synthesis_mode": "external"}, errors.PLAN_INVALID),
            ({"contract_versions": {**base["contract_versions"], "evidence": "ca-evidence/0.0"}},
             errors.CONTRACT_VERSION_MISMATCH),
            ({"rule_versions": {"ledger": "not a version"}}, errors.CONTRACT_VERSION_MALFORMED),
            ({"expected_acquisitions": []}, errors.PLAN_INVALID),
            ({"expected_acquisitions": base["expected_acquisitions"] * 2}, errors.PLAN_INVALID),
            ({"expected_acquisitions": [{"source_id": "loki", "query_id": "k8s.pods", "mandatory": True}]},
             errors.SOURCE_SCOPE_MISMATCH),
            ({"expected_acquisitions": [{"source_id": "nope", "query_id": "q", "mandatory": True}]},
             errors.SOURCE_UNKNOWN),
            ({"ground_truth": "deploy"}, errors.RECORD_FIELD_UNKNOWN),
            ({"api_token": "x"}, errors.RECORD_FIELD_UNKNOWN),
            ({"query": "sum(rate(x[5m]))"}, errors.RECORD_FIELD_UNKNOWN),
        ]
        for change, code in cases:
            with self.subTest(change=list(change)):
                self.assertEqual(code_of(pl.RunPlan.from_record, {**base, **change}, M.REGISTRY), code)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.plan = M.make_plan(["configmaps", "deployments", "logs", "metrics", "alerts"])

    def check(self, name, change, code, plan=None):
        record = M.batch_record(name, plan or self.plan)
        for key, value in change.items():
            record[key] = value
        self.assertEqual(code_of(acq.decode_batch, record, plan or self.plan, M.REGISTRY), code)

    def test_outcome_consistency(self):
        coverage = {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T08:30:00Z"}
        untruncated = {"truncated": False, "reason": None, "omitted_count": None}
        cases = [
            ("metric-1", {"outcome": "complete"}, errors.BATCH_INVALID),          # complete needs observations
            ("cm-1", {"outcome": "empty"}, errors.BATCH_INVALID),                 # empty cannot carry observations
            ("metric-failed", {"coverage": coverage}, errors.BATCH_INVALID),      # failure has no coverage
            ("metric-failed", {"reason": None}, errors.BATCH_INVALID),
            ("metric-failed", {"reason": "authorization_denied"}, errors.BATCH_INVALID),
            ("alert-denied", {"reason": "timeout"}, errors.BATCH_INVALID),
            ("log-1", {"reason": None}, errors.BATCH_INVALID),                    # partial needs a reason
            ("cm-1", {"reason": "timeout"}, errors.BATCH_INVALID),
            ("log-1", {"truncation": {"truncated": True, "reason": "timeout", "omitted_count": 1}},
             errors.BATCH_INVALID),
            ("log-1", {"truncation": {"truncated": True, "reason": "page_limit", "omitted_count": 0}},
             errors.BATCH_INVALID),
            ("cm-1", {"truncation": {"truncated": False, "reason": "page_limit", "omitted_count": None}},
             errors.BATCH_INVALID),
            ("cm-1", {"truncation": {"truncated": True, "reason": "page_limit", "omitted_count": None}},
             errors.BATCH_INVALID),
            ("cm-1", {"outcome": "succeeded"}, errors.BATCH_INVALID),
            ("cm-1", {"truncation": untruncated, "coverage": None}, errors.BATCH_INVALID),
        ]
        for name, change, code in cases:
            with self.subTest(name=name, change=list(change)):
                self.check(name, change, code)

    def test_coverage_cursor_identity_and_scope(self):
        cases = [
            ("cm-1", {"coverage": {"start": "2026-10-15T07:59:59Z", "end": "2026-10-15T08:30:00Z"}}),
            ("cm-1", {"coverage": {"start": "2026-10-15T08:10:00Z", "end": "2026-10-15T08:10:00Z"}}),
            ("cm-1", {"coverage": {"start": "2026-10-15T08:00:00.0005Z", "end": "2026-10-15T08:30:00Z"}}),
            ("cm-1", {"cursor": {"before": "c0", "after": "c1"}}),
            ("deploy-2", {"cursor": {"before": None, "after": "d2"}}),
            ("cm-1", {"cursor": {"before": None, "after": "bad cursor!"}}),
            ("cm-1", {"batch_key": "Bad Key"}),
            ("cm-1", {"sequence": 0}),
            ("cm-1", {"sequence": 11}),
            ("cm-1", {"delivery": {"attempt": 0}}),
            ("cm-1", {"delivery": {"attempt": 1, "received_at": "now"}}),
        ]
        for name, change in cases:
            with self.subTest(change=change):
                self.check(name, change, errors.BATCH_INVALID if "coverage" not in change or "0005" not in str(change)
                           else errors.PLAN_INVALID)
        self.check("cm-1", {"plan_digest": canonical.DIGEST_ALGORITHM + ":" + "1" * 64}, errors.PLAN_MISMATCH)
        self.check("cm-1", {"query_id": "k8s.pods"}, errors.SOURCE_SCOPE_MISMATCH)
        self.check("cm-1", {"credentials": "x"}, errors.RECORD_FIELD_UNKNOWN)
        self.check("cm-1", {"contract_version": "ca-acquisition-batch/0.2-provisional"},
                   errors.CONTRACT_VERSION_MISMATCH)
        bad_observation = M.batch_record("cm-1", self.plan)
        bad_observation["observations"][0]["entity"]["namespace"] = "kube-system"
        self.assertEqual(code_of(acq.decode_batch, bad_observation, self.plan, M.REGISTRY),
                         errors.SOURCE_SCOPE_MISMATCH)

    def test_finite_limits(self):
        def plan_with(**limits):
            base = M.plan_record(["configmaps", "deployments", "logs"])
            return pl.RunPlan.from_record({**base, "limits": {**base["limits"], **limits}}, M.REGISTRY)

        tight = plan_with(max_observations_per_batch=1)
        record = M.batch_record("cm-1", tight)
        record["observations"] = record["observations"] * 2
        self.assertEqual(code_of(acq.decode_batch, record, tight, M.REGISTRY), errors.LIMIT_EXCEEDED)
        small = plan_with(max_batch_bytes=512)
        self.assertEqual(code_of(acq.decode_batch, M.batch_record("cm-1", small), small, M.REGISTRY),
                         errors.LIMIT_EXCEEDED)
        few = plan_with(max_observations_total=2)
        records = [M.batch_record(n, few) for n in ("cm-1", "deploy-1", "log-1")]
        self.assertEqual(code_of(fi.seal, few, M.REGISTRY, records), errors.LIMIT_EXCEEDED)
        light = plan_with(max_total_bytes=1500)
        records = [M.batch_record(n, light) for n in ("cm-1", "deploy-1")]
        self.assertEqual(code_of(fi.seal, light, M.REGISTRY, records), errors.LIMIT_EXCEEDED)

    def test_batch_digest_excludes_delivery_only(self):
        a, b = M.batch_record("cm-1", self.plan, attempt=1), M.batch_record("cm-1", self.plan, attempt=9)
        self.assertEqual(acq.batch_digest(a), acq.batch_digest(b))
        b["cursor"] = {"before": None, "after": "c2"}
        self.assertNotEqual(acq.batch_digest(a), acq.batch_digest(b))

    def test_manifest_codes_are_pinned(self):
        self.assertEqual(errors.MANIFEST_CODES, {"plan_invalid", "plan_mismatch", "registry_mismatch",
                                                 "batch_invalid", "limit_exceeded", "manifest_digest_mismatch",
                                                 "replay_mismatch", "page_missing", "page_unexpected",
                                                 "page_invalid", "page_digest_mismatch"})


if __name__ == "__main__":
    unittest.main()
