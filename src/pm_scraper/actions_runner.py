"""GitHub Actions orchestration. Plain state stays outside both Git checkouts."""
import argparse
import base64
import hashlib
import imaplib
import io
import json
import os
from pathlib import Path
import re
import smtplib
import sqlite3
import ssl
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from email.message import EmailMessage
import zipfile

AAD = b'tiny-job-scraper-state-v1'
FILES = {'state.sqlite3', 'meta.json', 'audit.md', 'results.json', 'email.json'}


def key_bytes(value):
    key = base64.b64decode(value.strip(), validate=True)
    if len(key) != 32:
        raise ValueError('STATE_ENCRYPTION_KEY must encode exactly 32 bytes')
    return key


def seal(folder, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(FILES):
            path = Path(folder)/name
            if path.exists():
                z.writestr(name, path.read_bytes())
    nonce = os.urandom(12)
    return AAD + nonce + AESGCM(key).encrypt(nonce, archive.getvalue(), AAD)


def unseal(data, folder, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not data.startswith(AAD):
        raise ValueError('Unsupported encrypted state format')
    nonce = data[len(AAD):len(AAD)+12]
    plain = AESGCM(key).decrypt(nonce, data[len(AAD)+12:], AAD)
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        if not {'state.sqlite3','meta.json'} <= set(z.namelist()) or len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Incomplete or duplicate state entries')
        if any(i.filename not in FILES or i.file_size > 100_000_000 for i in z.infolist()):
            raise ValueError('Unexpected archive entry')
        Path(folder).mkdir(parents=True, exist_ok=True)
        for name in z.namelist():
            p = Path(folder)/name
            p.write_bytes(z.read(name));p.chmod(0o600)
    validate_state(Path(folder)/'state.sqlite3')


def validate_state(path):
    if not Path(path).is_file():
        raise FileNotFoundError('Production state is missing')
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        if db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() != ('1',):
            raise ValueError('Unsupported database schema')
        for table in ('jobs', 'runs', 'deliveries'):
            db.execute('SELECT count(*) FROM '+table).fetchone()


def git(folder, *args):
    return subprocess.check_output(['git', '-C', str(folder), *args], text=True, stderr=subprocess.PIPE).strip()


def persist(folder, checkout, key, label):
    validate_state(Path(folder)/'state.sqlite3')
    if git(checkout, 'branch', '--show-current') != 'runtime-state':
        raise ValueError('State persistence requires the runtime-state branch')
    # A normal push is a compare-and-swap: a concurrent remote update rejects
    # this commit. Never force-push or silently overwrite another writer.
    (Path(checkout)/'state.enc').write_bytes(seal(folder, key))
    git(checkout, 'add', '--', 'state.enc')
    git(checkout, 'commit', '-m', label)
    git(checkout, 'push', 'origin', 'HEAD:refs/heads/runtime-state')


class Gmail:
    def __init__(self, address, password):
        self.address, self.password = address.strip(), ''.join(password.split())

    def find(self, message_id):
        with imaplib.IMAP4_SSL('imap.gmail.com', ssl_context=ssl.create_default_context()) as mail:
            mail.login(self.address, self.password)
            status, rows = mail.list()
            if status != 'OK':
                raise RuntimeError('Gmail folder enumeration failed')
            folder = None
            for row in rows:
                if isinstance(row, bytes) and b'\\Sent' in row.split(b')',1)[0]:
                    match = re.match(rb'\([^)]*\) "[^"]*" (.*)', row)
                    if match:
                        folder = match.group(1).decode('ascii')
                        break
            if folder is None:
                raise RuntimeError('Gmail Sent folder unavailable')
            if mail.select(folder, readonly=True)[0] != 'OK':
                raise RuntimeError('Gmail Sent folder cannot be selected')
            status, rows = mail.uid('search', None, 'HEADER', 'Message-ID', '"'+message_id+'"')
            if status != 'OK':
                raise RuntimeError('Gmail Sent reconciliation failed')
            return rows[0].decode().split() if rows and rows[0] else []

    def send(self, recipient, draft, message_id):
        from markdown_it import MarkdownIt
        message = EmailMessage()
        message['From'] = self.address
        message['To'] = recipient
        message['Subject'] = draft['subject']
        message['Message-ID'] = message_id
        message.set_content(draft['body_markdown'])
        message.add_alternative(MarkdownIt('commonmark', {'html':False}).render(draft['body_markdown']), subtype='html')
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=45, context=ssl.create_default_context()) as smtp:
            smtp.login(self.address, self.password)
            refused = smtp.send_message(message)
            if refused:
                raise RuntimeError('Gmail rejected a recipient')


def write_meta(folder, meta):
    (Path(folder)/'meta.json').write_text(json.dumps(meta, indent=2)+'\n')


def set_saving(draft, note):
    draft['body_markdown'] = re.sub(r'^- Saving:.*$', '- Saving: '+note, draft['body_markdown'], flags=re.M)


def failure_draft(started, kind, freshness_days=2):
    from .daily import prepare_email
    payload = {'freshness_hours':freshness_days*24, 'started_at':started, 'coverage':{'sources':0,'complete':0,'attention':1},
               'sources':[{'company':'Runner','status':kind,'complete':False,'messages':[]}], 'jobs':[], 'counts':{}}
    return prepare_email([], payload)


def record_audit(folder, marker, draft, receipt=None):
    with sqlite3.connect(Path(folder)/'state.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS comprehensive_run_audits(run_marker TEXT PRIMARY KEY, started_at TEXT NOT NULL, results_json TEXT NOT NULL, email_message_id TEXT, sent_at TEXT)')
        results = Path(folder)/'results.json'
        db.execute('INSERT OR REPLACE INTO comprehensive_run_audits VALUES(?,?,?,?,?)',
                   (marker, datetime.now(timezone.utc).isoformat(), results.read_text() if results.exists() else '{}',
                    receipt, datetime.now(timezone.utc).isoformat() if receipt else None))


def announce_coverage(folder):
    path=Path(folder)/'results.json'
    if not path.exists():return
    data=json.loads(path.read_text())
    coverage=data.get('coverage')
    if not coverage:return
    def escaped(text):
        return str(text).replace('%','%25').replace('\r','%0D').replace('\n','%0A')
    summary=f"{coverage['complete']}/{coverage['sources']} source scopes complete; {coverage['attention']} need attention"
    print('::notice title=Source coverage::'+escaped(summary))
    gaps=[s['company']+': '+s['status']+(' — '+'; '.join(s.get('messages',[])) if s.get('messages') else '') for s in data.get('sources',[]) if not s['complete'] or s['status']!='ok']
    if gaps:print('::notice title=Coverage gaps::'+escaped('; '.join(gaps)))


def execute(checkout, source, output, send=False, freshness_days=2):
    key = key_bytes(os.environ['STATE_ENCRYPTION_KEY'])
    run_id = os.environ['GITHUB_RUN_ID']
    if not re.fullmatch(r'\d+', run_id):
        raise ValueError('Invalid GitHub run ID')
    marker = 'tiny-actions-'+run_id
    message_id = '<'+marker+'@tiny-job-scraper.invalid>'
    output = Path(output);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tiny-actions-') as temp:
        folder = Path(temp)
        unseal((Path(checkout)/'state.enc').read_bytes(), folder, key)
        meta = json.loads((folder/'meta.json').read_text())
        attempt = meta.setdefault('attempts', {}).get(run_id, {})
        if send:
            missing = [name for name in ('GMAIL_ADDRESS','GMAIL_APP_PASSWORD') if not os.environ.get(name,'').strip()]
            if missing:
                raise ValueError('Missing Actions secret: '+', '.join(missing))
        gmail = Gmail(os.environ['GMAIL_ADDRESS'], os.environ['GMAIL_APP_PASSWORD']) if send else None
        if send and attempt.get('status') == 'sent':
            print('This GitHub run already has a confirmed receipt; no retrieval or send repeated.')
            return 0
        if send and any(k != run_id and v.get('status') in {'prepared','sending'} for k,v in meta['attempts'].items()):
            raise RuntimeError('Another run has an unresolved delivery; reconcile it before starting a new run')
        # Always reconcile before retrieval: even an earlier failure to persist
        # a receipt must not make a retry send the same run twice.
        found = gmail.find(message_id) if send else []
        if found:
            attempt.update(status='sent', message_id=message_id, sent_uids=found)
            meta['attempts'][run_id] = attempt;write_meta(folder, meta)
            persist(folder, checkout, key, 'Reconcile '+marker)
            print('Existing Gmail message reconciled; no duplicate sent.')
            return 0
        if send and attempt.get('status') == 'sending':
            raise RuntimeError('Previous send outcome is uncertain; Sent has no matching message yet. Manual reconciliation required; refusing automatic resend.')
        if send and attempt.get('status') == 'prepared':
            freshness_days = attempt.get('freshness_days',freshness_days)
            draft = json.loads((folder/'email.json').read_text())
            if draft['run_marker'] != marker:
                raise RuntimeError('Prepared draft does not belong to this run; refusing mismatched delivery')
            code = attempt['scraper_exit_code']
        else:
            started = datetime.now(timezone.utc).isoformat()
            reports = folder/'reports'
            # Imported artifacts are historical. Only files created in the new
            # empty reports directory can become this attempt's outgoing email.
            try:
                result = subprocess.run([sys.executable, str(Path(source)/'run.py'), 'run', '--require-existing-state',
                    '--state',str(folder/'state.sqlite3'),'--output',str(reports),'--max-post-age-days',str(freshness_days)], cwd=source, timeout=2220)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 1
            if (reports/'email.json').exists():
                draft = json.loads((reports/'email.json').read_text())
                for src,dst in [('results.json','results.json'),('report.md','audit.md')]:
                    if (reports/src).exists():
                        (folder/dst).write_bytes((reports/src).read_bytes())
                # Failure paths must not retain old results/audit under a new marker.
                if not (reports/'report.md').exists():
                    (folder/'audit.md').write_text(draft['body_markdown'])
            else:
                draft = failure_draft(started, 'Runtime failure or timeout',freshness_days)
                (folder/'results.json').write_text(json.dumps({'started_at':started,'failure':True})+'\n')
                (folder/'audit.md').write_text(draft['body_markdown'])
            old_marker = draft['run_marker']
            draft['run_marker'] = marker
            draft['body_markdown'] = draft['body_markdown'].replace(old_marker, marker)
        announce_coverage(folder)
        attempt = {'status':'prepared','scraper_exit_code':code,'message_id':message_id,
                   'freshness_days':freshness_days, 'source_commit':git(source,'rev-parse','HEAD')}
        meta['attempts'][run_id] = attempt
        if not send:
            set_saving(draft, 'Validation only; production state unchanged; no email sent.')
            (folder/'email.json').write_text(json.dumps(draft,indent=2)+'\n')
            write_meta(folder,meta)
            (output/'validation.enc').write_bytes(seal(folder,key))
            (output/'summary.json').write_text(json.dumps({'mode':'validation','scraper_exit_code':code,
                'delivery':'not_sent','source_commit':attempt['source_commit']},indent=2)+'\n')
            print('Validation bundle encrypted; production state and Gmail unchanged. Scraper exit code:',code)
            return 0 if code in (0,2) else 1
        set_saving(draft, 'State and audit checkpoint saved to encrypted runtime-state; delivery pending.')
        (folder/'email.json').write_text(json.dumps(draft,indent=2)+'\n')
        write_meta(folder,meta);record_audit(folder,marker,draft)
        try:
            persist(folder,checkout,key,'Prepare '+marker)
            attempt['status']='sending';write_meta(folder,meta)
            persist(folder,checkout,key,'Record send intent '+marker)
        except subprocess.CalledProcessError:
            # Fulfil the operational-failure email even when persistence fails.
            # The stable Message-ID is searched in Sent before every retry.
            set_saving(draft,'Durable saving FAILED; original remote state preserved; manual reconciliation required before retry.')
            if not gmail.find(message_id):
                gmail.send(meta['recipient'],draft,message_id)
            raise RuntimeError('State checkpoint failed; failure email attempted. Inspect Sent and remote state before retrying.') from None
        # Any exception after persisted intent leaves an uncertain send; a rerun
        # must reconcile Sent rather than automatically repeat SMTP submission.
        gmail.send(meta['recipient'],draft,message_id)
        attempt.update(status='sent',message_id=message_id)
        draft['delivery_status']='smtp_accepted'
        set_saving(draft,'State and audit saved; Gmail accepted this message; receipt checkpoint follows.')
        (folder/'email.json').write_text(json.dumps(draft,indent=2)+'\n')
        write_meta(folder,meta);record_audit(folder,marker,draft,message_id)
        persist(folder,checkout,key,'Receipt '+marker)
        (output/'summary.json').write_text(json.dumps({'mode':'delivery','scraper_exit_code':code,'delivery':'smtp_accepted','source_commit':attempt['source_commit']},indent=2)+'\n')
        print('Gmail accepted the report and encrypted receipt was persisted. Scraper exit code:',code)
        if code == 2:
            print('::warning::Source coverage incomplete; details are in the delivered report.')
        return 0 if code in (0,2) else 1


def safe_error(error):
    text = str(error).lower()
    if isinstance(error, imaplib.IMAP4.error):
        if any(word in text for word in ('authenticationfailed', 'invalid credentials', 'authenticate failed', 'login failed')):
            return 'Gmail rejected IMAP authentication; verify GMAIL_ADDRESS and a Google app password for that same account.'
        if 'application-specific password' in text:
            return 'Gmail requires a Google app password; a normal account password cannot be used.'
        if 'disabled' in text or 'not enabled' in text:
            return 'Gmail IMAP access is disabled by account or organization settings.'
        if 'empty' in text:
            return 'Gmail received an empty username or password; check the two Actions secrets.'
        return 'Gmail IMAP request failed; check account IMAP policy and app-password access.'
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return 'Gmail rejected SMTP authentication; check sender and Google app password.'
    if isinstance(error, ValueError) and str(error).startswith('Missing Actions secret:'):
        return str(error)
    return 'Runner failed ('+type(error).__name__+'); check encrypted state and reconcile Sent before retrying.'


def main():
    p=argparse.ArgumentParser();p.add_argument('--state-checkout',required=True);p.add_argument('--source',default='.');p.add_argument('--output',default='output/actions');p.add_argument('--send',action='store_true')
    p.add_argument('--freshness-days',type=int,choices=[2,7],default=2)
    args=p.parse_args()
    try:
        return execute(Path(args.state_checkout).resolve(),Path(args.source).resolve(),Path(args.output).resolve(),args.send,args.freshness_days)
    except Exception as error:
        # SMTP/IMAP exceptions can contain account details; never dump them.
        print('::error::'+safe_error(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
