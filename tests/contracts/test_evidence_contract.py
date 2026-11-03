"""Unit tests for the source registry, observation decoding, evidence records and the conflict ledger."""

import copy
import dataclasses
import random
import unittest

import _evidence_support as S
from cloud_autopsy.contracts import canonical, errors, evidence as ev, sources
from cloud_autopsy.contracts.errors import ContractError, VersionError


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ContractError as exc:
        return exc.code
    return None


def registry_with(**changes):
    record = copy.deepcopy(S.DOC["registry"])
    record["sources"][0].update(changes)
    return sources.SourceRegistry.from_record(record)


class SourceRegistryTests(unittest.TestCase):
    def test_round_trip_and_stable_digest(self):
        record = S.REGISTRY.to_record()
        self.assertEqual(sources.SourceRegistry.from_record(canonical.loads(canonical.canonical_bytes(record))),
                         S.REGISTRY)
        shuffled = copy.deepcopy(S.DOC["registry"])
        shuffled["sources"].reverse()
        for s in shuffled["sources"]:
            s["query_ids"].reverse()
        self.assertEqual(sources.SourceRegistry.from_record(shuffled).digest, S.REGISTRY.digest)

    def test_invalid_registries(self):
        base = S.DOC["registry"]
        cases = [
            ({"sources": []}, errors.REGISTRY_INVALID),
            ({"sources": base["sources"] + [base["sources"][0]]}, errors.REGISTRY_INVALID),
            ({"registry_id": "Bad Id"}, errors.REGISTRY_INVALID),
            ({"extra": 1}, errors.RECORD_FIELD_UNKNOWN),
            ({"contract_version": "ca-source-registry/0.2-provisional"}, errors.CONTRACT_VERSION_MISMATCH),
        ]
        for change, code in cases:
            with self.subTest(change=list(change)):
                self.assertEqual(code_of(sources.SourceRegistry.from_record, {**base, **change}), code)
        source_cases = [
            ({"source_kind": "kubectl_exec"}, errors.REGISTRY_INVALID),
            ({"namespace": "Not_A_Label"}, errors.REGISTRY_INVALID),
            ({"clock_domain_ids": []}, errors.REGISTRY_INVALID),
            ({"query_ids": ["q", "q"]}, errors.REGISTRY_INVALID),
            ({"cluster_id": 7}, errors.REGISTRY_INVALID),
            ({"credentials": "x"}, errors.RECORD_FIELD_UNKNOWN),
        ]
        for change, code in source_cases:
            with self.subTest(source_change=list(change)):
                record = copy.deepcopy(base)
                record["sources"][0].update(change)
                self.assertEqual(code_of(sources.SourceRegistry.from_record, record), code)

    def test_observation_kind_must_match_source_kind_even_with_a_shared_clock_domain(self):
        record = copy.deepcopy(S.DOC["registry"])
        record["sources"].append({"source_id": "loki-shared", "source_kind": "loki", "cluster_id": "ca-kind-synthetic",
                                  "namespace": "ca-demo", "clock_domain_ids": ["prometheus"],
                                  "query_ids": ["loki.checkout-api"]})
        registry = sources.SourceRegistry.from_record(record)
        _, observation = S.case("metric")
        self.assertEqual(code_of(ev.observe, observation, source_id="loki-shared", registry=registry),
                         errors.SOURCE_SCOPE_MISMATCH)

    def test_unmatched_log_line_keeps_untrusted_text_without_fields(self):
        source_id, observation = S.case("log")
        observation["attributes"].update(template=None, fields={})
        record = ev.observe(observation, source_id=source_id, registry=S.REGISTRY)
        self.assertIsNone(record.attributes["template"])
        self.assertEqual(ev.ObservedEvidence.from_record(record.to_record(), S.REGISTRY), record)

    def test_unknown_source(self):
        self.assertEqual(code_of(S.REGISTRY.get, "nope"), errors.SOURCE_UNKNOWN)


