"""CA-P2-004g (M12): a rollout outside the verified interval with a symptom inside it never yields a supported chain.

A rollout known only from the listed starting state (recording 0.6, M12c) carries no ``observed`` bracket: it
was not witnessed during the segment. Under rule profile 2 it cannot be ordered against a symptom's bracket,
so the chain is never supported. A rollout witnessed only after the symptoms is contradicted by them.
"""

import unittest

import test_ordering_rules as T
import test_pod_log_engine as P


class OutsideTheInterval(P.Base4):
    def hypothesis(self, inv):
        return next(h for h in inv.result["hypotheses"] if h["mechanism"] == "rollout_limit_reduction"
                    and h["change_evidence_id"])

    def test_a_listed_rollout_without_a_bracket_does_not_support_an_in_window_symptom(self):
        inv = self.run_case(P.spec4(roll=T.rollout(observed=None)))
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        self.assertNotEqual(self.hypothesis(inv)["status"], "supported")

    def test_a_rollout_witnessed_after_the_symptom_is_contradicted(self):
        late = T.rollout(observed=("2026-11-12T10:05:00.000000000Z", 1_000_000_000))
        inv = self.run_case(P.spec4(roll=late))
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        self.assertNotEqual(self.hypothesis(inv)["status"], "supported")


class TheEngineDoesNotScopeToThePlanWindow(P.Base4):
    """Why the M12d safeguard lives in the converter (``_window_decision``). The engine reads the plan window only
    for the result header and the frozen input's coverage holes; it evaluates every sealed observation. So a bundle
    whose window covers *other* times than its cause and symptoms still resolves. The converter therefore never
    narrows a window while a relevant change or symptom has a bracket outside it
    (tests/collector/test_window_scope.py). An engine-side guard is proposed separately (needs approval)."""

    def test_positive_control_inside_the_window_resolves(self):
        self.assertEqual(self.outcome(P.spec4())["status"], "resolved")

    def test_a_cause_and_symptom_before_the_window_still_resolve_in_the_engine_alone(self):
        roll = T.rollout(observed=("2026-11-12T09:50:00.000000000Z", 1_000_000_000))
        log = P.k8s_log(observed=("2026-11-12T09:55:00.000000000Z", 1_000_000_000))
        pods = T.pod(observed=("2026-11-12T09:51:00.000000000Z", 1_000_000_000))
        outcome = self.outcome(P.spec4(roll=roll, pods=pods, logs=[log]))   # the plan window is 10:00-10:10
        self.assertEqual(outcome["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
