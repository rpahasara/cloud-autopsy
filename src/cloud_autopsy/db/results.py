"""Clock declarations and immutable investigation results (CA-P2-006a). Provisional.

``declare_clocks``         ca_planner, while the run is collecting: freeze the run's clock
                           assumptions (``ca-clock-declaration/0.1-provisional``).
``investigate``            ca_engine, read-only: sealed run + its stored declaration -> engine
                           -> verified result bytes. The caller cannot supply clock domains.
``store_result``           ca_result_writer: write the result once.
``load_verified_result``   ca_engine, read-only: a stored result is returned only after it has
                           been re-verified against the sealed run and replayed byte for byte.

Write-once policy (both tables; the database enforces it with a primary key per run and
append-only triggers):
- first write: stored;
- the same bytes again (a retry, or two concurrent writers of one deterministic result):
  ``IDENTICAL``, nothing is written;
- different bytes for the same run: refused with ``ResultConflict`` / ``ClockDeclarationConflict``.
  Nothing is overwritten and nothing is quarantined: the deterministic engine cannot produce
  two results for one sealed input, so a second, different result is either a defect or
  tampering, and the first stored result stays authoritative. The refusal is the signal.
Every value is bound as a parameter.
"""

import hashlib
from dataclasses import dataclass

from ..contracts import canonical
from ..contracts.errors import ContractError
from ..engine import clocks, inputs, result
from .adapter import with_retry
from .read import SealedRunUnavailable, read_sealed_run

STORED, IDENTICAL = "stored", "identical"


class ResultConflict(RuntimeError):
    """A different result is already stored for this run; it was not overwritten."""


class ClockDeclarationConflict(RuntimeError):
    """A different clock declaration is already bound to this run; it was not replaced."""


class StoredResultUnavailable(RuntimeError):
    """No stored result for this run is visible to this role (or the run is not sealed)."""


