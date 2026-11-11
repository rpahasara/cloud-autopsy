"""Evidence bundles, ``ca-investigation-bundle/0.1-provisional`` (CA-P2-004a, provisional).

A bundle is a directory that holds exactly the records needed to create one investigation, in
the existing contracts. It adds no new evidence schema:

  bundle.json              the manifest (below)
  registry.json            ca-source-registry/0.1-provisional
  plan.json                ca-run-plan/0.2-provisional, pinned to the registry digest
  clocks.json              {"clock_domains": [declared clock-domain records]}
  batches/NNNN.json        ca-acquisition-batch/0.1-provisional, in delivery order

  bundle.json = {"contract_version": "ca-investigation-bundle/0.1-provisional",
                 "bundle_id": "<identifier>", "data_classification": "synthetic",
                 "registry": {"path": ..., "sha256": ...}, "plan": {...}, "clocks": {...},
                 "batches": [{"path": ..., "sha256": ...}, ...]}

``load`` refuses, before anything is created anywhere:
- **Unsafe paths:** absolute or traversing paths, symlinks, Windows reparse points (junctions),
  hard-linked files, and anything that is not a regular file or directory.
- **Unexpected content:** any file or directory the manifest does not list, so nothing else
  (ground truth, notes, credentials) can travel inside a bundle.
- **Size and count:** limits are checked from metadata before any file is read.
- **Bad documents:** a file whose bytes differ from its recorded SHA-256, or that is not
  canonical JSON under the profile.
- **Bad records:** anything the contracts refuse. The registry, plan (pinned to that registry),
  clock declaration and every batch (bound to that plan) are validated with the same decoders
  the database path uses.

Two batches that disagree under one batch key are evidence, not a structural error: they are
kept, and the engine reports the conflict (the ``configmap-conflict`` variant). A bundle is
synthetic-only in this slice (``data_classification`` must be ``synthetic``).
"""

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from ..contracts import acquisition as acq
from ..contracts import canonical
from ..contracts import plan as pl
from ..contracts.errors import ContractError
from ..contracts.sources import SourceRegistry
from ..engine import clocks

BUNDLE_VERSION = "ca-investigation-bundle/0.1-provisional"
MANIFEST = "bundle.json"
CLASSIFICATION = "synthetic"
MAX_MANIFEST_BYTES = 65_536
MAX_RECORD_BYTES = canonical.CEILING_BYTES      # 1 MiB per registry, plan, clocks or batch file
MAX_BATCH_FILES = 1_000
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = MAX_BATCH_FILES + 16
_PATH = re.compile(r"([a-z0-9][a-z0-9_-]{0,63}/)?[a-z0-9][a-z0-9_-]{0,63}\.json", re.ASCII)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}", re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_ENTRY_KEYS = {"path", "sha256"}
_MANIFEST_KEYS = {"contract_version", "bundle_id", "data_classification", "registry", "plan", "clocks", "batches"}
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class BundleError(ValueError):
    """A refused bundle. ``code`` is stable; messages name the manifest path at most, never file contents."""

    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Bundle:
    bundle_id: str
    registry: SourceRegistry
    plan: pl.RunPlan
    clock_records: tuple
    batches: tuple            # validated batch records, in delivery order
    manifest_sha256: str      # SHA-256 of bundle.json: identifies exactly what was loaded

    @property
    def scenario_id(self):
        return f"bundle-{self.bundle_id}"


# ------------------------------------------------------------------------------------ export

def _canonical(value):
    return canonical.canonical_bytes(value)


def write(directory, bundle_id, registry_record, plan_record, clock_records, batch_records):
    """Write a new bundle into ``directory``, which must not exist. Returns the directory path."""
    if not isinstance(bundle_id, str) or not _IDENTIFIER.fullmatch(bundle_id):
        raise BundleError("bundle_id_invalid", "bundle_id must be a lowercase identifier")
    if len(batch_records) > MAX_BATCH_FILES:
        raise BundleError("bundle_too_many_batches", f"at most {MAX_BATCH_FILES} batches")
    root = Path(directory)
    root.mkdir(parents=False, exist_ok=False)
    (root / "batches").mkdir()
    files = {"registry.json": _canonical(registry_record), "plan.json": _canonical(plan_record),
             "clocks.json": _canonical({"clock_domains": list(clock_records)})}
    for i, record in enumerate(batch_records, 1):
        files[f"batches/{i:04d}.json"] = _canonical(record)
    entry = lambda path: {"path": path, "sha256": hashlib.sha256(files[path]).hexdigest()}  # noqa: E731
    manifest = {"contract_version": BUNDLE_VERSION, "bundle_id": bundle_id, "data_classification": CLASSIFICATION,
                "registry": entry("registry.json"), "plan": entry("plan.json"), "clocks": entry("clocks.json"),
                "batches": [entry(f"batches/{i:04d}.json") for i in range(1, len(batch_records) + 1)]}
    for path, data in files.items():
        _create(root / path, data)
    _create(root / MANIFEST, _canonical(manifest))
    return root


