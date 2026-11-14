import json
import subprocess
import sys
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'tools'/'real_world_tests.py'
ROOT=SCRIPT.parents[1]

def call(*args):
    return subprocess.run([sys.executable,str(SCRIPT),*args],capture_output=True,text=True)

def test_catalog_and_runs_validate():
    p=call('verify')
    assert p.returncode==0,p.stderr+p.stdout

def test_imported_snapshot_preserved():
    cases=json.loads((ROOT/'testing/catalog.json').read_text(encoding='utf8'))
    legacy=json.loads((ROOT/'testing/runs/legacy-spreadsheet-0.27.0.json').read_text(encoding='utf8'))
    assert len(cases)>=881
    assert [x['id'] for x in cases[:881]]==list(range(1,882))
    assert len(legacy['results'])==881
    from collections import Counter
    statuses=Counter(v['status'] for v in legacy['results'].values())
    assert statuses=={'pass':405,'fail':14,'blocked':35,'na':10,'not-tested':417}

def test_public_export_omits_evidence(tmp_path):
    p=call('publish','--output',str(tmp_path))
    assert p.returncode==0,p.stderr+p.stdout
    data=(tmp_path/'runs.json').read_text(encoding='utf8')
    assert not any(set(x).intersection({'evidence','tester','notes'}) for x in json.loads(data))
    # (every case in the catalog but those on hold: it grows as features add theirs)
    cases=json.loads((ROOT/'testing/catalog.json').read_text(encoding='utf8'))
    held={t['id'] for t in cases if t.get('on_hold')}
    published=json.loads((tmp_path/'catalog.json').read_text(encoding='utf8'))
    assert len(published)==len(cases)-len(held) and len(cases)>=881

def test_tests_on_hold_stay_out_of_public_data_and_new_runs(tmp_path):
    sys.path.insert(0,str(SCRIPT.parent))
    import real_world_tests as cli
    held=cli.on_hold()
    assert {31,49,781,801,821}<=held  # the Dad Test, on hold for now
    assert held.isdisjoint(cli.scope('full',set(),set(),set()))
    p=call('publish','--output',str(tmp_path))
    assert p.returncode==0,p.stderr+p.stdout
    assert held.isdisjoint(t['id'] for t in json.loads((tmp_path/'catalog.json').read_text(encoding='utf8')))
    runs=json.loads((tmp_path/'runs.json').read_text(encoding='utf8'))
    for r in runs:
        assert held.isdisjoint(r['required_ids']) and held.isdisjoint(int(k) for k in r['results'])
    # (oldest version first: the dashboard's latest-result view relies on it)
    keys=[cli.version_key(r['cc_version']) for r in runs]
    assert keys==sorted(keys) and cli.version_key('0.27.0 (legacy workbook snapshot)')==(0,27,0)
    held_fix=call('new-run','--run','x-on-hold','--version','9.9.9','--kind','patch','--fixes','821')
    assert held_fix.returncode!=0 and 'on hold' in held_fix.stderr+held_fix.stdout
    assert not (ROOT/'testing/runs/x-on-hold.json').exists()

def test_smoke_and_run_immutability(tmp_path):
    # Test the scope algorithm without altering the repository.
    sys.path.insert(0,str(SCRIPT.parent))
    import real_world_tests as cli
    g=cli.scope('patch',set(),set(),set())
    assert set(g)=={t['id'] for t in cli.catalog() if t['type']=='Gate'}-cli.on_hold()
    assert len(g)==20-len({t['id'] for t in cli.catalog() if t['type']=='Gate'}&cli.on_hold())
    assert set(g).issubset(set(cli.scope('minecraft',set(),set(),set())))
