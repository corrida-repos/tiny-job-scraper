import argparse
import csv
import json
import os
import sys
import tempfile
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from .models import utcnow, parse_date
from .daily import prepare_email
from .filtering import Screener
from .fetchers import Fetcher
from .http import HttpClient
from .state import State
from .criteria import load as load_criteria

ROOT=Path(__file__).resolve().parents[2]
CONFIG=ROOT/"config" if (ROOT/"config").is_dir() else Path(sys.prefix)/"share/pm-career-scraper/config"

@contextmanager
def lock(path):
    path=Path(str(path)+'.lock');path.parent.mkdir(parents=True,exist_ok=True)
    f=path.open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            f.seek(0);f.write(b'0');f.flush();f.seek(0)
            try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError('Another scraper process holds the state lock')
        else:
            import fcntl
            try:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('Another scraper process holds the state lock')
        yield
    finally:f.close()

def atomic(path, content):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f:f.write(content);temp=f.name
    os.replace(temp,path)

def md(value):return str(value or '').replace('|','\\|').replace('\n',' ')

def export(out,results,pairs,delivery,selected,started,finished,requests,freshness_hours=48,criteria=None):
    health=[r.summary() for r in sorted(results,key=lambda x:x.company)]
    counts=Counter(a.status for j,a in pairs)
    payload={'freshness_hours':freshness_hours,'started_at':started,'finished_at':finished,'http_requests':requests,'coverage':{'sources':len(results),'complete':sum(r.complete and r.status=='ok' for r in results),'attention':sum(not r.complete or r.status!='ok' for r in results)},'counts':dict(counts),'sources':health,
             'jobs':[{'job':j.to_dict(),'assessment':asdict(a)} for j,a in pairs]}
    if criteria is not None:
        payload['criteria'] = criteria
    atomic(out/'results.json',json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    atomic(out/'source-health.json',json.dumps(health,ensure_ascii=False,indent=2)+'\n')
    email = prepare_email(pairs, payload)
    atomic(out/'email.json',json.dumps(email,ensure_ascii=False,indent=2)+'\n')
    atomic(out/'email.md',email['body_markdown'])
    digest={'delivery_id':delivery,'created_at':finished,'jobs':[{'job':j.to_dict(),'assessment':asdict(a)} for j,a in selected]}
    atomic(out/'digest.json',json.dumps(digest,ensure_ascii=False,indent=2)+'\n')
    report=[f'# PM careers monitor — {finished[:10]}','',f"Checked {len(results)} sources: {payload['coverage']['complete']} complete; {payload['coverage']['attention']} need attention.",f"Allowed-title candidates: {len(pairs)}. Eligible: {counts['eligible']}; review: {counts['review']}; rejected: {counts['rejected']}. New eligible for notification: {len(selected)}.",'',
      'Eligibility is rule-based screening, not a guarantee of workload or working conditions. Review means evidence is missing. Employer work-life-balance notes are context from the saved shortlist.','',
      '## New eligible roles','']
    if selected:
        for j,a in selected:
            report += [f'### {j.company} — {j.title}',f'- Apply: {j.url}',f'- Location: {j.location}',f'- Original date: {j.posted_at}',f'- Attendance: {a.checks["attendance"]["evidence"]}',f'- Travel: {a.checks["travel"]["evidence"]}',f'- Work-life balance: {j.metadata.get("wlb_context","")}',f'- Salary: {a.checks["salary"]["evidence"]}','']
        report += [f'Delivery ID: `{delivery}`. Not marked reported until successful delivery is acknowledged.','']
    else:report += ['No new, fully verified matches. This does not mean all companies have no relevant vacancies.','']
    report+=['## Roles needing confirmation','','| Employer | Role | Location | Evidence needed |','|---|---|---|---|']
    for j,a in sorted(pairs,key=lambda x:(-x[1].score,x[0].metadata.get('employer_rank',999))):
        if a.status=='review':report.append(f'| {md(j.company)} | [{md(j.title)}]({j.url}) | {md(j.location)} | {md("; ".join(a.reasons))} |')
    report+=['','## Source health','','| Employer | Adapter | Status | Listed | Candidates | Details |','|---|---|---|---:|---:|---|']
    for r in sorted(results,key=lambda x:x.company):report.append(f'| {md(r.company)} | {r.adapter} | {r.status} | {r.discovered} | {len(r.jobs)} | {md("; ".join(r.messages))} |')
    report+=['','Full descriptions, evidence and all rejected candidates are in results.json and roles.csv.','']
    atomic(out/'report.md','\n'.join(report))
    # CSV is an export for inspection. Guard formula-leading cells when opened in spreadsheets.
    from io import StringIO
    buf=StringIO();writer=csv.writer(buf);writer.writerow(['company','title','location','status','priority_score','original_posted','date_kind','url','reasons','key'])
    def cell(v):
        v=str(v or '')
        return "'"+v if v.startswith(('=','+','-','@','\t','\r')) else v
    for j,a in pairs:writer.writerow([cell(x) for x in [j.company,j.title,j.location,a.status,a.score,j.posted_at,j.date_kind,j.url,'; '.join(a.reasons),j.key]])
    atomic(out/'roles.csv',buf.getvalue())
    return payload

def run(args, started=None):
    started = started or utcnow().isoformat()
    if args.require_existing_state and not Path(args.state).is_file():
        raise FileNotFoundError('Required production state is missing; refusing to create an empty database')
    companies=json.loads(Path(args.companies).read_text());criteria=load_criteria(args.criteria)
    if args.max_post_age_days is not None:
        criteria['max_post_age_days'] = args.max_post_age_days
    screener=Screener(criteria)
    if args.only:
        selected=set(args.only.split(','));companies=[c for c in companies if c['id'] in selected or str(c['rank']) in selected]
        if not companies:raise ValueError('--only did not match an employer ID/rank')
    if len({c['id'] for c in companies})!=len(companies):raise ValueError('Duplicate company IDs')
    out=Path(args.output);statepath=Path(args.state);statepath.parent.mkdir(parents=True,exist_ok=True)
    overrides=json.loads(Path(args.overrides).read_text()) if args.overrides and Path(args.overrides).exists() else {}
    http=HttpClient(timeout=args.timeout,delay=args.delay,retries=1)
    with lock(statepath):
        state=State(statepath)
        try:
            results=[];pairs=[]
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futures={ex.submit(Fetcher(http,screener,args.max_pages,args.max_details).fetch,c):c for c in companies}
                for future in as_completed(futures):
                    c=futures[future];r=future.result();results.append(r);local=[]
                    for j in r.jobs:
                        j.metadata.update({'employer_rank':c['rank'],'wlb_context':c['wlb_note'],'employer_location_context':c['location_note'],'careers_url':c['careers_url']})
                        state.original(j)
                        a=screener.assess(j,now=parse_date(started),override=overrides.get(j.key));local.append((j,a))
                    pairs+=local;state.record(r,local,utcnow().isoformat())
                    print(json.dumps({'company':r.company,'status':r.status,'listed':r.discovered,'candidates':len(r.jobs),'messages':r.messages},ensure_ascii=False),flush=True)
            finished=utcnow().isoformat();delivery,selected=state.eligible_delivery(pairs,finished)
            payload=export(out,results,pairs,delivery,selected,started,finished,http.requests,criteria["max_post_age_days"]*24,criteria)
            state.record_run(uuid.uuid4().hex,started,finished,payload['sources'])
            print(json.dumps({'output':str(out.resolve()),'coverage':payload['coverage'],'counts':payload['counts'],'delivery_id':delivery,'new_eligible':len(selected)},ensure_ascii=False))
            return 2 if payload['coverage']['attention'] else 0
        finally:state.close()

def main(argv=None):
    p=argparse.ArgumentParser(description='Daily 56-employer PM careers scraper; public read-only retrieval')
    sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');r.add_argument('--companies',default=str(CONFIG/'companies.json'));r.add_argument('--criteria',default=str(CONFIG/'criteria.json'));r.add_argument('--state',default='data/state.sqlite3');r.add_argument('--output',default='output/latest');r.add_argument('--overrides',default=str(CONFIG/'verified-overrides.json'))
    r.add_argument('--only',help='Comma-separated company IDs or ranks');r.add_argument('--workers',type=int,default=6);r.add_argument('--delay',type=float,default=1.0);r.add_argument('--timeout',type=int,default=25);r.add_argument('--max-pages',type=int,default=None,help='Override source page limits (normally 60; Infineon 200)');r.add_argument('--max-details',type=int,default=250)
    r.add_argument('--max-post-age-days',type=int,choices=range(1,31),default=None,help='One-run freshness override (1–30 days); default uses saved criteria')
    r.add_argument('--require-existing-state',action='store_true',help='Refuse to create a new state database; use for production migration')
    a=sub.add_parser('ack',help='Mark a digest reported only after confirmed successful delivery');a.add_argument('delivery_id');a.add_argument('--receipt',required=True);a.add_argument('--state',default='data/state.sqlite3')
    pending=sub.add_parser('pending',help='List unacknowledged digest attempts for send reconciliation');pending.add_argument('--state',default='data/state.sqlite3')
    s=sub.add_parser('sources');s.add_argument('--companies',default=str(CONFIG/'companies.json'))
    v=sub.add_parser('validate-criteria',help='Check screening settings without network, state writes or email');v.add_argument('--criteria',default=str(CONFIG/'criteria.json'))
    args=p.parse_args(argv)
    if args.command=='validate-criteria':
        try:
            criteria=load_criteria(args.criteria)
        except (OSError, ValueError) as error:
            print('Invalid criteria: '+str(error),file=sys.stderr)
            return 1
        print(f"Valid criteria: {len(criteria['role_families'])} role families; {criteria['max_post_age_days']*24}-hour freshness; potential matches {'included' if criteria['include_potential_matches'] else 'excluded'}; unknown freshness {'included' if criteria['include_unknown_freshness'] else 'excluded'}; future-dated {'included' if criteria['include_future_dated'] else 'excluded'}")
        return 0
    if args.command=='run':
        if not 1<=args.workers<=12 or args.delay<0.5 or (args.max_pages is not None and not 1<=args.max_pages<=200) or not 1<=args.max_details<=1000:p.error('Use workers 1..12, delay >=0.5, pages 1..200, details 1..1000')
        started = utcnow().isoformat()
        try:
            return run(args, started)
        except Exception as error:
            # A failed attempt also needs a fresh artifact, never yesterday's
            # email or an empty-success report. Preserve the failure exit code.
            payload = {'freshness_hours': (args.max_post_age_days or 2)*24, 'started_at': started, 'finished_at': utcnow().isoformat(),
                       'coverage': {'sources': 0, 'complete': 0, 'attention': 1},
                       'counts': {}, 'jobs': [], 'sources': [
                           {'company': 'Run failure', 'status': type(error).__name__,
                            'complete': False, 'messages': [str(error)]}]}
            out = Path(args.output)
            try:
                email = prepare_email([], payload, saving='Attempt failed; durable saving and delivery not confirmed')
                atomic(out/'results.json', json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
                atomic(out/'source-health.json', json.dumps(payload['sources'], ensure_ascii=False, indent=2)+'\n')
                atomic(out/'email.json', json.dumps(email, ensure_ascii=False, indent=2)+'\n')
                atomic(out/'email.md', email['body_markdown'])
            except OSError as write_error:
                print(f'Failure report could not be saved: {type(write_error).__name__}', file=sys.stderr)
            print(f'Run failed: {type(error).__name__}: {error}', file=sys.stderr)
            return 1
    if args.command=='sources':
        for c in json.loads(Path(args.companies).read_text()):print(f"{c['rank']:02} {c['id']} [{c['source']['adapter']}] {c['careers_url']}")
        return 0
    if args.command=='pending':
        state=State(args.state)
        try:print(json.dumps([dict(r) for r in state.db.execute("SELECT id,created_at,keys_json FROM deliveries WHERE status='pending'").fetchall()]))
        finally:state.close()
        return 0
    if args.command=='ack':
        with lock(args.state):
            state=State(args.state)
            try:print('Acknowledged' if state.ack(args.delivery_id,utcnow().isoformat(),args.receipt) else 'Already acknowledged')
            finally:state.close()
        return 0

if __name__=='__main__':raise SystemExit(main())
