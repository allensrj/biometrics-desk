"""Cloud release gate: independent provenance, exact date window and source health."""
from pathlib import Path
from datetime import datetime,timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json

root=Path(__file__).resolve().parents[1]
data=json.loads((root/'clinical.json').read_text())
today=datetime.now(ZoneInfo('Asia/Shanghai')).date()
assert data['collectorVersion']=='official-direct-v1'
assert data['windowEnd']==today.isoformat(), 'Refuse to publish an old collection as today'
assert data['windowStart']==(today-timedelta(days=89)).isoformat()
assert len(data['sources'])==9
assert len({s['name'] for s in data['sources']})==9
assert any(s['read'] for s in data['sources']), 'No official source was read'
assert data['items'] or data['agendaOnly'], 'No independently verified records available'
assert data['items']==sorted(data['items'],key=lambda r:(r['published'],r['source'],r['url']),reverse=True)
allowed={'cdisc.org','cde.org.cn','ich.org','fda.gov','phuse.global','federalregister.gov','pmda.go.jp','nih.gov','ema.europa.eu'}
for row in data['items']+data['agendaOnly']:
    assert row['provenance']['kind']=='official-direct-v1'
    host=urlsplit(row['url']).hostname or ''
    assert any(host==d or host.endswith('.'+d) for d in allowed),host
    assert row['importance'] in ('高','中','低')
    assert row['evidence'] and row['analysisMethod'].startswith('DeepSeek')
for row in data['items']:
    assert data['windowStart']<=row['published']<=data['windowEnd']
    assert row['dateEvidence']
for row in data['agendaOnly']:
    assert row['deadline']>=data['windowEnd'] and row['deadlineEvidence']
# Build code must not fetch the old published aggregate, even as a fallback.
for path in [root/'refresh.py',*(root/'collector').glob('*.py')]:
    code=path.read_text()
    assert 'EmilyLiu312/clinical-biometrics-radar/main/data.json' not in code
    assert 'upstream_clinical' not in code
print(f"PASS: {len(data['items'])} independent news, {len(data['agendaOnly'])} agenda records, 9 explicit source statuses")