class IdentityTests(unittest.TestCase):
    def test_delivery_metadata_is_not_identity_or_content(self):
        source_id, observation = S.case("deploy")
        first = ev.observe(observation, source_id=source_id, registry=S.REGISTRY,
                           delivery={"query_id": "k8s.deployments", "batch_id": "batch-1", "attempt": 1})
        again = ev.observe(observation, source_id=source_id, registry=S.REGISTRY,
                           delivery={"query_id": "k8s.pods", "batch_id": "batch-9", "attempt": 7})
        self.assertEqual(first, again)
        self.assertNotIn("batch-1", str(first.to_record()))

    def test_delivery_validation(self):
        source_id, observation = S.case("cm")
        for delivery, code in [({"query_id": "loki.checkout-api", "batch_id": "b", "attempt": 1}, errors.SOURCE_SCOPE_MISMATCH),
                               ({"query_id": "k8s.configmaps", "batch_id": "B!", "attempt": 1}, errors.RECORD_FIELD_INVALID),
                               ({"query_id": "k8s.configmaps", "batch_id": "b", "attempt": 0}, errors.RECORD_FIELD_INVALID),
                               ({"query_id": "k8s.configmaps", "batch_id": "b", "attempt": True}, errors.RECORD_FIELD_INVALID),
                               ({"query_id": "k8s.configmaps", "batch_id": "b"}, errors.RECORD_FIELD_MISSING)]:
            with self.subTest(delivery=delivery):
                self.assertEqual(code_of(ev.observe, observation, source_id=source_id, registry=S.REGISTRY,
                                         delivery=delivery), code)

    def test_identity_material_and_id_format(self):
        record = S.build("cm")
        source = S.REGISTRY.get("k8s-api")
        material = ev.identity_material(source, "configmap_change", "uid-cm-checkout-db-pool", "1002")
        self.assertEqual(set(material), {"algorithm", "source_id", "cluster_id", "namespace", "observation_kind",
                                         "source_uid", "source_version"})
        self.assertEqual(record.evidence_id.split(":")[0], ev.ID_ALGORITHM)
        self.assertNotEqual(record.evidence_id.split(":")[1], record.content_digest.split(":")[1])

    def test_rebinding_a_source_changes_identity(self):
        rebound = registry_with(cluster_id="ca-kind-moved")
        self.assertNotEqual(S.build("cm", rebound).evidence_id, S.build("cm").evidence_id)
        self.assertEqual(S.build("cm", rebound).content_digest, S.build("cm").content_digest)

    def test_prototype_and_foreign_ids_are_rejected(self):
        for text in ("ev:K8S-CONFIG:" + "a" * 24, "sha256:" + "a" * 64, canonical.DIGEST_ALGORITHM + ":" + "a" * 64,
                     ev.CONTENT_ALGORITHM + ":" + "a" * 64, ev.ID_ALGORITHM + ":" + "A" * 64, None):
            with self.subTest(text=text):
                self.assertEqual(code_of(ev.parse_evidence_id, text), errors.EVIDENCE_ID_MISMATCH)


class RecordTests(unittest.TestCase):
    def test_round_trip_for_every_vector(self):
        for name in S.DOC["observations"]:
            with self.subTest(name):
                record = S.build(name)
                decoded = canonical.loads(canonical.canonical_bytes(record.to_record()))
                self.assertEqual(ev.ObservedEvidence.from_record(decoded, S.REGISTRY), record)
                source_id, _ = S.case(name)
                self.assertEqual(ev.observe(record.observation(), source_id=source_id, registry=S.REGISTRY), record)

    def test_tampered_records(self):
        record = S.build("deploy").to_record()
        other = S.build("rs").to_record()
        cases = [
            ({"content_digest": other["content_digest"]}, errors.CONTENT_DIGEST_MISMATCH),
            ({"evidence_id": other["evidence_id"]}, errors.EVIDENCE_ID_MISMATCH),
            ({"attributes": {**record["attributes"], "image_after": "registry.invalid/evil:1"}},
             errors.CONTENT_DIGEST_MISMATCH),
            ({"source_version": "2002"}, errors.EVIDENCE_ID_MISMATCH),
            ({"cluster_id": "attacker-cluster"}, errors.RECORD_INCONSISTENT),
            ({"source_binding_digest": canonical.DIGEST_ALGORITHM + ":" + "0" * 64}, errors.RECORD_INCONSISTENT),
            ({"evidence_class": "LOG"}, errors.RECORD_INCONSISTENT),
            ({"origin": "derived"}, errors.RECORD_FIELD_INVALID),
            ({"times": [{**record["times"][0], "local_upper_ms": record["times"][0]["local_upper_ms"] + 9}]},
             errors.RECORD_INCONSISTENT),
            ({"contract_version": "ca-evidence/0.2-provisional"}, errors.CONTRACT_VERSION_MISMATCH),
        ]
        for change, code in cases:
            with self.subTest(change=list(change)):
                self.assertEqual(code_of(ev.ObservedEvidence.from_record, {**record, **change}, S.REGISTRY), code)
        self.assertEqual(code_of(ev.ObservedEvidence.from_record, {**record, "extra": 1}, S.REGISTRY),
                         errors.RECORD_FIELD_UNKNOWN)
        self.assertEqual(code_of(ev.ObservedEvidence.from_record, record, registry_with(cluster_id="moved")),
                         errors.EVIDENCE_ID_MISMATCH)


