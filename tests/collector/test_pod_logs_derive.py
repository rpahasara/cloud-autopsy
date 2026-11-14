"""CA-P2-004g: pod-log derivation -- continuity, protocol-only brackets, handshake, identity (plan 4.3-4.9, 5).

A small simulator produces what the collector would record from a *true* timeline: each line has a true
write time ``w`` and append time ``a = w + d`` (the runtime's write-to-append delay ``d``, never known to
the product). Streams deliver what the kubelet would: a history stream every line appended so far and
later; a ``tailLines=0`` stream opened at ``O`` only lines appended after ``O`` (plus a kubelet start
latency). The tests then check what the product derives against the truth.
"""

import random
import unittest

import _fake_api  # noqa: F401  (adds src to the path)
from cloud_autopsy.app import pod_logs as P

S = 1_000_000_000
UID, UID2 = "6f1c2a7e-0000-4000-8000-000000000001", "6f1c2a7e-0000-4000-8000-000000000002"
POD, C = "checkout-api-7d9-abcde", "checkout-api"


class Sim:
    """True timeline of one container instance plus the collector's recorded entries."""

    def __init__(self, uid=UID, pod=POD, boot="0a1b2c3d", start=10 * S, delays=0, handshake=True, rng=None):
        self.uid, self.pod, self.boot = uid, pod, boot
        self.rng = rng or random.Random(7)
        self.delays = delays
        self.handshake = handshake
        self.lines = []          # (seq, w, a, template, fields, synced)
        self.t = start
        self.entries = []
        self.stream = 0

    def write(self, template, fields=None, gap_s=1.0):
        seq = len(self.lines) + 1
        w = self.t
        if self.handshake and self.lines:
            w = max(w, self.lines[-1][2] + 1)   # the workload waits for the previous append
        d = self.delays(seq) if callable(self.delays) else self.delays
        a = max(w + int(d * S), self.lines[-1][2] + 1 if self.lines else 0)
        synced = seq - 1 if self.handshake and seq > 1 else None
        if template == "STARTED":
            fields = {"pod_uid": self.uid, "container": C}
        self.lines.append((seq, w, a, template, fields or {}, synced))
        self.t = w + int(gap_s * S)
        return seq

    def run(self, n_heartbeats, symptom_from=None):
        self.write("STARTED")
        for i in range(n_heartbeats):
            if symptom_from is not None and i >= symptom_from:
                self.write("POOL_EXHAUSTED", {"pool": "checkout-db", "in_use": "8", "max": "4"})
            else:
                self.write("HEARTBEAT")
        return self

    def _line(self, seq):
        s, w, a, template, fields, synced = self.lines[seq - 1]
        return {"ts": "2026-11-13T10:00:00Z", "boot": self.boot, "seq": s, "synced": synced,
                "lag_ms": 1 if synced is not None else None, "template": template, "fields": dict(fields)}

    def open(self, mode, at, until=None, kubelet_latency=0, recheck_uid=None, recheck_status=200, skip=(),
             status=200):
        """Record one stream opened at ``at``; it delivers lines appended in (start, until]."""
        self.stream += 1
        n = self.stream
        self.entries.append({"type": "log_open", "stream": n, "pod": self.pod, "uid": self.uid, "container": C,
                             "mode": mode, "sent_ns": at, "http_status": status, "error": None})
        follow_from = at + kubelet_latency
        last = at
        if status == 200:
            for s, w, a, *_ in self.lines:
                if until is not None and a > until:
                    break
                if mode != "history" and a <= follow_from:
                    continue
                if s in skip:
                    continue
                received = max(a, at) + 1000
                last = max(last, received)
                self.entries.append({"type": "log_line", "stream": n, "received_ns": received, "line": self._line(s)})
        close = (until or last) + 1000
        self.entries.append({"type": "log_close", "stream": n, "at_ns": close, "code": "rotated"})
        self.entries.append({"type": "log_recheck", "stream": n, "sent_ns": close + 1, "received_ns": close + 2,
                             "http_status": recheck_status, "uid": recheck_uid or self.uid if recheck_status == 200 else None})
        return n

    def append_time(self, seq):
        return self.lines[seq - 1][2]

    def write_time(self, seq):
        return self.lines[seq - 1][1]


def pods(created_lower=5 * S, restarts=0, deleted=False, uid=UID, pod=POD):
    return {uid: {"name": pod, "containers": [C], "created_lower_ns": created_lower, "restarts_first": 0,
                  "restarts_max": restarts, "deleted": deleted}}


def names(*events):
    out = {}
    for at, name, uid, kind in events:
        out.setdefault(name, []).append((at, uid, kind))
    return {k: sorted(v) for k, v in out.items()}


