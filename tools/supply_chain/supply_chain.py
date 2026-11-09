"""CA-P2-001 repository supply-chain checks (ca-supply-chain/0.2). Python 3.13 standard library only.

Offline and bounded: reads files in the repository, never contacts a network service, never
installs anything and never modifies the repository except an explicitly requested new SBOM
file. Passing these checks is conformance evidence for review, not license clearance or
security approval.

Commands:
  check                 inventory, license policy, workflow pins/permissions, container-image
                        digest pins, hash-pinned dependency manifests matching the inventory,
                        imports (standard library, first-party, or an inventoried package inside
                        its allowed paths), secret patterns, SBOM drift

Version 0.2 (CA-P2-003b readiness) adds container-image components pinned by digest,
python-package components with exact versions, artifact hashes, import names and allowed
paths, and checks that manifests, imports and image references agree with the inventory.
  sbom [--out PATH]     deterministic CycloneDX 1.6 JSON derived from the inventory
"""

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

TOOL_VERSION = "ca-supply-chain/0.2"
INVENTORY_SCHEMA = "ca-dep-inventory/0.2"
INVENTORY_PATH = "supply-chain/dependency-inventory.json"
SBOM_PATH = "supply-chain/sbom.cdx.json"
MAX_SCAN_BYTES = 2 * 1024 * 1024

COMPONENT_TYPES = {"runtime", "github-action", "ci-runner", "python-package", "container-image"}
SCOPES = {"build-and-test", "ci-only", "runtime-shipped"}
# "provisional": a recorded product-owner disposition for test-only scope. It is not licensing
# clearance, never applies to shipped components and never covers GPL-family licenses.
REVIEW_STATES = {"pending", "approved", "provisional"}
PIN_KINDS = {"git-commit", "exact-version", "version-line", "mutable-label", "image-digest"}
# name[:tag]@sha256:<64 hex>; the tag is informational, the digest is the pin.
IMAGE_REF = re.compile(r"^([a-z0-9][a-z0-9._/-]*)(?::([A-Za-z0-9._-]+))?@sha256:([0-9a-f]{64})$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
IMPORT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Licenses acceptable for non-distributed build/CI tooling pending specialist review.
PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "PSF-2.0", "0BSD"}
# Never bundled or shipped without an approved specialist record (technology-evaluation.md).
REVIEW_REQUIRED = re.compile(r"^(A?GPL|LGPL|MPL|EUPL|SSPL|BUSL|CDDL|EPL|CC-BY-SA)", re.I)
SHA40 = re.compile(r"^[0-9a-f]{40}$")
DEPENDENCY_MANIFESTS = {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
                        "Pipfile.lock", "poetry.lock", "uv.lock", "pdm.lock", "environment.yml"}
REQUIREMENT_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.+!_-]+(\s+--hash=sha256:[0-9a-f]{64})+$")
IMPORT_ROOTS = ("prototype", "tools", "src")
# High-confidence credential shapes only; matches are reported by location, never by value.
SECRET_PATTERNS = {
    "private-key-block": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY"),
    "aws-access-key-id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "slack-token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "openai-or-anthropic-key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{32,}\b"),
}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".svg", ".zip", ".gz"}


class SupplyChainError(RuntimeError):
    pass


def repo_files(root):
    """Tracked files when ``root`` is a Git work tree, otherwise every file below it."""
    root = Path(root)
    if (root / ".git").exists():
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
        names = [n for n in out.stdout.decode("utf-8").split("\0") if n]
        return sorted(p for p in (root / n for n in names) if p.is_file() and not p.is_symlink())
    return sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts)