class StoredResultInvalid(RuntimeError):
    """A stored result failed verification on read. ``code`` is stable."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


# --- clock declarations -------------------------------------------------------------------

def declare_clocks(planner_db, run_id, plan, registry, clock_domain_records):
    """Bind ``clock_domain_records`` to the run; return (outcome, ClockDeclaration)."""
    declaration = clocks.declare(registry, list(clock_domain_records))
    if plan.registry_digest != registry.digest:
        raise clocks.ClockDeclarationError("clock_declaration_registry_mismatch", "plan and registry differ")
    return with_retry(lambda: _declare_once(planner_db, run_id, plan, declaration)), declaration


def _declare_once(db, run_id, plan, declaration):
    with db.transaction():
        existing = db.one("SELECT declaration_digest FROM ca.run_clock_declaration WHERE run_id = CAST(:r AS uuid)",
                          r=run_id)
        if existing is None:
            inserted = db.run(
                "INSERT INTO ca.run_clock_declaration (run_id, plan_digest, registry_digest, contract_version, "
                "declaration_digest, declaration_bytes) VALUES (CAST(:r AS uuid), :p, :g, :v, :d, :b) "
                "ON CONFLICT (run_id) DO NOTHING RETURNING 1",
                r=run_id, p=plan.digest, g=declaration.registry_digest, v=clocks.CLOCK_DECLARATION_VERSION,
                d=declaration.digest, b=declaration.raw)
            if inserted:
                return STORED
            existing = db.one("SELECT declaration_digest FROM ca.run_clock_declaration "
                              "WHERE run_id = CAST(:r AS uuid)", r=run_id)
    if existing[0] == declaration.digest:
        return IDENTICAL
    raise ClockDeclarationConflict("a different clock declaration is already bound to this run")


# --- investigation and storage ------------------------------------------------------------

def _input_for(sealed):
    if sealed.clock_declaration_bytes is None:
        raise inputs.InputError("clock_declaration_missing", "the sealed run has no clock declaration")
    try:
        declaration = clocks.ClockDeclaration.from_bytes(sealed.clock_declaration_bytes, sealed.registry,
                                                         expected_digest=sealed.clock_declaration_digest)
    except clocks.ClockDeclarationError as exc:
        raise inputs.InputError(exc.code, "stored clock declaration refused") from None
    return inputs.build_input(sealed.frozen, sealed.plan, sealed.registry, sealed.evidence_records, declaration,
                              expected_manifest_digest=sealed.manifest_digest)


@dataclass(frozen=True)
class Investigation:
    run_id: str
    investigation_id: str
    result: dict
    result_bytes: bytes


def investigate(engine_db, run_id):
    """Investigate a sealed run with its own stored clock declaration; return verified bytes."""
    with engine_db.transaction(isolation="REPEATABLE READ", read_only=True):
        sealed = read_sealed_run(engine_db, run_id)
    inp = _input_for(sealed)
    _, raw = result.build(inp)
    return Investigation(run_id, sealed.investigation_id, result.verify_result(raw, inp), raw)


INSERT_RESULT = (
    "INSERT INTO ca.investigation_result (run_id, investigation_id, plan_digest, manifest_digest, "
    "clock_declaration_digest, contract_version, result_digest, engine_version, catalog_version, "
    "timeline_rules_version, outcome_status, result_bytes, result_bytes_sha256) VALUES (CAST(:r AS uuid), "
    "CAST(:i AS uuid), :p, :m, :c, :v, :d, :e, :k, :t, :o, :b, :h) ON CONFLICT (run_id) DO NOTHING RETURNING 1")


def result_row(run_id, investigation_id, result_bytes):
    """Bound parameters for ``INSERT_RESULT``; every column is taken from the bytes themselves."""
    raw = bytes(result_bytes)
    doc = canonical.loads(raw)
    if canonical.canonical_bytes(doc) != raw or not isinstance(doc, dict):
        raise StoredResultInvalid("result_not_canonical", "result bytes are not canonical")
    rules, inp = doc["rule_versions"], doc["inputs"]
    return dict(r=run_id, i=investigation_id, p=inp["plan_digest"], m=inp["manifest_digest"],
                c=inp["clock_declaration_digest"], v=doc["contract_version"], d=doc["result_digest"],
                e=doc["engine_version"], k=rules["mechanism-catalog"], t=rules["timeline-rules"],
                o=doc["outcome"]["status"], b=raw, h=hashlib.sha256(raw).hexdigest())


def store_result(writer_db, run_id, investigation_id, result_bytes):
    """Write the result once; return STORED or IDENTICAL; raise ResultConflict on different bytes."""
    row = result_row(run_id, investigation_id, result_bytes)
    return with_retry(lambda: _store_once(writer_db, row))


def _store_once(db, row):
    with db.transaction():
        inserted = db.run(INSERT_RESULT, **row)
        if inserted:
            return STORED
        existing = db.one("SELECT result_digest, result_bytes FROM ca.investigation_result "
                          "WHERE run_id = CAST(:r AS uuid)", r=row["r"])
    if existing[0] == row["d"] and bytes(existing[1]) == row["b"]:
        return IDENTICAL
    raise ResultConflict("a different result is already stored for this run")


# --- verify on read -----------------------------------------------------------------------

@dataclass(frozen=True)
class VerifiedResult:
    run_id: str
    investigation_id: str
    result_digest: str
    result: dict
    result_bytes: bytes


def _invalid(code, message):
    raise StoredResultInvalid(code, message)


def load_verified_result(engine_db, run_id):
    """Load the stored result and re-verify it completely before returning it.

    Checks, in order: canonical bytes and the stored SHA-256; the digest inside the document;
    that every stored column equals the field inside the bytes; that the result is bound to this
    run's investigation, plan, sealed manifest and clock declaration; the clock declaration bytes
    against their digest and the registry; and finally a full re-execution of the engine on the
    sealed evidence, which must reproduce the stored bytes exactly (``result.verify_result``).
    """
    with engine_db.transaction(isolation="REPEATABLE READ", read_only=True):
        row = engine_db.one(
            "SELECT CAST(investigation_id AS text), plan_digest, manifest_digest, clock_declaration_digest, "
            "contract_version, result_digest, engine_version, catalog_version, timeline_rules_version, "
            "outcome_status, result_bytes, result_bytes_sha256 FROM ca.sealed_investigation_result "
            "WHERE run_id = CAST(:r AS uuid)", r=run_id)
        if row is None:
            raise StoredResultUnavailable("no stored result for a sealed run with this ID")
        try:
            sealed = read_sealed_run(engine_db, run_id)
        except SealedRunUnavailable:
            raise StoredResultUnavailable("the run is not sealed or not visible") from None
    (investigation_id, plan_digest, manifest_digest, clock_digest, version, digest, engine_version,
     catalog_version, timeline_version, outcome_status, raw, raw_sha) = row
    raw = bytes(raw)
    if hashlib.sha256(raw).hexdigest() != raw_sha:
        _invalid("result_bytes_corrupt", "stored bytes do not match their stored SHA-256")
    try:
        doc = canonical.loads(raw)
        canonical_form = canonical.canonical_bytes(doc)
    except ContractError:
        _invalid("result_not_canonical", "stored bytes are not canonical JSON")
    if canonical_form != raw or not isinstance(doc, dict):
        _invalid("result_not_canonical", "stored bytes are not canonical")
    if doc.get("contract_version") != result.RESULT_VERSION or version != result.RESULT_VERSION:
        _invalid("result_version_unsupported", "stored result has an unsupported contract version")
    fields = (doc.get("result_digest"), doc.get("engine_version"), doc.get("rule_versions", {}).get("mechanism-catalog"),
              doc.get("rule_versions", {}).get("timeline-rules"), doc.get("inputs", {}).get("plan_digest"),
              doc.get("inputs", {}).get("manifest_digest"), doc.get("inputs", {}).get("clock_declaration_digest"),
              doc.get("outcome", {}).get("status"))
    if fields != (digest, engine_version, catalog_version, timeline_version, plan_digest, manifest_digest,
                  clock_digest, outcome_status):
        _invalid("result_columns_mismatch", "stored columns differ from the fields inside the result")
    if investigation_id != sealed.investigation_id or plan_digest != sealed.plan.digest \
            or manifest_digest != sealed.manifest_digest:
        _invalid("result_binding_mismatch", "result is not bound to this run's investigation, plan and manifest")
    if clock_digest != sealed.clock_declaration_digest:
        _invalid("clock_declaration_mismatch", "result was not produced from this run's clock declaration")
    try:
        inp = _input_for(sealed)
        verified = result.verify_result(raw, inp)  # digest, citations, outcome, byte-identical replay
    except inputs.InputError as exc:
        _invalid(exc.code, "stored result failed re-verification")
    except ContractError:
        _invalid("sealed_input_invalid", "the sealed run failed re-verification")
    return VerifiedResult(run_id, investigation_id, digest, verified, raw)