NAMES = names((6 * S, POD, UID, "ADDED"))


def stream_everything(sim, end, rotation_s=5, latency=0):
    """History at 11 s, rotations every ``rotation_s`` (each until the next opens, with overlap), drain at end."""
    sim.open("history", 11 * S, until=13 * S)
    t = 12 * S
    while t < end:
        sim.open("rotation", t, until=t + rotation_s * S + S, kubelet_latency=latency)
        t += rotation_s * S
    return sim


class Clean(unittest.TestCase):
    def test_a_complete_instance_has_no_gap_and_bounded_symptoms(self):
        sim = Sim().run(60, symptom_from=40)
        p_end = sim.append_time(55)
        stream_everything(sim, sim.append_time(61) + S)
        d = P.derive(sim.entries, pods(), NAMES, p_end)
        self.assertEqual(d.gaps, [])
        info = d.instances[f"{UID}/{C}/0a1b2c3d"]
        self.assertTrue(info["covered_to_end"])
        self.assertGreater(info["handshake_bounds"], 0)
        symptoms = [l for l in d.lines if l["template"] == "POOL_EXHAUSTED"]
        self.assertEqual(len(symptoms), 20)
        for l in symptoms:
            self.assertLessEqual(l["lower_ns"], sim.write_time(l["seq"]))
            self.assertGreaterEqual(l["upper_ns"], sim.write_time(l["seq"]))
            self.assertGreater(l["lower_ns"], 5 * S)  # tightened beyond the pod-creation bound

    def test_a_stopped_instance_is_covered_without_a_drain(self):
        sim = Sim().run(10)
        sim.write("STOPPED")
        sim.open("history", 11 * S)
        d = P.derive(sim.entries, pods(), NAMES, p_end_ns=10 ** 15)
        self.assertEqual(d.gaps, [])


class TimingSensitivity(unittest.TestCase):
    """Delays below and above 2 s: every computed lower bound is at or before the true write time."""

    DELAYS = (0, 0.5, 1.9, 2.1, 5, 30)

    def check_bounds(self, sim, d):
        for l in d.lines:
            if l["lower_ns"] is not None:
                self.assertLessEqual(l["lower_ns"], sim.write_time(l["seq"]))
            self.assertGreaterEqual(l["upper_ns"], sim.write_time(l["seq"]))

    def test_with_the_handshake_bounds_are_always_safe(self):
        for delay in self.DELAYS:
            for latency in (0, int(0.3 * S)):
                with self.subTest(delay=delay, latency=latency):
                    sim = Sim(delays=delay).run(80, symptom_from=10)
                    stream_everything(sim, sim.append_time(81) + S, latency=latency)
                    d = P.derive(sim.entries, pods(), NAMES, sim.append_time(60))
                    self.check_bounds(sim, d)

    def test_without_the_handshake_only_the_pod_creation_bound_is_used(self):
        for delay in self.DELAYS:
            with self.subTest(delay=delay):
                sim = Sim(delays=delay, handshake=False).run(60, symptom_from=10)
                stream_everything(sim, sim.append_time(61) + S)
                d = P.derive(sim.entries, pods(), NAMES, sim.append_time(50))
                self.check_bounds(sim, d)
                self.assertEqual({l["lower_ns"] for l in d.lines}, {5 * S})
                self.assertIn((UID, C, "tail_unproven"), d.gaps)  # nothing establishes a write after p_end

    def test_without_any_bound_a_line_has_no_lower_time(self):
        sim = Sim(handshake=False).run(10, symptom_from=5)
        sim.write("STOPPED")
        sim.open("history", 11 * S)
        d = P.derive(sim.entries, pods(created_lower=None), NAMES, 10 ** 15)
        self.assertEqual({l["lower_ns"] for l in d.lines}, {None})

    def test_the_rejected_delta_rule_would_be_wrong_above_two_seconds(self):
        """With d > 2 s, O - 2 s lies after the true write of a line first delivered by a stream at O.
        The product never computes O - delta: its bound stays at or before the write."""
        sim = Sim(delays=5, handshake=False).run(30, symptom_from=0)
        o = sim.append_time(20) - S          # a stream opened 1 s before line 20's append
        sim.open("history", 11 * S)
        sim.open("rotation", o)
        d = P.derive(sim.entries, pods(), NAMES, 10 ** 15)
        line20 = next(l for l in d.lines if l["seq"] == 20)
        self.assertGreater(o - 2 * S, sim.write_time(20))   # what the rejected rule would claim: too late
        self.assertLessEqual(line20["lower_ns"], sim.write_time(20))


