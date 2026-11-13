"""CA-P2-004g: declared numeric limits are the only env values ever read (plan section 6.2)."""

import json
import unittest

import _fake_api  # noqa: F401  (adds src to the path)
from cloud_autopsy.app import k8s_recording as K
from cloud_autopsy.collector import limits as LIM
from cloud_autopsy.collector import project

DECLARED = LIM.check_declarations([("checkout-api", "DB_POOL_MAX", "pool.maxConnections")])


def rs_item(env, name="checkout-api", revision="2"):
    return {"metadata": {"name": f"checkout-api-{revision}", "namespace": "ca-incident", "uid": f"rs-{revision}",
                         "resourceVersion": "10", "creationTimestamp": "2026-11-13T10:00:00Z",
                         "annotations": {"deployment.kubernetes.io/revision": revision},
                         "ownerReferences": [{"controller": True, "kind": "Deployment", "name": "checkout-api",
                                              "uid": "dep-1"}]},
            "spec": {"template": {"spec": {"containers": [{"name": name, "image": "busybox@sha256:" + "a" * 64,
                                                            "env": env}]}}}}


class Projection(unittest.TestCase):
    def project(self, env, name="checkout-api"):
        counts = {}
        out = project.project("replicasets", rs_item(env, name), counts, DECLARED)
        return out["spec"]["template"]["spec"]["containers"][0].get("env", []), counts

    def test_only_a_declared_literal_integer_is_kept(self):
        env, counts = self.project([{"name": "DB_POOL_MAX", "value": "4"}, {"name": "API_TOKEN", "value": "PLANTED"},
                                    {"name": "OTHER", "value": "7"}])
        self.assertEqual(env, [{"name": "DB_POOL_MAX", "value": "4"}])
        self.assertEqual(counts, {})
        self.assertNotIn("PLANTED", json.dumps(env))

    def test_everything_else_is_withheld_and_counted(self):
        for entry in ({"name": "DB_POOL_MAX", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}},
                      {"name": "DB_POOL_MAX", "valueFrom": {"configMapKeyRef": {"name": "c", "key": "k"}}},
                      {"name": "DB_POOL_MAX", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
                      {"name": "DB_POOL_MAX", "valueFrom": {"resourceFieldRef": {"resource": "limits.cpu"}}},
                      {"name": "DB_POOL_MAX", "value": "4", "valueFrom": {"fieldRef": {}}},
                      *({"name": "DB_POOL_MAX", "value": v} for v in (" 4", "04", "1e3", "-4", "４", "4\n", "",
                                                                       "1234567", "4.0", "0x4"))):
            with self.subTest(entry=entry):
                env, counts = self.project([entry])
                self.assertEqual([e for e in env if "value" in e], [])
                self.assertEqual(counts.get("declared_limit_withheld"), 1)

    def test_a_declared_key_in_another_container_is_not_read(self):
        env, counts = self.project([{"name": "DB_POOL_MAX", "value": "4"}], name="sidecar")
        self.assertEqual(env, [])

    def test_without_declarations_nothing_changes(self):
        counts = {}
        out = project.project("replicasets", rs_item([{"name": "DB_POOL_MAX", "value": "4"}]), counts)
        self.assertNotIn("env", out["spec"]["template"]["spec"]["containers"][0])

    def test_declarations_are_checked(self):
        for bad in ([("checkout-api", "DB_PASSWORD", "pool.maxConnections")],
                    [("checkout-api", "API_TOKEN", "pool.maxConnections")],
                    [("checkout-api", "db_pool_max", "pool.maxConnections")],
                    [("Checkout", "DB_POOL_MAX", "pool.maxConnections")],
                    [("checkout-api", "DB_POOL_MAX", "secret.key")],
                    [("checkout-api", "DB_POOL_MAX", "a"), ("checkout-api", "DB_POOL_MAX", "b")],
                    "checkout-api", [("a", "B")]):
            with self.subTest(bad=bad), self.assertRaises(LIM.LimitDeclarationError):
                LIM.check_declarations(bad)


class FieldChanges(unittest.TestCase):
    def rollout(self, before, after, declared=DECLARED):
        old = {"template": project.project("replicasets", rs_item(before, revision="1"), {}, declared)["spec"]["template"]}
        new = {"template": project.project("replicasets", rs_item(after), {}, declared)["spec"]["template"]}
        for rs in (old, new):
            rs["image"], rs["config_refs"] = "busybox", []
        return K._field_changes(old, new, declared), K._changed_fields(old, new, declared)

    def test_a_lowered_limit_is_a_typed_field_change(self):
        changes, fields = self.rollout([{"name": "DB_POOL_MAX", "value": "16"}], [{"name": "DB_POOL_MAX", "value": "4"}])
        self.assertEqual([(c["config_key"], c["before_value"], c["after_value"]) for c in changes],
                         [("pool.maxConnections", "16", "4")])
        self.assertEqual(fields, ["spec.template.spec.containers[checkout-api].env[DB_POOL_MAX]"])

    def test_unchanged_withheld_or_one_sided_values_give_no_change(self):
        for before, after in (([{"name": "DB_POOL_MAX", "value": "4"}], [{"name": "DB_POOL_MAX", "value": "4"}]),
                              ([{"name": "DB_POOL_MAX", "value": "16"}],
                               [{"name": "DB_POOL_MAX", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}}]),
                              ([], [{"name": "DB_POOL_MAX", "value": "4"}])):
            with self.subTest(before=before, after=after):
                self.assertEqual(self.rollout(before, after)[0], [])

    def test_a_tampered_projected_value_is_refused_by_the_converter(self):
        old = {"template": {"spec": {"containers": [{"name": "checkout-api", "env": [{"name": "DB_POOL_MAX", "value": "16"}]}]}}}
        new = {"template": {"spec": {"containers": [{"name": "checkout-api", "env": [{"name": "DB_POOL_MAX", "value": "x4"}]}]}}}
        with self.assertRaises(K._ItemInvalid):
            K._field_changes(old, new, DECLARED)


if __name__ == "__main__":
    unittest.main()
