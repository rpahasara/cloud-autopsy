"""Negative tests for PR #13 review findings (replay integrity, fail-open gaps/time, joins).

Written before the corresponding engine fixes. Expectations come from the review and the
fixture specification; they never read evaluator ground truth.
"""

import copy
import shutil
import unittest

from ca_spike.pipeline import replay
from ca_spike.store import FileArtifactStore
from tests.helpers import RunTestCase, acquisition, hypothesis, prereq

CM_REF = "k8s:configmap/ca-demo/checkout-db-pool@1002"


class ReplayDerivedFieldTests(RunTestCase):
    """P1: replay must authenticate derived evidence fields, not only source-origin fields."""

    def _tamper(self, name, edit):
        _, store, _ = self.run_variant("D")
        dest = self.tmp / f"tamper-{self._count}-{name}"
        shutil.copytree(store.run_dir, dest)
        copy_store = FileArtifactStore(dest)
        data = copy_store.get(name)
        edit(data)
        copy_store.put(name, data)
        return replay(copy_store)["state"]

    def _first_time(self, records, predicate):
        for rec in records:
            for t in rec["times"]:
                if predicate(t):
                    return t
        raise AssertionError("no matching time")

    def test_derived_interval_bound_edit_is_detected(self):
        def edit(records):
            self._first_time(records, lambda t: t["lower_ms"] is not None)["lower_ms"] -= 60000
        self.assertEqual(self._tamper("evidence.json", edit), "integrity_mismatch")

    def test_derived_clock_and_parse_status_edits_are_detected(self):
        edits = {
            "clock_status": lambda r: self._first_time(r, lambda t: t["clock_status"] == "unknown").update(
                clock_status="declared"),
            "parse_status": lambda r: self._first_time(r, lambda t: t["parse_status"] == "error").update(
                parse_status="ok"),
            "parsed_utc": lambda r: self._first_time(r, lambda t: t["parsed_utc"] is not None).update(
                parsed_utc="2026-10-15T00:00:00.000Z"),
            "evidence_class": lambda r: r[0].update(
                evidence_class="LOG" if r[0]["evidence_class"] != "LOG" else "METRIC"),
            "trust": lambda r: r[0].update(trust="trusted"),
        }
        for field, edit in edits.items():
            with self.subTest(field=field):
                self.assertEqual(self._tamper("evidence.json", edit), "integrity_mismatch")

    def test_baseline_artifact_edit_is_detected(self):
        def edit(baseline):
            baseline["outcome"]["status"] = "abstained"
        self.assertEqual(self._tamper("baseline.json", edit), "integrity_mismatch")


class FailClosedGapTests(RunTestCase):
    """P1: partial coverage and duplicate acquisitions must not leave mandatory sources open."""

    def test_partial_mandatory_acquisition_creates_gap_and_blocks_support(self):
        scenario = self.scenario("A")
        acquisition(scenario, "loki.checkout-api")["status"] = "partial"
        run, _, bundle = self.run_scenario(scenario)
        self.assertIn(("loki.checkout-api", "missing", "partial_coverage"),
                      {(g["query_id"], g["gap_type"], g["reason"]) for g in bundle["gaps"]})
        self.assertNotEqual(hypothesis(bundle, "config_value_change")["status"], "supported")
        self.assertEqual(bundle["outcome"]["status"], "abstained")
        self.assertEqual(run["state"], "partial")

    def test_duplicate_query_cannot_mask_a_failed_acquisition(self):
        scenario = self.scenario("A")
        logs = acquisition(scenario, "loki.checkout-api")
        duplicate = copy.deepcopy(logs)
        logs["status"], logs["reason"] = "failed", "connector_timeout"
        scenario["observations"]["acquisitions"].append(duplicate)
        digests = set()
        for seed in (None, 1, 2, 3):
            _, _, bundle = self.run_scenario(scenario, permute_seed=seed)
            digests.add(bundle["manifest_digest"])
            gaps = {(g["query_id"], g["gap_type"], g["reason"]) for g in bundle["gaps"]}
            self.assertIn(("loki.checkout-api", "unverifiable", "duplicate_acquisition"), gaps)
            self.assertIn(("loki.checkout-api", "failed", "connector_timeout"), gaps)
            self.assertEqual(bundle["outcome"]["status"], "abstained")
        self.assertEqual(len(digests), 1)


class FailClosedChronologyTests(RunTestCase):
    """P1: unordered change-versus-consumption must not become positive mechanism evidence."""

    def test_unordered_consumption_is_not_accepted(self):
        scenario = self.scenario("A")
        for domain in ("node-a", "node-b"):
            scenario["observations"]["clock_domains"][domain] = {
                "status": "unknown", "precision_ms": 1, "provenance": "fixture-declared"}
        _, _, bundle = self.run_scenario(scenario)
        consumed = [r for r in bundle["relations"] if r["relation_type"] == "config_value_consumed"]
        self.assertEqual(consumed, [])
        cfg = hypothesis(bundle, "config_value_change")
        self.assertEqual(prereq(cfg, "consumed_by_symptomatic_pods")["result"], "unsatisfied")
        self.assertEqual(cfg["status"], "unresolved")
        self.assertEqual(bundle["outcome"]["status"], "abstained")
        unordered = [c for c in bundle["chronology_rejections"] if c["reason"] == "consumption_order_unknown"]
        self.assertEqual(len(unordered), 4)


