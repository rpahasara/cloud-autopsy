"""CA-P2-006b hardening regressions (PR #24 review: H1 concurrency, H2 malformed results, logging).

Offline: no database. The real-PostgreSQL counterparts are in tests/integration/test_api.py.
"""

import copy
import hashlib
import http.client
import io
import threading
import unittest

import _api_support as A
from cloud_autopsy.api import service as svc
from cloud_autopsy.api.transport import LoopbackServer
from cloud_autopsy.contracts import canonical
from cloud_autopsy.engine import RESULT_DIGEST_ALGORITHM, inputs, result

LIMIT = svc.DEFAULT_MAX_IN_FLIGHT if hasattr(svc, "DEFAULT_MAX_IN_FLIGHT") else 4
FLOOD = 12


class _Headers(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class BlockingBackend(A.FakeBackend):
    """Every backend call blocks until released, and records the peak number of concurrent calls."""

    def __init__(self):
        super().__init__()
        self.release, self.lock, self.active, self.peak = threading.Event(), threading.Lock(), 0, 0
        self.entered = threading.Semaphore(0)

    def _enter(self):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        self.entered.release()
        self.release.wait(10)
        with self.lock:
            self.active -= 1

    def load_verified(self, run_id):
        self._enter()
        return super().load_verified(run_id)

    def check_ready(self):
        self._enter()


def flood(service, path, token):
    headers = _Headers({"Authorization": f"Bearer {token}"} if token else {})
    statuses, threads = [], []

    def call():
        statuses.append(service.handle("GET", path, headers))

    for _ in range(FLOOD):
        threads.append(threading.Thread(target=call))
        threads[-1].start()
    return statuses, threads


class ConcurrencyTests(unittest.TestCase):  # H1
    def make(self):
        _, tokens, _ = A.service()
        path, tokens = A.provision({"all": list(A.RUNS.values())})
        backend = BlockingBackend()
        service = svc.ApiService(A.G.load(path), backend.load_verified, backend.check_ready)
        return service, tokens["all"], backend

    def run_flood(self, path, token, expected_slots):
        service, real_token, backend = self.make()
        statuses, threads = flood(service, path, real_token if token else None)
        for _ in range(expected_slots):  # the admitted requests are now inside the backend
            self.assertTrue(backend.entered.acquire(timeout=10))
        for t in threads:  # everyone else must already have been answered, without waiting
            if t.is_alive():
                t.join(0.5)
        refused = [r for r in statuses if r.status == 503]
        self.assertEqual(len(refused), FLOOD - expected_slots)
        for r in refused:
            self.assertEqual(canonical.loads(r.body), {"error": "overloaded"})
            self.assertIn(("Retry-After", "1"), r.headers)
        backend.release.set()
        for t in threads:
            t.join(10)
        self.assertEqual(backend.peak, expected_slots)
        return [r for r in statuses if r.status != 503]

    def test_authorized_requests_are_bounded_with_deterministic_overload(self):
        admitted = self.run_flood(f"/v1/runs/{A.RUNS['config-cause']}/result", True, LIMIT)
        self.assertEqual([r.status for r in admitted], [200] * LIMIT)

    def test_readiness_probes_are_bounded_separately(self):
        admitted = self.run_flood("/readyz", False, svc.READY_MAX_IN_FLIGHT if hasattr(svc, "READY_MAX_IN_FLIGHT")
                                  else 1)
        self.assertTrue(all(r.status == 200 for r in admitted))

    def test_refusals_before_the_backend_do_not_consume_slots(self):
        service, token, backend = self.make()
        statuses, threads = flood(service, f"/v1/runs/{A.RUNS['config-cause']}/result", None)  # no token
        for t in threads:
            t.join(10)
        self.assertEqual([r.status for r in statuses], [401] * FLOOD)
        self.assertEqual(backend.peak, 0)


def _reencode(raw, mutate):
    doc = canonical.loads(raw)
    body = {k: v for k, v in doc.items() if k != "result_digest"}
    mutate(body)
    body["result_digest"] = f"{RESULT_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"
    return canonical.canonical_bytes(body)


MALFORMED = {
    "rule_versions_list": lambda b: b.update(rule_versions=[]),
    "inputs_string": lambda b: b.update(inputs="x"),
    "outcome_list": lambda b: b.update(outcome=[]),
    "hypotheses_object": lambda b: b.update(hypotheses={}),
    "hypothesis_not_object": lambda b: b.update(hypotheses=[1]),
    "prerequisites_null": lambda b: b["hypotheses"][0].update(prerequisites=None),
    "evidence_ids_string": lambda b: b["hypotheses"][0]["prerequisites"][0].update(evidence_ids="abc"),
    "ordering_not_object": lambda b: b["hypotheses"][0]["prerequisites"][0].update(orderings=["x"]),
    "contradictions_object": lambda b: b["hypotheses"][0].update(contradictions={"a": 1}),
    "outcome_reasons_number": lambda b: b["outcome"].update(reasons=1),
    "outcome_gap_ids_null": lambda b: b["outcome"].update(gap_ids=None),
}


class MalformedResultTests(unittest.TestCase):  # H2
    def test_self_consistent_malformed_documents_fail_closed_with_a_stable_code(self):
        inp = A.engine_support.build("config-cause")
        _, raw = result.build(inp)
        for name, mutate in MALFORMED.items():
            with self.subTest(case=name):
                bad = _reencode(raw, mutate)
                with self.assertRaises(inputs.InputError) as caught:
                    result.verify_result(bad, inp)
                self.assertEqual(caught.exception.code, "result_malformed")
        for doc in ([], "x", 1, None):
            with self.subTest(top_level=repr(doc)):
                with self.assertRaises(inputs.InputError) as caught:
                    result.verify_result(canonical.canonical_bytes(doc), inp)
                self.assertEqual(caught.exception.code, "result_malformed")

    def test_unexpected_backend_faults_become_a_bare_500(self):
        def broken(run_id):
            raise AttributeError("'list' object has no attribute 'get' -- stored secret-ish detail")

        path, tokens = A.provision({"all": [A.RUNS["config-cause"]]})
        service = svc.ApiService(A.G.load(path), broken, lambda: None)
        server = LoopbackServer(service, 0, quiet=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            con = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
            con.request("GET", f"/v1/runs/{A.RUNS['config-cause']}/result",
                        headers={"Authorization": f"Bearer {tokens['all']}"})
            response = con.getresponse()
            self.assertEqual((response.status, canonical.loads(response.read())), (500, {"error": "internal_error"}))
        finally:
            server.shutdown()
            server.server_close()


class LoggingTests(unittest.TestCase):  # access-log sanitization
    SECRET = "s3cr3t-Value-In-The-Url-0123456789abcdefghijk"

    def test_access_log_records_route_templates_only(self):
        service, tokens, _ = A.service()
        log = io.StringIO()
        server = LoopbackServer(service, 0, log=log)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        run = A.RUNS["config-cause"]
        requests = [("GET", f"/v1/runs/{run}/result?token={self.SECRET}"),
                    ("GET", f"/v1/runs/{run}/result%3Ftoken%3D{self.SECRET}"),
                    ("GET", f"/{self.SECRET}"),
                    ("GET", f"/v1/runs/{run}/evidence/{self.SECRET}"),
                    ("POST", f"/v1/runs/{run}/{self.SECRET}"),
                    (f"X{self.SECRET[:8].upper()}", "/healthz"),
                    ("GET", f"/v1/runs/{run}/result")]
        try:
            for method, path in requests:
                con = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
                con.request(method, path, headers={"Authorization": f"Bearer {tokens['all']}"})
                con.getresponse().read()
                con.close()
            raw = socket_request(server.port, f"GET /{self.SECRET} HTTP/1.1 extra\r\n\r\n".encode())
            self.assertTrue(raw.startswith(b"HTTP/1.1 400"))
            self.assertNotIn(self.SECRET.encode(), raw)  # no echo of the request line to the client either
        finally:
            server.shutdown()
            server.server_close()
        text = log.getvalue()
        self.assertNotIn(self.SECRET, text)
        self.assertNotIn(self.SECRET[:8].upper(), text)
        self.assertNotIn(tokens["all"], text)
        self.assertNotIn(run, text)  # route templates, not identifying values
        self.assertIn("GET /v1/runs/{run_id}/result 200", text)
        self.assertIn("<rejected>", text)


def socket_request(port, data):
    import socket
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(data)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


if __name__ == "__main__":
    unittest.main()
