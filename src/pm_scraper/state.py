"""Durable SQLite state; retrieval and successful notification are separate events."""
import json
import sqlite3
from hashlib import sha256
from dataclasses import asdict
from .models import parse_date
from .htmlutil import norm

class State:
    def __init__(self, path):
        self.db=sqlite3.connect(path)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT OR IGNORE INTO meta VALUES('schema_version','1');
        CREATE TABLE IF NOT EXISTS jobs(
          key TEXT PRIMARY KEY, company_id TEXT NOT NULL, url TEXT NOT NULL,
          first_seen TEXT NOT NULL,last_seen TEXT NOT NULL, original_posted TEXT,
          fingerprint TEXT NOT NULL, job_json TEXT NOT NULL, assessment_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'present',misses INTEGER NOT NULL DEFAULT 0,
          reported_at TEXT, last_changed TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company_id);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT NOT NULL,health_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,keys_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',sent_at TEXT,receipt TEXT);
        ''')
        version=self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        if version!='1':raise RuntimeError('Unsupported state schema: '+version)

    def close(self):self.db.close()

    def original(self, job):
        """Publication dates cannot become newer on refresh/repost of the same ID."""
        row=self.db.execute('SELECT original_posted FROM jobs WHERE key=?',(job.key,)).fetchone()
        previous=parse_date(row['original_posted']) if row else None
        current=parse_date(job.posted_at) if job.date_kind=='original_posted' else None
        if previous and (not current or previous<current):
            job.metadata['current_source_date']=job.posted_at
            job.posted_at=previous.isoformat();job.date_kind='original_posted'
            job.date_evidence='Earliest original publication retained in durable state'
        return job

    def record(self, result, assessed, now):
        seen=set()
        with self.db:
            for job,assessment in assessed:
                seen.add(job.key)
                previous=self.db.execute('SELECT * FROM jobs WHERE key=?',(job.key,)).fetchone()
                fingerprint=sha256(json.dumps({'title':job.title,'location':job.location,'description':job.description,'workplace':job.workplace},sort_keys=True).encode()).hexdigest()
                published=job.posted_at if job.date_kind=='original_posted' and parse_date(job.posted_at) else None
                if previous:
                    self.db.execute('''UPDATE jobs SET url=?,last_seen=?,original_posted=COALESCE(?,original_posted),fingerprint=?,job_json=?,assessment_json=?,status='present',misses=0,last_changed=? WHERE key=?''',
                      (job.url,now,published,fingerprint,json.dumps(job.to_dict(),ensure_ascii=False),json.dumps(asdict(assessment),ensure_ascii=False),now if previous['fingerprint']!=fingerprint else previous['last_changed'],job.key))
                else:
                    self.db.execute('''INSERT INTO jobs(key,company_id,url,first_seen,last_seen,original_posted,fingerprint,job_json,assessment_json,last_changed) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                       (job.key,job.company_id,job.url,now,now,published,fingerprint,json.dumps(job.to_dict(),ensure_ascii=False),json.dumps(asdict(assessment),ensure_ascii=False),now))
            # Only fully enumerated, successful boards can accumulate absence evidence.
            # "missing" is not a claim that an employer closed the job.
            if result.complete and result.status=='ok':
                old=self.db.execute('SELECT key,misses FROM jobs WHERE company_id=?',(result.company_id,)).fetchall()
                for row in old:
                    if row['key'] not in seen:
                        misses=row['misses']+1
                        self.db.execute('UPDATE jobs SET misses=?,status=? WHERE key=?',(misses,'missing_unconfirmed' if misses>=2 else 'not_seen_once',row['key']))

    def was_reported(self, job):
        row=self.db.execute('SELECT reported_at FROM jobs WHERE key=? OR (company_id=? AND url=?)',(job.key,job.company_id,job.url)).fetchall()
        return any(r['reported_at'] for r in row)

    def eligible_delivery(self, pairs, now, limit=10):
        fresh=[(j,a) for j,a in pairs if a.status=='eligible' and not self.was_reported(j)]
        fresh.sort(key=lambda x:(-x[1].score,x[0].metadata.get('employer_rank',999),x[0].title))
        selected=fresh[:limit]
        if not selected:return None,[]
        keys=sorted(j.key for j,a in selected)
        delivery='pm-'+sha256(json.dumps(keys).encode()).hexdigest()[:20]
        with self.db:self.db.execute('INSERT OR IGNORE INTO deliveries(id,created_at,keys_json) VALUES(?,?,?)',(delivery,now,json.dumps(keys)))
        return delivery,selected

    def ack(self, delivery, now, receipt):
        row=self.db.execute('SELECT * FROM deliveries WHERE id=?',(delivery,)).fetchone()
        if not row:raise ValueError('Unknown delivery ID')
        if not receipt.strip():raise ValueError('A successful delivery receipt/message ID is required')
        if row['status']=='sent':return False
        with self.db:
            for key in json.loads(row['keys_json']):
                self.db.execute('UPDATE jobs SET reported_at=COALESCE(reported_at,?) WHERE key=?',(now,key))
            self.db.execute("UPDATE deliveries SET status='sent',sent_at=?,receipt=? WHERE id=?",(now,receipt,delivery))
        return True

    def record_run(self, run_id, started, finished, health):
        with self.db:self.db.execute('INSERT INTO runs VALUES(?,?,?,?)',(run_id,started,finished,json.dumps(health,ensure_ascii=False)))

    def stats(self):
        return dict(self.db.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status').fetchall())
