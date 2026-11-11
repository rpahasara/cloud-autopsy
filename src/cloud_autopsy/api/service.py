"""Request handling for the local read-only investigation API (transport-independent).

Routes (GET only; everything else is 405):

  /healthz                                   liveness, no authentication, no database
  /readyz                                    readiness: the database answers, is classified
                                             synthetic and has this package's contract pins
  /v1/runs/{run_id}/result                   the verified investigation result document
  /v1/runs/{run_id}/timeline                 its deterministic timeline
  /v1/runs/{run_id}/hypotheses               hypotheses and outcome
  /v1/runs/{run_id}/citations                per-hypothesis citations, contradictions and gaps
  /v1/runs/{run_id}/evidence/{evidence_hex}  one sealed evidence record of that run; the path
                                             carries the 64-hex digest of the evidence ID
                                             (``ca-evidence-id-sha256/0.1-provisional:<hex>``)

Order of checks for ``/v1``: method, request body, path shape (strict regular expressions, no
query string, no percent-encoding), bearer token, explicit run grant, then verify-on-read.
A run that is not granted is refused (403) before the database is touched, so the answer does
not reveal whether the run exists. A granted run is served only after
``load_verified_result`` succeeds: a verification failure is reported as an error code and
never falls back to database rows. Errors carry a stable code and nothing else.

Concurrency (PR #24 review, H1): work that reaches the database (a database connection, a
full reload of the sealed run and an engine replay) is admitted through two non-blocking
gates: at most ``max_in_flight`` verified reads (default 4) and, separately, at most
``READY_MAX_IN_FLIGHT`` readiness probes (1), so an unauthenticated readiness flood cannot
starve verified reads. A request that finds its gate full is answered at once with
``503 {"error": "overloaded"}`` and ``Retry-After: 1``; nothing queues. Refusals that need no
backend (400/401/403/404/405/413/414/431) are answered without taking a slot. Together the
gates bound the API's database connections to ``max_in_flight + READY_MAX_IN_FLIGHT``.

Run summaries (CA-P2-006d): ``/v1/summaries/{page}`` pages through the run IDs in the caller's
own grant (never any other run), in run-ID order, ``SUMMARY_PAGE_SIZE`` per page. Every run on
the page is loaded through the same verify-on-read loader before anything about it is returned;
a run that fails is reported only by state (``unverifiable`` with its reason, ``not_found`` or
``unavailable``), never with data. Any other failure while one run is verified or summarized is
contained to that run: it is listed as ``error`` (no reason, no data, never verified), the rest of
the page is still served, and only the exception's class name is logged (never its message, the
run ID, a token or any evidence). One page request holds a single slot of the verified-read
gate and verifies its runs one after another, so the work per request is bounded and the
existing concurrency limits still hold. There is no unrestricted listing and no aggregation
beyond the page: totals across pages are left to the client, which knows how much it examined.

Dashboard (CA-P2-006c): when built with ``ui`` assets (``ui.load_assets()``), ``GET /`` and a
fixed set of ``/ui/...`` paths return the static read-only dashboard with its own strict CSP.
No other route changes. ``preview=True`` is used only by the labelled synthetic preview
(``app.preview``): results are then computed in memory from fixtures, never read from a sealed
run, and every ``/v1`` envelope says ``"verified": false`` and ``"data_source": "synthetic-preview"``.
"""

import re
import threading
from dataclasses import dataclass, field

from ..contracts import canonical
from ..contracts.errors import ContractError
from . import API_VERSION
from .grants import UUID
from .ui import UI_HEADERS

MAX_PATH = 256
MAX_HEADER_BYTES = 8_192
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_IN_FLIGHT = 4      # PROVISIONAL
READY_MAX_IN_FLIGHT = 1
OVERLOADED_HEADERS = (("Retry-After", "1"),)
EVIDENCE_ID_PREFIX = "ca-evidence-id-sha256/0.1-provisional:"
EVIDENCE_HEX = re.compile(r"[0-9a-f]{64}", re.ASCII)
_RUN_ROUTE = re.compile(r"/v1/runs/([^/]+)/(result|timeline|hypotheses|citations)", re.ASCII)
_EVIDENCE_ROUTE = re.compile(r"/v1/runs/([^/]+)/evidence/([^/]+)", re.ASCII)
_SUMMARY_ROUTE = re.compile(r"/v1/summaries/([0-9]{1,4})", re.ASCII)
SUMMARY_PAGE_SIZE = 10     # PROVISIONAL: verified loads per summary request
_PATH_CHARS = re.compile(r"[A-Za-z0-9/._:-]+", re.ASCII)
SECURITY_HEADERS = (("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"),
                    ("X-Content-Type-Options", "nosniff"), ("Content-Security-Policy", "default-src 'none'"),
                    ("Referrer-Policy", "no-referrer"))


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: tuple = field(default=SECURITY_HEADERS)


