#!/usr/bin/env python3
"""Craft Conductor real-world testing. Stdlib only; safe for Claude Code on Windows.

Record results in versioned JSON runs; never mutate a previous release's result by creating
an unrelated run. Keep raw evidence in private issue attachments; published HTML excludes notes.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'testing'
CATALOG = DATA / 'catalog.json'
RUNS = DATA / 'runs'
STATUSES = ('pass', 'fail', 'blocked', 'na', 'not-tested')
KINDS = ('patch', 'feature', 'minecraft', 'high-risk', 'full')

def read(path):
    with open(path, encoding='utf-8') as f: return json.load(f)

def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')
    tmp.replace(path)

def catalog():
    return read(CATALOG)

def index():
    return {int(x['id']): x for x in catalog()}

def on_hold():
    """Tests put on hold (`hold`): kept in the catalog and in old runs, but left out of new runs, reports and
    the public dashboard until `unhold`."""
    return {int(x['id']) for x in catalog() if x.get('on_hold')}

def version_key(version):
    """Sorts runs by Craft Conductor version: '0.30.3' after '0.29.0' ('0.27.0 (legacy ...)' counts as 0.27.0)."""
    m=re.match(r'\d+(?:\.\d+)*',str(version))
    return tuple(int(n) for n in m.group().split('.')) if m else ()

def load_run(value):
    p = Path(value)
    if not p.is_file(): p = RUNS / (value if str(value).endswith('.json') else value+'.json')
    if not p.is_file(): raise SystemExit(f'No run: {value}')
    return p, read(p)

def utc(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

def ids(text):
    if not text: return set()
    out=set()
    for piece in text.split(','):
        piece=piece.strip()
        if not piece:continue
        if '-' in piece:
            lo,hi=map(int,piece.split('-',1)); out.update(range(lo,hi+1))
        else:out.add(int(piece))
    return out

def scope(kind, feature, fixes, extra):
    rows=catalog()
    selected={x['id'] for x in rows if x.get('type')=='Gate'}
    if kind in ('minecraft','high-risk','full'):
        selected.update(x['id'] for x in rows if kind=='full' or 'minecraft-version' in x.get('tags',[]))
    if kind in ('high-risk','full'):
        selected.update(x['id'] for x in rows if kind=='full' or 'security' in x.get('tags',[]))
    selected |= feature | fixes | extra
    missing = selected - set(index())
    if missing:raise SystemExit(f'Test ID(s) not in catalog: {sorted(missing)}. Add cases first.')
    held = (feature | fixes | extra) & on_hold()
    if held:raise SystemExit(f'Test ID(s) on hold: {sorted(held)}. Use unhold first.')
    return sorted(selected - on_hold())

def cmd_new(a):
    if not re.fullmatch(r'[A-Za-z0-9._-]+',a.run): raise SystemExit('Run slug must use letters, digits, . _ -')
    target=RUNS/f'{a.run}.json'
    if target.exists(): raise SystemExit(f'Run already exists: {target}; no reset or overwrite allowed')
    if a.kind in ('patch','feature') and not (a.features or a.fixes) and not a.confirm_no_changes:
        raise SystemExit('For a patch or feature run, pass --features/--fixes or --confirm-no-changes. Do not silently omit new features or fixes.')
    chosen=scope(a.kind,ids(a.features),ids(a.fixes),ids(a.extra))
    obj={'schema_version':1,'id':a.run,'cc_version':a.version,'minecraft_version':a.minecraft or '',
         'os':a.os or '', 'kind':a.kind,'created_at':utc(),'features':sorted(ids(a.features)),
         'fixes':sorted(ids(a.fixes)),'required_ids':chosen,'results':{},'notes':a.notes or ''}
    write(target,obj)
    print(f'Created {target.relative_to(ROOT)} with {len(chosen)} required tests; nothing is pre-passed.')

def cmd_record(a):
    p, run=load_run(a.run)
    t=int(a.id)
    if t not in index():raise SystemExit(f'Unknown test ID {t}; use add-test first.')
    if t in on_hold():raise SystemExit(f'Test {t} is on hold ({index()[t]["on_hold"]}); use unhold first.')
    if t not in run['required_ids']:
        if not a.allow_extra:raise SystemExit(f'Test {t} is outside the run scope. Use --allow-extra to record it intentionally.')
        run['required_ids']=sorted(set(run['required_ids'])|{t})
    old=run['results'].get(str(t))
    if old and not a.replace:raise SystemExit(f'Test {t} already has a result; use --replace for a documented correction.')
    item={'status':a.status, 'tested_at':utc(), 'tester':a.tester or '', 'notes':a.notes or '', 'evidence':a.evidence or ''}
    if a.date:item['tested_at']=a.date
    if old:item['supersedes']=old
    run['results'][str(t)]=item
    write(p,run)
    print(f'{a.run} / test {t}: {a.status} recorded')

def cmd_add(a):
    rows=catalog()
    proposed=int(a.id) if a.id else max([int(x['id']) for x in rows]+[0])+1
    if proposed in index():raise SystemExit(f'Test ID {proposed} already exists')
    rows.append({'id':proposed,'section':a.section,'step':a.step,'type':a.type,
                 'tags':sorted(set(a.tag or [])), 'source':'added-in-git'})
    rows.sort(key=lambda x:int(x['id']))
    write(CATALOG,rows)
    print(f'Added test {proposed}. Include it as --features or --fixes in the release run.')

def cmd_hold(a, hold=True):
    rows=catalog(); chosen=ids(a.ids)
    missing=chosen-{int(x['id']) for x in rows}
    if missing:raise SystemExit(f'Test ID(s) not in catalog: {sorted(missing)}')
    for x in rows:
        if x['id'] in chosen:
            if hold:x['on_hold']=a.reason
            else:x.pop('on_hold',None)
    write(CATALOG,rows)
    print(f"{len(chosen)} test(s) {'on hold' if hold else 'back in testing'}.")

def cmd_report(a):
    p,run=load_run(a.run)
    results=run.get('results',{})
    held=on_hold()
    selected=[t for t in run.get('required_ids',[]) if t not in held]
    counts=Counter(results.get(str(t),{}).get('status','not-tested') for t in selected)
    # not-tested isn't silently considered passed, even for older releases.
    print(f"Run: {run['id']} | Craft Conductor {run['cc_version']} | kind={run['kind']} | Minecraft={run.get('minecraft_version') or '?'} | OS={run.get('os') or '?'}")
    print(f"Required: {len(selected)} | " + ' | '.join(f'{k}: {counts[k]}' for k in STATUSES)
          + (f" | on hold (not counted): {len(set(run.get('required_ids',[]))&held)}" if set(run.get('required_ids',[]))&held else ''))
    ready=bool(selected) and counts['pass']+counts['na']==len(selected)
    print('Release gate:', 'READY FOR REVIEW' if ready else 'NOT READY')
    if a.missing:
        for t in selected:
            item=results.get(str(t))
            if not item or item['status']!='pass':
                print(f"#{t} {item['status'] if item else 'not-tested'} | {index()[t]['step'][:150]}")
    return 0 if ready or not a.fail_if_not_ready else 2

def cmd_summary(a):
    rows=catalog(); print(f'Catalog: {len(rows)} cases, {len({x["section"] for x in rows})} sections, {len(on_hold())} on hold')
    for p in sorted(RUNS.glob('*.json')):
        r=read(p); s=Counter(v.get('status') for v in r.get('results',{}).values())
        print(f"{r.get('id',p.stem):<28} {r.get('cc_version','?'):<12} " + ' '.join(f'{k}={s[k]}' for k in STATUSES))

def cmd_list(a):
    cases=catalog()
    if a.section:cases=[x for x in cases if a.section.lower() in x['section'].lower()]
    if a.search:cases=[x for x in cases if a.search.lower() in (x['section']+' '+x['step']).lower()]
    if a.type:cases=[x for x in cases if x.get('type')==a.type]
    results=load_run(a.run)[1].get('results',{}) if a.run else None
    for x in cases:
        st=f" [{results.get(str(x['id']),{}).get('status','not-tested')}]" if results is not None else ''
        if x.get('on_hold'):st+=' [on hold]'
        print(f"#{x['id']} ({x['type']}){st} {x['section']}: {x['step']}")

def cmd_verify(a):
    c=catalog(); known=set(); errs=[]
    for t in c:
        if not isinstance(t.get('id'),int) or t['id'] in known:errs.append(f'Duplicate/invalid test id {t.get("id")}')
        known.add(t['id'])
        for field in ('section','step','type'):
            if not str(t.get(field,'' )).strip():errs.append(f"Test {t.get('id')}: missing {field}")
        if 'on_hold' in t and not (isinstance(t['on_hold'],str) and t['on_hold'].strip()):
            errs.append(f"Test {t.get('id')}: on_hold needs a reason")
    for p in RUNS.glob('*.json'):
        r=read(p)
        for key in ('id','cc_version','kind','required_ids','results'):
            if key not in r:errs.append(f'{p}: missing {key}')
        for n in r.get('required_ids',[]):
            if n not in known:errs.append(f'{p}: unknown required test {n}')
        for n,item in r.get('results',{}).items():
            if not n.isdigit() or int(n) not in known:errs.append(f'{p}: unknown result {n}')
            if item.get('status') not in STATUSES:errs.append(f'{p}: unknown status {item.get("status")}')
    for e in errs:print('ERROR:',e)
    print(f'{len(c)} tests, {len(list(RUNS.glob("*.json")))} runs, {len(errs)} validation errors')
    return 1 if errs else 0

def cmd_publish(a):
    """Generate public data. Never expose notes/evidence, machine identifiers or tester details.
    Tests on hold are left out, with their results. Runs are oldest first (by version, then when made)."""
    target=Path(a.output);target.mkdir(parents=True,exist_ok=True)
    held=on_hold()
    c=[t for t in catalog() if t['id'] not in held]
    sanitized=[{'id':t['id'],'section':t['section'],'step':t['step'],'type':t['type'],'tags':t.get('tags',[])} for t in c]
    write(target/'catalog.json',sanitized)
    runs=[]
    for p in sorted(RUNS.glob('*.json')):
        r=read(p)
        runs.append({'id':r['id'],'cc_version':r['cc_version'],'kind':r['kind'],
          'minecraft_version':r.get('minecraft_version',''),'os':r.get('os',''),
          'created_at':str(r.get('created_at',''))[:10],
          'required_ids':[t for t in r.get('required_ids',[]) if t not in held],
          'results':{k:v['status'] for k,v in r['results'].items() if v.get('status') in STATUSES and int(k) not in held}})
    runs.sort(key=lambda r:(version_key(r['cc_version']),r['created_at'],r['id']))
    write(target/'runs.json',runs)
    print(f'Public dashboard data: {len(sanitized)} tests, {len(runs)} runs, NO evidence/testers/notes.')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='cmd',required=True)
    z=sub.add_parser('summary');z.set_defaults(fn=cmd_summary)
    z=sub.add_parser('list');z.add_argument('--search');z.add_argument('--section');z.add_argument('--type',choices=['Core','Gate','Extra']);z.add_argument('--run');z.set_defaults(fn=cmd_list)
    z=sub.add_parser('new-run');z.add_argument('--run',required=True);z.add_argument('--version',required=True);z.add_argument('--kind',choices=KINDS,required=True);z.add_argument('--minecraft');z.add_argument('--os');z.add_argument('--features',default='');z.add_argument('--fixes',default='');z.add_argument('--extra',default='');z.add_argument('--notes');z.add_argument('--confirm-no-changes',action='store_true');z.set_defaults(fn=cmd_new)
    z=sub.add_parser('record');z.add_argument('--run',required=True);z.add_argument('--id',type=int,required=True);z.add_argument('--status',choices=STATUSES,required=True);z.add_argument('--tester');z.add_argument('--notes');z.add_argument('--evidence');z.add_argument('--date');z.add_argument('--replace',action='store_true');z.add_argument('--allow-extra',action='store_true');z.set_defaults(fn=cmd_record)
    z=sub.add_parser('add-test');z.add_argument('--id',type=int);z.add_argument('--section',required=True);z.add_argument('--step',required=True);z.add_argument('--type',choices=['Core','Gate','Extra'],default='Core');z.add_argument('--tag',action='append');z.set_defaults(fn=cmd_add)
    z=sub.add_parser('hold');z.add_argument('--ids',required=True);z.add_argument('--reason',required=True);z.set_defaults(fn=cmd_hold)
    z=sub.add_parser('unhold');z.add_argument('--ids',required=True);z.set_defaults(fn=lambda a:cmd_hold(a,hold=False))
    z=sub.add_parser('report');z.add_argument('--run',required=True);z.add_argument('--missing',action='store_true');z.add_argument('--fail-if-not-ready',action='store_true');z.set_defaults(fn=cmd_report)
    z=sub.add_parser('verify');z.set_defaults(fn=cmd_verify)
    z=sub.add_parser('publish');z.add_argument('--output',required=True);z.set_defaults(fn=cmd_publish)
    a=p.parse_args(argv)
    try: return a.fn(a) or 0
    except (ValueError,KeyError,json.JSONDecodeError) as e:
        print(f'Invalid test data or arguments: {e}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
