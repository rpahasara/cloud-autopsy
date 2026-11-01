"""Validate Phase 1 documentation structure and exact reverse traceability."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding='utf-8')
def ids(text, kind): return set(re.findall(r'CA-'+kind+r'-\d{3}', text))
def rows(path, prefix):
    return [line.split('|')[1:-1] for line in read(path).splitlines() if line.startswith(prefix)]

srs = read('docs/srs.md')
blocks = dict(re.findall(r'^### (CA-(?:FR|NFR|SEC)-\d{3})[^\n]*\n(.*?)(?=^### |^## |\Z)', srs, re.M|re.S))
expected = {f'CA-{kind}-{i:03}' for kind,count in [('FR',14),('NFR',10),('SEC',12)] for i in range(1,count+1)}
assert set(blocks) == expected, 'Requirement inventory mismatch'
for rid,body in blocks.items():
    for attr in ['**Owner:**','**Priority:**','**Verification:**','**Trace:**','**Acceptance criteria']:
        assert attr in body, (rid,attr)
    assert 'Unassigned' not in body.split('**Owner:**')[1].splitlines()[0], rid

matrix = {}
for row in rows('docs/requirement-matrix.md','| <a id='):
    assert len(row)==7, ('matrix columns',row)
    rid=re.search(r'\[(CA-(?:FR|NFR|SEC)-\d{3})\]',row[0])[1]
    assert rid not in matrix, rid
    matrix[rid]=row
    assert 'CA-TEST-'+rid[3:] in row[6], rid
    assert row[1].strip() in blocks[rid], ('owner',rid)
assert set(matrix)==expected

backlog={re.search(r'CA-(\d{3})',r[0])[1]:r for r in rows('docs/traceability.md','| [CA-')}
for rid,row in matrix.items():
    forward=set(re.findall(r'CA-(\d{3}) / #',row[2]))
    reverse={n for n,r in backlog.items() if rid in ids(r[1],'(?:FR|NFR|SEC)')}
    assert forward==reverse, ('issue reverse edge',rid,forward,reverse)
    assert forward==set(re.findall(r'`CA-(\d{3})`',blocks[rid])), ('SRS issue edge',rid)

threats={r[0].strip():r for r in rows('docs/security/threat-model.md','| CA-THREAT-')}
assert len(threats)==6
for tid,row in threats.items():
    assert ids(row[3],'RISK') and ids(row[4],'(?:FR|NFR|SEC)'), tid
    assert {'CA-TEST-'+r[3:] for r in ids(row[4],'(?:FR|NFR|SEC)')} == ids(row[5],'TEST-(?:FR|NFR|SEC)'), tid
for rid,row in matrix.items():
    forward=set(re.findall(r'CA-THREAT-[STRIDE]-\d{3}',row[5]))
    reverse={tid for tid,t in threats.items() if rid in ids(t[4],'(?:FR|NFR|SEC)')}
    assert forward==reverse, ('threat reverse edge',rid)
    for tid in forward:
        assert ids(threats[tid][3],'RISK')<=ids(row[4],'RISK'), ('risk chain',rid,tid)

riskrows=rows('docs/security/risk-register.md','| CA-RISK-')
for row in riskrows:
    rid=row[0].strip()
    if len(row)==3 and 'Threat requirements/tests' in row[2]:
        assert set(re.findall(r'CA-THREAT-[STRIDE]-\d{3}',row[1]))=={t for t,r in threats.items() if rid in ids(r[3],'RISK')}, ('risk threat reverse',rid)
    elif len(row)==3:
        assert ids(row[1],'(?:FR|NFR|SEC)')=={r for r,m in matrix.items() if rid in ids(m[4],'RISK')}, ('risk requirement reverse',rid)

for i in range(1,9):
    did=f'CA-DEC-{i:03}'
    d=read(f'docs/architecture/adr/{did}.md')
    for attr in ['**Status:** Proposed','**Decision owner:**','**Approval status:** No approval recorded','## Rationale','## Alternatives','## Security implications','## Review triggers','## Approval record']:
        assert attr in d, (did,attr)
    assert ids(d,'(?:FR|NFR|SEC)')=={r for r,m in matrix.items() if did in m[3]}, ('decision reverse',did)
assert 'CA-DEC-007' in backlog['010'][2]
scenario=read('docs/scenarios/CA-SCENARIO-001.md')
assert 'CA-TEST-FR-011' in scenario and 'CA-TEST-SEC-007' in scenario
assert len(set(re.findall(r'^### CA-SCENARIO-001-[A-E]',scenario,re.M)))==5

links=0
for path in ROOT.rglob('*.md'):
    if '.git' in path.parts: continue
    content=path.read_text(encoding='utf-8')
    assert content.endswith('\n') and not content.endswith('\n\n'), ('EOF',path)
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',content):
        if re.match(r'\w+://|mailto:',target): continue
        name,_,anchor=target.partition('#')
        dest=(path.parent/name).resolve() if name else path
        assert dest.is_file(), ('broken link',path,target)
        if anchor:
            assert f'id="{anchor}"' in dest.read_text(encoding='utf-8'), ('missing explicit anchor',path,target)
        links+=1
    # Catch blank lines accidentally splitting tables or wrong-width rows.
    table_width=None
    for line in content.splitlines():
        if line.startswith('|'):
            width=line.count('|')
            if table_width is None: table_width=width
            assert width==table_width, ('table width',path,line)
        else: table_width=None
print(f'PASS: 36/36 requirement attributes, owner and test mappings; 10 issue reverse mappings; 8 proposed decision reverse mappings; 6 STRIDE threat/risk/requirement/test chains; risk reverse mappings; five variants; {links} local links/anchors; Markdown table widths and EOF formatting.')
print('Documentation validation only. No application, security, replay or benchmark test has been executed.')