def _create(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def export_variant(directory, variant):
    """Write one synthetic scenario-001 variant as a bundle (contract records only: no expected outcome)."""
    from ..synthetic import scenario_001 as scenario
    return write(directory, f"ca-scenario-001-{variant}", scenario.REGISTRY_RECORD, scenario.plan_record(variant),
                 scenario.clock_domain_records(variant), scenario.batches(variant))


# -------------------------------------------------------------------------------------- load

def _lstat(path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        raise BundleError("bundle_file_missing", _rel_hint(path)) from None
    except OSError:
        raise BundleError("bundle_unreadable", _rel_hint(path)) from None


def _rel_hint(path):
    return Path(path).name


def _check_node(path, *, directory):
    """Refuse links, reparse points, hard links and special files; return the lstat result."""
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE:
        raise BundleError("bundle_link_refused", f"{_rel_hint(path)} is a symlink or reparse point")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise BundleError("bundle_not_directory", _rel_hint(path))
    else:
        if not stat.S_ISREG(info.st_mode):
            raise BundleError("bundle_not_regular_file", _rel_hint(path))
        if info.st_nlink != 1:
            raise BundleError("bundle_hard_link_refused", f"{_rel_hint(path)} has more than one link")
    return info


def _read(path, limit, expected=None):
    """Read a checked regular file without following links; the open handle must be the checked file."""
    info = _check_node(path, directory=False)
    if info.st_size > limit:
        raise BundleError("bundle_file_too_large", f"{_rel_hint(path)} exceeds {limit} bytes")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise BundleError("bundle_unreadable", _rel_hint(path)) from None
    with os.fdopen(fd, "rb") as fh:
        opened = os.fstat(fh.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or not stat.S_ISREG(opened.st_mode):
            raise BundleError("bundle_file_changed", f"{_rel_hint(path)} changed while being read")
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise BundleError("bundle_file_too_large", f"{_rel_hint(path)} exceeds {limit} bytes")
    if expected is not None and hashlib.sha256(data).hexdigest() != expected:
        raise BundleError("bundle_digest_mismatch", f"{_rel_hint(path)} differs from its manifest SHA-256")
    return data


def _parse(data, name, limit=MAX_RECORD_BYTES):
    try:
        value = canonical.loads(data, canonical.Limits(max_bytes=limit))
    except ContractError as exc:
        raise BundleError("bundle_json_invalid", f"{name}: {exc.code}") from None
    if canonical.canonical_bytes(value) != bytes(data):
        raise BundleError("bundle_not_canonical", f"{name} is not in canonical form")
    return value


def _entry(value, field):
    if not isinstance(value, dict) or set(value) != _ENTRY_KEYS:
        raise BundleError("bundle_manifest_invalid", f"{field} must have exactly path and sha256")
    path, digest = value["path"], value["sha256"]
    if not isinstance(path, str) or not _PATH.fullmatch(path) or path == MANIFEST:
        raise BundleError("bundle_path_refused", f"{field}: only lowercase relative names like batches/0001.json")
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
        raise BundleError("bundle_manifest_invalid", f"{field}.sha256 must be 64 lowercase hex digits")
    return path, digest


def _manifest(root):
    data = _read(root / MANIFEST, MAX_MANIFEST_BYTES)
    manifest = _parse(data, MANIFEST, MAX_MANIFEST_BYTES)
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise BundleError("bundle_manifest_invalid", "the manifest must have exactly the documented fields")
    if manifest["contract_version"] != BUNDLE_VERSION:
        raise BundleError("bundle_version_unsupported", "unsupported bundle contract version")
    if not isinstance(manifest["bundle_id"], str) or not _IDENTIFIER.fullmatch(manifest["bundle_id"]):
        raise BundleError("bundle_manifest_invalid", "bundle_id must be a lowercase identifier")
    if manifest["data_classification"] != CLASSIFICATION:
        raise BundleError("bundle_classification_refused", "only synthetic bundles are accepted")
    batches = manifest["batches"]
    if not isinstance(batches, list) or not 1 <= len(batches) <= MAX_BATCH_FILES:
        raise BundleError("bundle_manifest_invalid", f"batches must list 1-{MAX_BATCH_FILES} files")
    entries = {"registry": _entry(manifest["registry"], "registry"), "plan": _entry(manifest["plan"], "plan"),
               "clocks": _entry(manifest["clocks"], "clocks"),
               "batches": [_entry(b, f"batches[{i}]") for i, b in enumerate(batches)]}
    paths = [entries["registry"][0], entries["plan"][0], entries["clocks"][0]] + [p for p, _ in entries["batches"]]
    if len(set(paths)) != len(paths):
        raise BundleError("bundle_manifest_conflict", "a file is listed more than once")
    return manifest, entries, paths, hashlib.sha256(data).hexdigest()


def _check_layout(root, paths):
    """The bundle directory holds exactly the manifest and the listed files: no links, nothing else."""
    expected_files = set(paths) | {MANIFEST}
    expected_dirs = {p.rsplit("/", 1)[0] for p in paths if "/" in p}
    found = 0
    for directory in [""] + sorted(expected_dirs):
        here = root / directory if directory else root
        _check_node(here, directory=True)
        with os.scandir(here) as it:
            for item in it:
                found += 1
                if found > MAX_DIRECTORY_ENTRIES:
                    raise BundleError("bundle_too_many_entries", "the bundle has too many entries")
                rel = f"{directory}/{item.name}" if directory else item.name
                if item.is_symlink():
                    raise BundleError("bundle_link_refused", f"{item.name} is a symlink")
                if rel in expected_dirs and not directory:
                    continue
                if rel not in expected_files:
                    raise BundleError("bundle_unexpected_entry", f"{item.name} is not listed in the manifest")
    total = 0
    for rel in paths:
        info = _check_node(root / rel, directory=False)
        if info.st_size > MAX_RECORD_BYTES:
            raise BundleError("bundle_file_too_large", f"{Path(rel).name} exceeds {MAX_RECORD_BYTES} bytes")
        total += info.st_size
    if total > MAX_TOTAL_BYTES:
        raise BundleError("bundle_too_large", f"the bundle exceeds {MAX_TOTAL_BYTES} bytes")


def load(directory):
    """Load and fully validate the bundle in ``directory``; raise ``BundleError`` on any refusal."""
    root = Path(os.path.abspath(directory))
    _check_node(root, directory=True)
    manifest, entries, paths, manifest_sha = _manifest(root)
    _check_layout(root, paths)  # every limit and link check happens before any record is read

    def record(kind):
        path, digest = entries[kind]
        return _parse(_read(root / path, MAX_RECORD_BYTES, digest), path)

    try:
        registry = SourceRegistry.from_record(record("registry"))
        plan = pl.RunPlan.from_record(record("plan"), registry)
        clock_doc = record("clocks")
        if not isinstance(clock_doc, dict) or set(clock_doc) != {"clock_domains"}:
            raise BundleError("bundle_record_invalid", "clocks.json must have exactly clock_domains")
        clock_records = tuple(clock_doc["clock_domains"]) if isinstance(clock_doc["clock_domains"], list) else None
        if clock_records is None:
            raise BundleError("bundle_record_invalid", "clock_domains must be a list")
        clocks.declare(registry, list(clock_records))
        if len(entries["batches"]) > plan.limit("max_batch_deliveries"):
            raise BundleError("bundle_limit_exceeded", "more batch files than the plan's max_batch_deliveries")
        batches = []
        for path, digest in entries["batches"]:
            batch = _parse(_read(root / path, plan.limit("max_batch_bytes"), digest), path)
            acq.decode_batch(batch, plan, registry)
            batches.append(batch)
    except ContractError as exc:
        raise BundleError("bundle_record_invalid", exc.code) from None
    except clocks.ClockDeclarationError as exc:
        raise BundleError("bundle_record_invalid", getattr(exc, "code", "clock_declaration_invalid")) from None
    return Bundle(manifest["bundle_id"], registry, plan, clock_records, tuple(batches), manifest_sha)
