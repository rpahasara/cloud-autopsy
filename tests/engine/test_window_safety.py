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


if __name__ == "__main__":
    unittest.main()