class Unavailable(Exception):
    """Raised by a loader: no stored result for this run (or the run is not sealed)."""


class Unverifiable(Exception):
    """Raised by a loader: the stored result failed verification. ``code`` is stable."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class BackendDown(Exception):
    """Raised by a loader or readiness probe: the database could not be used."""


def _json(status, document, extra=()):
    try:
        body = canonical.canonical_bytes(document)
    except ContractError:
        return _error(500, "response_too_large")
    if len(body) > MAX_RESPONSE_BYTES:
        return _error(500, "response_too_large")
    return Response(status, body, SECURITY_HEADERS + tuple(extra))


def _error(status, code, extra=()):
    return Response(status, canonical.canonical_bytes({"error": code}), SECURITY_HEADERS + tuple(extra))


def _cited(hypothesis):
    ids = {e for p in hypothesis["prerequisites"] for e in p["evidence_ids"]}
    ids |= {e for p in hypothesis["prerequisites"] for o in p["orderings"] for e in (o["a"], o["b"])}
    ids |= {e for c in hypothesis["contradictions"] for e in c["evidence_ids"]}
    return sorted(ids)


def _summary(run_id, verified, preview):
    """A compact digest of one verified result: only fields read from the verified document."""
    r = verified.result
    entries = r["timeline"]["entries"]
    by_source = {}
    seen = set()
    for e in entries:
        if e["evidence_id"] in seen:
            continue
        seen.add(e["evidence_id"])
        by_source.setdefault(e["source_id"], {"records": 0, "gaps": 0})["records"] += 1
    for gap in r["gaps"]:
        by_source.setdefault(gap["source_id"], {"records": 0, "gaps": 0})["gaps"] += 1
    cited = set(r["outcome"]["evidence_ids"])
    statuses = {}
    for h in r["hypotheses"]:
        cited.update(_cited(h))
        statuses[h["status"]] = statuses.get(h["status"], 0) + 1
    item = {"run_id": run_id, "state": "preview" if preview else "verified", "verified": not preview,
            "result_digest": verified.result_digest, "plan_id": r["inputs"]["plan_id"],
            "window": r["inputs"]["window"],
            "outcome": {"status": r["outcome"]["status"], "mechanism": r["outcome"]["mechanism"],
                        "reasons": r["outcome"]["reasons"]},
            "manifest": {"status": r["inputs"]["manifest_status"], "limitations": r["inputs"]["manifest_limitations"]},
            "evidence": {"records": len(seen), "cited": len(cited & seen), "by_source": by_source},
            "gaps": {"total": len(r["gaps"]), "mandatory": sum(1 for g in r["gaps"] if g["mandatory"]),
                     "reasons": sorted({reason for g in r["gaps"] for reason in g["reasons"]})},
            "hypotheses": statuses,
            "ordering": {"unplaced": sum(1 for e in entries if not e["reference_ms"]),
                         "unordered_pairs": sum(1 for o in r["timeline"]["adjacent_orderings"] if o["order"] != "before")}}
    return item


def _views(result):
    return {
        "result": result,
        "timeline": result["timeline"],
        "hypotheses": {"outcome": result["outcome"], "hypotheses": result["hypotheses"]},
        "citations": {
            "outcome": {"status": result["outcome"]["status"], "evidence_ids": result["outcome"]["evidence_ids"],
                        "gap_ids": result["outcome"]["gap_ids"], "reasons": result["outcome"]["reasons"]},
            "hypotheses": [{"hypothesis_id": h["hypothesis_id"], "mechanism": h["mechanism"], "status": h["status"],
                            "cited_evidence_ids": _cited(h), "contradictions": h["contradictions"],
                            "limiting_gap_ids": h["limiting_gap_ids"]} for h in result["hypotheses"]],
            "gaps": result["gaps"],
        },
    }


class ApiService:
    """``load_verified(run_id)`` returns an object with ``result_digest``, ``result`` (the verified
    document) and ``evidence`` ({evidence_id: {"coverage", "record"}}), or raises ``Unavailable``,
    ``Unverifiable`` or ``BackendDown``. ``check_ready()`` returns or raises ``BackendDown``."""

    def __init__(self, grants, load_verified, check_ready, max_in_flight=DEFAULT_MAX_IN_FLIGHT, ui=None,
                 preview=False, log=None):
        if not 1 <= int(max_in_flight) <= 64:
            raise ValueError("max_in_flight must be between 1 and 64")
        self.grants, self.load_verified, self.check_ready = grants, load_verified, check_ready
        self.ui, self.preview = dict(ui or {}), bool(preview)
        self.log = log  # ``log(line)`` for safe diagnostics; the loopback transport supplies its own
        self._work = threading.BoundedSemaphore(int(max_in_flight))
        self._ready = threading.BoundedSemaphore(READY_MAX_IN_FLIGHT)

    @staticmethod
    def _admitted(gate, operation):
        """Run ``operation()`` if ``gate`` has a free slot; otherwise answer 503 overloaded at once."""
        if not gate.acquire(blocking=False):
            return None, _error(503, "overloaded", OVERLOADED_HEADERS)
        try:
            return operation(), None
        finally:
            gate.release()

    def route_template(self, method, path):
        """A loggable form of the request: a fixed route template, never user-supplied values."""
        if method not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            return "-", "<rejected>"
        if path in ("/healthz", "/readyz") or path in self.ui:
            return method, path
        if len(path) <= MAX_PATH and _PATH_CHARS.fullmatch(path):
            if _RUN_ROUTE.fullmatch(path):
                return method, "/v1/runs/{run_id}/" + _RUN_ROUTE.fullmatch(path).group(2)
            if _EVIDENCE_ROUTE.fullmatch(path):
                return method, "/v1/runs/{run_id}/evidence/{evidence_hex}"
            if _SUMMARY_ROUTE.fullmatch(path):
                return method, "/v1/summaries/{page}"
        return method, "<rejected>"

    def handle(self, method, path, headers, header_bytes=0):
        """``headers``: case-insensitive mapping of request headers."""
        if method != "GET":
            return _error(405, "method_not_allowed", (("Allow", "GET"),))
        if header_bytes > MAX_HEADER_BYTES:
            return _error(431, "headers_too_large")
        if headers.get("Transfer-Encoding") is not None:
            return _error(400, "request_body_not_allowed")
        length = headers.get("Content-Length")
        if length is not None and length.strip() != "0":
            return _error(413, "request_body_not_allowed")
        if len(path) > MAX_PATH:
            return _error(414, "path_too_long")
        if not _PATH_CHARS.fullmatch(path):
            return _error(400, "invalid_path")  # rejects query strings, percent-encoding, spaces
        if path in self.ui:
            content_type, body = self.ui[path]
            return Response(200, body, (("Content-Type", content_type),) + UI_HEADERS)
        if path == "/healthz":
            return _json(200, {"api_version": API_VERSION, "status": "ok"})
        if path == "/readyz":
            def probe():
                try:
                    self.check_ready()
                except BackendDown:
                    return _error(503, "not_ready")
                return _json(200, {"api_version": API_VERSION, "status": "ready"})
            response, overloaded = self._admitted(self._ready, probe)
            return overloaded or response

        summary_match = _SUMMARY_ROUTE.fullmatch(path)
        if summary_match:
            return self._summaries(summary_match.group(1), headers)

        match = _RUN_ROUTE.fullmatch(path)
        evidence_match = _EVIDENCE_ROUTE.fullmatch(path)
        if not match and not evidence_match:
            return _error(404, "route_not_found")
        run_id = (match or evidence_match).group(1)
        if not UUID.fullmatch(run_id):
            return _error(400, "invalid_run_id")
        evidence_id = None
        if evidence_match:
            if not EVIDENCE_HEX.fullmatch(evidence_match.group(2)):
                return _error(400, "invalid_evidence_id")
            evidence_id = EVIDENCE_ID_PREFIX + evidence_match.group(2)

        grant = self.grants.authenticate(headers.get("Authorization"))
        if grant is None:
            return _error(401, "invalid_token", (("WWW-Authenticate", 'Bearer realm="cloud-autopsy-local"'),))
        if not grant.authorizes(run_id):
            return _error(403, "run_not_authorized")

        def load():
            try:
                return self.load_verified(run_id), None
            except Unavailable:
                return None, _error(404, "run_not_found")
            except Unverifiable as exc:
                return None, _json(409, {"error": "result_unverifiable", "reason": exc.code})
            except BackendDown:
                return None, _error(503, "database_unavailable")

        loaded, overloaded = self._admitted(self._work, load)
        if overloaded:
            return overloaded
        verified, failure = loaded
        if failure:
            return failure

        envelope = {"api_version": API_VERSION, "run_id": run_id, "result_digest": verified.result_digest,
                    "verified": True,
                    "verification": "re-executed from the sealed run; byte-identical to the stored result"}
        if self.preview:
            envelope.update(verified=False, data_source="synthetic-preview",
                            verification="synthetic preview: computed in memory from fixtures; not read from "
                                         "or verified against a sealed database run")
        if evidence_id is not None:
            member = verified.evidence.get(evidence_id)
            if member is None:
                return _error(404, "evidence_not_found")
            cited_by = sorted(h["hypothesis_id"] for h in verified.result["hypotheses"] if evidence_id in _cited(h))
            return _json(200, {**envelope, "data": {"evidence_id": evidence_id, "coverage": member["coverage"],
                                                    "cited_by_hypothesis_ids": cited_by,
                                                    "record": member["record"]}})
        return _json(200, {**envelope, "data": _views(verified.result)[match.group(2)]})

    def _summaries(self, page_text, headers):
        if page_text.startswith("0"):
            return _error(400, "invalid_page")
        grant = self.grants.authenticate(headers.get("Authorization"))
        if grant is None:
            return _error(401, "invalid_token", (("WWW-Authenticate", 'Bearer realm="cloud-autopsy-local"'),))
        runs = sorted(grant.run_ids)  # only this grant's runs, in a deterministic order
        pages = max(1, -(-len(runs) // SUMMARY_PAGE_SIZE))
        page = int(page_text)
        if page > pages:
            return _error(404, "page_not_found")
        chunk = runs[(page - 1) * SUMMARY_PAGE_SIZE: page * SUMMARY_PAGE_SIZE]

        def failed(run_id, exc):
            # Contained to this run: a generic state, no data, never verified. Logged by class only.
            if self.log:
                self.log(f"api summary_item_error {type(exc).__name__}")
            return {"run_id": run_id, "state": "error"}

        def summarize():
            items = []
            for run_id in chunk:  # one at a time: one database connection, inside one gate slot
                try:
                    verified = self.load_verified(run_id)
                except Unavailable:
                    items.append({"run_id": run_id, "state": "not_found"})
                    continue
                except Unverifiable as exc:
                    items.append({"run_id": run_id, "state": "unverifiable", "reason": exc.code})
                    continue
                except BackendDown:
                    items.append({"run_id": run_id, "state": "unavailable"})
                    continue
                except Exception as exc:  # noqa: BLE001 -- contained to this run and logged by class
                    items.append(failed(run_id, exc))
                    continue
                try:
                    items.append(_summary(run_id, verified, self.preview))
                except Exception as exc:  # noqa: BLE001 -- a result that cannot be summarized shows no data
                    items.append(failed(run_id, exc))
            return items

        items, overloaded = self._admitted(self._work, summarize)
        if overloaded:
            return overloaded
        document = {"api_version": API_VERSION, "granted_total": len(runs), "page": page, "pages": pages,
                    "page_size": SUMMARY_PAGE_SIZE, "order": "run_id", "items": items,
                    "verification": ("synthetic preview: computed in memory from fixtures; not read from or verified "
                                     "against a sealed database run") if self.preview else
                                    ("each available item was re-executed from its sealed run and is byte-identical "
                                     "to the stored result; other items carry only their state")}
        if self.preview:
            document["data_source"] = "synthetic-preview"
        return _json(200, document)