class JoinScopeTests(RunTestCase):
    """P2: joins must stay within one change and one source-qualified entity identity."""

    def test_mapping_and_consumption_from_different_changes_are_not_combined(self):
        scenario = self.scenario("A")
        logs = acquisition(scenario, "loki.checkout-api")
        new_value_logs = [o for o in logs["observations"]
                          if o["attributes"]["template"] in ("CONFIG_LOADED", "CONFIG_RELOADED")
                          and o["attributes"]["fields"]["value"] == "4"]
        for o in new_value_logs:  # the pool change is now never consumed ...
            logs["observations"].remove(o)
        cms = acquisition(scenario, "k8s.configmap-checkpoints")["observations"]
        other = copy.deepcopy(cms[0])  # ... but an unmapped change to the same ConfigMap is
        other.update(source_ref="k8s:configmap/ca-demo/checkout-db-pool@1003", source_version="1003")
        other["times"][0]["raw"] = "2026-10-15T08:10:05Z"
        other["attributes"] = {"data_key": "log.level", "before_value": "debug", "after_value": "info",
                               "before_value_sha256": "b" * 64, "after_value_sha256": "c" * 64,
                               "previous_resource_version": "1002", "actor": "ops-config-sync"}
        cms.append(other)
        for o in new_value_logs:
            reload = copy.deepcopy(o)
            reload["source_version"] += "-ll"
            reload["source_ref"] += "-ll"
            reload["attributes"]["fields"] = {"config_key": "log.level", "value": "info", "value_sha256": "c" * 64,
                                              "config_path": "/etc/checkout/pool/log.level"}
            logs["observations"].append(reload)
        _, _, bundle = self.run_scenario(scenario)
        configs = [h for h in bundle["ledger"]["hypotheses"] if h["mechanism"] == "config_value_change"]
        self.assertEqual(len(configs), 2)  # one hypothesis per specific change
        self.assertFalse([h for h in configs if h["status"] == "supported"])
        self.assertEqual(bundle["outcome"]["status"], "abstained")

    def test_same_name_in_another_namespace_is_not_joined(self):
        scenario = self.scenario("A")
        pods = acquisition(scenario, "k8s.pods")["observations"]
        twin = copy.deepcopy(pods[0])
        twin["entity"]["namespace"] = "ca-other"
        twin.update(source_uid="uid-pod-other-a1", source_ref="k8s:pod/ca-other/checkout-api-6d4b5-a1")
        pods.append(twin)
        logs = acquisition(scenario, "loki.checkout-api")["observations"]
        twin_log = copy.deepcopy(next(o for o in logs if o["attributes"]["template"] == "POOL_EXHAUSTED"))
        twin_log["entity"]["namespace"] = "ca-other"
        twin_log.update(source_uid="uid-pod-other-a1", source_ref="loki:{namespace=ca-other}#1")
        logs.append(twin_log)
        _, store, bundle = self.run_scenario(scenario)
        ns_of = {e["evidence_id"]: e["entity"].get("namespace") for e in store.get("evidence.json")}
        ids = {e["source_ref"]: e["evidence_id"] for e in store.get("evidence.json")}
        crossing = [r for r in bundle["relations"] if len({ns_of[i] for i in r["inputs"]}) > 1]
        self.assertEqual(crossing, [])  # the ca-other pod may join its own log, never ca-demo evidence
        foreign = {ids["k8s:pod/ca-other/checkout-api-6d4b5-a1"], ids["loki:{namespace=ca-other}#1"]}
        cited = [p for h in bundle["ledger"]["hypotheses"] for p in h["prerequisites"] if foreign & set(p["evidence_ids"])]
        self.assertEqual(cited, [])
        self.assertEqual(bundle["outcome"]["status"], "resolved")

    def test_ambiguous_identity_in_one_namespace_is_excluded_and_reported(self):
        scenario = self.scenario("A")
        pods = acquisition(scenario, "k8s.pods")["observations"]
        twin = copy.deepcopy(pods[0])
        twin.update(source_uid="uid-pod-recreated-a1", source_ref="k8s:pod/ca-demo/checkout-api-6d4b5-a1#2")
        pods.append(twin)
        _, store, bundle = self.run_scenario(scenario)
        ids = {e["source_ref"]: e["evidence_id"] for e in store.get("evidence.json")}
        both = {ids[pods[0]["source_ref"]], ids[twin["source_ref"]]}
        self.assertEqual([a["name"] for a in bundle["identity_ambiguities"]], ["checkout-api-6d4b5-a1"])
        self.assertEqual([r for r in bundle["relations"] if both & set(r["inputs"])], [])


if __name__ == "__main__":
    unittest.main()
