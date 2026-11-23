"""Additive schema extension. Existing M1 tables and rows are retained."""
import json
from datetime import datetime, timezone


class CareerStorage:
    def init_extensions(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS profile_documents (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, content BLOB NOT NULL, text TEXT NOT NULL,
              kind TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS profile_facts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER REFERENCES profile_documents(id),
              category TEXT NOT NULL, text TEXT NOT NULL, source_quote TEXT, confirmed INTEGER DEFAULT 0,
              reviewed_at TEXT, provenance TEXT DEFAULT 'extracted');
            CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1), style TEXT, preferences TEXT);
            CREATE TABLE IF NOT EXISTS sources (
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER REFERENCES jobs(id), url TEXT,
              retrieved_at TEXT DEFAULT CURRENT_TIMESTAMP, content BLOB, text TEXT, mime TEXT, note TEXT);
            CREATE TABLE IF NOT EXISTS evaluations (
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER REFERENCES jobs(id),
              profile_hash TEXT, analysis_hash TEXT, payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS packages (
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER REFERENCES jobs(id),
              evaluation_id INTEGER REFERENCES evaluations(id), plan TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS drafts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, package_id INTEGER REFERENCES packages(id),
              item_key TEXT, title TEXT, body TEXT, evidence TEXT, warnings TEXT, file_path TEXT,
              version INTEGER, origin TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS operations (
              id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, model TEXT, job_id INTEGER REFERENCES jobs(id),
              state TEXT DEFAULT 'running', detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT);
            CREATE TABLE IF NOT EXISTS analysis_reviews (
              job_id INTEGER PRIMARY KEY REFERENCES jobs(id), analysis_hash TEXT, reviewed_at TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')

    def add_profile_document(self, name, content, text, kind):
        with self.connect() as db:
            return db.execute('INSERT INTO profile_documents(name,content,text,kind) VALUES(?,?,?,?)', (name, content, text, kind)).lastrowid

    def profile_documents(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,name,kind,created_at FROM profile_documents ORDER BY id DESC')]

    def remove_profile_document(self, document_id):
        with self.connect() as db:
            db.execute('DELETE FROM profile_facts WHERE document_id=?', (document_id,))
            db.execute('DELETE FROM profile_documents WHERE id=?', (document_id,))
            # Keep the import digest so an unchanged folder file is not immediately
            # reimported. Uploading it again explicitly is still supported.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_imports'").fetchone():
                db.execute('UPDATE local_imports SET document_id=NULL WHERE document_id=?', (document_id,))

    def profile_document(self, document_id):
        with self.connect() as db:
            return dict(db.execute('SELECT * FROM profile_documents WHERE id=?', (document_id,)).fetchone())

    def save_extracted_facts(self, document_id, facts):
        with self.connect() as db:
            # Retry never overwrites a correction or duplicates an existing fact.
            for f in facts:
                existing = db.execute('SELECT id FROM profile_facts WHERE document_id=? AND source_quote=? AND category=?', (document_id, f['source_quote'], f['category'])).fetchone()
                if not existing:
                    db.execute('INSERT INTO profile_facts(document_id,category,text,source_quote) VALUES(?,?,?,?)', (document_id, f['category'], f['text'], f['source_quote']))

    def facts(self, confirmed_only=False):
        with self.connect() as db:
            records = [dict(r) for r in db.execute('SELECT * FROM profile_facts ORDER BY id')]
        groups = {}
        for fact in records:
            key = ' '.join(fact['text'].split()).casefold()
            old = groups.get(key)
            # Prefer an explicit review over an unreviewed copy from another CV.
            priority = (fact['reviewed_at'] or '', fact['confirmed'], -fact['id'])
            if old is None or priority > (old['reviewed_at'] or '', old['confirmed'], -old['id']):
                groups[key] = fact
        return sorted((f for f in groups.values() if not confirmed_only or f['confirmed']), key=lambda f: f['id'])

    def save_fact(self, fact_id, category, text, confirmed):
        from office.career import CATEGORIES
        if category not in CATEGORIES or not text.strip() or len(text) > 2500:
            raise ValueError('Choose a valid category and enter 1–2500 characters.')
        with self.connect() as db:
            if fact_id is None:
                return db.execute("INSERT INTO profile_facts(category,text,source_quote,confirmed,reviewed_at,provenance) VALUES(?,?,'User supplied',?,CURRENT_TIMESTAMP,'user')", (category, text, int(confirmed))).lastrowid
            db.execute("UPDATE profile_facts SET category=?,text=?,confirmed=?,reviewed_at=CURRENT_TIMESTAMP,provenance='user reviewed' WHERE id=?", (category, text, int(confirmed), fact_id))

    def preferences(self):
        with self.connect() as db:
            row = db.execute('SELECT * FROM preferences WHERE id=1').fetchone()
            return dict(row) if row else {'style': '', 'preferences': ''}

    def confirm_fact_review(self, rows, expected):
        """One atomic review. Flagged unchanged facts stay excluded; edits are confirmed."""
        from office.career import CATEGORIES
        originals = {f['id']: f for f in expected}
        if len(rows) != len(originals) or {r['ID'] for r in rows} != set(originals):
            raise ValueError('The review rows changed. Reload My Profile before confirming.')
        updates = []
        for row in rows:
            old = originals[row['ID']]
            text, category = row['Fact'], row['Category']
            if not isinstance(text, str) or not text.strip() or len(text) > 2500 or category not in CATEGORIES:
                raise ValueError(f"Fact #{row['ID']}: choose a valid category and enter 1–2500 characters. Nothing was saved.")
            corrected = text != old['text'] or category != old['category']
            confirmed = not row['Incorrect'] or corrected
            updates.append((category, text, int(confirmed), row['ID']))
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for old in expected:
                current = conn.execute('SELECT * FROM profile_facts WHERE id=?', (old['id'],)).fetchone()
                if not current or any(current[k] != old[k] for k in ('text','category','confirmed','reviewed_at')):
                    raise ValueError('A fact changed in another session. Reload before confirming; nothing was saved.')
            all_rows = list(conn.execute('SELECT id,text FROM profile_facts'))
            expanded = []
            for category, text, confirmed, fact_id in updates:
                key = ' '.join(originals[fact_id]['text'].split()).casefold()
                expanded.extend((category, text, confirmed, r['id']) for r in all_rows if ' '.join(r['text'].split()).casefold() == key)
            conn.executemany("UPDATE profile_facts SET category=?,text=?,confirmed=?,reviewed_at=CURRENT_TIMESTAMP,provenance='user reviewed' WHERE id=?", expanded)
        return sum(row[2] for row in updates), sum(not row[2] for row in updates)

    def save_preferences(self, style, preferences):
        with self.connect() as db:
            db.execute('INSERT INTO preferences VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET style=excluded.style,preferences=excluded.preferences', (style, preferences))

    def operation_start(self, kind, model, job_id=None):
        with self.connect() as db:
            return db.execute('INSERT INTO operations(kind,model,job_id) VALUES(?,?,?)', (kind, model, job_id)).lastrowid

    def operation_finish(self, run, state, detail):
        with self.connect() as db:
            db.execute('UPDATE operations SET state=?,detail=?,finished_at=CURRENT_TIMESTAMP WHERE id=?', (state, detail, run))

    def operations(self, job_id=None):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM operations WHERE job_id IS ? ORDER BY id DESC', (job_id,))]

    def add_source(self, job_id, url, content, text, mime, note=''):
        with self.connect() as db:
            return db.execute('INSERT INTO sources(job_id,url,content,text,mime,note) VALUES(?,?,?,?,?,?)', (job_id, url, content, text, mime, note)).lastrowid

    def sources(self, job_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM sources WHERE job_id=? ORDER BY id', (job_id,))]

    def save_evaluation(self, job_id, profile_hash, analysis_hash, payload,expected_revision=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if expected_revision is not None:
                case=db.execute('SELECT revision FROM case_state WHERE job_id=?',(job_id,)).fetchone()
                if case and case['revision']!=expected_revision:
                    raise ValueError('Case changed during evaluation; rerun queued.')
            ident=db.execute('INSERT INTO evaluations(job_id,profile_hash,analysis_hash,payload) VALUES(?,?,?,?)', (job_id, profile_hash, analysis_hash, json.dumps(payload))).lastrowid
            db.execute("UPDATE case_state SET evaluation_dirty=0,selected=0,stage='evaluated',issue='' WHERE job_id=?",(job_id,))
            return ident

    def evaluation(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM evaluations WHERE job_id=? ORDER BY id DESC LIMIT 1', (job_id,)).fetchone()
            return dict(row) if row else None

    def save_package(self, job_id, evaluation_id, plan):
        with self.connect() as db:
            return db.execute('INSERT INTO packages(job_id,evaluation_id,plan) VALUES(?,?,?)', (job_id, evaluation_id, json.dumps(plan))).lastrowid

    def package(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM packages WHERE job_id=? ORDER BY id DESC LIMIT 1', (job_id,)).fetchone()
            return dict(row) if row else None

    def drafts(self, package_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM drafts WHERE package_id=? ORDER BY id DESC', (package_id,))]

    def save_draft(self, package_id, item_key, title, body, evidence, warnings, path, origin):
        with self.connect() as db:
            version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM drafts WHERE package_id=? AND item_key=?', (package_id, item_key)).fetchone()[0]
            return db.execute('INSERT INTO drafts(package_id,item_key,title,body,evidence,warnings,file_path,version,origin) VALUES(?,?,?,?,?,?,?,?,?)',
                (package_id,item_key,title,body,json.dumps(evidence),json.dumps(warnings),str(path),version,origin)).lastrowid

    def review_analysis(self, job_id, digest):
        with self.connect() as db:
            db.execute('INSERT INTO analysis_reviews(job_id,analysis_hash) VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET analysis_hash=excluded.analysis_hash,reviewed_at=CURRENT_TIMESTAMP', (job_id, digest))

    def is_analysis_reviewed(self, job_id, digest):
        with self.connect() as db:
            return bool(db.execute('SELECT 1 FROM analysis_reviews WHERE job_id=? AND analysis_hash=?', (job_id, digest)).fetchone())