class HandshakeFaults(unittest.TestCase):
    def build(self, mutate):
        sim = Sim().run(40, symptom_from=20)
        stream_everything(sim, sim.append_time(41) + S)
        for e in sim.entries:
            if e["type"] == "log_line":
                mutate(e["line"])
        return P.derive(sim.entries, pods(), NAMES, sim.append_time(30))

    def test_a_missing_synced_removes_the_bound(self):
        d = self.build(lambda l: l.update(synced=None, lag_ms=None) if l["seq"] > 1 else None)
        self.assertEqual({l["lower_ns"] for l in d.lines}, {5 * S})
        self.assertIn((UID, C, "tail_unproven"), d.gaps)
        self.assertNotIn((UID, C, "timing_inconsistent"), d.gaps)

    def test_a_skipped_or_wrong_synced_is_a_known_violation(self):
        for mutate in (lambda l: l.update(synced=l["seq"] - 2) if l["seq"] == 25 else None,
                       lambda l: l.update(synced=5) if l["seq"] == 1 else None):
            d = self.build(mutate)
            self.assertIn((UID, C, "timing_inconsistent"), d.gaps)

    def test_a_line_claiming_to_follow_one_received_later_is_a_violation(self):
        sim = Sim().run(20, symptom_from=10)
        sim.open("history", 11 * S)
        n = sim.open("rotation", sim.append_time(12) - 1)
        lines = [e for e in sim.entries if e["type"] == "log_line" and e["stream"] == n]
        lines[0]["received_ns"], lines[1]["received_ns"] = lines[1]["received_ns"] + 10 ** 9, lines[0]["received_ns"]
        # the history stream also received both, so make the first copy of line j the late one
        for e in sim.entries:
            if e["type"] == "log_line" and e["stream"] != n and e["line"]["seq"] == lines[0]["line"]["seq"]:
                e["received_ns"] += 10 ** 10
        d = P.derive(sim.entries, pods(), NAMES, 10 ** 15)
        self.assertIn((UID, C, "timing_inconsistent"), d.gaps)

    def test_out_of_order_delivery_in_a_stream_is_a_violation(self):
        sim = Sim().run(20)
        sim.open("history", 11 * S)
        n = sim.open("rotation", sim.append_time(12) - 1)
        lines = [e for e in sim.entries if e["type"] == "log_line" and e["stream"] == n]
        lines[2]["line"], lines[3]["line"] = lines[3]["line"], lines[2]["line"]
        self.assertIn((UID, C, "timing_inconsistent"), P.derive(sim.entries, pods(), NAMES, 10 ** 15).gaps)


class Continuity(unittest.TestCase):
    def derive(self, sim, p_end=None, **kw):
        return P.derive(sim.entries, pods(**kw), NAMES, p_end if p_end is not None else sim.append_time(len(sim.lines)))

    def test_a_disconnect_without_overlap_is_a_sequence_gap(self):
        sim = Sim().run(40)
        sim.open("history", 11 * S, until=sim.append_time(10))
        sim.open("rotation", sim.append_time(15), until=None)   # lines 11-15 were never delivered
        self.assertIn((UID, C, "sequence_gap"), self.derive(sim).gaps)

    def test_late_attachment_misses_started(self):
        sim = Sim().run(20)
        sim.open("rotation", sim.append_time(5))
        gaps = self.derive(sim).gaps
        self.assertIn((UID, C, "boot_unverified"), gaps)
        self.assertIn((UID, C, "not_collected"), gaps)

    def test_a_dropped_line_or_truncation_is_a_sequence_gap(self):
        sim = Sim().run(20)
        sim.open("history", 11 * S, skip=(7,))
        self.assertIn((UID, C, "sequence_gap"), self.derive(sim).gaps)

    def test_a_conflicting_duplicate_is_an_identity_conflict(self):
        sim = Sim().run(20)
        sim.open("history", 11 * S)
        sim.open("rotation", sim.append_time(5))
        dup = [e for e in sim.entries if e["type"] == "log_line" and e["line"]["seq"] == 10]
        dup[1]["line"] = dict(dup[1]["line"], template="POOL_EXHAUSTED",
                              fields={"pool": "checkout-db", "in_use": "1", "max": "1"})
        self.assertIn((UID, C, "identity_conflict"), self.derive(sim).gaps)

    def test_an_unparseable_line_is_a_gap_and_partial_lines_are_only_counted(self):
        sim = Sim().run(10)
        sim.write("STOPPED")
        n = sim.open("history", 11 * S)
        sim.entries.append({"type": "log_partial", "stream": n, "at_ns": 99 * S})
        d = self.derive(sim)
        self.assertEqual(d.gaps, [])
        self.assertEqual(d.counts.get("lines_partial"), 1)
        sim.entries.append({"type": "log_line", "stream": n, "received_ns": 99 * S, "line": {"invalid": "envelope"}})
        self.assertIn((UID, C, "unparseable_line"), self.derive(sim).gaps)

    def test_a_restart_without_stopped_and_a_missing_instance_are_gaps(self):
        sim = Sim().run(10)
        sim.open("history", 11 * S)
        second = Sim(boot="0a1b2c3e", start=sim.t + S).run(10)
        second.write("STOPPED")
        second.stream = sim.stream
        second.open("history", second.t)
        sim.entries += second.entries
        gaps = self.derive(sim, p_end=10 ** 15, restarts=1).gaps
        self.assertIn((UID, C, "tail_unproven"), gaps)        # the first boot ended unseen
        only_first = Sim().run(10)
        only_first.write("STOPPED")
        only_first.open("history", 11 * S)
        self.assertIn((UID, C, "instance_missing"), self.derive(only_first, restarts=1).gaps)

    def test_lines_after_stopped_and_a_missing_drain(self):
        sim = Sim().run(5)
        sim.write("STOPPED")
        sim.write("HEARTBEAT")
        sim.open("history", 11 * S)
        self.assertIn((UID, C, "lines_after_stopped"), self.derive(sim).gaps)
        alive = Sim().run(30)
        alive.open("history", 11 * S)
        alive.open("rotation", alive.append_time(10))
        self.assertIn((UID, C, "tail_unproven"), self.derive(alive, p_end=alive.append_time(30) + S).gaps)

    def test_a_pod_never_collected_is_a_gap(self):
        d = P.derive([], pods(), NAMES, 10 * S)
        self.assertEqual(d.gaps, [(UID, C, "not_collected")])

    def test_a_failed_open_is_not_coverage(self):
        sim = Sim().run(5)
        sim.open("history", 11 * S, status=403)
        self.assertIn((UID, C, "not_collected"), self.derive(sim).gaps)


