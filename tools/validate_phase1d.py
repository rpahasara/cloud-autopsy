"""Structural checks for the proposed Phase 1D approval package; no product tests."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'docs/reviews/phase1d'
def read(p): return p.read_text(encoding='utf-8')
def rows(p,prefix): return [line.split('|')[1:-1] for line in read(p).splitlines() if line.startswith(prefix)]
files=['README.md','consistency-review.md','approvals.md','technology-evaluation.md',
       'differentiation.md','benchmark-plan.md','completion-checklist.md',
       'outstanding-risks.md','phase2-backlog.md','verification.md']
assert all((PACKAGE/f).is_file() for f in files)

approvals=rows(PACKAGE/'approvals.md','| CA-DEC-')
assert len(approvals)==8 and {r[0].strip() for r in approvals}=={f'CA-DEC-{i:03}' for i in range(1,9)}
assert all(len(r)==4 and all(c.strip() for c in r) for r in approvals)
for i in range(1,9):
    d=read(ROOT/f'docs/architecture/adr/CA-DEC-{i:03}.md')
    for required in ['**Status:** Proposed','**Approval status:** No approval recorded',
                     '**Accepted terms:** None; no approval recorded.',
                     '**Provisional assumptions excluded from acceptance:**',
                     '**Specialist reviewers required:**','## Phase 1D approval request']:
        assert required in d,(i,required)

review=rows(PACKAGE/'consistency-review.md','| CA-REV-P1D-')
risk=rows(PACKAGE/'outstanding-risks.md','| CA-READY-')
assert len(review)==len(risk)==8
assert all(r[-1].strip()=='Open' for r in risk)
assert {re.search(r'CA-REV-P1D-\d{3}',r[0])[0] for r in risk}=={r[0].strip() for r in review}

backlog=rows(PACKAGE/'phase2-backlog.md','| CA-P2-')
items={re.search(r'CA-P2-\d{3}',r[0])[0]:r for r in backlog}
assert len(items)==12
known_requirements=set(re.findall(r'^### (CA-(?:FR|NFR|SEC)-\d{3})',read(ROOT/'docs/srs.md'),re.M))
for key,row in items.items():
    assert len(row)==5 and re.search(r'#\d+',row[3]) and row[4].strip(),key
    assert set(re.findall(r'CA-(?:FR|NFR|SEC)-\d{3}',row[3]))<=known_requirements,key
    for group in re.findall(r'CA-P2-(\d{3}(?:/\d{3})*)',row[2]):
        for suffix in group.split('/'):
            dep='CA-P2-'+suffix
            assert dep in items and int(dep[-3:])<int(key[-3:]),('dependency order',key,dep)

bench=read(PACKAGE/'benchmark-plan.md')
assert {r[0].strip() for r in rows(PACKAGE/'benchmark-plan.md','| CA-BENCH-')}=={f'CA-BENCH-B{i}' for i in range(7)}
for concept in ['Matched-evidence','End-to-end','Zero denominators','five independent attempts',
                'no benchmark runner','provisional']:
    assert concept.lower() in bench.lower(),concept
tech=read(PACKAGE/'technology-evaluation.md')
for name in ['OpenTelemetry','Prometheus','Loki','Alloy','HolmesGPT','K8sGPT','Fluent Bit','Vector','PostgreSQL']:
    assert name in tech,name
assert len(re.findall(r'https://github.com/[^)]+/releases/tag/',tech))==9
checklist=read(PACKAGE/'completion-checklist.md')
assert '[x]' not in checklist.lower() and len(re.findall(r'^- \[ \]',checklist,re.M))>=20
srs=read(ROOT/'docs/srs.md')
assert '| Version | `0.4.0-draft` |' in srs
assert '### 10.1 Design approval and implementation conformance' in srs
assert 'Unknown or unbounded clock uncertainty remains unordered.' in read(ROOT/'docs/architecture/adr/CA-DEC-003.md')
assert 'any unresolved Critical/High finding blocks passage' in read(ROOT/'docs/architecture/phase1c/signoff.md')
print('PASS: ten approval-package documents; eight scoped approval requests and Proposed ADRs; eight review findings/open readiness risks; twelve ordered Phase 2 tasks; seven benchmark arms/two tracks; required technology coverage and nine dated release sources; unchecked completion gates; proposed SRS gate/skew/security clarifications.')
print('No decision accepted, implementation readiness granted, dependency scan, benchmark or product/security runtime test performed.')