class BoundsTests(unittest.TestCase):
    def check(self, name, sets=(), deletes=(), code=None):
        source_id, observation = S.case(name)
        S.apply(observation, sets, deletes)
        self.assertEqual(code_of(ev.observe, observation, source_id=source_id, registry=S.REGISTRY), code)

    def test_size_and_count_ceilings(self):
        self.check("rs", [(["attributes", "padding"], "x" * ev.MAX_OBSERVATION_BYTES)],
                   code=errors.OBSERVATION_TOO_LARGE)
        self.check("deploy", [(["attributes", "changed_fields"], [f"spec.f{i}" for i in range(33)])],
                   code=errors.ATTRIBUTE_INVALID)
        self.check("deploy", [(["attributes", "changed_fields"], [f"spec.f{i}" for i in range(32)])])
        self.check("log", [(["attributes", "fields"], {f"k{i}": "v" for i in range(17)})], code=errors.ATTRIBUTE_INVALID)
        self.check("log", [(["attributes", "message"], "m" * 1025)], code=errors.ATTRIBUTE_INVALID)
        self.check("log", [(["attributes", "message"], "m" * 1024)])
        self.check("pod", [(["attributes", "restart_count"], 1_000_001)], code=errors.ATTRIBUTE_INVALID)
        self.check("pod", [(["attributes", "restart_count"], True)], code=errors.ATTRIBUTE_INVALID)
        self.check("pod", [(["attributes", "configmap_volumes"], [{"configmap": "a", "mount_path": "relative",
                                                                   "sub_path": False}])],
                   code=errors.ATTRIBUTE_INVALID)
        times = [{"timestamp_kind": "event", "raw": "2026-10-15T08:10:00Z", "clock_domain_id": "k8s-apiserver",
                  "declared_precision_ns": None}] * 5
        self.check("cm", [(["times"], times)], code=errors.RECORD_FIELD_INVALID)
        self.check("cm", [(["times"], [])], code=errors.RECORD_FIELD_INVALID)
        self.check("deploy", [(["times", 1, "timestamp_kind"], "event")], code=errors.ATTRIBUTE_INVALID)

    def test_credential_like_log_field_names(self):
        for key in ("password", "db_secret", "auth_token", "apikey", "authorization", "session_id", "cookie"):
            with self.subTest(key=key):
                self.check("log", [(["attributes", "fields", key], "x")], code=errors.ATTRIBUTE_FORBIDDEN)

    def test_untrusted_message_text_is_retained_inert(self):
        record = S.build("log")
        self.assertIn("kubectl delete", record.attributes["message"])
        self.assertEqual(record.observation_kind, "log_line")  # stored as data; nothing executes it

    def test_kind_registry_is_pinned(self):
        self.assertEqual({k: (s.evidence_class, s.source_kind) for k, s in ev.KINDS.items()}, {
            "configmap_change": ("K8S-CONFIG", "kubernetes_api"),
            "deployment_rollout": ("K8S-DEPLOY", "kubernetes_api"),
            "replicaset": ("K8S-DEPLOY", "kubernetes_api"),
            "pod": ("K8S-POD", "kubernetes_api"),
            "log_line": ("LOG", "loki"),
            "metric_sample": ("METRIC", "prometheus"),
            "alert_firing": ("ALERT", "prometheus"),
        })