class Identity(unittest.TestCase):
    def clean(self):
        sim = Sim().run(10, symptom_from=5)
        sim.write("STOPPED")
        return sim

    def test_name_reuse_during_the_stream_attributes_nothing(self):
        sim = self.clean()
        sim.open("history", 11 * S)
        reused = names((6 * S, POD, UID, "ADDED"), (12 * S, POD, UID, "DELETED"), (13 * S, POD, UID2, "ADDED"))
        d = P.derive(sim.entries, pods(deleted=True), reused, 10 ** 15)
        self.assertIn((UID, C, "name_reused"), d.gaps)
        self.assertEqual(d.lines, [])

    def test_a_stream_opened_while_the_name_meant_another_pod_is_unbound(self):
        sim = self.clean()
        sim.open("history", 11 * S)
        other = names((6 * S, POD, UID2, "ADDED"))
        d = P.derive(sim.entries, pods(), other, 10 ** 15)
        self.assertIn((UID, C, "watch_unbound"), d.gaps)
        self.assertEqual(d.lines, [])

    def test_started_naming_another_pod_or_container_verifies_nothing(self):
        for fields in ({"pod_uid": UID2, "container": C}, {"pod_uid": UID, "container": "sidecar"}):
            sim = self.clean()
            sim.lines[0] = sim.lines[0][:4] + (fields,) + sim.lines[0][5:]
            sim.open("history", 11 * S)
            d = P.derive(sim.entries, pods(), NAMES, 10 ** 15)
            self.assertIn((UID, C, "boot_unverified"), d.gaps)
            self.assertEqual(d.lines, [])

    def test_the_recheck_must_confirm_the_uid(self):
        for status, uid, deleted, expected in ((200, UID2, False, "recheck_mismatch"), (404, None, False, "recheck_mismatch"),
                                               (500, None, False, "recheck_mismatch")):
            sim = self.clean()
            sim.open("history", 11 * S, recheck_uid=uid, recheck_status=status)
            d = P.derive(sim.entries, pods(deleted=deleted), NAMES, 10 ** 15)
            self.assertIn((UID, C, expected), d.gaps)
            self.assertEqual(d.lines, [])
        sim = self.clean()
        sim.open("history", 11 * S, recheck_status=404)
        self.assertEqual(P.derive(sim.entries, pods(deleted=True), NAMES, 10 ** 15).gaps, [])
        sim = self.clean()
        sim.open("history", 11 * S)
        sim.entries = [e for e in sim.entries if e["type"] != "log_recheck"]
        self.assertIn((UID, C, "recheck_missing"), P.derive(sim.entries, pods(), NAMES, 10 ** 15).gaps)


if __name__ == "__main__":
    unittest.main()
