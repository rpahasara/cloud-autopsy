"""Documentation-only checks for architecture traceability and diagram artifacts."""
from pathlib import Path
import json
import re
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'docs/architecture/phase1c'
def read(p): return p.read_text(encoding='utf-8')
def rows(p,prefix): return [line.split('|')[1:-1] for line in read(p).splitlines() if line.startswith(prefix)]

baseline=rows(ROOT/'docs/requirement-matrix.md','| <a id=')
expected={re.search(r'\[(CA-(?:FR|NFR|SEC)-\d{3})\]',r[0])[1]:r for r in baseline}
architecture=rows(ARCH/'traceability.md','| [CA-')
mapped={}
issues=set()
for row in architecture:
    match=re.search(r'\[(CA-(?:FR|NFR|SEC)-\d{3})\]',row[0])
    if not match:
        issues.update(re.findall(r'/ #(\d+)',row[0]))
        continue
    rid=match[1]
    assert rid not in mapped, ('duplicate',rid)
    mapped[rid]=row
    assert row[1].strip()==expected[rid][1].strip(), ('owner',rid)
    assert row[2].strip()==expected[rid][2].strip(), ('issue edges',rid)
    assert row[4].strip()=='CA-TEST-'+rid[3:], ('test',rid)
    links=re.findall(r'\[[^\]]*\]\(([^)]+)\)',row[3])
    assert links and all((ARCH/x).is_file() for x in links), ('design links',rid)
assert set(mapped)==set(expected) and len(mapped)==36
assert issues=={str(i) for i in range(1,11)}

security=read(ARCH/'security.md')
flowrows=[r for r in rows(ARCH/'security.md','| F') if re.fullmatch(r'F\d+',r[0].strip())]
assert {r[0].strip() for r in flowrows}=={f'F{i}' for i in range(1,17)}
assert all(len(r)==5 and r[2].strip() and 'CA-TEST-' in r[4] for r in flowrows)
tests=rows(ARCH/'security.md','| CA-TEST-SEC-')
assert {r[0].strip() for r in tests}=={f'CA-TEST-SEC-{i:03}' for i in range(1,13)}
assert all(len(r)==3 and r[1].strip() and r[2].strip() for r in tests)
assert set(re.findall(r'CA-THREAT-[STRIDE]-\d{3}',security))=={
    'CA-THREAT-S-001','CA-THREAT-T-001','CA-THREAT-R-001',
    'CA-THREAT-I-001','CA-THREAT-D-001','CA-THREAT-E-001'}
contracts=rows(ARCH/'api.md','| CA-CON-')
assert {re.search(r'CA-CON-\d{3}',r[0])[0] for r in contracts}=={f'CA-CON-{i:03}' for i in range(1,9)}
for block in re.findall(r'```json\n(.*?)\n```',read(ARCH/'api.md'),re.S): json.loads(block)
checklist=read(ARCH/'signoff.md')
assert '[x]' not in checklist.lower()
assert len(re.findall(r'^- \[ \]',checklist,re.M))>=20
for i in range(1,9):
    d=read(ROOT/f'docs/architecture/adr/CA-DEC-{i:03}.md')
    assert '**Status:** Proposed' in d and '**Approval status:** No approval recorded' in d
    assert '## Phase 1C design refinement' in d
    assert f'CA-DEC-{i:03}' in checklist

sources=re.findall(r'```mermaid\n(.*?)\n```',read(ARCH/'diagrams.md'),re.S)
sources+=re.findall(r'```mermaid\n(.*?)\n```',read(ARCH/'data-model.md'),re.S)
names=['system','trust-boundaries','acquisition-flow','model-lifecycle-flow','data-model']
assert len(sources)==len(names)
for name,source in zip(names,sources,strict=True):
    assert read(ARCH/f'diagrams/{name}.mmd').strip()==source.strip(), ('source drift',name)
    tree=ET.parse(ARCH/f'diagrams/{name}.svg')
    assert tree.getroot().tag.endswith('svg'), name
    assert 'Syntax error' not in read(ARCH/f'diagrams/{name}.svg'), name
    png=(ARCH/f'diagrams/{name}.png').read_bytes()
    assert png[:8]==b'\x89PNG\r\n\x1a\n'
    width,height=struct.unpack('>II',png[16:24])
    assert width>100 and height>100, (name,width,height)

print('PASS: architecture coverage for 36/36 requirements, unchanged owner/issue/test edges, ten issue links, all 16 data flows, six stable threats, 12 security test specifications, eight component contracts, valid JSON examples, eight Proposed decision refinements and unchecked sign-off checklist.')
print('PASS: five Mermaid sources match embedded diagrams; five rendered SVGs and five PNG previews exist and have valid file structure. Mermaid rendering and visual inspection are separate documentation checks.')
print('No application, database, RBAC, network, model, security or benchmark test has been executed.')