def load_inventory(root):
    path = Path(root) / INVENTORY_PATH
    if not path.is_file():
        raise SupplyChainError(f"{INVENTORY_PATH}: missing")
    try:
        return json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SupplyChainError(f"{INVENTORY_PATH}: invalid JSON: {exc}") from None


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def check_inventory(inv):
    problems = []
    if not isinstance(inv, dict) or inv.get("schema") != INVENTORY_SCHEMA:
        return [f"inventory schema must be {INVENTORY_SCHEMA}"]
    comps = inv.get("components")
    if not isinstance(comps, list) or not comps:
        return ["inventory components must be a non-empty list"]
    ids = set()
    for i, c in enumerate(comps):
        where = f"component[{i}]"
        if not isinstance(c, dict):
            problems.append(f"{where}: not an object")
            continue
        cid = c.get("id")
        where = f"component {cid!r}"
        if not isinstance(cid, str) or not cid or cid in ids:
            problems.append(f"{where}: id missing or duplicated")
        ids.add(cid)
        for field in ("name", "version", "purpose", "upgrade_owner"):
            if not isinstance(c.get(field), str) or not c[field].strip():
                problems.append(f"{where}: {field} required")
        if c.get("type") not in COMPONENT_TYPES:
            problems.append(f"{where}: type must be one of {sorted(COMPONENT_TYPES)}")
        if c.get("scope") not in SCOPES:
            problems.append(f"{where}: scope must be one of {sorted(SCOPES)}")
        pin = c.get("pin") if isinstance(c.get("pin"), dict) else {}
        if pin.get("kind") not in PIN_KINDS or not isinstance(pin.get("value"), str) or not pin["value"]:
            problems.append(f"{where}: pin kind/value required")
        elif pin["kind"] == "git-commit" and not SHA40.match(pin["value"]):
            problems.append(f"{where}: git-commit pin must be a full 40-hex SHA")
        if c.get("type") == "github-action" and pin.get("kind") != "git-commit":
            problems.append(f"{where}: GitHub Actions must be pinned to a full commit SHA")
        if c.get("scope") == "runtime-shipped" and pin.get("kind") in {"version-line", "mutable-label"}:
            problems.append(f"{where}: shipped components need an exact or commit pin")
        if c.get("type") == "container-image":
            if pin.get("kind") != "image-digest" or not IMAGE_REF.match(str(pin.get("value", ""))):
                problems.append(f"{where}: container images must be pinned as name[:tag]@sha256:<64 hex>")
        elif pin.get("kind") == "image-digest":
            problems.append(f"{where}: image-digest pins are only for container images")
        if c.get("type") == "python-package":
            problems += _python_package_problems(where, c, pin)
        lic = c.get("license") if isinstance(c.get("license"), dict) else {}
        spdx = lic.get("spdx")
        if not isinstance(spdx, str) or not spdx or spdx.upper() in {"NOASSERTION", "UNKNOWN"}:
            problems.append(f"{where}: license.spdx must be a known SPDX expression")
            spdx = ""
        if not isinstance(lic.get("source"), str) or not lic["source"].startswith("https://"):
            problems.append(f"{where}: license.source must be an https reference")
        review = lic.get("review")
        if review not in REVIEW_STATES:
            problems.append(f"{where}: license.review must be one of {sorted(REVIEW_STATES)}")
        if review == "approved" and not lic.get("approval_record"):
            problems.append(f"{where}: approved license review needs approval_record")
        if review == "provisional":
            if not lic.get("disposition_record"):
                problems.append(f"{where}: provisional license disposition needs disposition_record")
            if c.get("scope") == "runtime-shipped":
                problems.append(f"{where}: shipped components cannot rely on a provisional disposition")
        copyleft = bool(REVIEW_REQUIRED.match(spdx))
        needs_specialist = copyleft or (spdx and spdx not in PERMISSIVE)
        provisional_ok = review == "provisional" and not copyleft and c.get("scope") != "runtime-shipped"
        if needs_specialist and review != "approved" and not provisional_ok:
            problems.append(f"{where}: license {spdx} requires an approved specialist review record")
        if c.get("scope") == "runtime-shipped" and review != "approved":
            problems.append(f"{where}: shipped component without approved license review")
    return problems


