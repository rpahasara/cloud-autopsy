"""CA-P2-004g causal-scope guard: rule profile 3 (timeline rules 0.3).

Under 0.3, a change or a symptom establishes a positive prerequisite only when its ``observed`` bracket lies
entirely inside the plan window (here 10:00-10:10). Contradictions still use every observation, inside the window
or not; identity evidence (pods) needs no bracket in the window. Profiles 1 and 2 are unchanged (the six pinned
digests are asserted in test_cross_scope.py, and profile 2 still resolves the out-of-window case below).
"""

import unittest

import test_ordering_rules as T
import test_pod_log_engine as P

BEFORE, AFTER = "2026-11-12T09:5", "2026-11-12T10:1"


def at(text, width_ns=1_000_000_000):
    return (text, width_ns)


class Profile3(P.Base4):
    def run3(self, roll=None, pods=None, logs=None, profile=3):
        return self.run_case(P.spec4(roll=roll, pods=pods, logs=logs), profile)

    def hypothesis(self, inv):
        return next(h for h in inv.result["hypotheses"] if h["mechanism"] == "rollout_limit_reduction"
                    and h["change_evidence_id"])

    def prereq(self, inv, key):
        return next(p for p in self.hypothesis(inv)["prerequisites"] if p["key"] == key)

    def test_1_rollout_and_symptom_inside_the_window_resolve(self):
        inv = self.run3()
        self.assertEqual((inv.result["outcome"]["status"], inv.result["outcome"]["mechanism"]),
                         ("resolved", "rollout_limit_reduction"))
        self.assertEqual(inv.result["rule_versions"]["timeline-rules"], "ca-timeline-rules/0.3-provisional")

    def test_2_rollout_and_symptom_outside_never_resolve_the_window(self):
        roll = T.rollout(observed=at("2026-11-12T09:50:00.000000000Z"))
        pods = T.pod(observed=at("2026-11-12T09:51:00.000000000Z"))
        logs = [P.k8s_log(observed=at("2026-11-12T09:55:00.000000000Z"))]
        inv = self.run3(roll, pods, logs)
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        self.assertEqual(self.prereq(inv, "rollout_observed")["reason"], "outside_plan_window")
        self.assertEqual(self.prereq(inv, "symptom_on_new_revision_after_rollout")["result"], "unsatisfied")
        # Profile 2 is unchanged: the same bundle resolves there (why profile 3 exists).
        self.assertEqual(self.run3(roll, pods, logs, profile=2).result["outcome"]["status"], "resolved")

    def test_3_rollout_outside_symptom_inside_is_not_attributed(self):
        inv = self.run3(roll=T.rollout(observed=at("2026-11-12T09:59:00.000000000Z")))
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        self.assertNotEqual(self.hypothesis(inv)["status"], "supported")
        self.assertEqual(self.prereq(inv, "rollout_observed")["reason"], "outside_plan_window")

    def test_rollout_inside_symptoms_after_the_window_do_not_support(self):
        inv = self.run3(logs=[P.k8s_log(observed=at("2026-11-12T10:12:00.000000000Z"))])
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        self.assertEqual(self.prereq(inv, "symptom_on_new_revision_after_rollout")["result"], "unsatisfied")

    def test_a_bracket_straddling_the_window_edge_does_not_count(self):
        inv = self.run3(logs=[P.k8s_log(observed=at("2026-11-12T10:09:59.500000000Z"))])
        self.assertEqual(inv.result["outcome"]["status"], "abstained")

    def test_4_a_contradiction_outside_the_window_stays_visible(self):
        early = P.k8s_log(seq=5, observed=at("2026-11-12T09:58:00.000000000Z"))
        inv = self.run3(logs=[early, P.k8s_log(seq=40)])
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        self.assertIn("contradicting_evidence_present", inv.result["outcome"]["reasons"])
        keys = {c["key"] for c in self.hypothesis(inv)["contradictions"]}
        self.assertIn("symptom_precedes_rollout", keys)

    def test_identity_evidence_needs_no_bracket_in_the_window(self):
        inv = self.run3(pods=T.pod(observed=None))
        self.assertEqual(inv.result["outcome"]["status"], "resolved")

    def test_false_cause_traps_still_abstain(self):
        for roll in (T.rollout(field_changes=False), T.rollout(after="60")):
            self.assertEqual(self.run3(roll=roll).result["outcome"]["status"], "abstained")

    def test_profile_3_needs_observed_brackets_and_one_session_clock(self):
        with self.assertRaises(Exception) as ctx:
            self.run_case(P.spec4(logs=[P.k8s_log(domain=T.COL2)]), 3, domains=(T.COL, T.COL2, T.SRV, P.RUNTIME))
        self.assertIn("observed_clock_domains_mixed", repr(ctx.exception) + repr(ctx.exception.__cause__))


if __name__ == "__main__":
    unittest.main()
