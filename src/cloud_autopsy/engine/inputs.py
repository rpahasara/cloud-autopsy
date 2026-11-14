"""Verified engine input: a sealed manifest, exactly its evidence and declared clock domains.

The engine never trusts its caller's bytes:
- the manifest root and every page are verified with ``frozen_input.verify_full`` against the
  plan and registry (and an expected manifest digest when the caller has one);
- the plan must pin exactly this engine's rule versions;
- every evidence record is strictly decoded with ``ObservedEvidence.from_record``, which
  re-derives its identity, content digest and time fields;
- the decoded set must equal the manifest's evidence membership exactly: nothing missing,
  nothing extra, no second copy, and each content digest equal to the sealed one;
- the clock assumptions are one frozen ``ca-clock-declaration`` for this registry, covering
  exactly the registered clock domains (``engine.clocks``).
Conflicted identities are not members (the seal quarantines them as identity gaps), so they
can never be cited as support.
"""

from dataclasses import dataclass

from ..contracts import canonical
from ..contracts import frozen_input as fi
from ..contracts.evidence import ObservedEvidence
from ..contracts.plan import RunPlan
from ..contracts.sources import SourceRegistry
from ..contracts.evidence import KIND_REGISTRY_VERSION_V3, KIND_REGISTRY_VERSION_V4, OBSERVED_TIME
from . import rule_profile
from .clocks import ClockDeclaration, ClockDeclarationError, declare

MAX_EVIDENCE = 5_000            # PROVISIONAL engine bound (unreviewed)


class InputError(RuntimeError):
    """Engine input refused. ``code`` is stable; messages never echo input values."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class Member:
    evidence: ObservedEvidence
    coverage: str  # verified | unverified (frozen-input qualification)


@dataclass(frozen=True)
class InvestigationInput:
    plan: RunPlan
    registry: SourceRegistry
    manifest_digest: str
    manifest_status: str
    manifest_limitations: tuple
    members: tuple          # Member, sorted by evidence_id
    gaps: tuple             # frozen-input gap items, sorted by gap_id
    clock_domains: dict     # clock_domain_id -> ti.ClockDomain
    clock_domain_records: tuple
    clock_declaration: ClockDeclaration

    @property
    def timeline_rules(self):
        """The timeline-rules version the plan pins (it selects the ordering stamp)."""
        return dict(self.plan.rule_versions)["timeline-rules"]

    def evidence(self, evidence_id):
        for member in self.members:
            if member.evidence.evidence_id == evidence_id:
                return member.evidence
        return None


def _record(item):
    if isinstance(item, (bytes, bytearray, memoryview)):
        return canonical.loads(bytes(item))
    if isinstance(item, dict):
        return item
    raise InputError("evidence_record_invalid", "evidence records must be canonical bytes or objects")


def build_input(frozen, plan, registry, evidence_records, clock_declaration, expected_manifest_digest=None):
    """``clock_declaration``: a verified ``ClockDeclaration``, or clock-domain records to declare."""
    if not isinstance(frozen, fi.FrozenInput) or not isinstance(plan, RunPlan) \
            or not isinstance(registry, SourceRegistry):
        raise InputError("input_invalid", "a FrozenInput, RunPlan and SourceRegistry are required")
    profile = rule_profile(plan.rule_versions)
    if profile is None:
        raise InputError("rule_versions_mismatch", "the plan does not pin exactly one of this engine's rule profiles")
    # Rule profile 2 needs observed brackets: contract profile 3 (kinds 0.3) or, since CA-P2-005c, contract
    # profile 4 (kinds 0.4, which adds pod logs read through the Kubernetes API).
    if profile in (2, 3) and plan.kind_registry_version not in (KIND_REGISTRY_VERSION_V3, KIND_REGISTRY_VERSION_V4):
        raise InputError("rule_profile_unsupported",
                         "rule profile 2 needs contract profile 3 or 4 (observation kinds 0.3 or 0.4)")
    root, pages = frozen.root(), frozen.pages()
    fi.verify_full(root, pages, plan, registry, expected_manifest_digest)

    sealed = {item["evidence_id"]: item for item in fi.collection_items(frozen, "evidence")}
    records = list(evidence_records)
    if len(records) > MAX_EVIDENCE or len(sealed) > MAX_EVIDENCE:
        raise InputError("limit_exceeded", f"more than {MAX_EVIDENCE} evidence records")
    members = {}
    for item in records:
        evidence = ObservedEvidence.from_record(_record(item), registry, plan.kind_registry_version)
        expected = sealed.get(evidence.evidence_id)
        if expected is None:
            raise InputError("evidence_not_in_manifest", "an evidence record is not a member of the sealed manifest")
        if evidence.content_digest != expected["content_digest"]:
            raise InputError("evidence_digest_mismatch", "an evidence record differs from the sealed content digest")
        if evidence.evidence_id in members:
            raise InputError("evidence_duplicated", "an evidence record was supplied twice")
        members[evidence.evidence_id] = Member(evidence, expected["coverage"])
    if set(members) != set(sealed):
        raise InputError("evidence_missing", "a sealed evidence member has no record")

    try:
        if not isinstance(clock_declaration, ClockDeclaration):
            clock_declaration = declare(registry, list(clock_declaration))
        elif clock_declaration.registry_digest != registry.digest:
            raise ClockDeclarationError("clock_declaration_registry_mismatch",
                                        "declaration was made for a different source registry")
    except ClockDeclarationError as exc:
        raise InputError(exc.code, "clock declaration refused") from None

    if profile in (2, 3):
        # One collection session = one collector clock: observed brackets from different sessions
        # are anchored to different wall readings and are never compared (R1, CA-P2-005b E6).
        observed = {t.clock_domain_id for m in members.values() for t in m.evidence.times
                    if t.timestamp_kind == OBSERVED_TIME}
        if len(observed) > 1:
            raise InputError("observed_clock_domains_mixed", "observed brackets come from more than one session clock")

    return InvestigationInput(
        plan=plan, registry=registry, manifest_digest=root["manifest_digest"], manifest_status=root["status"],
        manifest_limitations=tuple(root["limitations"]),
        members=tuple(members[k] for k in sorted(members)),
        gaps=tuple(sorted(fi.collection_items(frozen, "gaps"), key=lambda g: g["gap_id"])),
        clock_domains=dict(clock_declaration.domains),
        clock_domain_records=clock_declaration.records, clock_declaration=clock_declaration)