def normalize_package(name):
    """PEP 503 normalized distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_package_problems(where, c, pin):
    problems = []
    if pin.get("kind") != "exact-version" or pin.get("value") != c.get("version"):
        problems.append(f"{where}: python packages need an exact-version pin equal to version")
    hashes = c.get("hashes")
    if not isinstance(hashes, list) or not hashes or not all(isinstance(h, str) and SHA256_HEX.match(h)
                                                             for h in hashes) or len(set(hashes)) != len(hashes):
        problems.append(f"{where}: python packages need a non-empty list of distinct sha256 artifact hashes")
    names = c.get("import_names")
    if not isinstance(names, list) or not all(isinstance(n, str) and IMPORT_NAME.match(n) for n in names):
        problems.append(f"{where}: import_names must be a list of module names (empty for indirect dependencies)")
    paths = c.get("allowed_paths")
    if not isinstance(paths, list) or not all(isinstance(x, str) and x.endswith("/") and not x.startswith("/")
                                              and ".." not in x for x in paths):
        problems.append(f"{where}: allowed_paths must be a list of repository-relative directories ending in '/'")
    elif names and not paths:
        problems.append(f"{where}: a directly imported package needs at least one allowed path")
    return problems


def _workflow_problems(rel, text, actions):
    problems, used = [], set()
    if not re.search(r"^permissions:\s*$|^permissions:\s*\S", text, re.M):
        problems.append(f"{rel}: top-level permissions block required")
    for m in re.finditer(r"^\s*([A-Za-z-]+):\s*write\b|write-all", text, re.M):
        problems.append(f"{rel}: write permission is not allowed ({m.group(0).strip()})")
    if re.search(r"^\s*pull_request_target\s*:", text, re.M):
        problems.append(f"{rel}: pull_request_target is not allowed")
    if re.search(r"\$\{\{[^}]*\bsecrets\b", text):  # GitHub Actions secret contexts
        problems.append(f"{rel}: workflow must not reference secrets")
    for m in re.finditer(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", text, re.M):
        ref = m.group(1).strip("'\"")
        if ref.startswith("./"):
            problems.append(f"{rel}: local action {ref} is not inventoried")
            continue
        if ref.startswith("docker://"):
            continue  # container actions are checked as image references
        name, _, sha = ref.partition("@")
        if not SHA40.match(sha):
            problems.append(f"{rel}: {ref} is not pinned to a full commit SHA")
        elif actions.get(name) != sha:
            problems.append(f"{rel}: {name}@{sha} does not match the inventory")
        used.add(name)
    checkouts = len(re.findall(r"uses:\s*actions/checkout@", text))
    if checkouts and len(re.findall(r"persist-credentials:\s*false", text)) < checkouts:
        problems.append(f"{rel}: actions/checkout must set persist-credentials: false")
    return problems, used


def check_workflows(root, files, inv):
    actions = {c["name"]: c["pin"]["value"] for c in inv.get("components", [])
               if isinstance(c, dict) and c.get("type") == "github-action" and isinstance(c.get("pin"), dict)}
    problems, used = [], set()
    for path in files:
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".github/workflows/") and path.suffix in {".yml", ".yaml"}:
            p, u = _workflow_problems(rel, path.read_text(encoding="utf-8"), actions)
            problems += p
            used |= u
    for name in sorted(set(actions) - used):
        problems.append(f"inventory lists {name} but no workflow uses it")
    return problems


_IMAGE_LINE = re.compile(r"^\s*(?:-\s*)?image:\s*['\"]?([^\s'\"#]+)", re.M)
_FROM_LINE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", re.M | re.I)
_DOCKER_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?docker://([^\s'\"#]+)", re.M)


def check_images(root, files, inv):
    """Every container image referenced by YAML ``image:``, Dockerfile ``FROM`` or ``docker://`` must be
    digest-pinned and match an inventoried container-image component; inventoried images must be used."""
    pinned = {}
    for c in inv.get("components", []):
        if isinstance(c, dict) and c.get("type") == "container-image" and isinstance(c.get("pin"), dict):
            m = IMAGE_REF.match(str(c["pin"].get("value", "")))
            if m:
                pinned[(m.group(1), m.group(3))] = c.get("id")
    problems, used = [], set()
    for path in files:
        rel = path.relative_to(root).as_posix()
        refs = []
        if path.suffix in {".yml", ".yaml"}:
            text = path.read_text(encoding="utf-8")
            refs = _IMAGE_LINE.findall(text) + _DOCKER_USES.findall(text)
        elif path.name == "Dockerfile" or path.name.endswith(".Dockerfile") or path.name.startswith("Dockerfile."):
            refs = [r for r in _FROM_LINE.findall(path.read_text(encoding="utf-8")) if r.lower() != "scratch"]
        for ref in refs:
            m = IMAGE_REF.match(ref)
            if not m:
                problems.append(f"{rel}: image {ref} is not pinned as name[:tag]@sha256:<digest>")
            elif (m.group(1), m.group(3)) not in pinned:
                problems.append(f"{rel}: image {m.group(1)}@sha256:{m.group(3)[:12]}... does not match the inventory")
            else:
                used.add(pinned[(m.group(1), m.group(3))])
    for cid in sorted(set(pinned.values()) - used):
        problems.append(f"inventory lists container image {cid} but nothing references it")
    return problems


def _requirement_entries(path):
    """Yield (line number, name, version, hashes) from a hash-pinned requirements file (continuations joined)."""
    logical, start = "", None
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        if start is None:
            start = n
        if line.endswith("\\"):
            logical += line[:-1] + " "
            continue
        logical += line
        text = " ".join(logical.split())
        if text:
            yield start, text
        logical, start = "", None


def check_dependency_manifests(root, files, inv):
    declared = set(inv.get("dependency_manifests", []))
    packages = {normalize_package(c["name"]): c for c in inv.get("components", [])
                if isinstance(c, dict) and c.get("type") == "python-package" and isinstance(c.get("name"), str)}
    listed = set()
    problems = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        name = path.name
        is_manifest = name in DEPENDENCY_MANIFESTS or re.match(r"^requirements[\w.-]*\.(txt|in)$", name)
        if not is_manifest:
            continue
        if rel not in declared:
            problems.append(f"{rel}: third-party dependency manifest not declared in the inventory "
                            "(needs CA-P2-001 approval first)")
            continue
        if name.startswith("requirements") and name.endswith(".txt"):
            for n, line in _requirement_entries(path):
                if not REQUIREMENT_LINE.match(line):
                    problems.append(f"{rel}:{n}: requirement must be name==version with --hash=sha256 pins")
                    continue
                spec, *hash_parts = line.split()
                req_name, _, version = spec.partition("==")
                hashes = {h.split(":", 1)[1] for h in hash_parts}
                component = packages.get(normalize_package(req_name))
                if component is None:
                    problems.append(f"{rel}:{n}: {req_name} is not an inventoried python-package")
                    continue
                listed.add(normalize_package(req_name))
                if version != component.get("version"):
                    problems.append(f"{rel}:{n}: {req_name}=={version} differs from inventory version")
                if isinstance(component.get("hashes"), list) and hashes != set(component["hashes"]):
                    problems.append(f"{rel}:{n}: {req_name} hashes differ from the inventory")
    for rel in sorted(declared - {p.relative_to(root).as_posix() for p in files}):
        problems.append(f"{rel}: declared dependency manifest is missing")
    for name in sorted(set(packages) - listed):
        problems.append(f"inventory python-package {name} is not pinned in any declared requirements file")
    return problems


def first_party_names(root, files):
    names = set()
    for path in files:
        if path.suffix == ".py":
            names.add(path.stem)
            names.update(part for part in path.relative_to(root).parts[:-1])
    return names


def check_imports(root, files, inv=None):
    local = first_party_names(root, files)
    allowed = set(sys.stdlib_module_names) | local | {"__future__"}
    third_party = {}
    for c in (inv or {}).get("components", []):
        if isinstance(c, dict) and c.get("type") == "python-package":
            for module in c.get("import_names") or []:
                third_party[module] = tuple(c.get("allowed_paths") or ())
    problems = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if path.suffix != ".py" or rel.split("/", 1)[0] not in IMPORT_ROOTS:
            continue
        try:
            tree = ast.parse(path.read_bytes(), filename=rel)
        except SyntaxError as exc:
            problems.append(f"{rel}: cannot parse ({exc.msg})")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            else:
                continue
            for mod in mods:
                top = mod.split(".", 1)[0]
                if top in allowed:
                    continue
                if top not in third_party:
                    problems.append(f"{rel}:{node.lineno}: import {top!r} is not standard library "
                                    "or first-party; third-party packages need an approved inventory entry")
                elif not any(rel.startswith(prefix) for prefix in third_party[top]):
                    problems.append(f"{rel}:{node.lineno}: import {top!r} is only allowed under "
                                    f"{', '.join(third_party[top])}")
    return problems


def scan_secrets(root, files):
    findings = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        data = path.read_bytes()
        if len(data) > MAX_SCAN_BYTES:
            findings.append(f"{rel}: larger than {MAX_SCAN_BYTES} bytes; not scanned (review manually)")
            continue
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for kind, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{rel}:{n}: possible {kind} (value not shown)")
    return findings


def build_sbom(inv):
    """CycloneDX 1.6 JSON. Deterministic: no timestamp; serial number derived from the inventory."""
    canon = json.dumps(inv, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    serial = uuid.uuid5(uuid.NAMESPACE_URL, "urn:cloud-autopsy:sbom:" + hashlib.sha256(canon).hexdigest())
    components = []
    for c in sorted(inv["components"], key=lambda c: c["id"]):
        comp = {
            "type": "application" if c["type"] in {"github-action", "ci-runner"} else
                    "container" if c["type"] == "container-image" else
                    ("platform" if c["type"] == "runtime" else "library"),
            "bom-ref": c["id"],
            "name": c["name"],
            "version": c["version"],
            "scope": "required" if c["scope"] == "runtime-shipped" else "excluded",
            "licenses": [{"expression": c["license"]["spdx"]}],
            "properties": [
                {"name": "ca:pin-kind", "value": c["pin"]["kind"]},
                {"name": "ca:pin", "value": c["pin"]["value"]},
                {"name": "ca:usage-scope", "value": c["scope"]},
                {"name": "ca:license-review", "value": c["license"]["review"]},
            ],
            "externalReferences": [{"type": "license", "url": c["license"]["source"]}],
        }
        if c["type"] == "github-action":
            comp["purl"] = f"pkg:github/{c['name']}@{c['pin']['value']}"
        elif c["type"] == "python-package":
            comp["purl"] = f"pkg:pypi/{normalize_package(c['name'])}@{c['version']}"
            comp["hashes"] = [{"alg": "SHA-256", "content": h} for h in sorted(c.get("hashes", []))]
        elif c["type"] == "container-image":
            m = IMAGE_REF.match(c["pin"]["value"])
            repo = m.group(1) if "/" in m.group(1) else f"library/{m.group(1)}"
            comp["purl"] = f"pkg:docker/{repo}@sha256%3A{m.group(3)}"
        components.append(comp)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "tools": {"components": [{"type": "application", "name": TOOL_VERSION}]},
            "component": {"type": "application", "bom-ref": "cloud-autopsy", "name": "cloud-autopsy",
                          "version": inv.get("product_version", "unreleased")},
            "properties": [{"name": "ca:inventory-status", "value": inv.get("status", "")}],
        },
        "components": components,
    }


def sbom_bytes(inv):
    return (json.dumps(build_sbom(inv), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def check_sbom(root, inv):
    path = Path(root) / SBOM_PATH
    if not path.is_file():
        return [f"{SBOM_PATH}: missing; generate it with the sbom command"]
    if path.read_bytes().replace(b"\r\n", b"\n") != sbom_bytes(inv):
        return [f"{SBOM_PATH}: out of date with {INVENTORY_PATH}; regenerate it"]
    return []


def run_checks(root):
    """Return {section: [problems]}; every section runs even when earlier ones fail."""
    root = Path(root).resolve()
    files = repo_files(root)
    try:
        inv = load_inventory(root)
    except SupplyChainError as exc:
        return {"inventory": [str(exc)]}
    sections = {"inventory": check_inventory(inv)}
    valid = not sections["inventory"]
    sections["workflows"] = check_workflows(root, files, inv)
    sections["images"] = check_images(root, files, inv)
    sections["dependency-manifests"] = check_dependency_manifests(root, files, inv)
    sections["imports"] = check_imports(root, files, inv)
    sections["secrets"] = scan_secrets(root, files)
    sections["sbom"] = check_sbom(root, inv) if valid else ["skipped: inventory invalid"]
    return sections


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sb = sub.add_parser("sbom")
    sb.add_argument("--out")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "sbom":
        inv = load_inventory(root)
        problems = check_inventory(inv)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        data = sbom_bytes(inv)
        if args.out:
            with open(args.out, "xb") as fh:  # never overwrite an existing file
                fh.write(data)
        else:
            sys.stdout.buffer.write(data)
        return 0
    sections = run_checks(root)
    failed = False
    for name, problems in sections.items():
        print(f"{'FAIL' if problems else 'PASS'}: {name}" + (f" ({len(problems)})" if problems else ""))
        for p in problems:
            print(f"  - {p}")
        failed |= bool(problems)
    print(f"{TOOL_VERSION}: offline repository checks only; not license clearance, vulnerability "
          "scanning or security approval.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