class LedgerTests(unittest.TestCase):
    NAMES = ["deploy", "deploy-reordered", "deploy-changed", "cm", "cm-other-cluster", "log", "metric"]

    def test_final_state_is_independent_of_delivery_order(self):
        records = [S.build(n) for n in self.NAMES]
        rng = random.Random(29)
        orders = [list(range(len(records))), list(reversed(range(len(records))))]
        orders += [rng.sample(range(len(records)), len(records)) for _ in range(300)]
        reference = None
        for order in orders:
            ledger = ev.EvidenceLedger(S.REGISTRY)
            for i in order:
                ledger.admit(records[i])
            snapshot = canonical.canonical_bytes(ledger.snapshot())
            reference = reference or snapshot
            self.assertEqual(snapshot, reference)

    def test_identity_is_never_authoritative_under_two_digests(self):
        rng = random.Random(23)
        pool = [S.build(n) for n in self.NAMES + ["rs", "pod", "alert", "cm-invalid-time"]]
        for _ in range(200):
            ledger = ev.EvidenceLedger(S.REGISTRY)
            for record in rng.choices(pool, k=rng.randint(1, 12)):
                admission = ledger.admit(record)
                self.assertEqual(admission.state, ledger.state(record.evidence_id))
            for entry in ledger.snapshot()["entries"]:
                eid, digests = entry["evidence_id"], entry["content_digests"]
                if len(digests) == 1:
                    self.assertEqual(entry["state"], ev.AUTHORITATIVE)
                    self.assertEqual(ledger.authoritative(eid).content_digest, digests[0])
                    self.assertEqual(ledger.quarantined(eid), ())
                else:
                    self.assertEqual(entry["state"], ev.CONFLICTED)
                    self.assertIsNone(ledger.authoritative(eid))
                    self.assertEqual([r.content_digest for r in ledger.quarantined(eid)], sorted(digests))

    def test_conflicting_record_is_retained_not_overwritten(self):
        ledger = ev.EvidenceLedger(S.REGISTRY)
        original, changed = S.build("deploy"), S.build("deploy-changed")
        ledger.admit(original)
        result = ledger.admit(changed)
        self.assertEqual((result.outcome, result.state), (ev.CONFLICT_QUARANTINED, ev.CONFLICTED))
        self.assertEqual([r.content_digest for r in ledger.quarantined(original.evidence_id)],
                         sorted([original.content_digest, changed.content_digest]))
        self.assertIn(original, ledger.quarantined(original.evidence_id))
        self.assertIn(changed, ledger.quarantined(original.evidence_id))
        self.assertEqual(ledger.admit(original).outcome, ev.CONFLICT_QUARANTINED)  # conflict is sticky

    def test_tampered_record_is_rejected_and_ledger_unchanged(self):
        ledger = ev.EvidenceLedger(S.REGISTRY)
        ledger.admit(S.build("cm"))
        before = ledger.snapshot()
        forged = dataclasses.replace(S.build("deploy"), content_digest=S.build("cm").content_digest)
        self.assertEqual(code_of(ledger.admit, forged), errors.CONTENT_DIGEST_MISMATCH)
        sneaky = dataclasses.replace(S.build("deploy-changed"), content_digest=S.build("deploy").content_digest)
        self.assertEqual(code_of(ledger.admit, sneaky), errors.CONTENT_DIGEST_MISMATCH)
        self.assertEqual(ledger.snapshot(), before)
        self.assertEqual(code_of(ledger.admit, S.build("cm").to_record()), errors.RECORD_FIELD_INVALID)
        self.assertEqual(code_of(ev.EvidenceLedger, {}), errors.RECORD_FIELD_INVALID)


class ErrorHygieneTests(unittest.TestCase):
    CANARY = "canary-zz9-secret"

    def test_errors_never_echo_observed_values_or_keys(self):
        attempts = [
            ("cm", [(["attributes", "after_value"], self.CANARY)], ()),
            ("cm", [(["attributes", self.CANARY], "x")], ()),
            ("cm", [([self.CANARY], "x")], ()),
            ("cm", [(["observation_kind"], self.CANARY)], ()),
            ("cm", [(["entity", "namespace"], self.CANARY)], ()),
            ("cm", [(["entity", "name"], self.CANARY.upper())], ()),
            ("log", [(["attributes", "fields", self.CANARY + "_token"], "x")], ()),
            ("log", [(["attributes", "fields", "k"], self.CANARY + "\n")], ()),
            ("log", [(["times", 0, "clock_domain_id"], self.CANARY)], ()),
            ("rs", [(["attributes", "image"], self.CANARY + " ;rm -rf /")], ()),
        ]
        for name, sets, deletes in attempts:
            source_id, observation = S.case(name)
            S.apply(observation, sets, deletes)
            with self.subTest(name=name, sets=str(sets)[:40]):
                with self.assertRaises(ContractError) as ctx:
                    ev.observe(observation, source_id=source_id, registry=S.REGISTRY)
                self.assertNotIn("canary", str(ctx.exception).lower())
        with self.assertRaises(ContractError) as ctx:
            ev.observe(S.case("cm")[1], source_id=self.CANARY, registry=S.REGISTRY)
        self.assertNotIn("canary", str(ctx.exception).lower())

    def test_evidence_codes_are_pinned(self):
        self.assertEqual(errors.EVIDENCE_CODES, {
            "registry_invalid", "source_unknown", "source_scope_mismatch", "observation_kind_unsupported",
            "observation_too_large", "attribute_missing", "attribute_unknown", "attribute_invalid",
            "attribute_forbidden", "evidence_id_mismatch", "content_digest_mismatch"})

    def test_version_errors_are_typed(self):
        source_id, observation = S.case("cm")
        observation["contract_version"] = "ca-evidence/0.1-provisional"
        with self.assertRaises(VersionError):
            ev.observe(observation, source_id=source_id, registry=S.REGISTRY)


if __name__ == "__main__":
    unittest.main()
