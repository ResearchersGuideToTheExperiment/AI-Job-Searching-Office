import json
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path
from office.models import Analysis, STATUSES
from office.storage import CareerStorage


class Database(CareerStorage):
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              original TEXT NOT NULL, filename TEXT, original_file BLOB, source_url TEXT,
              status TEXT NOT NULL DEFAULT 'New', analysis TEXT, warnings TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS requirements (
              id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
              category TEXT, text TEXT, importance TEXT, source_quote TEXT);
            CREATE TABLE IF NOT EXISTS tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL REFERENCES jobs(id),
              text TEXT, source TEXT, verification INTEGER, importance TEXT, complete INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
              started_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT,
              model TEXT, api_url TEXT, prompt_version TEXT, outcome TEXT, detail TEXT, raw_response TEXT);
            CREATE TABLE IF NOT EXISTS agent_activity (
              id INTEGER PRIMARY KEY, agent INTEGER, label TEXT, job_id INTEGER,
              started TEXT DEFAULT CURRENT_TIMESTAMP, heartbeat TEXT DEFAULT CURRENT_TIMESTAMP,
              finished TEXT, state TEXT DEFAULT 'running', detail TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS office_control (
              id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT DEFAULT 'running',generation INTEGER DEFAULT 0);
            INSERT OR IGNORE INTO office_control(id) VALUES(1);
            CREATE TABLE IF NOT EXISTS processing_sessions (
              id TEXT PRIMARY KEY, state TEXT DEFAULT 'running',heartbeat TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS evaluation_decisions (
              id INTEGER PRIMARY KEY, job_id INTEGER, evaluation_id INTEGER,
              score INTEGER, decision TEXT, note TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS analysis_inputs (
              id INTEGER PRIMARY KEY,job_id INTEGER,run_id INTEGER,source_id INTEGER,url TEXT,
              parser_version TEXT,content_hash TEXT,text TEXT);
            CREATE TABLE IF NOT EXISTS analysis_evidence (
              id INTEGER PRIMARY KEY,job_id INTEGER,run_id INTEGER,input_id INTEGER,field TEXT,
              quote TEXT,start_offset INTEGER,end_offset INTEGER);
            CREATE TABLE IF NOT EXISTS case_state (
              job_id INTEGER PRIMARY KEY, revision INTEGER DEFAULT 0, evaluation_dirty INTEGER DEFAULT 1,
              stage TEXT DEFAULT 'pending', issue TEXT DEFAULT '', selected INTEGER DEFAULT 0,
              text_override TEXT, changed TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS case_revisions (
              id INTEGER PRIMARY KEY,job_id INTEGER,reason TEXT,snapshot TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS dashboard_presence (
              id TEXT PRIMARY KEY,heartbeat TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS office_worker (
              id INTEGER PRIMARY KEY CHECK(id=1),heartbeat TEXT,discovered TEXT);
            CREATE TABLE IF NOT EXISTS inference_metrics (
              id INTEGER PRIMARY KEY,job_id INTEGER,endpoint TEXT,model TEXT,elapsed REAL,
              input_tokens INTEGER,output_tokens INTEGER,error TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS extraction_cache (
              key TEXT PRIMARY KEY,job_id INTEGER,analysis TEXT,raw TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS evaluation_steps (
              key TEXT PRIMARY KEY,job_id INTEGER,payload TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT OR IGNORE INTO case_state(job_id) SELECT id FROM jobs;
            """)
        self.init_extensions()
        with self.connect() as db:
            if 'job_id' not in [r['name'] for r in db.execute('PRAGMA table_info(extraction_cache)')]:
                db.execute('ALTER TABLE extraction_cache ADD COLUMN job_id INTEGER')
            for table in ('agent_activity','processing_sessions','office_worker'):
                if 'owner_pid' not in [r['name'] for r in db.execute(f'PRAGMA table_info({table})')]:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN owner_pid INTEGER DEFAULT 0')

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            yield db

    def add_job(self, original, source_url="", filename=None, content=None):
        with self.connect() as db:
            ident=db.execute("INSERT INTO jobs(original,source_url,filename,original_file) VALUES(?,?,?,?)",
                              (original, source_url, filename, content)).lastrowid
            db.execute('INSERT INTO case_state(job_id) VALUES(?)',(ident,))
            return ident

    def jobs(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,created_at,status,analysis,substr(original,1,90) AS preview FROM jobs ORDER BY id DESC")]

    def copy_job_for_reanalysis(self,job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:
                raise ValueError('Job not found')
            ident=db.execute('INSERT INTO jobs(original,source_url,filename,original_file) VALUES(?,?,?,?)',
                             (row['original'],row['source_url'],row['filename'],row['original_file'])).lastrowid
            db.execute('INSERT INTO case_state(job_id) VALUES(?)',(ident,))
            db.execute('INSERT INTO sources(job_id,url,retrieved_at,content,text,mime,note) SELECT ?,url,retrieved_at,content,text,mime,note FROM sources WHERE job_id=?',(ident,job_id))
            return ident

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("Job not found")
            return dict(row)

    def tasks(self, job_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM tasks WHERE job_id=? ORDER BY id", (job_id,))]

    def set_complete(self, task_id, complete):
        with self.connect() as db:
            db.execute("UPDATE tasks SET complete=? WHERE id=?", (int(complete), task_id))

    def set_status(self, job_id, status):
        if status not in STATUSES:
            raise ValueError("Invalid application status")
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
        from office.cases import invalidate
        invalidate(self,job_id,'Application status changed')

    def start_run(self, job_id, settings, prompt_version):
        with self.connect() as db:
            return db.execute("INSERT INTO history(job_id,model,api_url,prompt_version,outcome) VALUES(?,?,?,?, 'running')",
                (job_id, settings.model, settings.api_url, prompt_version)).lastrowid

    def fail_run(self, run_id, message, raw=""):
        with self.connect() as db:
            db.execute("UPDATE history SET outcome='failed',detail=?,raw_response=?,finished_at=CURRENT_TIMESTAMP WHERE id=?", (message, raw, run_id))

    def save_analysis(self, job_id, analysis: Analysis, warnings, tasks, run_id, raw, expected=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if expected is not None:
                current=dict(db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone())
                if any(current[k]!=expected[k] for k in ('original','source_url','analysis')):
                    raise ValueError('Job changed during extraction; stale result was not saved.')
                if db.execute('SELECT 1 FROM analysis_reviews WHERE job_id=?',(job_id,)).fetchone():
                    raise ValueError('Reviewed analysis is protected. Create a separate corrected copy for review.')
            if not db.execute('SELECT 1 FROM history WHERE id=? AND job_id=?',(run_id,job_id)).fetchone():
                raise ValueError('Analysis history belongs to a different job.')
            previous = {row['text']: row['complete'] for row in db.execute('SELECT text,complete FROM tasks WHERE job_id=?', (job_id,))}
            db.execute("UPDATE jobs SET analysis=?,warnings=? WHERE id=?", (analysis.model_dump_json(), json.dumps(warnings), job_id))
            db.execute("INSERT OR IGNORE INTO case_state(job_id) VALUES(?)",(job_id,))
            db.execute("UPDATE case_state SET evaluation_dirty=1,selected=0,stage='evaluation_pending',issue='' WHERE job_id=?",(job_id,))
            db.execute("DELETE FROM requirements WHERE job_id=?", (job_id,))
            db.execute("DELETE FROM tasks WHERE job_id=?", (job_id,))
            db.executemany("INSERT INTO requirements(job_id,category,text,importance,source_quote) VALUES(?,?,?,?,?)",
                [(job_id, r.category, r.text, r.importance, r.source_quote) for r in analysis.requirements])
            db.executemany("INSERT INTO tasks(job_id,text,source,verification,importance,complete) VALUES(?,?,?,?,?,?)",
                [(job_id, t['text'], t['source'], int(t['verification']), t['importance'], previous.get(t['text'], 0)) for t in tasks])
            db.execute("UPDATE history SET outcome='success',detail=?,raw_response=?,finished_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(warnings), raw, run_id))

    def history(self, job_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM history WHERE job_id=? ORDER BY id DESC", (job_id,))]
